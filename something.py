import board
import adafruit_tca9548a
import time

i2c = board.I2C()
tca = adafruit_tca9548a.TCA9548A(i2c)

# Create the Raspberry Pi I2C bus
i2c = board.I2C()

# Create the TCA9548A object
tca = adafruit_tca9548a.TCA9548A(i2c)

print("Scanning TCA9548A channels...")

for channel in range(8):
    if tca[channel].try_lock():
        try:
            devices = tca[channel].scan()
            hex_devices = [hex(device) for device in devices]

            if hex_devices:
                print(f"Channel {channel}: found {hex_devices}")
            else:
                print(f"Channel {channel}: no devices found")
        finally:
            tca[channel].unlock()
    else:
        print(f"Channel {channel}: could not lock bus")