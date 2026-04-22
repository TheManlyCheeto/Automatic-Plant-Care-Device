import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from multiprocessing import Process

MOONRAKER_URL = "http://127.0.0.1:7125"
TIMEZONE = "America/Denver"

ON_MACRO   = "LIGHT_ON"
OFF_MACRO  = "LIGHT_OFF"
PUMP_ON_MACRO  = "PUMP_ON"
PUMP_OFF_MACRO = "PUMP_OFF"

ON_HOUR  = 6
OFF_HOUR = 18

WATERING_TIME          = 4
CHECK_INTERVAL_SECONDS = 30


def move_to(x: float, y: float, speed: int = 3000) -> None:
    gcode = f"G0 X{x} Y{y} F{speed}"
    url = f"{MOONRAKER_URL}/printer/gcode/script?script={urllib.parse.quote(gcode)}"
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()
        print(f"[{datetime.now()}] Moved to X{x} Y{y}: {body}")


def run_macro(macro_name: str) -> None:
    url = f"{MOONRAKER_URL}/printer/gcode/script?script={urllib.parse.quote(macro_name)}"
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()
        print(f"[{datetime.now()}] Ran {macro_name}: {body}")


def wateringlights() -> None:
    last_on_date  = None
    last_off_date = None
    tz = ZoneInfo(TIMEZONE)
    print(f"Watching time in {TIMEZONE}...")

    while True:
        now   = datetime.now(tz)
        today = now.date()
        try:
            if now.hour == ON_HOUR and last_on_date != today:
                run_macro(ON_MACRO)
                last_on_date = today
                run_macro(PUMP_ON_MACRO)
                time.sleep(WATERING_TIME)
                run_macro(PUMP_OFF_MACRO)

            if now.hour == OFF_HOUR and last_off_date != today:
                run_macro(OFF_MACRO)
                last_off_date = today

        except Exception as e:
            print(f"[{now}] Error: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


def movement_test() -> None:
    positions = [
        (0.0,   0.0),
        (120.0, 120.0),
        (210.0, 120.0),
        (210.0, 0.0),
        (120.0, 0.0),
        (120.0, 120.0),
        (0.0,   100.0),
        (0.0,   0.0),
        (120.0, 0.0),
        (120.0, 120.0),
        (10.0,  240.0),
        (0.0,   100.0),
        (120.0, 120.0),
        (120.0, 240.0),
        (210.0, 240.0),
        (210.0, 120.0),
        (120.0, 120.0),
        (120.0, 210.0),
        (0.0,   0.0),
    ]
    while True:
        for x, y in positions:
            move_to(x, y)
            time.sleep(10)


if __name__ == "__main__":
    water_process    = Process(target=wateringlights)
    movement_process = Process(target=movement_test)

    water_process.start()
    movement_process.start()

    water_process.join()
    movement_process.join()