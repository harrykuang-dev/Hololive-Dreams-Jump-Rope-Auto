"""Native UI inspired by Fishing Auto; MIT attribution in third_party/."""
from __future__ import annotations
import ctypes
import logging
import os
import queue
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import font, messagebox, ttk
import win32api
from app_locale import LANGUAGES, text
from app_settings import captured_hotkey, parse_stop_hotkey
from global_hotkey import GlobalHotkey
from batch_session import APP_VERSION, BatchSession, SessionConfig, diagnostic_base

PROJECT_URL = 'https://github.com/harrykuang-dev/Hololive-Dreams-Jump-Rope-Auto'


def window_dpi(root):
    try:
        return ctypes.windll.user32.GetDpiForWindow(root.winfo_id()) or 96
    except (AttributeError, OSError):
        return round(root.winfo_fpixels('1i'))


def window_work_area(root):
    try:
        area = win32api.GetMonitorInfo(win32api.MonitorFromWindow(root.winfo_id(), 2))['Work']
        return area[2]-area[0], area[3]-area[1]
    except Exception:
        return root.winfo_screenwidth(), root.winfo_screenheight()


class QueueLog(logging.Handler):
    def __init__(self, messages):
        super().__init__()
        self.messages = messages

    def emit(self, record):
        self.messages.put(('log', self.format(record)))


