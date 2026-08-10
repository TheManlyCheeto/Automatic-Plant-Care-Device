# Automatic Plant Care Device

**Senior Design Project — 2026**
**Authors:** Braeden Ewers & Tyson Limato

An autonomous, multi-plant care robot built by repurposing a **CoreXY 3D‑printer motion platform** into a gantry that drives across a 4‑plot grow bed, watering, lighting, imaging, and logging the health of each plant automatically. The whole system runs on **Klipper firmware + Moonraker** on a Raspberry Pi, with a custom sensor array, thermal camera, machine vision plot‑detection, and a purpose‑built LCD dashboard menu.

<p align="center">
  <img src="https://raw.githubusercontent.com/TheManlyCheeto/Automatic-Plant-Care-Device/main/Progress_Media/Final_Device.jpg" width="32%" alt="Complete Assembly">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/TheManlyCheeto/Automatic-Plant-Care-Device/main/Progress_Media/CoreXYGantry_Pump_Progress_03.jpg" width="32%" alt="CoreXY gantry and pump assembly">
  <img src="https://raw.githubusercontent.com/TheManlyCheeto/Automatic-Plant-Care-Device/main/Progress_Media/Frame_Construction_Progress_01.jpg" width="32%" alt="Frame construction">
  <img src="https://raw.githubusercontent.com/TheManlyCheeto/Automatic-Plant-Care-Device/main/Progress_Media/Lighting_and_plants_Progress_02.jpg" width="32%" alt="Grow lighting and plants">
</p>

> Build/test clips also live in [`Progress_Media/`](./Progress_Media): `Gantry_Test_X_and_Y_Axis.mp4`, `Basic_Gantry_Test_Y_Axis.mp4`, `Pump_Test_1.mp4`, `Camera_Test_Light.mp4`, `Camera_Test_Dark.mp4`.

---

## Key Features

- **Autonomous multi-plot watering** — a solenoid/relay-driven pump is triggered through Klipper G-code macros (`PUMP_ON` / `PUMP_OFF`) on a timed schedule, with per-plant, per-plot watering cooldowns and thresholds.
- **Scheduled grow lighting** — lights automatically switch on/off daily (`LIGHT_ON` at 06:00, `LIGHT_OFF` at 18:00) via the same macro system.
- **4-plot environmental monitoring** — soil moisture, air temperature, and humidity are sampled continuously across four independent grow plots through a multiplexed I²C sensor bus.
- **Plant growth tracking** — an ultrasonic distance sensor measures canopy height over time to quantify plant growth.
- **Thermal imaging** — a 24×32 IR array camera renders a live false-color heat map of the plants/soil for stress and cold/hot-spot detection.
- **Computer-vision plot calibration** — a Pi camera + OpenCV pipeline detects a printed QR code and uses homography to project a real-world 162×162 mm bounding box onto the frame, anchoring the gantry's coordinate system to physical plot geometry.
- **CoreXY gantry motion** — the printer's X/Y motion system (driven through Moonraker's HTTP API) moves the toolhead across the bed to service each plot in sequence.
- **On-device LCD dashboard** — a custom Klipper display menu (`lcd_plants.py`) replaces the stock printer menu with a scrollable plant-monitor UI: per-plot readings, active alerts, editable moisture-warning thresholds, and quick-access commands (lights, pump, homing, motors off).
- **Per-plant configurable thresholds** — each plant type (e.g. `plants/basil.json`) defines its own acceptable soil, humidity, and temperature ranges, watering cooldown, and pump dose time.
- **JSON time-series logging** — every plot's minute-by-minute moisture/temperature/humidity/alert data is persisted to disk for later review or the LCD dashboard to read back.
- **3D-printed, purpose-built hardware** — nearly every structural and mounting part (idlers, tensioners, carriage plates, LCD mounts, sensor mounts) is custom-designed and printable from the included STL files.

---

## System Architecture

