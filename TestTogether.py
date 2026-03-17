import time
import board
import adafruit_tca9548a
from adafruit_seesaw.seesaw import Seesaw

# Main Raspberry Pi I2C bus
i2c = board.I2C()

# TCA9548A multiplexer on the main bus
tca = adafruit_tca9548a.TCA9548A(i2c)

# Create one soil sensor per channel
soil_0 = Seesaw(tca[0], addr=0x36)   # sensor on channel 0
soil_1 = Seesaw(tca[1], addr=0x36)   # sensor on channel 1

while True:
    moisture_0 = soil_0.moisture_read()
    temp_0 = soil_0.get_temp()

    moisture_1 = soil_1.moisture_read()
    temp_1 = soil_1.get_temp()

    print(f"Channel 0 -> Temp: {temp_0:.2f} C, Moisture: {moisture_0}")
    print(f"Channel 1 -> Temp: {temp_1:.2f} C, Moisture: {moisture_1}")
    print("-" * 40)

    time.sleep(2)