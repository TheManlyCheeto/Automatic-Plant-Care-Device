import time 
import board 
import busio
from adafruit_seesaw.seesaw import Seesaw
# basic test file for Soil Sensor.
i2c = busio.I2C(board.SCL, board.SDA)
sensor = Seesaw(i2c, addr=0x36)

while True:
    print("moisture", sensor.moisture_read(),
          "temp (C):", round(sensor.get_temp(), 2))
    time.sleep(1)