```
                 ┌─────────────────────────┐
                 │   Raspberry Pi (host)   │
                 │  Klipper + Moonraker    │
                 └───────────┬─────────────┘
                              │ HTTP (Moonraker API) / G-code macros
        ┌─────────────────────┼─────────────────────────┐
        │                     │                           │
 ┌──────▼──────┐     ┌────────▼────────┐       ┌──────────▼──────────┐
 │ CoreXY Gantry│     │  Pump & Lights  │       │  Mini12864 LCD Menu │
 │ (X/Y motion) │     │ (relay macros)  │       │   (lcd_plants.py)   │
 └──────────────┘     └─────────────────┘       └──────────────────────┘

 ┌───────────────────────────── Sensor Bus (I²C via TCA9548A mux) ─────────────────────────────┐
 │  Soil moisture ×4 (Seesaw, addr 0x36)     Air temp/humidity ×2 (AHTx0)                        │
 └────────────────────────────────────────────────────────────────────────────────────────────┘

 ┌───────────── Standalone GPIO / peripheral sensors ─────────────┐
 │  HC-SR04 ultrasonic (plant height)   MLX90640 thermal camera    │
 │  Pi Camera + OpenCV (QR/plot calibration)                        │
 └────────────────────────────────────────────────────────────────┘

 Python orchestration (system_demo.py) runs each subsystem as a
 separate process: watering/lighting scheduler, gantry movement,
 soil/air sensor polling + logging, and plant-growth reporting.
```

---

## Embedded Components & Hardware

| Component | Role | Notes |
|---|---|---|
| **Raspberry Pi** | Host controller | Runs Klipper's `klippy` host software, Moonraker API server, and all Python sensor/control scripts |
| **Klipper firmware + Moonraker** | Motion control backend | The project repurposes a 3D-printer's CoreXY motion system; watering/lighting/pump/homing are all issued as Klipper G-code macros over Moonraker's REST API |
| **CoreXY Gantry (repurposed 3D printer frame)** | X/Y positioning | Moves a toolhead across the 4-plot bed; custom-printed carriage mounts, idlers, and tensioners (see [`Plant_Device_STLs/`](./Plant_Device_STLs)) |
| **TCA9548A** | 8-channel I²C multiplexer | Fans out a single I²C bus to isolate 4 soil sensors + 2 air sensors that would otherwise share addresses |
| **Adafruit STEMMA Soil Sensor (Seesaw, addr `0x36`)** | Capacitive soil moisture + temperature | One per plot (4 total), read over the multiplexed I²C bus |
| **AHTx0 (AHT10/AHT20)** | Air temperature & relative humidity | 2 sensors, each shared across a pair of plots |
| **HC-SR04 ultrasonic distance sensor** | Plant growth / canopy height tracking | Wired with a resistor voltage divider on the echo line to safely interface with 3.3V GPIO; converts distance-to-canopy into a growth measurement |
| **MLX90640** | 24×32 pixel thermal IR camera | Streamed and upscaled (cubic interpolation) into a live `matplotlib` heat-map display for thermal monitoring |
| **Raspberry Pi Camera Module (Picamera2)** | Machine vision | Detects a printed QR code, computes a homography, and projects a known-size (162×162 mm) bounding box to calibrate plot position in the camera frame |
| **UC1701 "Mini12864" LCD (16×4 emulated)** | On-device dashboard | Custom Klipper display menu class (`PlantMenuManager`) with scrollable per-plot detail screens, an editable moisture-warning threshold, and a command menu (lights/pump/homing/motors off) |
| **Water pump** | Irrigation actuator | Fired through `PUMP_ON` / `PUMP_OFF` Klipper macros on a timed watering cycle |
| **Grow lights** | Lighting actuator | Fired through `LIGHT_ON` / `LIGHT_OFF` Klipper macros on a fixed daily schedule (06:00–18:00) |
| **3D-printed structural parts** | Mechanical frame | Custom Z-belt clamps, front idlers/tensioners, X-carriage frames, MGN9 rail/blocks, LCD T-bar mounts, and tool-head sensor/carriage mounts — all included as STL/F3D files |

---

## Software Stack

- **Klipper** — 3D-printer firmware repurposed purely for precise, reliable stepper-driven X/Y motion and macro-based I/O control.
- **Moonraker** — HTTP API layer used from Python (`urllib`) to send G-code moves and run macros remotely.
- **Python 3** (`multiprocessing`) — orchestrates concurrent subsystems: watering/lighting scheduler, gantry movement loop, soil/air sensor polling, and ultrasonic growth reporting (`system_demo.py`).
- **Adafruit CircuitPython libraries** — `adafruit_tca9548a`, `adafruit_ahtx0`, `adafruit_seesaw`, `adafruit_mlx90640` for sensor I/O over I²C.
- **OpenCV + NumPy** — QR detection, perspective/homography transforms for camera-based plot calibration.
- **Matplotlib + SciPy** — live-rendered, interpolated thermal camera visualization.
- **RPi.GPIO** — direct GPIO control for the ultrasonic sensor's trigger/echo lines.
- **JSON-based data logging** — per-plot, per-minute summaries (avg/min/max moisture, humidity, temperature, watering recommendations, active alerts) written to `logs/`.
- **Per-plant config files** (`plants/*.json`) — declarative soil/humidity/temperature thresholds, watering cooldown, and pump dose time per plant species (e.g. `basil.json`).
- **Conda environment** (`environment_droplet.yml`) — reproducible environment for the computer-vision stack (OpenCV, FFmpeg, etc.).

