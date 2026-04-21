# lcd_plants.py
# ─────────────────────────────────────────────────────────────────────────────
# Plant Monitor LCD Menu — Klipper Extra
#
# Reads per-plot daily log files named:
#   <plant_name>_plot<1-4>_<YYYY-MM-DD>.json
# e.g.  basil_1_plot1_2026-03-20.json
#
# Place in:     ~/klipper/klippy/extras/lcd_plants.py
# printer.cfg:
#   [lcd_plants]
#   log_dir: /home/pi/plant_logs
#   plant_name: basil_1
#
# ── How it hooks into Klipper ─────────────────────────────────────────────────
#
# We subclass MenuManager so that:
#   • super().__init__() runs — MenuKeys, gcode, printer callbacks all wire up
#     correctly, begin()/is_running() work, no "Invalid root" errors
#   • We override screen_update_event() — draws our UI instead of the menu tree
#   • We override key_event() — routes input to our state machine, then calls
#     self.display.request_redraw() exactly as the original does
#
# ── Display: UC1701 Mini12864, font8x14 ───────────────────────────────────────
#   get_dimensions() → (16, 4)   i.e. 16 cols × 4 rows
#   draw_text(row, col, text, eventtime)
#
# ── UI: scrollable list pattern ───────────────────────────────────────────────
#   Row 0  fixed title
#   Row 1  > [cursor item]       selected item always on row 1
#   Row 2    [cursor+1 item]     next item (wraps)
#   Row 3  fixed hint
#
#  MAIN MENU
#   Title: Plant Monitor
#   Items: Plot 1 … Plot 4, Commands
#
#  PLOT DETAIL
#   Title: Plot N @HH:MM
#   Items: Moisture, Humidity, Temp, Watering, Alerts, Warn (editable)
#
#  COMMAND MENU
#   Title: Commands
#   Items: Lights ON/OFF, Pump ON/OFF, Home XY, Center, Motors OFF
#
#  EDIT SCREEN  (Warn threshold)
#   Row 0  Plot N Warn ADC
#   Row 1    Current: 400 ADC
#   Row 2  > Set:     410 ADC    scroll ±10
#   Row 3  Clk=save Lng=cncl
#
# ── Navigation ────────────────────────────────────────────────────────────────
#   up / down     scroll list  (or adjust value in edit mode)
#   click         select / confirm
#   long_click    back / cancel
#   back          back
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
import glob
import logging
import threading
import datetime

log = logging.getLogger(__name__)

LCD_COLS     = 16
LCD_ROWS     = 4
CONTENT_ROWS = 2   # rows 1-2 are scrollable content

# ── States ────────────────────────────────────────────────────────────────────
STATE_MAIN   = "main"
STATE_DETAIL = "detail"
STATE_CMDS   = "cmds"
STATE_EDIT   = "edit"

# ── Commands ──────────────────────────────────────────────────────────────────
COMMANDS = [
    ("Lights ON",  "LIGHT_ON"),
    ("Lights OFF", "LIGHT_OFF"),
    ("Pump ON",    "PUMP_ON"),
    ("Pump OFF",   "PUMP_OFF"),
    ("Home XY",    "HOME_XY"),
    ("Go Center",  "CENTER"),
    ("Motors OFF", "MOTORS_OFF"),
]

# ── Detail rows ───────────────────────────────────────────────────────────────
# (label, PlotData attribute or None, format callable or None)
# None attribute = the editable Warn threshold row
DETAIL_ROWS = [
    ("Moisture", "soil_moisture", lambda v: "%d ADC"    % v if v is not None else "---"),
    ("Humidity", "humidity",      lambda v: "%.1f %%"   % v if v is not None else "---"),
    ("Temp",     "temperature",   lambda v: "%.1f C"    % v if v is not None else "---"),
    ("Watering", "water_count",   lambda v: "%d rec%s"  % (v, "s" if v != 1 else "")
                                            if v is not None else "---"),
    ("Alerts",   "alerts",        lambda v: "%d active" % len(v) if v else "none"),
    ("Warn",     None,            None),   # editable
]
WARN_ROW_IDX = len(DETAIL_ROWS) - 1

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MOISTURE_WARN = [400, 400, 400, 400]
SETTINGS_FILE = "/tmp/plant_lcd_settings.json"


