import time
import board
import adafruit_ahtx0

i2c = board.I2C()  # SDA/SCL
sensor = adafruit_ahtx0.AHTx0(i2c)

print("AHTx0 detected, reading...")
while True:
    print(f"Temp: {sensor.temperature:.2f} C  Humidity: {sensor.relative_humidity:.2f} %")
    time.sleep(2)