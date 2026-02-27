# Basic bounding box
# referenced from tutorial from official docs
# https://docs.opencv.org/4.x/da/d0c/tutorial_bounding_rects_circles.html
#TODO
# After ssh access is reproducible the following needs to be added for variables
# sudo apt install -y python3-picamera2 python3-opencv libcamera-hello

import cv2 as cv
import numpy as np
import random as rng
import time
from picamera2 import Picamera2

rng.seed(12345)

W, H = 640, 480

# ---- Picamera2 setup ----
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"format": "BGR888", "size": (W, H)})
picam2.configure(config)
picam2.start()
time.sleep(1)  # AE settle

# ---- OpenCV UI ----
source_window = "Live"
cv.namedWindow(source_window)

max_thresh = 255
thresh = 100  # initial
def on_trackbar(val):
    global thresh
    thresh = val

cv.createTrackbar("Canny thresh", source_window, thresh, max_thresh, on_trackbar)

while True:
    frame = picam2.capture_array()  # BGR888 a numpy array is necessary "start" frame

    # does grayscale + blur
    gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
    gray = cv.blur(gray, (3, 3))

    # edges + contours for box
    canny_output = cv.Canny(gray, thresh, thresh * 2)
    contours, _ = cv.findContours(canny_output, cv.RETR_TREE, cv.CHAIN_APPROX_SIMPLE)

    # draw on a copy of the frame or copy the blank
    drawing = frame.copy()

    for c in contours:
        # ADJUST SO NOISE ISN'T Insane
        area = cv.contourArea(c)
        if area < 20: #noise threshhold 
            continue

        poly = cv.approxPolyDP(c, 3, True)
        x, y, w, h = cv.boundingRect(poly)
        (cx, cy), radius = cv.minEnclosingCircle(poly)

        color = (rng.randint(0, 256), rng.randint(0, 256), rng.randint(0, 256))
        cv.drawContours(drawing, [poly], -1, color, 2)
        cv.rectangle(drawing, (x, y), (x + w, y + h), color, 2)
        cv.circle(drawing, (int(cx), int(cy)), int(radius), color, 2)

    cv.imshow(source_window, drawing)

    key = cv.waitKey(1) & 0xFF
    if key == ord('q') or key == 27:  # q or ESC
        break

picam2.stop()
cv.destroyAllWindows()