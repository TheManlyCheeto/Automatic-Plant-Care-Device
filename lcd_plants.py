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
# ── Display: UC1701 Mini12864 with font8x14 ───────────────────────────────────
#   16 columns × 4 rows   (confirmed via get_dimensions() → (16, 4))
#   draw_text(row, col, text, eventtime)
#
# ── UI model ──────────────────────────────────────────────────────────────────
# Everything is a scrollable list. Row 0 is always a fixed title bar.
# Rows 1-2 show a 2-row window into the list. Row 3 is a fixed hint bar.
#
#  MAIN MENU  (4 plots + commands)
#   Row 0   Plant Monitor
#   Row 1  > Plot 1           ← cursor item (always shown)
#   Row 2    Plot 2           ← cursor+1 (or wraps)
#   Row 3   Clk=open Lng=cmd
#
#  PLOT DETAIL  (scrollable sensor values + Warn threshold)
#   Row 0  [ Plot 1 @13:32 ]
#   Row 1  > Moisture:378 ADC ← cursor item
#   Row 2    Humidity: 8.4 %  ← cursor+1
#   Row 3   Clk=edit Lng=back
#
#  COMMAND MENU  (all 7 commands scrollable)
#   Row 0   Commands
#   Row 1  > Lights ON
#   Row 2    Lights OFF
#   Row 3   Clk=run  Lng=back
#
#  EDIT MODE  (threshold adjustment)
#   Row 0  [ Plot 1 Warn ]
#   Row 1   Current: 400 ADC
#   Row 2  > Set:    410 ADC  ← scroll to adjust
#   Row 3   Clk=save Lng=cncl
#
# ── Navigation ────────────────────────────────────────────────────────────────
#  up/down     → scroll list cursor
#  click       → select / confirm
#  long_click  → back / cancel
#  back        → back
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import glob
import logging
import threading
import datetime

log = logging.getLogger(__name__)

LCD_COLS = 16
LCD_ROWS = 4
CONTENT_ROWS = 2          # rows 1-2 are scrollable content
SCROLL_WIN   = CONTENT_ROWS

# ── States ────────────────────────────────────────────────────────────────────
STATE_MAIN    = "main"
STATE_DETAIL  = "detail"
STATE_CMDS    = "cmds"
STATE_EDIT    = "edit"

# ── Commands ──────────────────────────────────────────────────────────────────
COMMANDS = [
    ("Lights ON",   "LIGHT_ON"),
    ("Lights OFF",  "LIGHT_OFF"),
    ("Pump ON",     "PUMP_ON"),
    ("Pump OFF",    "PUMP_OFF"),
    ("Home XY",     "HOME_XY"),
    ("Go Center",   "CENTER"),
    ("Motors OFF",  "MOTORS_OFF"),
]

# ── Detail rows ───────────────────────────────────────────────────────────────
# Each is (label, key_into_PlotData_or_None, format_string_or_callable)
# key=None means it is the editable Warn threshold row
DETAIL_ROWS = [
    ("Moisture",  "soil_moisture", lambda v: "%d ADC"   % v if v is not None else "---"),
    ("Humidity",  "humidity",      lambda v: "%.1f %%"  % v if v is not None else "---"),
    ("Temp",      "temperature",   lambda v: "%.1f C"   % v if v is not None else "---"),
    ("Watering",  "water_count",   lambda v: "%d rec%s" % (v, "s" if v != 1 else "") if v is not None else "---"),
    ("Alerts",    "alerts",        lambda v: "%d active" % len(v) if v else "none"),
    ("Warn",      None,            None),   # editable — handled specially
]

