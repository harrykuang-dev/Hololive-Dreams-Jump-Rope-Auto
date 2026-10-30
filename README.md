# Hololive Dreams Auto Jump Rope

[English](README.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Indonesian](README.id.md) · [简体中文](README.zh-CN.md)

A jump-rope program for the Windows version of *hololive Dreams*. It tracks the rope from the game screen, jumps through ordinary mouse input, and starts another round after the result screen.

## Download

Download **1.3.2** from [Releases](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/releases/latest) and extract the complete Windows x64 `.7z` package. It includes TensorRT 10.13 and DirectML. Compatible NVIDIA systems automatically use TensorRT FP16; other supported GPUs use DirectML.

Keep the EXE, `_internal/`, and `accelerators/` together. The player runtime does not use PyTorch. On the first TensorRT start, the program builds and caches an engine for the local GPU before gameplay; this can take several minutes.

The previous source and MIT License are preserved in [archive/v1.2.1](archive/v1.2.1/).

## Features

- Optional stop score: choose Unlimited or enter 1–999. Once the HUD score is confirmed at or above the limit, jumping stops until the result screen; the next round then follows the configured round limit.
- Tracks rope movement and automatically times jumps.
- A continuous −40 to +40 ms timing offset adjusts both circular and floor-sweeping jumps. The center preserves the default policy. Negative means earlier; positive means later. Click 0 or the center of the track to reset. The slider does not snap to the other marks.
- Recognizes start and result menus and continues after a completed round.
- Six interface languages: Traditional Chinese, Simplified Chinese, English, Japanese, Korean, and Indonesian. Changing the program language does not change the game settings.
- Configurable round target; stops when reached.
- Default shortcuts: F8 to start, F9 to stop. Click a shortcut field and press a key or key combination to change it. Start and stop shortcuts must differ.
- Activity log and optional local developer diagnostics.

## Usage

1. Open the game at the jump-rope start or result screen.
2. Run the EXE and choose a program language under Language.
3. Set a target of 1–999 rounds; the default is 1. Change shortcuts by clicking their fields and pressing the desired keys.
4. Click Start or press the start shortcut. The program attempts to bring the game to the foreground. Keep the game fully visible and unobstructed on the primary monitor. Choose dark-colored, short-haired characters with few decorations and accessories, for example **Juufuutei Raden (default outfit)** with pixel sunglasses.
5. Press the stop shortcut or click Stop to stop. If focus is lost, the program attempts to bring the game back, with at most one recovery attempt per batch. To switch to another program, stop first.

## Requirements and limitations

The program uses GPU inference only. The complete package includes TensorRT 10.13 and ONNX Runtime DirectML. Compatible NVIDIA systems automatically use TensorRT FP16; otherwise a supported DirectX 12 hardware GPU uses DirectML.

Requires Windows 10/11 x64 and the Windows game client. Keep the game client area at 16:9; do not minimize, cover, or move its window during operation.

Increase graphics settings as far as possible while keeping the game at a stable 60 FPS.

Jump inputs shown in the interface are input counts; read the actual score on the game's result screen. Character colors, animation, resolution, computer performance, and game updates can affect recognition. Stop and provide diagnostics if a problem occurs.

## Technical implementation

The full game client image is letterboxed to 640×640. One YOLO26n Detect model identifies the bounding box of the visible rope and the player’s triangular marker. The same trained weights run through TensorRT 10.13 FP16 or ONNX Runtime DirectML on a hardware GPU; CPU model inference is disabled.

The [temporal controller](controller/policy.py) combines successive box boundaries, motion and real frame intervals with reference motion patterns to estimate the next visible rope passage. The player marker and actual input history help identify airborne and grounded states. Partial boxes remain partial evidence; the controller does not fill in hidden rope geometry. Stable short-term reservations can bridge bounded occlusion, and circular timing adjusts to estimated speed.

The [timing slider](timing_control.py) shifts both circular and floor-sweeping decision windows and reservations continuously by −40 to +40 ms. The center is the default timing; click 0 or the track center to reset.

The [score monitor](score_limit.py) reads HUD digits from the same captured image. Repeated reliable readings and score-increment checks confirm the stop threshold. It then cancels pending jumps, releases input and waits for the normal result screen. Unlimited mode does not run the score reader.

The [control loop](jump_rope_bot.py) uses one DXGI capture and one input owner. A separate interruptible timer releases each jump after a target 25 ms while observation continues. Immediately before DOWN, the program rechecks focus, window size, stop requests and source-frame identity. Passage windows and bounded occlusion predictions remain enforced; start and result menus use text-independent geometry and color checks.

## Bug reports and developer mode

Report continuation failures, jump problems, or other issues through [GitHub Issues](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/issues).

Enable Developer mode before reproducing the problem. It saves diagnostic screenshots, frame recognition records, input timing, and processing times locally, without automatic uploads. Enabling it increases processing overhead.

Click `?` to view and open the diagnostics folder:

```text
%LOCALAPPDATA%\HololiveJumpRopeAuto\sessions\
```

Each run creates a timestamped folder with one `diagnostics.json` covering all rounds and diagnostic images. When execution ends, `diagnostics.zip` packages this JSON and the retained images, including when initialization fails before any frame is captured.

The report includes GPU and driver details, the selected inference backend and fallback errors, capture and inference timings, recognition and jump-decision records, native input timing, focus-loss window titles and process names, and the final stop reason. Attach this run's ZIP with a description of the problem.

## Source and license

Startup, building and tests are described in the [development guide](docs/DEVELOPMENT.md). Training and model export are documented in [training/](training/README.md). Historical changes are in the [version history](docs/VERSION_HISTORY.md).

The current program and YOLO-derived weights use [AGPL-3.0](LICENSE). The archived version retains its MIT License. Copyright and third-party terms are listed in [NOTICE.md](NOTICE.md).

[Annotations](annotations/README.md) include 672 training-ready manually corrected rope samples and 3 unresolved samples kept out of training. Original annotation data use CC BY 4.0; underlying game screenshots retain their original rights.
