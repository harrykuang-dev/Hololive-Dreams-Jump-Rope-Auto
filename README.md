# Hololive Dreams Auto Jump Rope — 1.0

[English](README.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Indonesian](README.id.md) · [简体中文](README.zh-CN.md)

A jump-rope program for the Windows version of *hololive Dreams*. It tracks the rope from the game screen, jumps through ordinary mouse input, and starts another round after the result screen.

## Download

Open [GitHub Releases](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/releases/tag/v1.0) and download `HololiveDreamsJumpRopeAuto-1.0.exe`.

Run the single EXE; Python is not required. A SHA-256 checksum is included. Source ZIPs require building the application yourself.

## Features

- Tracks rope movement and automatically times jumps.
- Recognizes start and result menus and continues after a completed round.
- Six interface languages: Traditional Chinese, Simplified Chinese, English, Japanese, Korean, and Indonesian. Changing the program language does not change the game settings.
- Configurable round target; stops when reached and resets the count on each start.
- Default shortcuts: F8 to start, F9 to stop. Click a shortcut field and press a key or key combination to change it. Start and stop shortcuts must differ.
- Activity log and optional local developer diagnostics.

## Usage

1. Open the game at the jump-rope start or result screen.
2. Run the EXE and choose an program language under Language.
3. Set a target of 1–999 rounds; the default is 1. Change shortcuts by clicking their fields and pressing the desired keys.
4. Click Start or press the start shortcut. The program attempts to bring the game to the foreground. Keep the game fully visible and unobstructed on the primary monitor. Choose dark-colored, short-haired characters with few decorations and accessories, for example **Juufuutei Raden (default outfit)** with pixel sunglasses.
5. Press the stop shortcut, click Stop, or switch windows to stop. Starting again resets the count.

## Requirements and limitations

Requires Windows 10/11 x64 and the Windows game client. Keep the game client area at 16:9; do not minimize, cover, or move its window during operation. Background play and automatic login after the daily reset are not supported.

Increase graphics settings as far as possible while keeping the game at a stable 60 FPS.

Jump inputs shown in the interface are input counts; read the actual score on the game's result screen. Character colors, animation, resolution, computer performance, and game updates can affect recognition. Stop and provide diagnostics if a problem occurs.

> [!WARNING]
> **Capture errors on dual-GPU computers**
>
> If starting produces `-2005270524 / 0x887A0004` (The specified device interface or feature level is not supported on this system.), adjust the program's GPU preference:
>
> ![DXGI capture error message](docs/dxgi-unsupported-error.png)
>
> 1. Open Windows Settings → System → Display → Advanced display, select the primary monitor used for the game, and note the name of the GPU connected to that monitor.
> 2. Return to Display → Graphics (“Graphics settings” on Windows 10), add a desktop app, and browse to the actual `HololiveDreamsJumpRopeAuto-1.0.exe` you run.
> 3. Select Options, choose the GPU identified above under Graphics preference, and select Save. “Power saving” usually refers to the integrated GPU and “High performance” to the discrete GPU; check the GPU names shown.
> 4. Fully close and reopen the program, then click Start to test.
>
> Apply this setting to the program EXE. Internal and external displays, discrete-only mode, and hybrid mode can use different display GPUs; choose based on the current display connection. If it still fails, enable Developer mode, reproduce once, and provide `session.log` from that run's folder, your GPU models, and display connection details.

## Technical implementation

### Capture and image processing

The [capture module](vision.py) uses DXGI/DXcam to acquire new frames from the game client area, checking focus, position, size, and occlusion before and after capture. The control loop targets 60 FPS; its actual rate depends on new game frames, recognition cost, and system scheduling. Missing frames never authorize jumping from old pixels. After a capture gap of at least 100ms, the recovery frame is discarded and the detector is reset. If no new frame arrives within 500ms, operation stops.

[Region processing](priority.py) uses a 960×540 recognition reference. It crops the sampling area before resizing at the original scale. Crop boundaries align with the integer ratio between input and output resolutions to preserve sample positions while reducing unnecessary pixel processing.

### Rope recognition and curve fitting

The [tracker](candidate_tracker.py) samples 100 columns across five horizontal bands. HSV masks select blue/purple, gold, pink, and bright white candidates; frame differences and thin-line contrast filter background pixels. Point groups from different bands produce multiple quadratic curves, scored by support along the curve and across bands. Confident observations also update a rope color reference for subsequent tracking.

The selected curve yields rope height relative to the player, visible support, dominant color, and motion direction. Visible side fragments can constrain the fit when the center is obscured by a character or prop. Insufficient evidence retains necessary state for reacquisition rather than triggering jumps on a fixed schedule.

### Jump decisions and occlusion recovery

The [detector](jump_detector.py) uses visible approach, crossing, retreat, and low-rope turning states to track whether a pass has already triggered. Rearming after occlusion checks consecutive visible fragments, support on both sides, and height changes to limit repeated triggers for the same pass.

The geometry-jump guard separates the last actual observation time from the last accepted-position time. A partially supported fit that suddenly moves toward the player is not accepted just because the stored position is old. Three recent raw observations showing a credible, coherent approach allow normal evaluation to resume.

### Input, menus, and round continuation

After a jump candidate, the [controller](jump_rope_bot.py) captures another new frame to check that gameplay is active, the player is ready, and the jump button is visible. It converts relative coordinates to screen coordinates and holds the left mouse button for a requested 25ms through Windows input. Interrupted input still releases the button. Diagnostics record the actual hold duration, which may vary with scheduling.

Menu recognition uses button position, cyan pill outline, white rim, and page colors, excluding the inner text. Navigation requires several confirming frames and bounds retries on the same page. Once the game HUD is confirmed, menu navigation is disabled for that round. [Session control](batch_session.py) starts another round only after completion and a stable result page, then stops at the target. Operation uses screen pixels and ordinary input without reading or modifying game process memory, saves, or game files.

## Bug reports and developer mode

Report continuation failures, jump problems, or other issues through [GitHub Issues](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/issues).

Enable Developer mode before reproducing the problem. It saves diagnostic screenshots, frame recognition records, input timing, and processing times locally, without automatic uploads. Enabling it increases processing overhead.

Click `?` to view and open the diagnostics folder:

```text
%LOCALAPPDATA%\HololiveJumpRopeAuto\sessions\
```

Each run creates a timestamped folder. Each completed round produces `diagnostics.zip` in its `round-XX` folder. Include the application version, game language/character, resolution, Windows display scaling, problem description, and the affected round's ZIP in your report.

## Source and license

Source startup, building, tests, and diagnostic formats are in the [development guide](docs/DEVELOPMENT.md). Changes reconstructed from this conversation are in the [version history](docs/VERSION_HISTORY.md); historical versions are marked as superseded. Both documents are in Traditional Chinese.

Code is licensed under the [MIT License](LICENSE). Logo and game-related rights belong to their respective owners.
