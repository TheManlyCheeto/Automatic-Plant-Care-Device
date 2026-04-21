import time
import board
import adafruit_tca9548a
import adafruit_ahtx0
from adafruit_seesaw.seesaw import Seesaw

# Main Raspberry Pi I2C bus
i2c = board.I2C()

# TCA9548A multiplexer on the main bus
tca = adafruit_tca9548a.TCA9548A(i2c)

# Create one soil sensor per channel
soil_0 = Seesaw(tca[0], addr=0x36)   # sensor on channel 0
soil_1 = Seesaw(tca[1], addr=0x36)   # sensor on channel 1
soil_2 = Seesaw(tca[1], addr=0x36)   # sensor on channel 2
soil_3 = Seesaw(tca[1], addr=0x36)   # sensor on channel 3

aht4 = adafruit_ahtx0.AHTx0(tca[3]) # outside humidity channel 4
aht5 = adafruit_ahtx0.AHTx0(tca[5]) # outside humidity channel 5
#aht6 = adafruit_ahtx0.AHTx0(tca[6]) # outside humidity channel 6
# aht7 = adafruit_ahtx0.AHTx0(tca[7]) # outside humidity channel 7
while True:
    moisture_0 = soil_0.moisture_read()
    temp_0 = soil_0.get_temp()

    moisture_1 = soil_1.moisture_read()
    temp_1 = soil_1.get_temp()

    moisture_2 = soil_2.moisture_read()
    temp_2 = soil_2.get_temp()

    moisture_3 = soil_3.moisture_read()
    temp_3 = soil_3.get_temp()

    air_temp1 = aht4.temperature
    air_humidity1 = aht4.relative_humidity

    air_temp2 = aht5.temperature
    air_humidity2 = aht5.relative_humidity

    #air_temp3 = aht6.temperature
    #air_humidity3 = aht6.relative_humidity

    #air_temp4 = aht7.temperature
    #air_humidity4 = aht7.relative_humidity

    print(f"Channel 0 -> Temp: {temp_0:.2f} C, Moisture: {moisture_0}")
    print(f"Channel 1 -> Temp: {temp_1:.2f} C, Moisture: {moisture_1}")
    print(f"Channel 2 -> Temp: {temp_2:.2f} C, Moisture: {moisture_2}")
    print(f"Channel 3 -> Temp: {temp_3:.2f} C, Moisture: {moisture_3}")
    print(f"Channel 4 -> Air Temp: {air_temp1:.2f} C, Humidity: {air_humidity1}")
    print(f"Channel 5 -> Air Temp: {air_temp2:.2f} C, Humidity: {air_humidity2}")
    #print(f"Channel 6 -> Air Temp: {air_temp3:.2f} C, Humidity: {air_humidity3}")
    #print(f"Channel 7 -> Air Temp: {air_temp4:.2f} C, Humidity: {air_humidity4}")
    print("-" * 40)

    time.sleep(2)