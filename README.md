# Hololive Dreams Jump Rope Auto

《Hololive Dreams》跳繩小遊戲的 Windows 自動遊玩程式。

## 原理

影片中的規則是按 Jump／Space 讓隊伍跳過繩子；繩速會越來越快，後段會出現大型物件遮擋視線。本程式不依賴容易被遮住的繩子影像，而是高速點擊遊戲右下角內建的 Jump 按鈕。遊戲只會在角色可跳時接受輸入，空中重複輸入會被忽略，因此角色落地後會立即再次起跳。

預設間隔為 0.045 秒（約每秒 22 次），可在介面中調整。

## 安裝

需要 Windows 10/11 與 Python 3.10 以上版本。

    python -m pip install -r requirements.txt

## 使用

1. 開啟 hololive-Dreams。
2. 進入跳繩小遊戲，選擇難度並按「遊玩」。
3. 在倒數或正式開始時執行 `python main_ui.py`。
4. 按「啟動（F8）」。程式會將遊戲切到前景。
5. 在程式介面按 F9 或「停止」結束。

也可使用命令列：

    python jump_rope_bot.py
    python jump_rope_bot.py --duration 15
    python jump_rope_bot.py --interval 0.04

## 注意

- Unity 使用前景輸入；執行期間不要切換到其他視窗，程式會嘗試重新聚焦遊戲。
- 預設不自動點擊選單或領取獎勵，避免誤操作其它遊戲頁面。
- 僅供個人學習、測試與電腦視覺／輸入自動化研究使用。

## 測試

    pytest -q
