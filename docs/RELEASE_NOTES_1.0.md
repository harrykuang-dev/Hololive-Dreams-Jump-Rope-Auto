## 繁體中文

Windows 版《hololive Dreams》的自動跳繩助手。

- 透過遊戲畫面追蹤繩子並控制起跳，結算後自動接續下一局。
- 提供六語言介面、1–999 局目標及自訂開始／停止快捷鍵，預設 F8 開始、F9 停止。
- 修正開啟 Num Lock 時，自訂開始／停止快捷鍵會被錯誤加上 Alt 的問題；真正的 Alt 組合鍵仍可正常設定。
- 開局按鈕依位置、顏色及外形識別，支援不同遊戲語言。
- 開發者模式保存逐幀識別記錄、按鍵時序及診斷截圖，每局結束後產生可附在 Issue 的 ZIP；資料保存在本機，不自動上傳。

下載 `HololiveDreamsJumpRopeAuto-1.0.exe` 即可執行，無需安裝 Python。附件 `SHA256SUMS-1.0.txt` 可用於核對 EXE。

運行時保持遊戲前景、完整位於主螢幕內且無遮擋；建議選用深色、短髮、裝飾少的角色和配飾，例如 Ina 搭配像素太陽眼睛（pixel sunglasses）。在確保遊戲穩定 60 幀的情況下，盡可能調高畫面設定。

使用方法、技術實現及問題回報方式見 [README](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto#readme)。

## English

An automatic jump-rope assistant for the Windows version of *hololive Dreams*.

- Tracks the rope in the game image, controls jumps, and continues to the next round after confirming the results screen.
- Includes six interface languages, a target of 1–999 rounds, and configurable start/stop hotkeys. Defaults: F8 to start and F9 to stop.
- Fixes an extra Alt modifier being added to custom start/stop hotkeys when Num Lock is enabled. Actual Alt combinations remain supported.
- Recognizes menu buttons by their position, color, and shape, supporting different game languages.
- Developer mode saves frame-by-frame detection records, input timing, and diagnostic screenshots. After each round, it creates a ZIP suitable for an Issue attachment. Data stays on your computer and is never uploaded automatically.

Download and run `HololiveDreamsJumpRopeAuto-1.0.exe`; Python installation is not required. Use the attached `SHA256SUMS-1.0.txt` to verify the executable.

Keep the entire game window visible on your primary monitor, in the foreground and unobstructed. Choose a character and accessories with dark colors, short hair, and few decorations—for example, Ina with pixel sunglasses. Increase game graphics settings as much as possible while maintaining a stable 60 FPS.

See the [English README](https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto/blob/main/README.en.md) for instructions, implementation details, and bug reporting.