# ─────────────────────────────────────────────────────────────────────────────
class PlotData:
    __slots__ = (
        "plot_id", "file_date", "last_minute",
        "soil_moisture", "humidity", "temperature",
        "water_count", "alerts", "file_mtime", "error",
    )

    def __init__(self):
        self.plot_id       = None
        self.file_date     = None
        self.last_minute   = None
        self.soil_moisture = None
        self.humidity      = None
        self.temperature   = None
        self.water_count   = 0
        self.alerts        = []
        self.file_mtime    = 0.0
        self.error         = None

    def copy_from(self, other):
        for s in self.__slots__:
            setattr(self, s, getattr(other, s))


# ─────────────────────────────────────────────────────────────────────────────
class LcdPlants:
    """
    Loaded by Klipper as a standalone extra via [lcd_plants] in printer.cfg.
    Waits for klippy:ready, then replaces display.menu with a PlantMenuManager
    instance that subclasses the real MenuManager.
    """

    def __init__(self, config):
        self.config  = config
        self.printer = config.get_printer()

        self.log_dir    = config.get("log_dir",    "/home/pi/plant_logs")
        self.plant_name = config.get("plant_name", "basil_1")

        self._plots = [PlotData() for _ in range(4)]
        self._lock  = threading.Lock()

        self.moisture_warn = list(DEFAULT_MOISTURE_WARN)
        self._load_settings()

        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        display = self.printer.lookup_object("display", None)
        if display is None:
            log.warning("lcd_plants: no [display]")
            return

        # Import MenuManager here so it's available at ready-time
        from .display import menu as menu_mod

        # Build our subclassed manager and swap it onto the display
        mgr = PlantMenuManager(
            self.config, display,
            self._plots, self._lock, self.moisture_warn,
            self._save_settings,
            self.log_dir, self.plant_name,
        )
        display.menu = mgr

        # Start polling loop
        reactor = self.printer.get_reactor()
        reactor.register_timer(self._poll_tick, reactor.NOW)
        log.info("lcd_plants: ready | dir=%s | plant=%s",
                 self.log_dir, self.plant_name)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r") as fh:
                d = json.load(fh)
            for i, v in enumerate(d.get("moisture_warn", [])[:4]):
                self.moisture_warn[i] = float(v)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.error("lcd_plants load settings: %s", exc)

    def _save_settings(self):
        try:
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"moisture_warn": self.moisture_warn}, fh, indent=2)
            os.replace(tmp, SETTINGS_FILE)
        except Exception as exc:
            log.error("lcd_plants save settings: %s", exc)

    # ── Data polling ──────────────────────────────────────────────────────────

    def _poll_tick(self, eventtime):
        for i in range(4):
            try:
                self._refresh(i, i + 1)
            except Exception as exc:
                log.error("lcd_plants poll plot%d: %s", i + 1, exc)
                with self._lock:
                    self._plots[i].error = "err"
        return eventtime + 10.0

    def _refresh(self, idx, plot_num):
        path = self._find_file(plot_num)
        if path is None:
            with self._lock:
                self._plots[idx].error      = "no file"
                self._plots[idx].last_minute = None
            return
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            with self._lock:
                self._plots[idx].error = "stat err"
            return
        with self._lock:
            if mtime == self._plots[idx].file_mtime:
                return
        try:
            with open(path, "r") as fh:
                raw = json.load(fh)
        except Exception as exc:
            with self._lock:
                self._plots[idx].error = "json err"
            log.error("lcd_plants parse error %s: %s", path, exc)
            return
        pd = self._parse(raw, mtime)
        with self._lock:
            self._plots[idx].copy_from(pd)

    def _find_file(self, plot_num):
        today = datetime.date.today().strftime("%Y-%m-%d")
        preferred = os.path.join(
            self.log_dir,
            "%s_plot%d_%s.json" % (self.plant_name, plot_num, today)
        )
        if os.path.isfile(preferred):
            return preferred
        pattern = os.path.join(
            self.log_dir,
            "%s_plot%d_*.json" % (self.plant_name, plot_num)
        )
        candidates = sorted(glob.glob(pattern))
        return candidates[-1] if candidates else None

    def _parse(self, raw, mtime):
        pd = PlotData()
        pd.file_mtime  = mtime
        pd.plot_id     = raw.get("plot_id")
        pd.file_date   = raw.get("date", "?")
        summary        = raw.get("minute_summary", {})
        if not summary:
            pd.error = "empty"
            return pd
        latest_key       = sorted(summary.keys())[-1]
        m                = summary[latest_key]
        pd.last_minute   = latest_key
        pd.soil_moisture = m.get("avg_soil_moisture")
        pd.humidity      = m.get("avg_humidity")
        pd.temperature   = m.get("avg_temperature_c")
        pd.water_count   = m.get("watering_recommended_count", 0)
        alerts_raw       = m.get("alerts_count", {})
        pd.alerts        = [k for k, v in alerts_raw.items() if v > 0]
        return pd


