# WARNING: GOES IN /media/sd_host/KlipperUSB/klipperusb/klipper/klippy/extras/ on the DEVICE
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
# ── Screen layout (8 rows × 21 cols) ─────────────────────────────────────────
#
#  GRID + COMMAND BAR
#   Row 0  >plot1    | plot2        label row (> = selected, ! = dry warning)
#   Row 1   M:378 H:8| M:376 H:8   moisture + humidity
#   Row 2  ----------+---------     divider
#   Row 3   plot3    | plot4
#   Row 4   M:365 H:3| M:390 H:8
#   Row 5  ═════════════════════    command section divider
#   Row 6  [LightsON][Pump ON]...   command bar (scroll to highlight)
#   Row 7   Clk=run  2xClk=plots   hint
#
#  PLOT SUBMENU  (opens when cursor is on a plot cell and you click)
#   Row 0  [ plot N @ HH:MM ]
#   Row 1    Moisture: <raw ADC>
#   Row 2    Humidity: <pct>%
#   Row 3    Temp:     <C> C
#   Row 4    Watering: <n> recs
#   Row 5    Alerts:   <scrolling text>
#   Row 6    Warn ADC: <threshold>  ← editable
#   Row 7    hint bar
#
# ── Navigation ────────────────────────────────────────────────────────────────
#  GRID VIEW
#    Scroll           → cursor moves: plots 0-3, then commands 4-(4+N-1)
#    Click (on plot)  → open plot submenu
#    Click (on cmd)   → run that gcode command immediately
#    2×Click          → toggle between plot-zone and command-zone
#
#  PLOT SUBMENU
#    Scroll  → move row cursor
#    Click   → edit Warn ADC value / confirm Back
#    2×Click → back to grid
#
#  EDIT MODE
#    Scroll  → adjust ADC threshold (step 10, range 0-1023)
#    Click   → confirm & save
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import glob
import time
import logging
import threading
import datetime

log = logging.getLogger(__name__)

# ── Display geometry ──────────────────────────────────────────────────────────
LCD_COLS = 21
LCD_ROWS = 8

# ── UI states ─────────────────────────────────────────────────────────────────
STATE_GRID    = "grid"
STATE_SUBMENU = "submenu"
STATE_EDIT    = "edit"

# ── Grid cursor zones ─────────────────────────────────────────────────────────
# Cursor 0-3   → plot cells
# Cursor 4+    → command bar items
PLOT_COUNT = 4

# ── Command bar definitions ───────────────────────────────────────────────────
# Each entry: (display_label, gcode_string)
# Labels are truncated to fit; keep them ≤9 chars.
# Add, remove, or reorder freely — the bar scrolls automatically.
COMMANDS = [
    ("LightON",  "LIGHT_ON"),
    ("LightOFF", "LIGHT_OFF"),
    ("Pump ON",  "PUMP_ON"),
    ("Pump OFF", "PUMP_OFF"),
    ("Home XY",  "HOME_XY"),
    ("Center",   "CENTER"),
    ("Mtr OFF",  "MOTORS_OFF"),
]

# ── Submenu field indices ─────────────────────────────────────────────────────
FIELD_MOISTURE      = 0
FIELD_HUMIDITY      = 1
FIELD_TEMP          = 2
FIELD_WATERING      = 3
FIELD_ALERTS        = 4
FIELD_MOISTURE_WARN = 5   # editable
FIELD_BACK          = 6
SUBMENU_COUNT       = 7

READONLY_FIELDS = {FIELD_MOISTURE, FIELD_HUMIDITY, FIELD_TEMP,
                   FIELD_WATERING, FIELD_ALERTS}
EDITABLE_FIELDS = {FIELD_MOISTURE_WARN}

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MOISTURE_WARN = [400, 400, 400, 400]

SETTINGS_FILE  = "/tmp/plant_lcd_settings.json"
DOUBLE_CLICK_S = 0.45

