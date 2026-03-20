import json
import os
import time
from datetime import datetime

import board
import adafruit_tca9548a
import adafruit_ahtx0
from adafruit_seesaw.seesaw import Seesaw


PLOTS = [
    {"plot_id": 1, "soil_channel": 0, "air_channel": 4},
    {"plot_id": 2, "soil_channel": 1, "air_channel": 5},
    {"plot_id": 3, "soil_channel": 2, "air_channel": 6},
    {"plot_id": 4, "soil_channel": 3, "air_channel": 7},
]


class PlantController:
    def __init__(self, plant_file):
        with open(plant_file, "r", encoding="utf-8") as f:
            self.plant = json.load(f)

    def _check_range(self, value, min_value, max_value, low_msg, high_msg):
        if value < min_value:
            return low_msg
        if value > max_value:
            return high_msg
        return None

    def check_plant(self, plot_id, soil_moisture, humidity, temperature_c):
        checks = [
            {
                "name": "soil",
                "value": soil_moisture,
                "min": self.plant["soil_min"],
                "max": self.plant["soil_max"],
                "low_msg": "Soil is too dry",
                "high_msg": "Soil is too wet"
            },
            {
                "name": "humidity",
                "value": humidity,
                "min": self.plant["humidity_min"],
                "max": self.plant["humidity_max"],
                "low_msg": "Humidity is too low",
                "high_msg": "Humidity is too high"
            },
            {
                "name": "temperature",
                "value": temperature_c,
                "min": self.plant["temp_min_c"],
                "max": self.plant["temp_max_c"],
                "low_msg": "Temperature is too low",
                "high_msg": "Temperature is too high"
            }
        ]

        alerts = []
        watering_recommended = False

        for check in checks:
            alert = self._check_range(
                check["value"],
                check["min"],
                check["max"],
                check["low_msg"],
                check["high_msg"]
            )

            if alert:
                alerts.append(alert)

            if check["name"] == "soil" and alert == "Soil is too dry":
                watering_recommended = True

        if watering_recommended:
            recommendation = (
                f"Watering recommended for plot {plot_id}. "
                f"Suggested pump time: {self.plant['pump_seconds']} seconds"
            )
        else:
            recommendation = f"No watering recommended for plot {plot_id} at this time"

        return {
            "plant": self.plant["name"],
            "plot_id": plot_id,
            "soil_moisture": soil_moisture,
            "humidity": humidity,
            "temperature_c": temperature_c,
            "alerts": alerts,
            "watering_recommended": watering_recommended,
            "recommendation": recommendation
        }