# ─────────────────────────────────────────────────────────────────────────────
class PlantMenuManager:
    """
    Minimal drop-in replacement for MenuManager.
    Satisfies all the attributes/methods that display.py and menu_keys.py
    call on display.menu:
      • screen_update_event(eventtime)
      • key_event(key, eventtime)
      • is_running()  — always True so _click_callback never calls begin()
    Everything else (begin, stack, root, etc.) is stubbed out.
    """

    def __init__(self, config, display,
                 plots, lock, moisture_warn, save_settings_fn,
                 log_dir, plant_name):
        self.display       = display
        self.printer       = config.get_printer()
        self._plots        = plots
        self._lock         = lock
        self.moisture_warn = moisture_warn
        self._save         = save_settings_fn

        # Register MenuKeys so the encoder/button hardware fires key_event
        # We have to instantiate it ourselves since we're not calling
        # MenuManager.__init__
        from .display import menu_keys
        menu_keys.MenuKeys(config, self.key_event)

        # UI state
        self.state      = STATE_MAIN
        self.cursor     = 0
        self.sub_plot   = 0
        self.edit_value = 0.0

    # ── Stubs expected by display.py / menu system ────────────────────────────

    def is_running(self):
        # Always return True so _click_callback (if ever called) uses press()
        # rather than begin(), and begin() is never called on us
        return True

    def screen_update_event(self, eventtime):
        """Called by PrinterLCD after lcd_chip.clear(), before lcd_chip.flush()"""
        try:
            if self.state == STATE_MAIN:
                self._draw_main(eventtime)
            elif self.state == STATE_DETAIL:
                self._draw_detail(eventtime)
            elif self.state == STATE_CMDS:
                self._draw_cmds(eventtime)
            elif self.state == STATE_EDIT:
                self._draw_edit(eventtime)
        except Exception as exc:
            log.exception("lcd_plants render: %s", exc)
        return None

    def key_event(self, key, eventtime):
        """Called by MenuKeys for all encoder/button events."""
        if key in ('up', 'fast_up'):
            self._scroll(-1)
        elif key in ('down', 'fast_down'):
            self._scroll(1)
        elif key == 'click':
            self._select()
        elif key in ('long_click', 'back'):
            self._back()
        # Trigger a redraw immediately
        self.display.request_redraw()

    # ── Input ─────────────────────────────────────────────────────────────────

    def _list_len(self):
        if self.state == STATE_MAIN:
            return 5           # 4 plots + Commands entry
        elif self.state == STATE_DETAIL:
            return len(DETAIL_ROWS)
        elif self.state == STATE_CMDS:
            return len(COMMANDS)
        return 1

    def _scroll(self, direction):
        if self.state == STATE_EDIT:
            self.edit_value = max(0.0,
                                  min(1023.0,
                                      self.edit_value + direction * 10.0))
            return
        n = self._list_len()
        self.cursor = (self.cursor + direction) % n

    def _select(self):
        if self.state == STATE_MAIN:
            if self.cursor < 4:
                self.sub_plot   = self.cursor
                self.cursor     = 0
                self.state      = STATE_DETAIL
            else:
                self.cursor = 0
                self.state  = STATE_CMDS

        elif self.state == STATE_DETAIL:
            if self.cursor == WARN_ROW_IDX:
                self.edit_value = float(self.moisture_warn[self.sub_plot])
                self.state      = STATE_EDIT

        elif self.state == STATE_CMDS:
            _, gcode = COMMANDS[self.cursor]
            try:
                gcode_obj = self.printer.lookup_object("gcode")
                gcode_obj.run_script_from_command(gcode)
                log.info("lcd_plants: ran %s", gcode)
            except Exception as exc:
                log.error("lcd_plants: %s failed: %s", gcode, exc)

        elif self.state == STATE_EDIT:
            self.moisture_warn[self.sub_plot] = self.edit_value
            self._save()
            self.cursor = WARN_ROW_IDX
            self.state  = STATE_DETAIL

    def _back(self):
        if self.state == STATE_DETAIL:
            self.cursor = self.sub_plot
            self.state  = STATE_MAIN
        elif self.state == STATE_CMDS:
            self.cursor = 4
            self.state  = STATE_MAIN
        elif self.state == STATE_EDIT:
            self.cursor = WARN_ROW_IDX
            self.state  = STATE_DETAIL

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _row(self, row, text, eventtime):
        if 0 <= row < LCD_ROWS:
            self.display.draw_text(row, 0,
                                   text[:LCD_COLS].ljust(LCD_COLS),
                                   eventtime)

    def _draw_list(self, title, items, hint, eventtime):
        """
        Shared list renderer.
        Row 0: title
        Row 1: > items[cursor]
        Row 2:   items[(cursor+1) % n]
        Row 3: hint
        """
        n = len(items)
        self._row(0, title, eventtime)
        if n == 0:
            self._row(1, "  (empty)", eventtime)
            self._row(2, "",          eventtime)
        else:
            for slot in range(CONTENT_ROWS):
                idx    = (self.cursor + slot) % n
                prefix = ">" if slot == 0 else " "
                self._row(slot + 1, prefix + " " + items[idx], eventtime)
        self._row(3, hint, eventtime)

    def _draw_main(self, eventtime):
        snaps = []
        with self._lock:
            for i in range(4):
                s = PlotData()
                s.copy_from(self._plots[i])
                snaps.append(s)

        items = []
        for i, pd in enumerate(snaps):
            dry = (pd.soil_moisture is not None and
                   pd.soil_moisture > self.moisture_warn[i])
            flag = " !" if dry else "  "
            if pd.error:
                val = pd.error
            else:
                val = ("%d ADC" % pd.soil_moisture
                       if pd.soil_moisture is not None else "-- ADC")
            items.append("Plot %d  %s%s" % (i + 1, val, flag))

        items.append("Commands >")

        self._draw_list("Plant Monitor", items,
                        "Clk=open Lng=---", eventtime)

    def _draw_detail(self, eventtime):
        idx = self.sub_plot
        with self._lock:
            pd = PlotData()
            pd.copy_from(self._plots[idx])
        thr = self.moisture_warn[idx]

        t_str = (" @%s" % pd.last_minute) if pd.last_minute else ""
        title = ("Plot %d%s" % (idx + 1, t_str))[:LCD_COLS]

        items = []
        for row_idx, (label, key, fmt) in enumerate(DETAIL_ROWS):
            if key is None:
                item = "Warn:  %d ADC >" % thr
            elif pd.error:
                item = "%s: ---" % label
            else:
                val  = getattr(pd, key, None)
                item = "%s: %s" % (label, fmt(val))
            items.append(item)

        hint = "Clk=edit Lng=back" if self.cursor == WARN_ROW_IDX \
               else "Scrl=mv  Lng=back"
        self._draw_list(title, items, hint, eventtime)

    def _draw_cmds(self, eventtime):
        items = [label for label, _ in COMMANDS]
        self._draw_list("Commands", items,
                        "Clk=run  Lng=back", eventtime)

    def _draw_edit(self, eventtime):
        idx = self.sub_plot
        thr = self.moisture_warn[idx]
        self._row(0, "Plot %d Warn ADC" % (idx + 1),  eventtime)
        self._row(1, "  Current:%d ADC" % thr,         eventtime)
        self._row(2, "> Set:    %d ADC" % self.edit_value, eventtime)
        self._row(3, "Clk=save Lng=cncl", eventtime)


# ── Klipper entry point ───────────────────────────────────────────────────────

def load_config(config):
    return LcdPlants(config)