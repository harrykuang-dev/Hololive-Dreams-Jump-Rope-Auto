# Hololive Dreams Jump Rope Auto

**实验版本，2026-10-01**。v15 已核实实际单局 **102 下**，达到 100 目标；自动七局结算 **81／92／61／89／102／67／91**，全部正常结束，结算后零起跳。最新本地入口为 `dist/HololiveJumpRopeBatch-v15.exe`。仍不保证每局达 100。历史最佳 132 是用户录像成绩，输入次数和候选不能当游戏分数。详见 [当前验证](docs/batch-v15-validation.md) 和 [接手指南](COMPUTER_USE_HANDOFF.md)。

Windows 实时视觉跳绳程序，用可见细线与几何轨迹拟合绳子，依据当前接近／回摆发出一次起跳。没有固定间隔、预定加速或失去视觉后的周期补跳。中央玩家用游戏自身黄色标记定位，不绑定服装或发色。道具遮挡仍可能误判或漏判。

## 使用

保持游戏前景、完整位于主屏幕内、无遮挡。双击 `dist/HololiveJumpRopeBatch-v15.exe`，默认最多七局，自动辨识下一步、OK、游玩；同页连续确认后点击，漏接时最多重试一次。观察到任何本局 HUD 即永久封闭该局菜单导航。无需每局手动开局。

**不操作能量恢复、BOOST、MODE、购买或道具。** 用户确认零能量也能正常游玩和测试；能量不是开局授权或停止条件。

每局独立停止并完成录影；批量器只有稳定确认前局成绩页后才开始下一局。第七局后不导航。F9、失焦、遮挡、未知实战画面、窗口移动、超时、真正的捕获或录影错误都会停止，不无限重开。结束后保留控制台，按 Enter 关闭；此时单例锁已释放。不要同时运行两个控制器。

批量入口默认 DXGI，只取新画面。开局静止加载页可在 120 秒上限内等待，不发送输入；实战无新帧不使用缓存。兼容 `--capture screen` 和 `--capture printwindow`，后者仍要求输入时游戏有焦点。单局／GUI 默认 screen。

## 本地证据

MP4 与 `.events.json` 位于 EXE 旁 `debug/`，不覆盖已有文件。每批 `.run.json` 记录 EXE SHA-256、后端、局数及录像路径；`.run.log` 记录菜单、开局和停止原因。EXE、build、debug、大型录像不进 Git；克隆后需本地构建。

JSON `frames[N]` 对应 MP4 第 N 张，每张记录画面只写一次，没有插帧。视频以 60 FPS 时基保存，捕获不足 60 时播放加速；实际输入时间用 JSON `t`／`input_t`，吞吐用 `performance.actual_round_fps`。v15 七局约 52.6–53.9 FPS，不能保证每局 60。

录影后台编码。32 张内存缓冲填满时，溢出写入 256 MiB 有界无损本地暂存，保持同一 FIFO 顺序；暂时拥塞可在编码恢复后排空。持续容量耗尽、编码失败、低磁盘空间仍停止。成功排空后移除暂存，失败暂存保留。不是无限缓冲，不丢帧继续输入。

v12 七局结算 **90／65／79／83／61／80／71**；v15 七局均已核对，包括第五局 **102**。达标原片和 JSON 保留；七局映射与停止检查见验证文档。尚未分析的原片、达标证据和用户源代码不删除；历史版本记录在 `HANDOFF.md` 和 `docs/batch-v*-validation.md`。

## 源码运行与构建

需要 Windows、Python 3.10+，建议项目虚拟环境。

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python tools/run_batch_test.py
```

`--rounds` 仅接受 1–7；默认目标及视频时基 60 FPS，可用 `--fps 15`／`--fps 30`。单局自动开局用 `python tools/run_round_test.py`；零输入观察用 `--observe`（手动开始后观察 10 秒），单局人工开局用 `--manual-start`。GUI 入口 `python main_ui.py`；独立控制器 `python jump_rope_bot.py --duration 120` 不自动重新开局。

```powershell
python -m PyInstaller --noconfirm --onefile --console --name HololiveJumpRopeBatch-v15 --hidden-import win32timezone --hidden-import dxcam --paths . --paths tools --add-data 'assets/startup;assets/startup' tools/run_batch_test.py
```

## 验证与分析

最新 168 项测试通过，覆盖视觉回归、安全门、菜单重试、DXGI 新鲜帧、加载等待、录像拥塞恢复及磁盘故障。它们不证明游戏达到 100。七轮离线压力试验每轮 180 张按 60 FPS 送入，暂停编码后恢复；解码帧顺序与 JSON 映射均通过，详见验证文档。

```powershell
python -m pytest -q
python tools/stress_recording.py --output work/pressure-test
python tools/analyze_round_failures.py debug/round.events.json
```

离线 `tools/replay_visual_pass.py`／`tools/scan_round_gate.py` 不操作游戏。旧用户录像要用对应的 `--crop LEFT TOP RIGHT BOTTOM`；历史裁切坐标不能用于当前桌面。
