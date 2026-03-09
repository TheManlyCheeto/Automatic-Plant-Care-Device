import time
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import zoom

import board
import busio
import adafruit_mlx90640

ROWS, COLS = 24, 32
UPSCALE = 10          # 24x32 → 240x320 
VMIN = 20             #°C lower bound (adjust)
VMAX = 35              #°C upper bound (adjust)

i2c = busio.I2C(board.SCL, board.SDA, frequency=800000)
mlx = adafruit_mlx90640.MLX90640(i2c)
mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_2_HZ

frame = [0.0] * (ROWS * COLS)

plt.ion()
fig, ax = plt.subplots()
fig.canvas.manager.set_window_title("MLXHeatCam")

img = ax.imshow(
    np.zeros((ROWS*UPSCALE, COLS*UPSCALE)),
    cmap="plasma",      
    vmin=VMIN,
    vmax=VMAX
)

ax.axis("off")
cbar = plt.colorbar(img, ax=ax, fraction=0.046)
cbar.set_label("Temperature (°C)")

while True:
    try:
        mlx.getFrame(frame)

        data = np.array(frame).reshape((ROWS, COLS))

       
        data = np.flipud(data)

        # Smooth upscale
        data_up = zoom(data, UPSCALE, order=3)  # cubic interpolation

        img.set_data(data_up)
        ax.set_title(
            f"Min {data.min():.1f}°C | Max {data.max():.1f}°C",
            color="white"
        )

        plt.pause(0.001)

    except ValueError:
        pass

    time.sleep(0.05)