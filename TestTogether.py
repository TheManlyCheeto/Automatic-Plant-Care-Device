#!/usr/bin/env python3

import os
import json
import time
import datetime

import board
import adafruit_tca9548a
import adafruit_ahtx0
from adafruit_seesaw.seesaw import Seesaw

# ── Config ───────────────────────────────────────────────────────────────────
LOG_DIR           = "/home/sd_host/Documents/Automatic-Plant-Care-Device/logs"
PLANT_NAME        = "basil_1"
POLL_INTERVAL     = 60
MOISTURE_WARN     = 400

os.makedirs(LOG_DIR, exist_ok=True)

# ── Hardware ─────────────────────────────────────────────────────────────────
i2c = board.I2C()
tca = adafruit_tca9548a.TCA9548A(i2c)

soil_0 = Seesaw(tca[0], addr=0x36)
soil_1 = Seesaw(tca[1], addr=0x36)
soil_2 = Seesaw(tca[2], addr=0x36)
soil_3 = Seesaw(tca[3], addr=0x36)

aht4 = adafruit_ahtx0.AHTx0(tca[4])
aht5 = adafruit_ahtx0.AHTx0(tca[5])

# Plot index → sensor mapping
SOIL_SENSORS = [soil_0, soil_1, soil_2, soil_3]
AIR_SENSORS  = [aht4, aht4, aht5, aht5]


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")

def now_minute_str():
    return datetime.datetime.now().strftime("%H:%M")

def log_path(plot_num):
    return os.path.join(LOG_DIR, "%s_plot%d_%s.json" % (PLANT_NAME, plot_num, today_str()))

# ── File helpers ─────────────────────────────────────────────────────────────
def load_log(path, plot_num):
    if os.path.isfile(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "plant":          PLANT_NAME,
        "plot_id":        plot_num,
        "date":           today_str(),
        "minute_summary": {},
    }

def write_log(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

# ── Build a single minute_summary entry ──────────────────────────────────────
def build_entry(moisture, air_temp, air_humidity):
    alerts = {}
    if air_humidity < 30.0:
        alerts["Humidity is too low"] = 1
    if air_humidity > 80.0:
        alerts["Humidity is too high"] = 1
    if air_temp > 35.0:
        alerts["Temperature is too high"] = 1
    if air_temp < 10.0:
        alerts["Temperature is too low"] = 1

    return {
        "count":                      1,
        "avg_soil_moisture":          round(float(moisture), 1),
        "min_soil_moisture":          int(moisture),
        "max_soil_moisture":          int(moisture),
        "avg_humidity":               round(float(air_humidity), 2),
        "min_humidity":               round(float(air_humidity), 2),
        "max_humidity":               round(float(air_humidity), 2),
        "avg_temperature_c":          round(float(air_temp), 2),
        "min_temperature_c":          round(float(air_temp), 2),
        "max_temperature_c":          round(float(air_temp), 2),
        "watering_recommended_count": 1 if moisture < MOISTURE_WARN else 0,
        "alerts_count":               alerts,
    }


# ── Main loop ────────────────────────────────────────────────────────────────
while True:
    minute_key = now_minute_str()

    for i in range(4):
        plot_num = i + 1
        try:
            moisture     = SOIL_SENSORS[i].moisture_read()
            air_temp     = AIR_SENSORS[i].temperature
            air_humidity = AIR_SENSORS[i].relative_humidity
        except Exception as e:
            print(f"Plot {plot_num} error: {e}")
            continue

        path     = log_path(plot_num)
        log_data = load_log(path, plot_num)
        log_data["date"] = today_str()
        log_data["minute_summary"][minute_key] = build_entry(
            moisture, air_temp, air_humidity
        )
        write_log(path, log_data)

        print(f"Plot {plot_num} [{minute_key}] M:{moisture} T:{air_temp:.1f}C H:{air_humidity:.1f}%")

    time.sleep(POLL_INTERVAL)