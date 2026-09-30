"""Record bounded, separately gated jump-rope rounds.

Each JumpRopeBot remains single-round and never reopens a result page. The
opt-in batch runner may create another bot only after the previous round's
result page has been independently observed. --observe sends no inputs.
"""
from __future__ import annotations

import argparse
import logging
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys
import time

import win32api
import win32con
import win32event
import win32gui
import winerror

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jump_rope_bot import BotConfig, JumpRopeBot
from vision import GameCapture, RoundGate, StartupScreen, NoFreshFrameError


def wait_for_result_page(hwnd: int, *, timeout: float = 15.0,
                         clock=time.perf_counter, sleeper=time.sleep,
                         capture_factory=GameCapture,
                         screen_factory=StartupScreen) -> bool:
    """Authorize a *new* round only from a stable previous score page."""
    capture = capture_factory(hwnd)
    screen = screen_factory()
    deadline = clock() + timeout
    confirmations = 0
    try:
        while clock() < deadline:
            if (win32gui.GetForegroundWindow() != hwnd
                    or win32api.GetAsyncKeyState(win32con.VK_F9) & 0x8000):
                return False
            try:
                frame = capture.grab()
            except NoFreshFrameError:
                continue  # Wait within deadline, without synthetic confirmations.
            if (not RoundGate.gameplay_visible(frame)
                    and screen.identify(frame) == "next"):
                confirmations += 1
                if confirmations >= 5:
                    return True
            else:
                confirmations = 0
            sleeper(.08)
        return False
    finally:
        getattr(capture, 'close', lambda: None)()