class SummaryLogger:
    def __init__(self, plant_name, plot_id, log_folder="logs", reset_today_on_start=False):
        self.plant_name = plant_name
        self.plot_id = plot_id
        self.log_folder = log_folder
        os.makedirs(self.log_folder, exist_ok=True)

        self.current_date = None
        self.current_minute = None
        self.minute_bucket = None

        if reset_today_on_start:
            today = datetime.now().strftime("%Y-%m-%d")
            file_path = self._get_file_path(today)
            if os.path.exists(file_path):
                os.remove(file_path)

    def _new_bucket(self):
        return {
            "count": 0,
            "soil_sum": 0.0,
            "soil_min": None,
            "soil_max": None,
            "humidity_sum": 0.0,
            "humidity_min": None,
            "humidity_max": None,
            "temp_sum": 0.0,
            "temp_min": None,
            "temp_max": None,
            "watering_recommended_count": 0,
            "alerts_count": {}
        }

    def _update_bucket(self, bucket, result):
        soil = result["soil_moisture"]
        humidity = result["humidity"]
        temp = result["temperature_c"]

        bucket["count"] += 1
        bucket["soil_sum"] += soil
        bucket["humidity_sum"] += humidity
        bucket["temp_sum"] += temp

        bucket["soil_min"] = soil if bucket["soil_min"] is None else min(bucket["soil_min"], soil)
        bucket["soil_max"] = soil if bucket["soil_max"] is None else max(bucket["soil_max"], soil)

        bucket["humidity_min"] = humidity if bucket["humidity_min"] is None else min(bucket["humidity_min"], humidity)
        bucket["humidity_max"] = humidity if bucket["humidity_max"] is None else max(bucket["humidity_max"], humidity)

        bucket["temp_min"] = temp if bucket["temp_min"] is None else min(bucket["temp_min"], temp)
        bucket["temp_max"] = temp if bucket["temp_max"] is None else max(bucket["temp_max"], temp)

        if result["watering_recommended"]:
            bucket["watering_recommended_count"] += 1

        for alert in result["alerts"]:
            bucket["alerts_count"][alert] = bucket["alerts_count"].get(alert, 0) + 1

    def _finalize_bucket(self, bucket):
        count = bucket["count"]
        if count == 0:
            return {}

        return {
            "count": count,
            "avg_soil_moisture": round(bucket["soil_sum"] / count, 2),
            "min_soil_moisture": bucket["soil_min"],
            "max_soil_moisture": bucket["soil_max"],
            "avg_humidity": round(bucket["humidity_sum"] / count, 2),
            "min_humidity": round(bucket["humidity_min"], 2),
            "max_humidity": round(bucket["humidity_max"], 2),
            "avg_temperature_c": round(bucket["temp_sum"] / count, 2),
            "min_temperature_c": round(bucket["temp_min"], 2),
            "max_temperature_c": round(bucket["temp_max"], 2),
            "watering_recommended_count": bucket["watering_recommended_count"],
            "alerts_count": bucket["alerts_count"]
        }

    def _get_file_path(self, date_str):
        return os.path.join(
            self.log_folder,
            f"{self.plant_name}_plot{self.plot_id}_{date_str}.json"
        )

    def _load_day_file(self, date_str):
        file_path = self._get_file_path(date_str)

        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f), file_path

        data = {
            "plant": self.plant_name,
            "plot_id": self.plot_id,
            "date": date_str,
            "minute_summary": {},
            "hour_summary": {}
        }
        return data, file_path

    def _rebuild_hour_summary(self, data):
        hour_groups = {}

        for minute_key, minute_data in data["minute_summary"].items():
            hour_key = minute_key[:2]
            hour_groups.setdefault(hour_key, []).append(minute_data)

        hour_summary = {}
        for hour_key, minute_list in sorted(hour_groups.items()):
            total_count = sum(item["count"] for item in minute_list)
            if total_count == 0:
                continue

            soil_weighted_sum = sum(item["avg_soil_moisture"] * item["count"] for item in minute_list)
            humidity_weighted_sum = sum(item["avg_humidity"] * item["count"] for item in minute_list)
            temp_weighted_sum = sum(item["avg_temperature_c"] * item["count"] for item in minute_list)

            alerts_count = {}
            watering_count = 0

            for item in minute_list:
                watering_count += item["watering_recommended_count"]
                for alert, count in item.get("alerts_count", {}).items():
                    alerts_count[alert] = alerts_count.get(alert, 0) + count

            hour_summary[hour_key] = {
                "count": total_count,
                "avg_soil_moisture": round(soil_weighted_sum / total_count, 2),
                "min_soil_moisture": min(item["min_soil_moisture"] for item in minute_list),
                "max_soil_moisture": max(item["max_soil_moisture"] for item in minute_list),
                "avg_humidity": round(humidity_weighted_sum / total_count, 2),
                "min_humidity": round(min(item["min_humidity"] for item in minute_list), 2),
                "max_humidity": round(max(item["max_humidity"] for item in minute_list), 2),
                "avg_temperature_c": round(temp_weighted_sum / total_count, 2),
                "min_temperature_c": round(min(item["min_temperature_c"] for item in minute_list), 2),
                "max_temperature_c": round(max(item["max_temperature_c"] for item in minute_list), 2),
                "watering_recommended_count": watering_count,
                "alerts_count": alerts_count
            }

        data["hour_summary"] = hour_summary

    def add_reading(self, result, now):
        date_str = now.strftime("%Y-%m-%d")
        minute_key = now.strftime("%H:%M")

        if self.current_date is None:
            self.current_date = date_str
            self.current_minute = minute_key
            self.minute_bucket = self._new_bucket()

        elif date_str != self.current_date or minute_key != self.current_minute:
            self._write_current_minute()
            self.current_date = date_str
            self.current_minute = minute_key
            self.minute_bucket = self._new_bucket()

        self._update_bucket(self.minute_bucket, result)
        self._write_current_minute()

    def _write_current_minute(self):
        if self.minute_bucket is None or self.minute_bucket["count"] == 0:
            return

        data, file_path = self._load_day_file(self.current_date)
        data["minute_summary"][self.current_minute] = self._finalize_bucket(self.minute_bucket)
        self._rebuild_hour_summary(data)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def close(self):
        self._write_current_minute()