class JumpRopeApp:
    BG, TEXT, MUTED = '#f3f3f3', '#202020', '#666666'
    BLUE, GREEN, RED = '#0067c0', '#187b38', '#b42318'

    def __init__(self, root, *, session_factory=BatchSession):
        self.root, self.session_factory = root, session_factory
        self.session = self.worker = None
        self.messages = queue.Queue()
        self._closing = self._capturing = self.has_error = False
        self._capture_target = 'stop'
        self._hotkey_generation = 0
        self.dpi = window_dpi(root)
        self.scale = self.dpi/96
        root.tk.call('tk', 'scaling', self.dpi/72)
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            font.nametofont(name).configure(family='Segoe UI', size=11)
        font.nametofont('TkFixedFont').configure(family='Consolas', size=10)
        root.configure(bg=self.BG)
        width, height = window_work_area(root)
        root.geometry(f'{min(self.px(640),width-self.px(40))}x{min(self.px(790),height-self.px(40))}')
        root.minsize(min(self.px(570),width-self.px(40)), min(self.px(620),height-self.px(40)))
        root.protocol('WM_DELETE_WINDOW', self.close)
        try:
            root.iconbitmap(default=str(Path(__file__).resolve().parent/'assets'/'jump-rope.ico'))
        except tk.TclError:
            pass
        self.language = tk.StringVar(root, value='繁體中文')
        self.target = tk.StringVar(root, value='1')
        self.stop_key = tk.StringVar(root, value='F9')
        self.shortcut_display = tk.StringVar(root, value='F9')
        self.start_key = tk.StringVar(root, value='F8')
        self.start_shortcut_display = tk.StringVar(root, value='F8')
        self.diagnostics = tk.BooleanVar(root, value=False)
        self._build()
        self.apply_language()
        self.hotkey = GlobalHotkey(lambda:self.messages.put(('start_hotkey', self._hotkey_generation)),
                                   lambda value,ok,error:self.messages.put(('hotkey_status', (value,ok,error))))
        self.hotkey.start()
        self.log_handler = QueueLog(self.messages)
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s  %(message)s', datefmt='%H:%M:%S'))
        self.logger = logging.getLogger('jump-rope-auto')
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self.log_handler)
        root.bind('<Button-1>', self._cancel_capture, add='+')
        root.after(100, self.poll)

    def px(self, value):
        return round(value*self.scale)

    def tr(self, key, **values):
        return text(LANGUAGES[self.language.get()], key, **values)

    def reason(self, value):
        return self.tr('reason_'+value)

    def _build(self):
        style = ttk.Style(self.root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('TFrame', background=self.BG)
        style.configure('TLabel', background=self.BG, foreground=self.TEXT)
        style.configure('Muted.TLabel', foreground=self.MUTED)
        style.configure('Title.TLabel', font=('Segoe UI',18,'bold'))
        style.configure('Count.TLabel', font=('Segoe UI',16,'bold'))
        style.configure('Action.TButton', padding=(self.px(12),self.px(10)))
        style.configure('TCheckbutton', background=self.BG)
        main = self.main_frame = ttk.Frame(self.root, padding=self.px(24))
        main.pack(fill='both', expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(9, weight=1)
        def label(name, row, style='TLabel', pady=0):
            widget = ttk.Label(main, style=style, wraplength=self.px(570), justify='left')
            widget.grid(row=row, column=0, sticky='ew', pady=pady)
            setattr(self, name, widget)
        header = ttk.Frame(main)
        header.grid(row=0,column=0,sticky='ew')
        header.columnconfigure(1,weight=1)
        logo = tk.PhotoImage(master=self.root,file=str(
            Path(__file__).resolve().parent/'assets'/'hopping-rope-logo.png'))
        self.logo_image = logo.subsample(max(1,round(logo.width()/self.px(128))))
        self.logo_label = ttk.Label(header,image=self.logo_image)
        self.logo_label.grid(row=0,column=0,sticky='w',padx=(0,self.px(12)))
        self.title_label = ttk.Label(header,style='Title.TLabel',
            wraplength=self.px(390),justify='left')
        self.title_label.grid(row=0,column=1,sticky='ew')
        label('instructions',1,'Muted.TLabel',(self.px(8),self.px(14)))
        label('status',2,'Muted.TLabel',(0,self.px(8)))
        label('counter',3,'Count.TLabel')
        label('inputs_label',4,'Muted.TLabel',(self.px(4),self.px(12)))
        form = ttk.Frame(main)
        form.grid(row=5,column=0,sticky='ew')
        form.columnconfigure(1,weight=1)
        for row,name in ((0,'language_label'),(1,'rounds_label'),(3,'start_shortcut_label'),(4,'shortcut_label')):
            widget = ttk.Label(form)
            widget.grid(row=row,column=0,sticky='w',padx=(0,self.px(18)),pady=self.px(5))
            setattr(self,name,widget)
        self.language_choice = ttk.Combobox(form,textvariable=self.language,values=tuple(LANGUAGES),state='readonly')
        self.language_choice.grid(row=0,column=1,sticky='ew',pady=self.px(5))
        self.language_choice.bind('<<ComboboxSelected>>',self.apply_language)
        self.target_entry = ttk.Entry(form,textvariable=self.target)
        self.target_entry.grid(row=1,column=1,sticky='ew',pady=self.px(5))
        self.round_hint = ttk.Label(form,style='Muted.TLabel',wraplength=self.px(380))
        self.round_hint.grid(row=2,column=1,sticky='w')
        self.start_shortcut_entry = ttk.Entry(form,textvariable=self.start_shortcut_display,state='readonly')
        self.start_shortcut_entry.grid(row=3,column=1,sticky='ew',pady=self.px(5))
        self.start_shortcut_entry.bind('<Button-1>',self.begin_start_capture)
        self.start_shortcut_entry.bind('<FocusOut>',self.end_capture)
        self.start_shortcut_entry.bind('<KeyPress>',self.capture_key)
        self.shortcut_entry = ttk.Entry(form,textvariable=self.shortcut_display,state='readonly')
        self.shortcut_entry.grid(row=4,column=1,sticky='ew',pady=self.px(5))
        self.shortcut_entry.bind('<Button-1>',self.begin_capture)
        self.shortcut_entry.bind('<FocusOut>',self.end_capture)
        self.shortcut_entry.bind('<KeyPress>',self.capture_key)
        controls = ttk.Frame(main)
        controls.grid(row=6,column=0,sticky='ew',pady=(self.px(14),self.px(12)))
        controls.columnconfigure((0,1),weight=1,uniform='actions')
        self.start_button = ttk.Button(controls,style='Action.TButton',command=self.start)
        self.stop_button = ttk.Button(controls,style='Action.TButton',command=self.stop,state='disabled')
        self.start_button.grid(row=0,column=0,sticky='ew',padx=(0,self.px(6)))
        self.stop_button.grid(row=0,column=1,sticky='ew',padx=(self.px(6),0))
        options = ttk.Frame(main)
        options.grid(row=7,column=0,sticky='ew')
        self.diagnostics_check = ttk.Checkbutton(options,variable=self.diagnostics)
        self.diagnostics_check.grid(row=0,column=0,sticky='w')
        self.help_button = ttk.Button(options,text='?',width=3,command=self.show_help)
        self.help_button.grid(row=0,column=1,padx=self.px(6))
        label('log_title',8,'TLabel',(self.px(8),self.px(6)))
        logs = ttk.Frame(main)
        logs.grid(row=9,column=0,sticky='nsew')
        self.log = tk.Text(logs,wrap='word',state='disabled',font='TkFixedFont',height=5,
            bg='white',fg=self.TEXT,relief='solid',bd=1,padx=self.px(10),pady=self.px(8))
        scroll = ttk.Scrollbar(logs,command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        self.log.pack(fill='both',expand=True)

    def apply_language(self,_event=None):
        self.root.title(f'Hololive Dreams — {self.tr("title")} v{APP_VERSION}')
        for widget,key in ((self.title_label,'title'),(self.instructions,'instructions'),
                (self.language_label,'language'),(self.rounds_label,'rounds'),(self.round_hint,'round_hint'),
                (self.shortcut_label,'shortcut'),(self.start_shortcut_label,'start_shortcut'),(self.start_button,'start'),
                (self.stop_button,'stop'),(self.diagnostics_check,'diagnostics'),
                (self.log_title,'log')):
            widget.configure(text=self.tr(key))
        if not self.worker or not self.worker.is_alive():
            self.status.configure(text=self.tr('ready'),foreground=self.MUTED)
        self.refresh_counts()

    def refresh_counts(self):
        done = self.session.completed_rounds if self.session else 0
        target = self.session.config.rounds if self.session else self.target.get()
        inputs = self.session.inputs if self.session else 0
        self.counter.configure(text=self.tr('counter',done=done,target=target))
        self.inputs_label.configure(text=self.tr('inputs',count=inputs))

    def begin_capture(self,_event=None):
        if not self.shortcut_entry.instate(['disabled']):
            self._capture_target = 'stop'
            self._capturing = True
            self._hotkey_generation += 1
            self.hotkey.configure(enabled=False)
            self.shortcut_entry.focus_set()
            self.shortcut_display.set(self.tr('capture_key'))
        return 'break'

    def begin_start_capture(self,_event=None):
        if not self.start_shortcut_entry.instate(['disabled']):
            self._capture_target = 'start'
            self._capturing = True
            self._hotkey_generation += 1
            self.hotkey.configure(enabled=False)
            self.start_shortcut_entry.focus_set()
            self.start_shortcut_display.set(self.tr('capture_key'))
        return 'break'

    def end_capture(self,_event=None):
        self._capturing = False
        self.shortcut_display.set(self.stop_key.get())
        self.start_shortcut_display.set(self.start_key.get())
        if hasattr(self,'hotkey'):
            self.hotkey.configure(value=self.start_key.get(),enabled=not self._closing and not (self.worker and self.worker.is_alive()))

    def _cancel_capture(self,event):
        if event.widget not in (self.shortcut_entry,self.start_shortcut_entry):
            self.end_capture()

    def capture_key(self,event):
        if not self._capturing or self.shortcut_entry.instate(['disabled']):
            return
        value = captured_hotkey(event.keysym,event.state,event.keycode)
        if value:
            start = value if self._capture_target == 'start' else self.start_key.get()
            stop = value if self._capture_target == 'stop' else self.stop_key.get()
            sm,sk = parse_stop_hotkey(start)
            tm,tk = parse_stop_hotkey(stop)
            if sk == tk and set(sm) == set(tm):
                return 'break'
            (self.start_key if self._capture_target == 'start' else self.stop_key).set(value)
            self.end_capture()
        return 'break'

    def set_controls(self,running):
        self._hotkey_generation += 1
        self.end_capture()
        self.start_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')
        self.language_choice.configure(state='disabled' if running else 'readonly')
        self.shortcut_entry.configure(state='disabled' if running else 'readonly')
        self.start_shortcut_entry.configure(state='disabled' if running else 'readonly')
        self.hotkey.configure(value=self.start_key.get(),enabled=not running and not self._closing)
        for widget in (self.target_entry,self.diagnostics_check,self.help_button):
            widget.configure(state='disabled' if running else 'normal')

    def append_log(self,message):
        self.log.configure(state='normal')
        self.log.insert('end',message+'\n')
        if int(self.log.index('end-1c').split('.')[0]) > 500:
            self.log.delete('1.0','101.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def start(self):
        if self._closing or self._capturing:
            return
        if self.worker and self.worker.is_alive():
            return
        try:
            config = SessionConfig(rounds=int(self.target.get()),stop_hotkey=self.stop_key.get(),
                                   diagnostics=self.diagnostics.get())
            config.validate()
        except ValueError:
            messagebox.showerror(self.tr('error'),self.tr('invalid'),parent=self.root)
            return
        self.has_error = False
        self.session = self.session_factory(config,notify=lambda kind,value:self.messages.put((kind,value)))
        self.set_controls(True)
        self.refresh_counts()
        self.status.configure(text=self.tr('running',index=1,target=config.rounds),foreground=self.BLUE)
        self.append_log(self.tr('session_start',target=config.rounds))
        self.worker = threading.Thread(target=self.run_session,name='jump-rope-session',daemon=True)
        self.worker.start()

    def run_session(self):
        try:
            self.session.run()
        except Exception as error:
            self.messages.put(('error',str(error)))
        finally:
            self.messages.put(('done',None))

    def stop(self):
        if self.worker and self.worker.is_alive():
            self.session.stop()
            self.stop_button.configure(state='disabled')
            self.status.configure(text=self.tr('stopping'),foreground=self.MUTED)

    def poll(self):
        try:
            while True:
                kind,value = self.messages.get_nowait()
                if kind == 'log':
                    self.append_log(value)
                elif kind == 'diagnostics':
                    self.append_log(self.tr('saved',path=value))
                elif kind == 'packing':
                    self.status.configure(text=self.tr('packing',index=value),foreground=self.BLUE)
                elif kind == 'archive':
                    self.append_log(self.tr('archive',path=value))
                elif kind == 'start_hotkey':
                    if value == self._hotkey_generation:
                        self.start()
                elif kind == 'hotkey_status':
                    if not value[1]:
                        self.append_log(self.tr('hotkey_error',key=value[0]))
                elif kind == 'round':
                    self.status.configure(text=self.tr('running',index=value[0],target=value[1]),foreground=self.GREEN)
                elif kind == 'round_done':
                    self.append_log(self.tr('round_done',index=value[0],reason=self.reason(value[1]),count=value[2]))
                elif kind == 'error':
                    self.has_error = True
                    self.append_log(f'{self.tr("error")}: {value}')
                    self.status.configure(text=f'{self.tr("error")}: {value}',foreground=self.RED)
                elif kind == 'done':
                    self.set_controls(False)
                    if not self.has_error:
                        self.status.configure(text=self.tr('stopped',reason=self.reason(self.session.stop_reason)),foreground=self.MUTED)
        except queue.Empty:
            pass
        self.refresh_counts()
        if not self._closing:
            self.root.after(100,self.poll)

    def show_help(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr('help_title'))
        dialog.transient(self.root)
        panel = ttk.Frame(dialog,padding=self.px(20))
        panel.pack(fill='both',expand=True)
        self.help_dialog = dialog
        wrap = self.px(620)
        def paragraph(value, pady=0):
            ttk.Label(panel,text=value,wraplength=wrap,justify='left').pack(anchor='w',pady=pady)
        def link(value, command):
            widget = ttk.Label(panel,text=value,wraplength=wrap,justify='left',
                foreground=self.BLUE,cursor='hand2',font=('Segoe UI',11,'underline'),takefocus=True)
            widget.pack(anchor='w',pady=(0,self.px(16)))
            widget.bind('<Button-1>',lambda _:command())
            widget.bind('<Return>',lambda _:command())
        paragraph(self.tr('help'),(self.px(8),self.px(20)))
        paragraph(self.tr('help_location'),(0,self.px(8)))
        link(str(self.diagnostics_directory()),self.open_diagnostics)
        paragraph(self.tr('help_usage'),(0,self.px(20)))
        paragraph(self.tr('help_project'),(0,self.px(8)))
        link(PROJECT_URL,lambda:webbrowser.open(PROJECT_URL))
        ttk.Button(panel,text=self.tr('close'),width=12,command=dialog.destroy).pack(anchor='e',pady=(self.px(8),0))
        dialog.bind('<Escape>',lambda _:dialog.destroy())
        dialog.grab_set()

    def diagnostics_directory(self):
        return self.session.directory if self.session and self.session.directory else diagnostic_base()

    def open_diagnostics(self):
        directory = self.diagnostics_directory()
        directory.mkdir(parents=True,exist_ok=True)
        os.startfile(str(directory))

    def close(self):
        self._closing = True
        self.hotkey.close()
        self.stop()
        self.root.after(100,self.finish_close)

    def finish_close(self):
        if self.worker and self.worker.is_alive():
            self.root.after(100,self.finish_close)
        else:
            self.logger.removeHandler(self.log_handler)
            self.log_handler.close()
            self.root.destroy()


def main():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('HololiveJumpRopeAuto.Desktop')
    except (AttributeError,OSError):
        pass
    root = tk.Tk()
    JumpRopeApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
