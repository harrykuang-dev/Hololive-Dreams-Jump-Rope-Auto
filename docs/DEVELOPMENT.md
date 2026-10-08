# 開發說明 — 1.0

一般使用方式見 [README](../README.md)。

## 原始碼啟動與建置

需要 Windows x64 和 Python；目前建置環境使用 Python 3.13。

```powershell
python -m pip install -r requirements-dev.txt
python main_ui.py
python -m pytest -q
python -m pytest -q -m gui
python tools/build_release.py
python tools/verify_release_bundle.py dist/HololiveDreamsJumpRopeAuto-1.0.exe --output build-verification.json
```

GUI 測試使用模擬會話，不操作遊戲，但會建立測試視窗。請在沒有實戰測試運行時執行。

建置產物是包含執行環境的單檔 EXE。打包檢查會比對程式碼及顯示資源，確認未包含遊戲資源包、解包工具或影片編碼工具。`work/`、`build/`、`dist/` 及本機測試資料不進入 Git。

## 程式結構

- `main_ui.py`：六語言介面、快捷鍵設定、執行記錄及開發者說明。
- `batch_session.py`：局數限制、會話計數、停止控制及診斷打包。
- `vision.py`：DXGI 擷取、遊戲畫面判斷與選單按鈕識別。
- `jump_detector.py`：正式使用的視覺識別器入口。
- `rope_geometry.py`、`candidate_tracker.py`、`candidates.py`、`priority.py`、`repair_detector.py`：繩線幾何擬合、運動判斷及遮擋處理。
- `jump_rope_bot.py`：開局導航、局內控制、25ms 滑鼠输入及結束處理。
- `diagnostics.py`：逐幀記錄、診斷截圖與 Issue 附件。

## 診斷格式

開發者模式預設關閉，關閉時不啟用診斷模組、不保存截圖。啟用後，每次運行建立以時間命名的資料夾，每局結束後產生 `diagnostics.zip`。資料只保存在本機，不自動上傳。

```text
%LOCALAPPDATA%\HololiveJumpRopeAuto\sessions\時間戳\round-局號\
```

ZIP 包含：

- `frames.jsonl.gz`：完整逐幀觀察，包含候選、實際輸入、拟合結果、階段及診斷用心數／角色標記。`t` 是擷取時刻，`input_elapsed` 是滑鼠按下時刻。心數與角色標記只用於診斷。
- `screenshots/`：最多 20 組事件原圖與繩線疊加圖，有測量時附原始 BGR 採樣列。
- `failure-window/`：掉心或結束前約 0.75 秒、後約 0.25 秒的密集截圖，最多 80 幀。與事件截圖重複時復用檔案。
- `performance.json`：實際識別幀率、延遲及完整按鍵脈衝。
- `session.json`、`session.log`：程式版本、EXE 雜湊及執行記錄。ZIP 保留最近 1MiB 日誌，完整日誌在會話資料夾中。
- `manifest.json`：檔案映射、結束原因及診斷版本。

每局 ZIP 上限為 20MiB，不包含影片。運行時保留有界截圖快取，JPEG 壓縮在本局控制結束後執行。診斷擁塞、磁碟或打包失敗時會停止並保留已產生的資料。

## 測試範圍

自動測試涵蓋捕獲、畫面與輸入保護、選單識別、會話計數、快捷鍵、診斷檔案及介面版面。自動測試不代表實際遊戲成績；驗證實機問題時，請使用同一角色、畫面設定及窗口條件，並透過開發者模式記錄問題局。