def setup_sensors():
    i2c = board.I2C()
    tca = adafruit_tca9548a.TCA9548A(i2c)

    soil_sensors = {
        0: Seesaw(tca[0], addr=0x36),
        1: Seesaw(tca[1], addr=0x36),
        2: Seesaw(tca[2], addr=0x36),
        3: Seesaw(tca[3], addr=0x36),
    }

    air_sensors = {
        4: adafruit_ahtx0.AHTx0(tca[4]),
        5: adafruit_ahtx0.AHTx0(tca[5]),
        6: adafruit_ahtx0.AHTx0(tca[6]),
        7: adafruit_ahtx0.AHTx0(tca[7]),
    }

    return soil_sensors, air_sensors


def read_plot_sensors(plot, soil_sensors, air_sensors):
    soil_sensor = soil_sensors[plot["soil_channel"]]
    air_sensor = air_sensors[plot["air_channel"]]

    soil_moisture = soil_sensor.moisture_read()
    humidity = air_sensor.relative_humidity
    temperature_c = air_sensor.temperature

    return soil_moisture, humidity, temperature_c


if __name__ == "__main__":
    print("RUNNING:", __file__)

    controller = PlantController("plants/basil.json")
    soil_sensors, air_sensors = setup_sensors()

    loggers = {
        plot["plot_id"]: SummaryLogger(
            plant_name=controller.plant["name"],
            plot_id=plot["plot_id"],
            log_folder="logs",
            reset_today_on_start=True
        )
        for plot in PLOTS
    }

    sample_interval_seconds = 20

    try:
        while True:
            now = datetime.now()
            print("=" * 70)
            print("Time:", now.strftime("%Y-%m-%d %H:%M:%S"))

            for plot in PLOTS:
                plot_id = plot["plot_id"]
                logger = loggers[plot_id]

                try:
                    soil_moisture, humidity, temperature_c = read_plot_sensors(
                        plot, soil_sensors, air_sensors
                    )

                    result = controller.check_plant(
                        plot_id=plot_id,
                        soil_moisture=soil_moisture,
                        humidity=humidity,
                        temperature_c=temperature_c
                    )

                    logger.add_reading(result, now)

                    print(f"Plot {plot_id}")
                    print(f"  Soil Channel: {plot['soil_channel']}")
                    print(f"  Air Channel: {plot['air_channel']}")
                    print(f"  Soil Moisture: {result['soil_moisture']}")
                    print(f"  Humidity: {result['humidity']:.2f}")
                    print(f"  Temperature (C): {result['temperature_c']:.2f}")
                    print(f"  Alerts: {result['alerts']}")
                    print(f"  Watering Recommended: {result['watering_recommended']}")
                    print(f"  Recommendation: {result['recommendation']}")
                    print()

                except Exception as e:
                    print(f"Plot {plot_id} Error: {e}")
                    print()

            time.sleep(sample_interval_seconds)

    except KeyboardInterrupt:
        for logger in loggers.values():
            logger.close()
        print("\nStopped by user.")