def main(default_rounds: int = 1, default_capture: str = 'screen') -> int:
    interactive = bool(getattr(sys, "frozen", False) and len(sys.argv) == 1)
    parser = argparse.ArgumentParser(description="有上限地錄製跳繩測試")
    parser.add_argument("--observe", action="store_true", help="只觀察，不送出任何輸入")
    parser.add_argument("--manual-start", action="store_true",
                        help="不操作開局選單，由人手動開始")
    parser.add_argument("--wait-seconds", type=float, default=120,
                        help="等待你手動點「遊玩」的最長秒數")
    parser.add_argument("--round-seconds", type=float,
                        help="確認開局後的最長秒數；觀察預設 10，實戰預設 180")
    parser.add_argument("--record", type=Path,
                        help="本地 MP4 路徑；預設為 debug/round-test-時間戳.mp4")
    parser.add_argument("--rounds", type=int, default=default_rounds,
                        help="連續測試局數，1–7；批量版預設 7 局")
    parser.add_argument('--fps', type=int, choices=(15, 30, 60), default=60,
                        help='擷取目標及 MP4 時基；實際幀率記錄於 JSON，不保證達到目標')
    parser.add_argument('--capture', choices=('screen', 'printwindow', 'dxgi'), default=default_capture,
                        help='高速可見客戶區擷取；printwindow 為舊版相容模式')
    args = parser.parse_args()
    if not 1 <= args.rounds <= 7:
        parser.error("--rounds 必須介於 1 和 7")
    if args.rounds > 1 and (args.observe or args.manual_start):
        parser.error("批量模式需要自動開局；不能搭配 --observe 或 --manual-start")
    round_seconds = args.round_seconds if args.round_seconds is not None else (10 if args.observe else 180)
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    default_path = base / "debug" / f"{'batch' if args.rounds > 1 else 'round'}-test-{stamp}.mp4"
    requested_path = args.record or default_path
    paths = ([requested_path] if args.rounds == 1 else [
        requested_path.with_name(f"{requested_path.stem}-round-{index:02d}.mp4")
        for index in range(1, args.rounds + 1)
    ])
    for path in paths:
        if path.exists() or path.with_suffix(".events.json").exists():
            parser.error(f"錄影路徑已存在，不覆蓋：{path}")
    mutex = win32event.CreateMutex(None, False, "Local\\HololiveJumpRopeAutoSingleRound")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.CloseHandle(mutex)
        print("另一個跳繩測試程式正在運行；此視窗沒有送出輸入。", flush=True)
        if interactive:
            input("Press Enter to close... ")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.observe or args.manual_start:
        print("已待命。請手動進入遊戲；此模式不操作開局選單。", flush=True)
    elif args.rounds > 1:
        print(f"批量模式：最多 {args.rounds} 局。只在上局已停止且再次確認成績頁後，才開下一局；F9／失焦／未知畫面立即停止。", flush=True)
    else:
        print("已待命。僅在開局前辨識並點擊 OK／下一步／遊玩一次；本局結束後絕不重開。", flush=True)
    print("模式：只觀察" if args.observe else "模式：視覺起跳（成績尚未驗證）", flush=True)
    print("按 F9 可隨時停止。", flush=True)
    print(f'擷取目標 {args.fps} FPS；背景錄影，實際幀率及耗時以 JSON performance 為準。', flush=True)
    print(f'擷取方式：{args.capture}。請勿讓其他視窗覆蓋遊戲；不支援最小化。', flush=True)
    result = 0
    file_handler = None
    try:
        requested_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path = requested_path.with_suffix('.run.json')
        executable = Path(sys.executable).resolve() if getattr(sys, 'frozen', False) else None
        manifest = {'capture_backend': args.capture, 'round_limit': args.rounds,
                    'target_fps': args.fps, 'recordings': [str(p.resolve()) for p in paths],
                    'executable': str(executable) if executable else None,
                    'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest() if executable else None}
        with manifest_path.open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
        file_handler = logging.FileHandler(requested_path.with_suffix('.run.log'), mode='x', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logging.getLogger('jump-rope-auto').addHandler(file_handler)
        for index, path in enumerate(paths, 1):
            print(f"第 {index}/{args.rounds} 局：{path.name}", flush=True)
            bot = JumpRopeBot(BotConfig(observe_only=args.observe, record_path=path,
                                        target_fps=args.fps,
                                        capture_backend=args.capture,
                                        wait_for_round=True, startup_timeout=args.wait_seconds,
                                        round_timeout=round_seconds,
                                        result_postroll=3.0 if args.rounds > 1 else 1.0,
                                        auto_start=not args.observe and not args.manual_start))
            try:
                bot.run()
            finally:
                print(f"第 {index} 局停止原因：{bot.stop_reason}；候選={bot.candidate_count}；"
                      f"送出輸入={bot.tap_count}（不是遊戲分數）", flush=True)
                print(f"MP4：{path.resolve()}", flush=True)
                print(f"JSON：{path.with_suffix('.events.json').resolve()}", flush=True)
                logging.getLogger('jump-rope-auto').info('Round %d stopped: %s, taps=%d, video=%s',
                                                        index, bot.stop_reason, bot.tap_count, path)
                performance = getattr(bot, 'recording_performance', None)
                if performance and performance.get('actual_round_fps') is not None:
                    print(f"實際擷取 {performance['actual_round_fps']:.1f} FPS；"
                          f"P95 幀間隔 {performance['frame_interval_p95_ms']:.1f} ms；"
                          f"重複畫面 {performance['duplicate_measurements']}。", flush=True)
            if index == args.rounds:
                if bot.stop_reason != "round_finished" or bot.round_started_at is None:
                    result = 2
                break
            if bot.stop_reason != "round_finished" or bot.round_started_at is None:
                print("本局未正常完成；批量測試安全停止，不會開下一局。", flush=True)
                result = 2
                break
            result_page_ready = (wait_for_result_page(bot._hwnd) if args.capture == 'screen'
                                 else wait_for_result_page(bot._hwnd, capture_factory=lambda hwnd:
                                                           GameCapture(hwnd, backend=args.capture)))
            if not result_page_ready:
                print("未再次確認成績頁，或已失焦／按 F9；安全停止，不會開下一局。", flush=True)
                result = 2
                break
    except KeyboardInterrupt:
        print("已中斷；不會開下一局。", flush=True)
        result = 2
    except Exception as error:
        print(f"測試失敗：{error}", flush=True)
        result = 1
    finally:
        if file_handler is not None:
            logging.getLogger('jump-rope-auto').removeHandler(file_handler)
            file_handler.close()
        print("請以 MP4 中的遊戲分數核對 JSON 的 input_t；兩者都要檢查。", flush=True)
        # The finished console may remain open for the user to read, but it
        # must not keep the single-run mutex while no controller is active.
        win32api.CloseHandle(mutex)
        if interactive:
            input("Press Enter to close... ")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
