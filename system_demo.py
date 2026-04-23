import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from multiprocessing import Process
from TestTogether import soil_temp_sens
#from std_vis import camera_runtime
from ultrasonic_sensor import report_plant_growth

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
        (120.0, 120.0),
        (210.0, 120.0),
        (210.0, 1.0),
        (120.0, 1.0),
        (120.0, 120.0),
        (1.0,   100.0),
        (1.0,   1.0),
        (120.0, 1.0),
        (120.0, 120.0),
        (10.0,  235.0),
        (1.0,   100.0),
        (120.0, 120.0),
        (120.0, 235.0),
        (210.0, 235.0),
        (210.0, 120.0),
        (120.0, 120.0),
        (120.0, 210.0),
        (1.0,   1.0),
    ]
    while True:
        for x, y in positions:
            move_to(x, y)
            time.sleep(10)


if __name__ == "__main__":
    water_process    = Process(target=wateringlights)
    movement_process = Process(target=movement_test)
    soil_temp_process = Process(target=soil_temp_sens)
    #camera_process = Process(target=camera_runtime)
    ultrasonic_process = Process(target=report_plant_growth)

    #camera_process.start()
    water_process.start()
    movement_process.start()
    soil_temp_process.start()
    ultrasonic_process.start()

    #camera_process.join()
    water_process.join()
    movement_process.join()
    soil_temp_process.join()
    ultrasonic_process.join()