---

## Repository Structure

```
Automatic-Plant-Care-Device/
├── Plant_Device_STLs/        # 3D-printable CAD parts (gantry, mounts, idlers, LCD brackets)
├── Progress_Media/           # Build photos & test videos
├── logs/                     # Per-plot, per-day JSON sensor logs
├── plants/                   # Per-plant threshold configs (e.g. basil.json)
├── scripts/                  # Helper/setup scripts (e.g. update_environment_yml.sh)
├── std_vis/                  # Vision-related assets
├── system_demo.py            # Main orchestrator: watering/lighting, gantry, sensors, growth
├── TestTogether.py           # Combined soil + air sensor polling & JSON logging
├── DatabaseMainTest.py       # Per-plant threshold checking logic
├── Humidity.py               # Standalone AHTx0 sensor test
├── MultiplexorTest.py        # TCA9548A channel scan/test
├── Soili2cTest.py            # Standalone soil sensor test
├── ThermalDisplay.py         # Live MLX90640 thermal camera viewer
├── ThermalTest.py            # Thermal sensor test
├── ultrasonic_sensor.py      # HC-SR04 distance / plant-growth measurement
├── std_vis.py                # Pi Camera + OpenCV QR-based plot calibration
├── lcd_plants.py             # Custom Klipper LCD menu (plant dashboard)
└── environment_droplet.yml   # Conda environment for the CV stack
```

---

## Getting Started

> This project assumes a Klipper-controlled CoreXY frame (built from the included STL parts) with a Raspberry Pi running Klippy + Moonraker.

1. **Build the frame** — 3D-print the parts in [`Plant_Device_STLs/`](./Plant_Device_STLs) and assemble the CoreXY gantry, mounting the toolhead, LCD bracket, and sensor mounts.
2. **Flash & configure Klipper/Moonraker** on the Raspberry Pi, and add `PUMP_ON`, `PUMP_OFF`, `LIGHT_ON`, `LIGHT_OFF`, `HOME_XY`, and `CENTER` macros to `printer.cfg`.
3. **Install the LCD dashboard** — copy `lcd_plants.py` into `~/klipper/klippy/extras/display/`, and add a `[lcd_plants]` section to `printer.cfg` with your `log_dir` and `plant_name`.
4. **Wire up the sensors** — soil sensors + AHTx0 sensors through the TCA9548A multiplexer, HC-SR04 to GPIO 5 (trig) / GPIO 24 (echo, with a voltage divider), MLX90640 over I²C, and the Pi Camera to the CSI port.
5. **Set up the Python environment**:
   ```bash
   conda env create -f environment_droplet.yml
   conda activate cv
   pip install adafruit-circuitpython-tca9548a adafruit-circuitpython-ahtx0 adafruit-circuitpython-seesaw adafruit-circuitpython-mlx90640 RPi.GPIO
   ```
6. **Configure your plant(s)** — add/edit a JSON file in `plants/` (see `basil.json`) with soil/humidity/temperature ranges, watering cooldown, and pump dose time.
7. **Run the system**:
   ```bash
   python3 system_demo.py
   ```
   This starts the watering/lighting scheduler, gantry movement loop, soil/air sensor logger, and ultrasonic growth tracker as parallel processes.

---

## Media

| | |
|---|---|
| ![Frame construction](https://raw.githubusercontent.com/TheManlyCheeto/Automatic-Plant-Care-Device/main/Progress_Media/Frame_Construction_Progress_01.jpg) | Frame construction — the CoreXY chassis being assembled from printed and rail hardware. |
| ![Lighting and plants](https://raw.githubusercontent.com/TheManlyCheeto/Automatic-Plant-Care-Device/main/Progress_Media/Lighting_and_plants_Progress_02.jpg) | Grow lighting installed above the live plot bed. |
| ![Gantry and pump](https://raw.githubusercontent.com/TheManlyCheeto/Automatic-Plant-Care-Device/main/Progress_Media/CoreXYGantry_Pump_Progress_03.jpg) | CoreXY gantry with the watering pump mounted and integrated. |

Additional test footage (gantry motion, pump actuation, and camera performance in light/dark conditions) is available in [`Progress_Media/`](./Progress_Media).

---

## Authors

Built by **Braeden Ewers** and **Tyson Limato** as a Senior Design capstone project (2026).

---

## License

No license file is currently included in the repository — check with the authors before reuse or redistribution.
