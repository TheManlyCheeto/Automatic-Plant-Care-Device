import time
import board
import adafruit_ahtx0
from adafruit_seesaw.seesaw import Seesaw

# Main Raspberry Pi I2C bus
i2c = board.I2C()

# AHT20 on main I2C
aht20 = adafruit_ahtx0.AHTx0(i2c)

# Soil sensor on main I2C, usually address 0x36
soil = Seesaw(i2c, addr=0x36)


while True:
    try:
        air_temp_c = aht20.temperature
        humidity = aht20.relative_humidity

        soil_temp_c = soil.get_temp()
        moisture = soil.moisture_read()

        print("AHT20:")
        print(f"  Air Temp: {air_temp_c:.2f} C")
        print(f"  Humidity: {humidity:.2f} %")

        print("Soil Sensor:")
        print(f"  Soil Temp: {soil_temp_c:.2f} C")
        print(f"  Moisture: {moisture}")

        print("-" * 40)
        time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopped by user.")
        break

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(2)