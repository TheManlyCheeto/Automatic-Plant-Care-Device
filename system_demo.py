import time
import urllib.parse
import urllib.request
from datetime import datetime
from  zoneinfo import ZoneInfo


MOONRAKER_URL = "http://127.0.0.1:7125"
TIMEZONE = "America/Denver"

# MACRO DETAILS
ON_MACRO = "LIGHT_ON"
OFF_MACRO = "LIGHT_OFF"
PUMP_ON_MACRO = "PUMP_ON"
PUMP_OFF_MACRO = "PUMP_OFF"

ON_HOUR = 6
OFF_HOUR = 18

WATERING_TIME = 4
CHECK_INTERVAL_SECONDS = 30
last_on_date = None
last_off_date = None

def run_macro(macro_name: str) -> None:
    url = f"{MOONRAKER_URL}/printer/gcode/script?script={urllib.parse.quote(macro_name)}"
    req = urllib.request.Request(url,method="POST")
    with urllib.request.urlopen(req,timeout=10) as resp:
        body = resp.read().decode()
        print(f"[{datetime.now()}] Ran {macro_name}: {body}")