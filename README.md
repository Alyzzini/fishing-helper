# Fishing Helper

A Windows desktop tool for a fishing minigame, built with Python, Tkinter, NumPy, Pillow, and the Windows API. It combines region-based computer vision, predictive mouse control, local percentage recognition, and a timed collection sequence.

## How it works

**Cast → track the moving target → read the completion percentage → wait → hold T → cast again.**

The default sequence starts collection at **98%**, waits **1.5 seconds**, and holds **T continuously for 3.5 seconds**. Existing saved timings are preserved. Initial and repeat casts use the same configurable mouse-hold duration. There is no T-prompt detector.

## Features

- Separate Session and Settings tabs, scaled for Windows high-DPI displays.
- Yellow/green target detection and support for a dot tinted by the target.
- Predictive mouse control with cyan dot and orange target overlays.
- Percentage recognition using local font templates, including touching glyphs.
- A target loop rate of 60 Hz; actual tracking FPS is shown in the app.
- Verified Windows key-down timing, bounded input retries, and full-hold restart after a focus interruption.
- Automatic pickup re-arming when a new fishing meter is confirmed, even if early percentages were unreadable.
- One running instance, bounded rotating logs, reusable capture buffers, and one retry after a capture-surface failure.
- Saved pickup and cast timings; F7 input test and F9 stop.

## Run

Requires Windows 10/11, Python 3.11+ with Tkinter, and standard Windows fonts. Use the primary monitor.

Double-click **Start.bat**. It creates a local virtual environment and installs the two dependencies when needed. It also repairs missing dependencies after an incomplete setup.

Or run in a terminal:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

For VS Code, open this folder, run Start.bat once, install the recommended Python extensions, and choose **Fishing Helper** in Run and Debug. The included launch configuration uses the project's virtual environment.

## Set up a session

1. Start a catch manually to make the meter and percentage visible.
2. Choose **Select fishing bar** and enclose the entire narrow meter.
3. Choose **Select percentage text** and include every digit plus `%`, leaving enough room for `100%`. Exclude the Exit button.
4. Press **F8**, focus Roblox, and keep the pointer over the game.
5. Use **F9** to stop and release inputs.

In Settings, adjust tracking direction, tolerance, cast duration, or **Pickup timing**. F7 tests the configured T hold without casting. The count is completed pickup *sequences*, not independently verified items in inventory.

## Reliability and troubleshooting

- **Waiting with a catch on the rod:** inspect the last percentage in the status. If the completion reading was missed, use F7 to collect, then reselect the percentage area. The app does not infer success from a missing meter.
- **Paused:** give Roblox focus. Inputs are released while another app has focus. An interrupted pickup restarts its wait and full hold after focus returns.
- **T input failure:** Windows must confirm T is down. Two failed retries stop the session without casting.
- **Resolution or camera changes:** reselect the capture areas. A fixed selection cannot follow a relocated UI.
- **Capture failure:** the capture surface is rebuilt once; persistent failures stop with an error instead of using stale pixels.

`pickup.log` records percentage readings, pickup triggers, key transitions, focus changes, and failures. It rotates at 150 KB with one backup. Logs and settings remain local and are excluded from Git.

This is screen-based automation. OCR can miss or misread a frame, and Windows input confirmation does not prove the game accepted it. Disconnects, hidden or moved UI, and game updates can require intervention. It is not guaranteed to run unattended indefinitely.

## Design

| File | Responsibility |
| --- | --- |
| `app.py` | Session state machine, UI, overlays, and input scheduling |
| `capture.py` | Reusable GDI region captures and bounded recovery |
| `control.py` | Predictive tracking and hysteresis |
| `progress.py` | Percentage segmentation and template recognition |
| `keyboard_input.py` | Physical scan-code input through SendInput |
| `tests/` | Detection, timing, repeated-cycle, focus, and recovery regressions |

Pickup timings are snapshotted when a catch completes. A hold counts only after Windows reports the key down. If key state is lost, the continuous timer restarts. Pickup is disarmed after collection until a lower percentage or a confirmed new meter establishes a new cycle, preventing repeated pickup from stale completion text.

## Validation

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The automated suite includes 1,000 simulated collection cycles, exact wait/hold boundaries, stale-percentage suppression, missed-low-percentage recovery, focus interruption, failed key confirmation, and capture retry limits. GitHub Actions runs the suite on Windows with Python 3.11, 3.12, and 3.13.

A local capture stress check exercised 1,000 region captures with alternating sizes and returned GDI resource usage to its initial count. Simulated tests and resource checks do not replace live gameplay validation.
