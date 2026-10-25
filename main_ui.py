"""Native desktop interface for the jump-rope program."""
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
from PIL import Image, ImageTk
from fluent_theme import FluentTheme, FluentEntry, FluentTimingSlider, BG, TEXT, MUTED
from app_locale import LANGUAGES, text
from app_settings import captured_hotkey, parse_stop_hotkey
from global_hotkey import GlobalHotkey
from batch_session import APP_VERSION, BatchSession, SessionConfig, diagnostic_base
from timing_control import DEFAULT_TIMING_POSITION

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
    BG, TEXT, MUTED = BG, TEXT, MUTED
    BLUE = '#0067c0'
    STATUS_COLOR = '#8A6800'

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
            font.nametofont(name).configure(family='Segoe UI', size=10)
        font.nametofont('TkFixedFont').configure(family='Consolas', size=10)
        root.configure(bg=self.BG)
        width, height = window_work_area(root)
        # Client pixels at 120 DPI; scale independently of Tk's font units.
        root.geometry(f'{min(round(517*self.dpi/120),width-self.px(40))}x{min(round(1055*self.dpi/120),height-self.px(40))}')
        root.minsize(min(self.px(360),width-self.px(40)), min(self.px(680),height-self.px(40)))
        root.protocol('WM_DELETE_WINDOW', self.close)
        try:
            root.iconbitmap(default=str(Path(__file__).resolve().parent/'assets'/'jump-rope.ico'))
        except tk.TclError:
            pass
        self.language = tk.StringVar(root, value='繁體中文')
        self.target = tk.StringVar(root, value='1')
        self.score_mode = tk.StringVar(root,value='unlimited')
        self.score_amount = tk.StringVar(root,value='100')
        self._controls_running=False
        self.stop_key = tk.StringVar(root, value='F9')
        self.shortcut_display = tk.StringVar(root, value='F9')
        self.start_key = tk.StringVar(root, value='F8')
        self.start_shortcut_display = tk.StringVar(root, value='F8')
        self.diagnostics = tk.BooleanVar(root, value=False)
        self.timing = tk.DoubleVar(root, value=DEFAULT_TIMING_POSITION)
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
        self.theme = FluentTheme(self.root, self.px)
        self._resize_job = None
        self._layout_size = None
        self._compact = None
        viewport=ttk.Frame(self.root)
        viewport.pack(fill='both',expand=True)
        viewport.rowconfigure(0,weight=1);viewport.columnconfigure(0,weight=1)
        self.page_canvas=tk.Canvas(viewport,bg=self.BG,highlightthickness=0,bd=0)
        self.page_canvas.grid(row=0,column=0,sticky='nsew')
        self.page_scroll=ttk.Scrollbar(viewport,command=self.page_canvas.yview)
        self.page_canvas.configure(yscrollcommand=self.page_scroll.set)
        main = self.main_frame = ttk.Frame(self.page_canvas, padding=self.px(24))
        self.page_item=self.page_canvas.create_window(0,0,window=main,anchor='nw')
        self.page_canvas.bind('<Configure>',self.schedule_resize)
        self.root.bind('<MouseWheel>',self._scroll_page,add='+')
        self.root.bind('<FocusIn>',self._focus_visible,add='+')
        main.columnconfigure(0, weight=1)
        main.rowconfigure(8, weight=1, minsize=self.px(80))
        def label(name, row, style='TLabel', pady=0):
            widget = ttk.Label(main, style=style, wraplength=self.px(570), justify='left')
            widget.grid(row=row, column=0, sticky='ew', pady=pady)
            setattr(self, name, widget)
        header = ttk.Frame(main)
        header.grid(row=0,column=0,sticky='ew')
        header.columnconfigure(1,weight=1)
        with Image.open(Path(__file__).resolve().parent/'assets'/'hopping-rope-logo.png') as source:
            logo = source.convert('RGBA')
            logo.thumbnail((self.px(84),self.px(50)),Image.Resampling.LANCZOS)
            self.logo_image = ImageTk.PhotoImage(logo,master=self.root)
        self.logo_label = ttk.Label(header,image=self.logo_image)
        self.logo_label.grid(row=0,column=0,sticky='w',padx=(0,self.px(12)))
        self.title_label = ttk.Label(header,style='Title.TLabel',
            wraplength=self.px(330),justify='left')
        self.title_label.grid(row=0,column=1,sticky='ew')
        label('instructions',1,'Muted.TLabel',(self.px(8),self.px(12)))
        label('status',2,'Muted.TLabel',(0,self.px(12)))
        self.summary = ttk.Frame(main,style='Card.TFrame',padding=self.px(16))
        self.summary.grid(row=3,column=0,sticky='ew',pady=(0,self.px(12)))
        self.summary.columnconfigure(0,weight=1)
        self.counter = ttk.Label(self.summary,style='Count.TLabel',justify='left')
        self.counter.grid(row=0,column=0,sticky='ew')
        self.inputs_label = ttk.Label(self.summary,style='CardMuted.TLabel')
        self.inputs_label.grid(row=1,column=0,sticky='ew',pady=(self.px(4),0))
        form = self.form = ttk.Frame(main,style='Card.TFrame',padding=self.px(16))
        form.grid(row=4,column=0,sticky='ew',pady=(0,self.px(12)))
        form.columnconfigure(1,weight=1)
        self.form_labels = []
        for row,name in ((0,'language_label'),(1,'rounds_label'),(2,'score_label'),(3,'timing_label'),
                         (4,'start_shortcut_label'),(5,'shortcut_label')):
            widget = ttk.Label(form,style='Card.TLabel')
            widget.grid(row=row,column=0,sticky='w',padx=(0,self.px(18)),pady=self.px(6))
            setattr(self,name,widget)
            self.form_labels.append(widget)
        self.language_choice = ttk.Combobox(form,textvariable=self.language,values=tuple(LANGUAGES),state='readonly')
        self.language_choice.grid(row=0,column=1,sticky='ew',pady=self.px(6))
        self.language_choice.bind('<<ComboboxSelected>>',self.apply_language)
        self.field_frames = {}
        def entry(name,variable,row,readonly=False):
            frame = ttk.Frame(form,style='Field.TFrame',padding=(self.px(8),self.px(5)))
            frame.grid(row=row,column=1,sticky='ew',pady=self.px(6))
            frame.columnconfigure(0,weight=1)
            field = FluentEntry(frame,textvariable=variable,width=12,
                              state='readonly' if readonly else 'normal')
            field.grid(row=0,column=0,sticky='ew')
            # Match the native combobox height, including fractional DPI rounding.
            frame.configure(height=self.language_choice.winfo_reqheight())
            frame.grid_propagate(False)
            frame.rowconfigure(0,weight=1)
            self.field_frames[name] = frame
            field.bind('<FocusIn>',lambda _:frame.configure(style='FocusField.TFrame'),add='+')
            field.bind('<FocusOut>',lambda _:frame.configure(
                style='DisabledField.TFrame' if field.instate(['disabled']) else 'Field.TFrame'),add='+')
            return field
        self.target_entry = entry('target',self.target,1)
        self.score_options=ttk.Frame(form,style='Surface.TFrame')
        self.score_options.grid(row=2,column=1,sticky='ew',pady=self.px(6))
        self.score_options.columnconfigure(2,weight=1)
        self.score_unlimited=ttk.Radiobutton(self.score_options,variable=self.score_mode,
            value='unlimited',command=self._update_score_controls)
        self.score_unlimited.grid(row=0,column=0,sticky='w',padx=(0,self.px(10)))
        self.score_custom=ttk.Radiobutton(self.score_options,variable=self.score_mode,
            value='custom',text='',command=self._update_score_controls)
        self.score_custom.grid(row=0,column=1,sticky='w')
        score_field=ttk.Frame(self.score_options,style='DisabledField.TFrame',padding=(self.px(8),self.px(5)))
        score_field.grid(row=0,column=2,sticky='ew');score_field.columnconfigure(0,weight=1)
        score_field.configure(height=self.language_choice.winfo_reqheight());score_field.grid_propagate(False)
        score_field.rowconfigure(0,weight=1)
        self.field_frames['score']=score_field
        self.score_entry=FluentEntry(score_field,textvariable=self.score_amount,width=6,state='disabled')
        self.score_entry.grid(row=0,column=0,sticky='ew')
        self.score_entry.bind('<FocusIn>',lambda _:score_field.configure(style='FocusField.TFrame'),add='+')
        self.score_entry.bind('<FocusOut>',lambda _:self._update_score_controls(),add='+')
        timing_frame = ttk.Frame(form,style='Timing.TFrame')
        timing_frame.grid(row=3,column=1,sticky='ew',pady=self.px(2))
        timing_frame.columnconfigure((0,1,2),weight=1)
        self.timing_choice = FluentTimingSlider(timing_frame,variable=self.timing,
                                                px=self.px,on_change=self._timing_changed)
        self.timing_choice.grid(row=0,column=0,columnspan=3,sticky='ew')
        self.timing_early = ttk.Label(timing_frame,style='CardMuted.TLabel')
        self.timing_early.grid(row=1,column=0,sticky='w')
        self.timing_value = ttk.Label(timing_frame,style='Card.TLabel')
        self.timing_value.grid(row=1,column=1)
        self.timing_late = ttk.Label(timing_frame,style='CardMuted.TLabel')
        self.timing_late.grid(row=1,column=2,sticky='e')
        self.start_shortcut_entry = entry('start',self.start_shortcut_display,4,True)
        self.start_shortcut_entry.bind('<Button-1>',self.begin_start_capture)
        self.start_shortcut_entry.bind('<FocusOut>',self.end_capture)
        self.start_shortcut_entry.bind('<KeyPress>',self.capture_key)
        self.shortcut_entry = entry('stop',self.shortcut_display,5,True)
        self.shortcut_entry.bind('<Button-1>',self.begin_capture)
        self.shortcut_entry.bind('<FocusOut>',self.end_capture)
        self.shortcut_entry.bind('<KeyPress>',self.capture_key)
        controls = self.controls = ttk.Frame(main)
        controls.grid(row=5,column=0,sticky='ew',pady=(0,self.px(12)))
        controls.columnconfigure((0,1),weight=1,uniform='actions')
        self.start_button = ttk.Button(controls,style='Primary.TButton',command=self.start,
            image=(self.theme.play_icons['normal'],'disabled',self.theme.play_icons['disabled']),compound='left')
        self.stop_button = ttk.Button(controls,style='Secondary.TButton',command=self.stop,state='disabled',
            image=(self.theme.stop_icons['normal'],'disabled',self.theme.stop_icons['disabled']),compound='left')
        self.start_button.grid(row=0,column=0,sticky='ew',padx=(0,self.px(6)))
        self.stop_button.grid(row=0,column=1,sticky='ew',padx=(self.px(6),0))
        options = ttk.Frame(main)
        options.grid(row=6,column=0,sticky='ew')
        self.diagnostics_check = ttk.Checkbutton(options,variable=self.diagnostics)
        self.diagnostics_check.grid(row=0,column=0,sticky='w')
        self.help_button = ttk.Button(options,style='Info.TButton',
            image=(self.theme.help_icon,'disabled',self.theme.help_disabled_icon),command=self.show_help)
        self.help_button.grid(row=0,column=1,padx=self.px(6))
        logs = self.logs = ttk.Frame(main,style='Card.TFrame',padding=self.px(12))
        logs.grid(row=8,column=0,sticky='nsew',pady=(self.px(12),0))
        self.log = tk.Text(logs,wrap='word',state='disabled',font='TkFixedFont',height=5,
            bg='white',fg=self.TEXT,relief='flat',bd=0,padx=self.px(4),pady=self.px(4))
        scroll = ttk.Scrollbar(logs,command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y',padx=(self.px(8),0))
        self.log.pack(fill='both',expand=True)
        self.version_label = ttk.Label(main,text=f'v{APP_VERSION}',style='Muted.TLabel',cursor='hand2',takefocus=True)
        self.version_label.grid(row=9,column=0,sticky='w',pady=(self.px(8),0))
        for event in ('<Button-1>','<Return>','<space>'):
            self.version_label.bind(event,self.open_project)
        main.bind('<Configure>',self.schedule_resize)

    def open_project(self,_event=None):
        webbrowser.open(PROJECT_URL)
        return 'break'

    def _scroll_page(self,event):
        # The activity log retains its own scrolling; never hijack its wheel.
        if event.widget is self.log or event.widget.winfo_toplevel()!=self.root:
            return
        if self.page_canvas.yview()!=(0.,1.):
            units=-int(event.delta/120) if abs(event.delta)>=120 else (-1 if event.delta>0 else 1)
            self.page_canvas.yview_scroll(units,'units')
            return 'break'

    def _focus_visible(self,event):
        if event.widget.winfo_toplevel()!=self.root:return
        self.root.after_idle(lambda:self._reveal_widget(event.widget))

    def _reveal_widget(self,widget):
        if self._closing or not widget.winfo_exists() or self.page_canvas.yview()==(0.,1.):return
        y=widget.winfo_rooty()-self.main_frame.winfo_rooty()
        top=self.page_canvas.canvasy(0);height=self.page_canvas.winfo_height()
        bottom=y+widget.winfo_height()
        if y<top:target=y-self.px(8)
        elif bottom>top+height:target=bottom-height+self.px(8)
        else:return
        total=max(1,self.main_frame.winfo_height())
        self.page_canvas.yview_moveto(max(0,target/total))

    def _sync_scroll_area(self):
        width=max(1,self.page_canvas.winfo_width());height=max(1,self.page_canvas.winfo_height())
        content=max(height,self.main_frame.winfo_reqheight())
        self.page_canvas.itemconfigure(self.page_item,width=width,height=content)
        self.page_canvas.configure(scrollregion=(0,0,width,content))
        if content>height:
            self.page_scroll.grid(row=0,column=1,sticky='ns')
        else:
            self.page_scroll.grid_remove();self.page_canvas.yview_moveto(0)

    def schedule_resize(self,_event=None):
        if self._resize_job is None and not self._closing:
            self._resize_job = self.root.after_idle(self.apply_resize)

    def apply_resize(self):
        self._resize_job = None
        if self._closing:
            return
        self._sync_scroll_area()
        width,height = self.page_canvas.winfo_width(),self.page_canvas.winfo_height()
        compact = height < self.px(720)
        size = (width,compact)
        if self._layout_size == size:
            return
        self._layout_size = size
        outer,padding,gap = (16,12,8) if compact else (24,16,12)
        self.main_frame.configure(padding=self.px(outer))
        if compact != self._compact:
            self._compact = compact
            self.main_frame.rowconfigure(8,minsize=self.px(60 if compact else 80))
            self.logs.configure(padding=self.px(8 if compact else 12))
            for card in (self.summary,self.form):
                card.configure(padding=self.px(padding))
                card.grid_configure(pady=(0,self.px(gap)))
            self.theme.style.configure('Count.TLabel',font=('Segoe UI',18 if compact else 20,'bold'))
            self.theme.style.configure('Title.TLabel',font=('Segoe UI',16 if compact else 18,'bold'))
            self.controls.grid_configure(pady=(0,self.px(gap)))
            self.status.grid_configure(pady=(0,self.px(gap)))
            self.instructions.grid_configure(pady=(self.px(4 if compact else 8),self.px(gap)))
            self.logs.grid_configure(pady=(self.px(8 if compact else 12),0))
            self.version_label.grid_configure(pady=(self.px(0 if compact else 8),0))
            for label in self.form_labels:
                label.grid_configure(pady=self.px(3 if compact else 6))
            for field in self.field_frames.values():
                field.grid_configure(pady=self.px(3 if compact else 6))
                field.configure(padding=(self.px(8),self.px(3 if compact else 5)))
            self.language_choice.grid_configure(pady=self.px(3 if compact else 6))
            self.score_options.grid_configure(pady=self.px(3 if compact else 6))
            self.field_frames['score'].grid_configure(pady=0)
            self.language_choice.configure(style='Compact.TCombobox' if compact else 'TCombobox')
            for field in self.field_frames.values():
                field.configure(height=self.language_choice.winfo_reqheight())
            for name in ('Primary','Secondary'):
                self.theme.style.configure(name+'.TButton',padding=(self.px(12),self.px(10)))
        available = max(self.px(240),width-2*self.px(outer))
        self.title_label.configure(wraplength=available-self.logo_image.width()-self.px(12))
        for widget in (self.instructions,self.status,self.counter,self.inputs_label):
            widget.configure(wraplength=max(self.px(200),available-2*self.px(padding)))

    def apply_language(self,_event=None):
        self.root.title(f'Hololive Dreams — {self.tr("title")}')
        for widget,key in ((self.title_label,'title'),(self.instructions,'instructions'),
                (self.language_label,'language'),(self.rounds_label,'rounds'),
                (self.score_label,'score_limit'),(self.score_unlimited,'unlimited'),
                (self.timing_label,'timing'),(self.timing_early,'timing_early'),
                (self.timing_late,'timing_late'),
                (self.shortcut_label,'shortcut'),(self.start_shortcut_label,'start_shortcut'),(self.start_button,'start'),
                (self.stop_button,'stop'),(self.diagnostics_check,'diagnostics')):
            value = self.tr(key)
            if key in ('start','stop'):
                value = value.removeprefix('▶').removeprefix('■').lstrip()
            widget.configure(text=value)
        self._timing_changed()
        if not self.worker or not self.worker.is_alive():
            self.status.configure(text=self.tr('ready'),foreground=self.STATUS_COLOR)
        self.refresh_counts()
        self._layout_size = None
        self.schedule_resize()

    def refresh_counts(self):
        done = self.session.completed_rounds if self.session else 0
        target = self.session.config.rounds if self.session else self.target.get()
        inputs = self.session.inputs if self.session else 0
        self.counter.configure(text=self.tr('counter',done=done,target=target))
        self.inputs_label.configure(text=self.tr('inputs',count=inputs))

    def _update_score_controls(self):
        disabled=self._controls_running or self.score_mode.get()=='unlimited'
        self.score_entry.configure(state='disabled' if disabled else 'normal')
        self.field_frames['score'].configure(style='DisabledField.TFrame' if disabled else 'Field.TFrame')
        for widget in (self.score_unlimited,self.score_custom):
            widget.configure(state='disabled' if self._controls_running else 'normal')

    def _timing_changed(self, _value=None):
        position = max(0.,min(1.,self.timing.get()))
        if hasattr(self,'timing_value'):
            amount = f'{abs(position-.5)*80:.1f}'
            self.timing_value.configure(text=self.tr('timing_default') if position == .5
                else self.tr('timing_early_n',count=amount) if position < .5
                else self.tr('timing_late_n',count=amount))

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
        self._controls_running=running
        self._hotkey_generation += 1
        self.end_capture()
        self.start_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')
        self.language_choice.configure(state='disabled' if running else 'readonly')
        self.timing_choice.set_enabled(not running)
        self.shortcut_entry.configure(state='disabled' if running else 'readonly')
        self.start_shortcut_entry.configure(state='disabled' if running else 'readonly')
        self.hotkey.configure(value=self.start_key.get(),enabled=not running and not self._closing)
        for widget in (self.target_entry,self.diagnostics_check,self.help_button):
            widget.configure(state='disabled' if running else 'normal')
        for frame in self.field_frames.values():
            frame.configure(style='DisabledField.TFrame' if running else 'Field.TFrame')
        self._update_score_controls()

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
                                   diagnostics=self.diagnostics.get(),
                                   timing_position=self.timing.get(),
                                   score_limit=None if self.score_mode.get()=='unlimited' else int(self.score_amount.get()))
            config.validate()
        except ValueError:
            messagebox.showerror(self.tr('error'),self.tr('invalid'),parent=self.root)
            return
        self.has_error = False
        self.session = self.session_factory(config,notify=lambda kind,value:self.messages.put((kind,value)))
        self.set_controls(True)
        self.refresh_counts()
        self.status.configure(text=self.tr('running',index=1,target=config.rounds),foreground=self.STATUS_COLOR)
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
            self.status.configure(text=self.tr('stopping'),foreground=self.STATUS_COLOR)

    def poll(self):
        try:
            while True:
                kind,value = self.messages.get_nowait()
                if kind == 'log':
                    self.append_log(value)
                elif kind == 'diagnostics':
                    self.append_log(self.tr('saved',path=value))
                elif kind == 'packing':
                    self.status.configure(text=self.tr('packing',index=value),foreground=self.STATUS_COLOR)
                elif kind == 'archive':
                    self.append_log(self.tr('archive',path=value))
                elif kind == 'start_hotkey':
                    if value == self._hotkey_generation:
                        self.start()
                elif kind == 'hotkey_status':
                    if not value[1]:
                        self.append_log(self.tr('hotkey_error',key=value[0]))
                elif kind == 'round':
                    self.status.configure(text=self.tr('running',index=value[0],target=value[1]),foreground=self.STATUS_COLOR)
                elif kind == 'score_limit':
                    message=self.tr('score_wait',score=value)
                    self.status.configure(text=message,foreground=self.STATUS_COLOR)
                    self.append_log(message)
                elif kind == 'round_done':
                    self.append_log(self.tr('round_done',index=value[0],reason=self.reason(value[1]),count=value[2]))
                elif kind == 'error':
                    self.has_error = True
                    self.append_log(f'{self.tr("error")}: {value}')
                    self.status.configure(text=f'{self.tr("error")}: {value}',foreground=self.STATUS_COLOR)
                elif kind == 'done':
                    self.set_controls(False)
                    if not self.has_error:
                        self.status.configure(text=self.tr('stopped',reason=self.reason(self.session.stop_reason)),foreground=self.STATUS_COLOR)
        except queue.Empty:
            pass
        self.refresh_counts()
        if not self._closing:
            self.root.after(100,self.poll)

    def show_help(self):
        if getattr(self,'help_dialog',None) is not None and self.help_dialog.winfo_exists():
            self.help_dialog.lift()
            return
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.configure(bg=self.BG)
        dialog.resizable(False,False)
        dialog.title(self.tr('help_title'))
        dialog.transient(self.root)
        panel = ttk.Frame(dialog,padding=self.px(20))
        panel.pack(fill='both',expand=True)
        self.help_dialog = dialog
        wrap = min(self.px(420),window_work_area(self.root)[0]-self.px(80))
        def paragraph(parent,value,pady=0,bold=False):
            widget = ttk.Label(parent,text=value,style='Card.TLabel' if bold else 'CardMuted.TLabel',
                               wraplength=wrap,justify='left')
            if bold:
                widget.configure(font=('Segoe UI',-round(11*self.dpi/72),'bold'))
            widget.pack(anchor='w',pady=pady)
        def link(parent,value, command,pady=0):
            widget = ttk.Label(parent,text=value,style='Card.TLabel',wraplength=wrap,justify='left',
                foreground=self.BLUE,cursor='hand2',font=('Segoe UI',-round(10*self.dpi/72),'underline'),takefocus=True)
            widget.pack(anchor='w',pady=pady)
            widget.bind('<Button-1>',lambda _:command())
            widget.bind('<Return>',lambda _:command())
        diagnostics = ttk.Frame(panel,style='Card.TFrame',padding=self.px(16))
        diagnostics.pack(fill='x',pady=(0,self.px(12)))
        paragraph(diagnostics,self.tr('diagnostics'),(0,self.px(8)),bold=True)
        paragraph(diagnostics,self.tr('help')+'\n\n'+self.tr('help_location'))
        link(diagnostics,str(self.diagnostics_directory()),self.open_diagnostics,(self.px(4),0))
        paragraph(diagnostics,self.tr('help_usage'),(self.px(12),0))
        project = ttk.Frame(panel,style='Card.TFrame',padding=self.px(16))
        project.pack(fill='x',pady=(0,self.px(12)))
        paragraph(project,self.tr('help_project'),(0,self.px(8)),bold=True)
        link(project,PROJECT_URL,lambda:webbrowser.open(PROJECT_URL))
        close = ttk.Button(panel,text=self.tr('close'),style='Dialog.TButton',command=dialog.destroy)
        close.pack(anchor='e')
        dialog.bind('<Escape>',lambda _:dialog.destroy())
        self.center_dialog(dialog)
        dialog.grab_set()
        close.focus_set()

    def center_dialog(self,dialog):
        dialog.update_idletasks()
        width,height = dialog.winfo_reqwidth(),dialog.winfo_reqheight()
        x = self.root.winfo_rootx()+(self.root.winfo_width()-width)//2
        y = self.root.winfo_rooty()+(self.root.winfo_height()-height)//2
        dialog.geometry(f'{width}x{height}{x:+}{y:+}')
        dialog.deiconify()
        dialog.update_idletasks()
        try:
            parent = int(self.root.tk.call('wm','frame',self.root._w),0)
            child = int(dialog.tk.call('wm','frame',dialog._w),0)
            left,top,right,bottom = win32api.GetMonitorInfo(win32api.MonitorFromWindow(parent,2))['Work']
            from ctypes import wintypes
            parent_rect,child_rect = wintypes.RECT(),wintypes.RECT()
            user32 = ctypes.windll.user32
            user32.GetWindowRect(wintypes.HWND(parent),ctypes.byref(parent_rect))
            user32.GetWindowRect(wintypes.HWND(child),ctypes.byref(child_rect))
            width,height = child_rect.right-child_rect.left,child_rect.bottom-child_rect.top
            x = max(left,min(right-width,(parent_rect.left+parent_rect.right-width)//2))
            y = max(top,min(bottom-height,(parent_rect.top+parent_rect.bottom-height)//2))
            user32.SetWindowPos(wintypes.HWND(child),None,x,y,0,0,0x0015)
        except (AttributeError,OSError):
            pass

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
    import sys
    if '--cpu' in sys.argv:raise SystemExit('CPU inference is no longer supported')
    if '--directml' in sys.argv:
        import os
        os.environ['JUMPROPE_BACKEND']='directml'
    if '--check-only' in sys.argv:
        from detector import FullFrameDetector
        detector=FullFrameDetector()
        from pathlib import Path
        import json
        report={'status':'ok','backend':detector.backend,'fallback_reason':detector.fallback_reason,
                'adapter':getattr(detector.runtime,'adapter',None),'cpu_inference':False,
                'precision':getattr(detector.runtime,'precision','fp32'),
                'torch_imported':'torch' in sys.modules,'capture':False,'input':False}
        if '--report' in sys.argv:
            Path(sys.argv[sys.argv.index('--report')+1]).write_text(json.dumps(report),encoding='utf-8')
    else:
        main()