WARN_ROW_IDX = len(DETAIL_ROWS) - 1   # index of the editable row in DETAIL_ROWS

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

    def __init__(self, config):
        self.printer    = config.get_printer()
        self.reactor    = self.printer.get_reactor()

        self.log_dir    = config.get("log_dir",    "/home/pi/plant_logs")
        self.plant_name = config.get("plant_name", "basil_1")

        self._plots = [PlotData() for _ in range(4)]
        self._lock  = threading.Lock()

        self.moisture_warn = list(DEFAULT_MOISTURE_WARN)
        self._load_settings()

        # UI state
        self.state      = STATE_MAIN
        self.cursor     = 0       # index in current list
        self.sub_plot   = 0       # which plot the detail/edit screen is for
        self.edit_value = 0.0

        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    # ── Startup ───────────────────────────────────────────────────────────────

    def _handle_ready(self):
        self.display = self.printer.lookup_object("display", None)
        if self.display is None:
            log.warning("lcd_plants: no [display]")
            return
        self.display.menu = self
        self.reactor.register_timer(self._poll_tick, self.reactor.NOW)
        log.info("lcd_plants: ready | dir=%s | plant=%s",
                 self.log_dir, self.plant_name)

    # ── Menu shim ─────────────────────────────────────────────────────────────

    def screen_update_event(self, eventtime):
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
        if key in ('up', 'fast_up'):
            self._scroll(-1)
        elif key in ('down', 'fast_down'):
            self._scroll(1)
        elif key == 'click':
            self._select()
        elif key in ('long_click', 'back'):
            self._back()

    # ── Input ─────────────────────────────────────────────────────────────────

    def _list_len(self):
        """Number of items in the current scrollable list."""
        if self.state == STATE_MAIN:
            return 4 + 1          # 4 plots + "Commands" entry
        elif self.state == STATE_DETAIL:
            return len(DETAIL_ROWS)
        elif self.state == STATE_CMDS:
            return len(COMMANDS)
        elif self.state == STATE_EDIT:
            return 1              # single value, scroll adjusts it
        return 1

    def _scroll(self, direction):
        if self.state == STATE_EDIT:
            # Scroll adjusts the edit value instead of moving cursor
            self.edit_value = max(0.0,
                                  min(1023.0,
                                      self.edit_value + direction * 10.0))
            return
        n = self._list_len()
        self.cursor = (self.cursor + direction) % n

    def _select(self):
        if self.state == STATE_MAIN:
            if self.cursor < 4:
                # Open plot detail
                self.sub_plot   = self.cursor
                self.cursor     = 0
                self.state      = STATE_DETAIL
            else:
                # Open commands menu
                self.cursor = 0
                self.state  = STATE_CMDS

        elif self.state == STATE_DETAIL:
            if self.cursor == WARN_ROW_IDX:
                # Enter edit mode for this plot's Warn threshold
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
            # Save and return to detail
            self.moisture_warn[self.sub_plot] = self.edit_value
            self._save_settings()
            self.cursor = WARN_ROW_IDX
            self.state  = STATE_DETAIL

    def _back(self):
        if self.state == STATE_DETAIL:
            self.cursor = self.sub_plot
            self.state  = STATE_MAIN
        elif self.state == STATE_CMDS:
            self.cursor = 4       # restore cursor to Commands entry
            self.state  = STATE_MAIN
        elif self.state == STATE_EDIT:
            # Cancel — discard changes
            self.cursor = WARN_ROW_IDX
            self.state  = STATE_DETAIL

    # ── File discovery ────────────────────────────────────────────────────────

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
            log.error("lcd_plants parse %s: %s", path, exc)
            return
        pd = self._parse(raw, mtime)
        with self._lock:
            self._plots[idx].copy_from(pd)

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

    # ─────────────────────────────────────────────────────────────────────────
    # Drawing primitives
    # ─────────────────────────────────────────────────────────────────────────

    def _row(self, row, text, eventtime):
        """Write one full display row, padded/truncated to LCD_COLS."""
        if 0 <= row < LCD_ROWS:
            self.display.draw_text(row, 0,
                                   text[:LCD_COLS].ljust(LCD_COLS),
                                   eventtime)

    def _draw_list(self, eventtime, title, items, hint):
        """
        Generic scrollable list renderer.

        Row 0: title (fixed)
        Row 1: items[cursor]     with '>' prefix if selected
        Row 2: items[cursor+1]   (wraps around list)
        Row 3: hint (fixed)

        items: list of strings, already formatted to fit LCD_COLS-2
        """
        n = len(items)
        if n == 0:
            self._row(0, title,         eventtime)
            self._row(1, "  (empty)",   eventtime)
            self._row(2, "",            eventtime)
            self._row(3, hint,          eventtime)
            return

        self._row(0, title, eventtime)

        for slot in range(CONTENT_ROWS):
            idx    = (self.cursor + slot) % n
            item   = items[idx]
            prefix = ">" if slot == 0 else " "
            # Add scroll indicators on the second content row
            if slot == 1 and n > 2:
                suffix = chr(0x19)  # down-arrow glyph if available, else space
            else:
                suffix = ""
            line = prefix + " " + item
            self._row(slot + 1, line, eventtime)

        self._row(3, hint, eventtime)

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN MENU
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_main(self, eventtime):
        """
        Items:
          Plot 1  [M:378 ADC !]    ← dry warning shown inline
          Plot 2  [M:376 ADC  ]
          Plot 3  [M:365 ADC  ]
          Plot 4  [M:390 ADC !]
          Commands >
        """
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
            warn_flag = "!" if dry else " "
            if pd.error:
                val = pd.error[:6]
            else:
                val = ("%d ADC" % pd.soil_moisture
                       if pd.soil_moisture is not None else "-- ADC")
            # "Plot 1 378 ADC !" fits in 14 chars (prefix + space = 16)
            items.append("Plot %d %s %s" % (i + 1, val, warn_flag))

        items.append("Commands >")

        self._draw_list(eventtime,
                        title="Plant Monitor",
                        items=items,
                        hint="Clk=open Lng=--")

    # ─────────────────────────────────────────────────────────────────────────
    # PLOT DETAIL
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_detail(self, eventtime):
        """
        Scrollable list of sensor readings + editable Warn threshold.

        Items:
          Moisture: 378 ADC
          Humidity: 8.4 %
          Temp:     24.6 C
          Watering: 0 recs
          Alerts:   none
          Warn:     400 ADC  ← click to edit
        """
        idx = self.sub_plot
        with self._lock:
            pd = PlotData()
            pd.copy_from(self._plots[idx])
        thr = self.moisture_warn[idx]

        # Build title
        t_str = (" @%s" % pd.last_minute) if pd.last_minute else ""
        title = ("Plot %d%s" % (idx + 1, t_str))[:LCD_COLS]

        # Build item strings
        items = []
        for row_idx, (label, key, fmt) in enumerate(DETAIL_ROWS):
            if key is None:
                # Warn threshold row
                item = "Warn:     %d ADC" % thr
            elif pd.error:
                item = "%s: ---" % label
            else:
                val  = getattr(pd, key, None)
                item = "%s: %s" % (label, fmt(val))

            # Mark the Warn row as clickable
            if row_idx == WARN_ROW_IDX:
                item = item[:13] + " >"

            items.append(item)

        hint = "Clk=edit Lng=back" if self.cursor == WARN_ROW_IDX \
               else "Scrl=mv  Lng=back"

        self._draw_list(eventtime, title=title, items=items, hint=hint)

    # ─────────────────────────────────────────────────────────────────────────
    # COMMAND MENU
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_cmds(self, eventtime):
        items = [label for label, _ in COMMANDS]
        self._draw_list(eventtime,
                        title="Commands",
                        items=items,
                        hint="Clk=run  Lng=back")

    # ─────────────────────────────────────────────────────────────────────────
    # EDIT SCREEN
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_edit(self, eventtime):
        """
        Row 0  [ Plot 1 Warn ]
        Row 1    Current: 400 ADC
        Row 2  > Set:     410 ADC   ← scroll to adjust ±10
        Row 3    Clk=save Lng=cncl
        """
        idx = self.sub_plot
        thr = self.moisture_warn[idx]

        self._row(0, "Plot %d Warn ADC" % (idx + 1), eventtime)
        self._row(1, "  Current:%d ADC" % thr,        eventtime)
        self._row(2, "> Set:    %d ADC" % self.edit_value, eventtime)
        self._row(3, "Clk=save Lng=cncl", eventtime)


# ── Klipper entry point ───────────────────────────────────────────────────────

def load_config(config):
    return LcdPlants(config)