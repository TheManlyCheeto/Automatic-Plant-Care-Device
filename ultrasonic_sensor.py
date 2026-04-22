import RPi.GPIO as GPIO
import time
# Voltage Divider on the Echo pin.
# ECHO pin -> 1kohm -> GPIO 24 -> 2kohm -> GND

TRIG_PIN = 26
ECHO_PIN = 24

GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIG_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)

def measure_distance() -> float:
    # Send trigger pulse
    GPIO.output(TRIG_PIN, False)
    time.sleep(0.002)  # let sensor settle (buffer for prop delay)

    GPIO.output(TRIG_PIN, True)
    time.sleep(0.00001)  # 10us pulse
    GPIO.output(TRIG_PIN, False)

    # Wait for echo to start
    pulse_start = time.time()
    while GPIO.input(ECHO_PIN) == 0:
        #print("wait fore echo to start")
        pulse_start = time.time()

    # Wait for echo to end
    pulse_end = time.time()
    while GPIO.input(ECHO_PIN) == 1:
        #print("Wait for echo to end")
        pulse_end = time.time()

    # Calculate distance
    pulse_duration = pulse_end - pulse_start
    distance = (pulse_duration * 34300) / 2  # speed of sound in cm/s
    print(f"distance: {distance}")
    return round(distance, 2)

try:
    print("while is running")
    while True:
        dist = measure_distance()
        plant_growth = 24.53 - dist # distance from ultrasonic sensor to the dirt level
        print(f"Distance: {dist} cm, Plant Growth: {plant_growth} cm")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Stopped")
    GPIO.cleanup()