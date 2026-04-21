import cv2 as cv
import numpy as np
import time
from picamera2 import Picamera2

W, H = 640, 480

# -----------------------------
# Physical dimensions in mm
# -----------------------------
QR_SIZE_MM = 31     #SOLVED: CHANGE THIS to the actual printed QR size I SWEAR TO GOD TYSON YOU BASTARD MAN
BOX_SIZE_MM = 162.0    # desired box size

# -----------------------------
# Picamera2 setup
# -----------------------------
picam2 = Picamera2()
config = picam2.create_preview_configuration(
    main={"format": "BGR888", "size": (W, H)}
)
picam2.configure(config)
picam2.start()
time.sleep(1)

# -----------------------------
# OpenCV setup
# -----------------------------
source_window = "QR Box"
cv.namedWindow(source_window)

qr_detector = cv.QRCodeDetector()

def draw_labeled_polygon(img, pts, color, label=None, thickness=2):
    pts_int = pts.astype(np.int32).reshape((-1, 1, 2))
    cv.polylines(img, [pts_int], True, color, thickness)

    if label is not None:
        x, y = pts_int[0, 0]
        cv.putText(
            img,
            label,
            (x + 8, y - 8),
            cv.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv.LINE_AA
        )

while True:
    frame = picam2.capture_array()
    frame = cv.flip(frame, -1) # then flip 180 degrees (accross horizontal line)
    display = frame.copy()

    retval, decoded_info, points, _ = qr_detector.detectAndDecodeMulti(frame)

    if retval and points is not None:
        for i, qr_pts in enumerate(points):
            img_pts = np.array(qr_pts, dtype=np.float32)

            # Draw detected QR outline
            draw_labeled_polygon(display, img_pts, (0, 255, 0), "QR")

            # Read and display decoded QR value
            qr_text = decoded_info[i] if i < len(decoded_info) else ""
            if qr_text:
                tx, ty = img_pts[0].astype(int)
                cv.putText(
                    display,
                    f"Data: {qr_text}",
                    (tx + 8, ty + 20),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    2,
                    cv.LINE_AA
                )
                print(f"QR decoded: {qr_text}")

            # -----------------------------------------
            # QR real-world coordinates in mm
            # top-left, top-right, bottom-right, bottom-left
            # -----------------------------------------
            world_qr = np.array([
                [0.0, 0.0],
                [QR_SIZE_MM, 0.0],
                [QR_SIZE_MM, QR_SIZE_MM],
                [0.0, QR_SIZE_MM]
            ], dtype=np.float32)

            # Homography from mm plane -> image
            H_mat = cv.getPerspectiveTransform(world_qr, img_pts)

            # -----------------------------------------
            # 162 mm x 162 mm box
            # QR is the BOTTOM-RIGHT corner of the box
            #
            # So the box extends:
            #   left by BOX_SIZE_MM from QR left edge
            #   up by BOX_SIZE_MM from QR bottom edge
            #
            # In world coordinates:
            #   QR occupies x: [0, QR_SIZE_MM], y: [0, QR_SIZE_MM]
            #   Box bottom-right aligns with QR bottom-right: (QR_SIZE_MM, QR_SIZE_MM)
            #   Box extends left and up by BOX_SIZE_MM
            # -----------------------------------------
            world_box = np.array([
                [QR_SIZE_MM - BOX_SIZE_MM, QR_SIZE_MM - BOX_SIZE_MM],   # top-left of box
                [QR_SIZE_MM,               QR_SIZE_MM - BOX_SIZE_MM],   # top-right of box
                [QR_SIZE_MM,               QR_SIZE_MM],                  # bottom-right = QR bottom-right
                [QR_SIZE_MM - BOX_SIZE_MM, QR_SIZE_MM]                  # bottom-left of box
            ], dtype=np.float32).reshape(-1, 1, 2)

            img_box = cv.perspectiveTransform(world_box, H_mat).reshape(-1, 2)

            # Draw projected 162x162 mm box
            draw_labeled_polygon(display, img_box, (255, 0, 255), "162mm x 162mm")

            # Mark anchor at QR bottom-right
            anchor_world = np.array([[[QR_SIZE_MM, QR_SIZE_MM]]], dtype=np.float32)
            anchor_img = cv.perspectiveTransform(anchor_world, H_mat).reshape(2)
            anchor = tuple(anchor_img.astype(int))

            cv.circle(display, anchor, 5, (0, 0, 255), -1)
            cv.putText(
                display,
                "Anchor: QR bottom-right",
                (anchor[0] + 8, anchor[1] - 8),
                cv.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                2,
                cv.LINE_AA
            )

    else:
        cv.putText(
            display,
            "No QR detected",
            (20, 30),
            cv.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
            cv.LINE_AA
        )

    cv.imshow(source_window, display)

    key = cv.waitKey(1) & 0xFF
    if key == ord('q') or key == 27:
        break

picam2.stop()
cv.destroyAllWindows()
