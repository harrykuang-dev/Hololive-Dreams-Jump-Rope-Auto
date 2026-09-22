"""Small Traditional-Chinese GUI for the jump-rope bot."""

import tkinter as tk
from tkinter import messagebox, ttk

from jump_rope_bot import BotConfig, GameNotFoundError, JumpRopeBot


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Hololive Dreams 跳繩自動遊玩")
        self.geometry("430x245")
        self.resizable(False, False)
        self.bot: JumpRopeBot | None = None
        panel = ttk.Frame(self, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Hololive Dreams 跳繩自動遊玩", font=("", 16, "bold")).pack()
        ttk.Label(panel, text="先在遊戲中選好難度並按「遊玩」，看到倒數後再啟動。\n程式會辨識繩子掃到腳部區域，再點擊 Jump。", justify="center").pack(pady=(12, 10))
        row = ttk.Frame(panel)
        row.pack()
        ttk.Label(row, text="連跳間隔（秒）").pack(side="left")
        self.interval = tk.StringVar(value="0.045")
        ttk.Entry(row, width=8, textvariable=self.interval).pack(side="left", padx=8)
        buttons = ttk.Frame(panel)
        buttons.pack(pady=15)
        self.start_button = ttk.Button(buttons, text="啟動（F8）", command=self.start_bot)
        self.start_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(buttons, text="停止（F9）", command=self.stop_bot, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.status = tk.StringVar(value="待機中")
        ttk.Label(panel, textvariable=self.status).pack()
        self.bind("<F8>", lambda _: self.start_bot())
        self.bind("<F9>", lambda _: self.stop_bot())
        self.protocol("WM_DELETE_WINDOW", self.close)

    def start_bot(self) -> None:
        if self.bot and self.bot.running:
            return
        try:
            config = BotConfig(tap_interval=float(self.interval.get()))
            config.validate()
            self.bot = JumpRopeBot(config)
            self.bot.find_game()
        except (ValueError, GameNotFoundError) as error:
            messagebox.showerror("無法啟動", str(error))
            return
        self.bot.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.after(200, self.monitor_bot)

    def monitor_bot(self) -> None:
        if self.bot and self.bot.running:
            self.status.set(f"執行中：已送出 {self.bot.tap_count} 次輸入（F9 停止）")
            self.after(250, self.monitor_bot)
        elif self.stop_button["state"] != "disabled":
            if self.bot and self.bot.last_error:
                messagebox.showerror("程式已停止", str(self.bot.last_error))
            self.finish_stop()

    def stop_bot(self) -> None:
        if self.bot:
            self.bot.stop()
            self.bot.join(1.0)
        self.finish_stop()

    def finish_stop(self) -> None:
        taps = self.bot.tap_count if self.bot else 0
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status.set(f"已停止；最後一次共送出 {taps} 次輸入")

    def close(self) -> None:
        self.stop_bot()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
