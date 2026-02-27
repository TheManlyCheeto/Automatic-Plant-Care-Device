#Braeden Ewers
#thermal is working and shows 0x33 address.
#Testing code to see if it works.

import time
import board
import busio
import adafruit_mlx90640

i2c = busio.I2C(board.SCL, board.SDA, frequency=800000)

mlx = adafruit_mlx90640.MLX90640(i2c)

mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_2_HZ

frame = [0.0] * 768

print("Camera detected, reading frames")

while True:
    try:
        mlx.getFrame(frame)

        t_min = min(frame)
        t_max = max(frame)
        center = frame[(24//12) * 32 + (32//2)]

        print(f"Min: {t_min:5.1f} C | Max: {t_max:5.1f} C | Center: {center:5.1f} C")

    except ValueError:
        print("Frame read error could happenb")

    time.sleep(0.5)