# ── Total cursor positions ────────────────────────────────────────────────────
CURSOR_TOTAL = PLOT_COUNT + len(COMMANDS)   # 4 plots + N commands


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

        # ── UI state ──────────────────────────────────────────────────────────
        self.state       = STATE_GRID
        # grid_cursor: 0-3 = plots, 4+ = commands
        self.grid_cursor = 0
        self.sub_cursor  = 0
        self.edit_value  = 0.0
        self._last_click = 0.0

        # Alert scrolling
        self._alert_tick   = 0
        self._alert_offset = 0

        # Command bar: which command is the leftmost visible in the 21-col bar
        # The bar shows as many labels as fit; we scroll the window.
        self._cmd_scroll = 0   # index of leftmost visible command

        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    # ── Startup ───────────────────────────────────────────────────────────────

    def _handle_ready(self):
        self.display = self.printer.lookup_object("display", None)
        if self.display is None:
            log.warning("lcd_plants: no [display]")
            return

        self.display.encoder_callback = self._on_encoder
        self.display.button_callback  = self._on_button

        self.reactor.register_timer(self._poll_tick,   self.reactor.NOW)
        self.reactor.register_timer(self._render_tick, self.reactor.NOW)
        log.info("lcd_plants: ready | dir=%s | plant=%s",
                 self.log_dir, self.plant_name)

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
                    self._plots[i].error = "poll err"
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
        pd.file_mtime = mtime
        pd.plot_id    = raw.get("plot_id")
        pd.file_date  = raw.get("date", "?")
        summary = raw.get("minute_summary", {})
        if not summary:
            pd.error = "empty"
            return pd
        latest_key     = sorted(summary.keys())[-1]
        m              = summary[latest_key]
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

    # ── Helper: is cursor on a plot cell? ────────────────────────────────────

    @property
    def _on_plot(self):
        return self.grid_cursor < PLOT_COUNT

    @property
    def _cmd_index(self):
        """Which COMMANDS entry is currently selected (when on cmd zone)."""
        return self.grid_cursor - PLOT_COUNT

    # ── Input ─────────────────────────────────────────────────────────────────

    def _on_encoder(self, direction):
        if self.state == STATE_GRID:
            self.grid_cursor = (self.grid_cursor + direction) % CURSOR_TOTAL
            # Keep command bar scroll window centred on selected command
            if not self._on_plot:
                self._sync_cmd_scroll()

        elif self.state == STATE_SUBMENU:
            self.sub_cursor = (self.sub_cursor + direction) % SUBMENU_COUNT

        elif self.state == STATE_EDIT:
            self.edit_value = max(0.0,
                                  min(1023.0, self.edit_value + direction * 10.0))

    def _sync_cmd_scroll(self):
        """
        Ensure the selected command is visible in the command bar.
        The bar is 21 chars wide. Each label slot is 10 chars ([label   ]).
        Two slots fit side-by-side (2 × 10 = 20 + 1 divider = 21).
        We show a sliding window of 2 commands at a time.
        """
        cmd_i = self._cmd_index
        # Window start: show cmd_i and cmd_i+1 (or whatever fits)
        # Just make sure cmd_i is always the leftmost visible
        window_size = 2
        self._cmd_scroll = max(0,
                               min(cmd_i,
                                   len(COMMANDS) - window_size))

    def _on_button(self):
        now    = time.time()
        double = (now - self._last_click) < DOUBLE_CLICK_S
        self._last_click = now

        if self.state == STATE_GRID:
            if double:
                # Double-click: jump cursor to opposite zone
                if self._on_plot:
                    self.grid_cursor = PLOT_COUNT   # jump to first command
                    self._sync_cmd_scroll()
                else:
                    self.grid_cursor = 0            # jump back to plot 1
                return

            if self._on_plot:
                # Single click on a plot → open submenu
                self.sub_cursor  = 0
                self._alert_tick = 0
                self.state       = STATE_SUBMENU
            else:
                # Single click on a command → run it
                cmd_label, gcode = COMMANDS[self._cmd_index]
                try:
                    gcode_obj = self.printer.lookup_object("gcode")
                    gcode_obj.run_script_from_command(gcode)
                    log.info("lcd_plants: ran command %s", gcode)
                except Exception as exc:
                    log.error("lcd_plants: command %s failed: %s", gcode, exc)

        elif self.state == STATE_SUBMENU:
            if double or self.sub_cursor == FIELD_BACK:
                self.state = STATE_GRID
                return
            f = self.sub_cursor
            if f in READONLY_FIELDS:
                pass
            elif f in EDITABLE_FIELDS:
                self.edit_value = float(self.moisture_warn[self.grid_cursor])
                self.state = STATE_EDIT

        elif self.state == STATE_EDIT:
            self.moisture_warn[self.grid_cursor] = self.edit_value
            self._save_settings()
            self.state = STATE_SUBMENU

    # ── Render loop ───────────────────────────────────────────────────────────

    def _render_tick(self, eventtime):
        if not hasattr(self, "display") or self.display is None:
            return eventtime + 0.2
        try:
            self._alert_tick += 1
            if self._alert_tick % 10 == 0:
                self._alert_offset += 1
            if self.state == STATE_GRID:
                self._draw_grid()
            else:
                self._draw_submenu()
        except Exception as exc:
            log.exception("lcd_plants render: %s", exc)
        return eventtime + 0.2

    # ─────────────────────────────────────────────────────────────────────────
    # GRID RENDERER
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_grid(self):
        """
        Compressed 2×2 grid (rows 0-4) + command bar (rows 5-7).

         col: 0         1         2
              012345678901234567890
         row 0  >plot1!  | plot2       label (> selected, ! dry)
         row 1   M:378 H:| M:376 H     moisture + humidity
         row 2  ---------+----------   horizontal divider
         row 3   plot3   | plot4
         row 4   M:365 H:| M:390 H
         row 5  ═══ Commands ════════  section header
         row 6  [LightON ][Pump ON ]   command slots (scrollable)
         row 7   Clk=run  2x=plots     hint

        Each cell: 9 chars wide. Col 10 = vertical divider.
        Command slots: two 10-char slots per row, [ label    ].
        """
        lcd = self.display
        lcd.clear()

        # ── Grid chrome ───────────────────────────────────────────────────
        for r in (0, 1, 3, 4):
            lcd.write_text(10, r, "|")
        lcd.write_text(0, 2, "-" * 10 + "+" + "-" * 10)

        # ── Snapshot ──────────────────────────────────────────────────────
        snaps = []
        with self._lock:
            for i in range(4):
                s = PlotData()
                s.copy_from(self._plots[i])
                snaps.append(s)

        cell_col = [0, 11, 0, 11]
        cell_row = [0,  0, 3,  3]

        for i, pd in enumerate(snaps):
            col = cell_col[i]
            row = cell_row[i]
            sel = (self._on_plot and i == self.grid_cursor)
            dry = (pd.soil_moisture is not None and
                   pd.soil_moisture > self.moisture_warn[i])

            # Row 0/3 — label
            prefix = ">" if sel else " "
            suffix = "!" if dry else " "
            label  = ("%splot%d%s" % (prefix, i + 1, suffix))[:9]
            lcd.write_text(col, row, label.ljust(9))

            # Row 1/4 — M + H  (9 chars per cell, no W/A row)
            if pd.error:
                vals = pd.error[:9]
            else:
                ms = ("M:%.0f" % pd.soil_moisture
                      if pd.soil_moisture is not None else "M:---")
                hs = ("H:%.0f" % pd.humidity
                      if pd.humidity is not None else "H:--")
                vals = ("%s %s" % (ms, hs))[:9]
            lcd.write_text(col, row + 1, vals.ljust(9))

        # ── Command section header (row 5) ────────────────────────────────
        lcd.write_text(0, 5, "= Commands " + "=" * 10)

        # ── Command bar (row 6) ───────────────────────────────────────────
        # Show two 10-char slots: [label    ] side by side = 20 chars + space
        # Scroll window starts at self._cmd_scroll
        bar = ""
        for slot in range(2):
            cmd_i = self._cmd_scroll + slot
            if cmd_i >= len(COMMANDS):
                bar += " " * 10
                continue
            label, _ = COMMANDS[cmd_i]
            selected  = (not self._on_plot and self._cmd_index == cmd_i)
            # Selected command gets angle brackets instead of square
            if selected:
                slot_str = ("<%s>" % label[:7]).ljust(10)
            else:
                slot_str = ("[%s]" % label[:7]).ljust(10)
            bar += slot_str
        # Pad to LCD width and add scroll indicator if more commands exist
        bar = bar[:20]
        more_right = (self._cmd_scroll + 2) < len(COMMANDS)
        more_left  = self._cmd_scroll > 0
        indicator  = (">" if more_right else (" " if not more_left else "<"))
        lcd.write_text(0, 6, bar + indicator)

        # ── Hint bar (row 7) ──────────────────────────────────────────────
        if self._on_plot:
            hint = "Clk=detail 2x=cmds"
        else:
            hint = "Clk=run    2x=plots"
        lcd.write_text(0, 7, hint[:LCD_COLS])

    # ─────────────────────────────────────────────────────────────────────────
    # SUBMENU RENDERER
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_submenu(self):
        """
        Row 0  [ plot N @ HH:MM ]
        Row 1    Moisture: <raw ADC>
        Row 2    Humidity: <pct>%
        Row 3    Temp:     <C> C
        Row 4    Watering: <n> recs
        Row 5    Alerts:   <scrolling text>
        Row 6    Warn ADC: <thr>  ← editable  /  < Back
        Row 7    hint
        """
        lcd = self.display
        lcd.clear()

        idx = self.grid_cursor
        with self._lock:
            pd = PlotData()
            pd.copy_from(self._plots[idx])
        thr = self.moisture_warn[idx]

        # Title
        title = "[ plot%d" % (idx + 1)
        if pd.last_minute:
            title += " @ %s" % pd.last_minute
        title += " ]"
        lcd.write_text(0, 0, title[:LCD_COLS].center(LCD_COLS))

        # Value strings
        if pd.error:
            m_s = "Moisture: %s" % pd.error
            h_s = "Humidity: ---"
            t_s = "Temp:     ---"
            w_s = "Watering: ---"
            a_s = "Alerts:   ---"
        else:
            m_s = "Moisture: %.0f" % (pd.soil_moisture or 0)
            h_s = "Humidity: %.1f%%" % (pd.humidity or 0)
            t_s = "Temp:     %.1f C" % (pd.temperature or 0)
            w_s = "Watering: %d rec%s" % (
                pd.water_count or 0,
                "s" if (pd.water_count or 0) != 1 else "")
            if pd.alerts:
                combined   = " / ".join(pd.alerts)
                win        = 13
                scroll_max = max(0, len(combined) - win)
                offset     = (self._alert_offset * 2) % (scroll_max + 1) \
                    if scroll_max else 0
                a_s = "Alerts: " + combined[offset:offset + win]
            else:
                a_s = "Alerts:   none"

        # Rows 1-5: read-only fields
        for field, text in enumerate([m_s, h_s, t_s, w_s, a_s]):
            sel    = (field == self.sub_cursor)
            marker = ">" if sel else " "
            lcd.write_text(0, field + 1, (marker + " " + text)[:LCD_COLS])

        # Row 6: Warn ADC or Back
        if self.sub_cursor == FIELD_BACK:
            r6 = ">  < Back"
        elif self.sub_cursor == FIELD_MOISTURE_WARN:
            if self.state == STATE_EDIT:
                r6 = ">  WarnADC:*%.0f*" % self.edit_value
            else:
                r6 = ">  Warn ADC: %.0f" % thr
        else:
            r6 = "   Warn ADC: %.0f" % thr
        lcd.write_text(0, 6, r6[:LCD_COLS])

        # Hint
        if self.state == STATE_EDIT:
            hint = "Scroll=adj  Click=save"
        else:
            hint = "Click=edit  2xClk=back"
        lcd.write_text(0, 7, hint[:LCD_COLS])


# ── Klipper entry point ───────────────────────────────────────────────────────

def load_config(config):
    return LcdPlants(config)