"""Cached rounded surfaces for native, keyboard-accessible ttk widgets."""
from itertools import count
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageFont, ImageTk

BG, SURFACE, TEXT, MUTED = '#F5F5F5', '#FFFFFF', '#242424', '#616161'
ACCENT, HOVER, PRESSED, INK = '#FFE36A', '#F6D75A', '#EACB4C', '#483800'
BORDER, CARD_BORDER = '#D1D1D1', '#E5E5E5'
_instances = count()


class FluentEntry(tk.Entry):
    """A flat native entry whose readonly surface remains white on Windows."""
    def __init__(self, master, **kwargs):
        super().__init__(master, background=SURFACE, readonlybackground=SURFACE,
                         disabledbackground='#F0F0F0', foreground=TEXT,
                         disabledforeground='#A0A0A0', insertbackground=TEXT,
                         selectbackground=ACCENT, selectforeground=INK,
                         relief='flat', borderwidth=0, highlightthickness=0, **kwargs)

    def instate(self, states):
        current = str(self.cget('state'))
        return all(current != state[1:] if state.startswith('!') else current == state
                   for state in states)


class FluentTimingSlider(tk.Canvas):
    """Continuous timing control with five labelled reference marks."""

    def __init__(self, master, *, variable, px, on_change):
        self.variable, self.px, self.on_change = variable, px, on_change
        super().__init__(master, width=px(210), height=px(32), background=SURFACE,
                         borderwidth=0, highlightthickness=0, takefocus=1,
                         cursor='hand2')
        self._thumb_images = {(enabled, focused): self._make_thumb(enabled, focused)
                              for enabled, focused in ((True, False), (True, True), (False, False))}
        self.variable.trace_add('write', self._value_changed)
        self.bind('<Configure>', lambda _event: self.redraw())
        self.bind('<Button-1>', self._choose)
        self.bind('<B1-Motion>', lambda event: self._choose(event, snap_centre=False))
        self.bind('<Left>', lambda _event: self._move(-.01))
        self.bind('<Right>', lambda _event: self._move(.01))
        self.bind('<Home>', lambda _event: self._set(0))
        self.bind('<End>', lambda _event: self._set(1))
        self.bind('<Double-Button-1>', lambda _event: self._set(.5))
        self.bind('<FocusIn>', lambda _event: self.redraw())
        self.bind('<FocusOut>', lambda _event: self.redraw())
        self.redraw()

    def instate(self, states):
        current = str(self.cget('state'))
        return all(current != state[1:] if state.startswith('!') else current == state
                   for state in states)

    def set_enabled(self, enabled):
        self.configure(state='normal' if enabled else 'disabled',
                       cursor='hand2' if enabled else 'arrow')
        self.redraw()

    def _value_changed(self, *_args):
        self.redraw()
        self.on_change()

    def _set(self, value):
        if not self.instate(['disabled']):
            self.variable.set(round(max(0., min(1., float(value))), 6))
        return 'break'

    def _move(self, direction):
        return self._set(self.variable.get()+direction)

    def _choose(self, event, *, snap_centre=True):
        if self.instate(['disabled']):
            return 'break'
        self.focus_set()
        left, right = self._ends()
        if snap_centre and abs(event.x-(left+right)/2) <= self.px(8):
            return self._set(.5)
        return self._set((event.x-left)/(right-left))

    def _ends(self):
        margin = self.px(1)
        return margin, max(margin+1, self.winfo_width()-margin)

    def _make_thumb(self, enabled, focused):
        size, supersample = self.px(20), 4
        image = Image.new('RGBA', (size*supersample, size*supersample))
        draw = ImageDraw.Draw(image)
        centre = size*supersample/2
        unit = size*supersample/20
        def circle(radius, **options):
            radius *= unit
            draw.ellipse((centre-radius, centre-radius, centre+radius, centre+radius), **options)
        if focused:
            circle(9, outline='#D8B64C', width=max(1, round(unit)))
        circle(7, fill=SURFACE if enabled else '#F0F0F0',
               outline='#CFC8B2' if enabled else '#D1D1D1', width=max(1, round(unit)))
        circle(3.8, fill=ACCENT if enabled else '#C4C4C4')
        return ImageTk.PhotoImage(image.resize((size,size),Image.Resampling.LANCZOS), master=self)

    def redraw(self):
        self.delete('all')
        left, right = self._ends()
        y = self.px(10)
        selected = max(0., min(1., float(self.variable.get())))
        active = not self.instate(['disabled'])
        coordinates = [left+(right-left)*index/4 for index in range(5)]
        x = left+(right-left)*selected
        rail_width = self.px(5)
        rail_left, rail_right = left, right
        self.create_line(rail_left,y,rail_right,y,width=rail_width,fill='#E8E8E8',
                         capstyle=tk.BUTT)
        self.create_line(rail_left,y,x,y,width=rail_width,
                         fill=ACCENT if active else '#D1D1D1',capstyle=tk.BUTT)
        for index,mark_x in enumerate(coordinates):
            self.create_line(mark_x,y-self.px(3),mark_x,y+self.px(3),
                             fill='#9A791A' if active else '#A8A8A8',
                             width=self.px(2),tags='timing_tick')
            self.create_text(mark_x,self.px(25),text=('-40','-20','0','+20','+40')[index],
                             anchor='w' if index == 0 else 'e' if index == 4 else 'center',
                             fill=TEXT if index == 2 and active else MUTED,
                             font=('Segoe UI',9,'bold' if index == 2 else 'normal'),
                             tags='timing_mark')
        thumb_margin = self.px(10)
        thumb_x = max(thumb_margin,min(self.winfo_width()-thumb_margin,x))
        self.create_image(thumb_x,y,image=self._thumb_images[(active,active and self.focus_get() is self)],
                          tags='timing_thumb')


class FluentTheme:
    def __init__(self, root, px):
        self.root, self.px, self.images = root, px, []
        self.prefix = f'JumpFluent{next(_instances)}'
        self.style = s = ttk.Style(root)
        s.theme_use('clam')
        s.configure('.', font=('Segoe UI', 10), background=BG, foreground=TEXT)
        s.configure('TFrame', background=BG)
        s.configure('Surface.TFrame',background=SURFACE)
        s.configure('Timing.TFrame', background=SURFACE)
        s.configure('TLabel', background=BG, foreground=TEXT)
        s.configure('Muted.TLabel', foreground=MUTED)
        s.configure('Title.TLabel', font=('Segoe UI', 18, 'bold'))
        s.configure('Card.TLabel', background=SURFACE)
        s.configure('CardMuted.TLabel', background=SURFACE, foreground=MUTED)
        s.configure('Count.TLabel', background=SURFACE, font=('Segoe UI', 20, 'bold'))
        for name, fill, border, radius, background in (
            ('Card', SURFACE, CARD_BORDER, 8, BG),
            ('Field', SURFACE, BORDER, 4, SURFACE),
            ('FocusField', SURFACE, '#B68D23', 4, SURFACE),
            ('DisabledField', '#F0F0F0', CARD_BORDER, 4, SURFACE)):
            element = self.element(name, self.rounded(fill, border, radius, background,
                                   (480, 320) if name == 'Card' else (320, 44)), radius+2)
            s.layout(name+'.TFrame', [(element, {'sticky': 'nswe'})])
            s.configure(name+'.TFrame', background=fill)
        self.button('Primary', ACCENT, HOVER, PRESSED, INK, content_padding=1)
        self.button('Secondary', SURFACE, '#F5F5F5', '#EBEBEB', TEXT, BORDER, content_padding=1)
        self.button('Info', BG, '#EBEBEB', '#E0E0E0', MUTED, content_padding=1)
        self.button('Dialog', ACCENT, HOVER, PRESSED, INK, content_padding=1)
        s.configure('Dialog.TButton',font=('Segoe UI',-round(10*px(96)/72)),padding=(px(12),px(10)))
        s.configure('Info.TButton', padding=px(3))
        self.play_icons = self.action_icons('play', INK)
        self.stop_icons = self.action_icons('stop', TEXT)
        self.help_icon = self.icon('help', MUTED)
        self.help_disabled_icon = self.icon('help', '#A0A0A0')
        self.combo()
        self.checkbox()
        self.radio()
        s.configure('Vertical.TScrollbar', background='#D6D6D6', troughcolor=SURFACE,
                    borderwidth=0, arrowsize=0, width=px(6))
        s.map('Vertical.TScrollbar', background=[('pressed', '#999999'), ('active', '#ADADAD')])
        s.layout('Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {'sticky': 'ns', 'children': [
            ('Vertical.Scrollbar.thumb', {'expand': True, 'sticky': 'nswe'})]})])

    def raster(self, size, paint):
        size = tuple(max(1, self.px(n)) for n in size)
        image = Image.new('RGBA', tuple(n*4 for n in size))
        paint(ImageDraw.Draw(image), image.size, 4*self.px(1))
        photo = ImageTk.PhotoImage(image.resize(size, Image.Resampling.LANCZOS), master=self.root)
        self.images.append(photo)
        return photo

    def rounded(self, fill, border, radius, background, size=(240, 44)):
        def paint(draw, size, unit):
            draw.rectangle((0, 0, *size), fill=background)
            draw.rounded_rectangle((unit/2, unit/2, size[0]-unit/2, size[1]-unit/2),
                                   radius=radius*unit, fill=fill, outline=border, width=unit)
        return self.raster(size, paint)

    def element(self, name, image, radius, *states, padding=None):
        name = self.prefix+'.'+name
        options = {} if padding is None else {'padding':padding}
        self.style.element_create(name, 'image', image, *states, border=self.px(radius),
                                  width=self.px(radius*2+1), height=self.px(radius*2+1), sticky='nswe', **options)
        return name

    def button(self, name, fill, hover, pressed, ink, border=None, content_padding=None):
        normal = self.rounded(fill, border or fill, 6, BG)
        disabled = self.rounded('#F0F0F0', '#E5E5E5', 6, BG)
        down = self.rounded(pressed, border or pressed, 6, BG)
        hot = self.rounded(hover, border or hover, 6, BG)
        focus = self.rounded(fill, '#B68D23', 6, BG)
        element = self.element(name, normal, 8, ('disabled', disabled), ('pressed', down),
                               ('active', hot), ('focus', focus),
                               padding=None if content_padding is None else self.px(content_padding))
        self.style.layout(name+'.TButton', [(element, {'sticky': 'nswe', 'children': [
            ('Button.padding', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})]})])
        self.style.configure(name+'.TButton', foreground=ink, background=BG, borderwidth=0,
                             padding=(self.px(12), self.px(10)), anchor='center')
        self.style.map(name+'.TButton', foreground=[('disabled', '#A0A0A0')])

    def action_icons(self, kind, color):
        return {state: self.icon(kind, ink) for state, ink in (
            ('normal', color), ('disabled', '#A0A0A0'))}

    def icon(self, kind, color):
        def paint(draw, dimensions, unit):
            w, h = dimensions
            if kind == 'play':
                draw.polygon([(w*.25, h*.15), (w*.8, h*.5), (w*.25, h*.85)], fill=color)
            elif kind == 'stop':
                draw.rounded_rectangle((w*.2, h*.2, w*.8, h*.8), radius=unit, fill=color)
            else:
                draw.ellipse((unit, unit, w-unit, h-unit), outline=color, width=unit)
                face = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', int(h*.72))
                draw.text((w*.5, h*.48), '?', font=face, fill=color, anchor='mm')
        return self.raster((16, 16), paint)

    def combo(self):
        normal = self.rounded(SURFACE, BORDER, 4, SURFACE, (320, 44))
        focus = self.rounded(SURFACE, '#B68D23', 4, SURFACE, (320, 44))
        disabled = self.rounded('#F0F0F0', CARD_BORDER, 4, SURFACE, (320, 44))
        box = self.element('combo', normal, 6, ('disabled', disabled), ('focus', focus), padding=self.px(1))
        def paint(draw, size, unit):
            w, h = size
            draw.line([(w*.3, h*.4), (w*.5, h*.6), (w*.7, h*.4)], fill=MUTED, width=unit)
        arrow = self.prefix+'.arrow'
        self.style.element_create(arrow, 'image', self.raster((28, 20), paint), sticky='')
        self.style.layout('TCombobox', [(box, {'sticky': 'nswe', 'children': [
            (arrow, {'side': 'right', 'sticky': 'ns'}), ('Combobox.padding', {'sticky': 'nswe',
                'children': [('Combobox.textarea', {'sticky': 'nswe'})]})]})])
        self.style.configure('TCombobox', padding=(self.px(8), self.px(5)), foreground=TEXT,
                             fieldbackground=SURFACE, borderwidth=0)
        self.style.configure('Compact.TCombobox', padding=(self.px(8), self.px(3)))
        self.style.map('TCombobox', fieldbackground=[('disabled', '#F0F0F0'), ('readonly', SURFACE)],
                       foreground=[('disabled', '#A0A0A0'), ('readonly', TEXT)],
                       selectbackground=[('readonly', SURFACE)], selectforeground=[('readonly', TEXT)])
        self.root.option_add('*TCombobox*Listbox.font', 'TkDefaultFont')

    def checkbox(self):
        def image(selected, disabled=False):
            def paint(draw, size, unit):
                w, h = size
                color = '#D1D1D1' if disabled else ACCENT if selected else SURFACE
                draw.rounded_rectangle((unit, unit, w-unit, h-unit), radius=3*unit,
                                       fill=color, outline='#A0A0A0' if disabled else '#8A8A8A', width=unit)
                if selected:
                    draw.line([(w*.23, h*.5), (w*.43, h*.7), (w*.78, h*.3)],
                              fill='#A0A0A0' if disabled else INK, width=2*unit)
            return self.raster((18, 18), paint)
        name = self.prefix+'.check'
        self.style.element_create(name, 'image', image(False),
            ('disabled', 'selected', image(True, True)), ('disabled', image(False, True)),
            ('selected', image(True)), sticky='')
        self.style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
            (name, {'side': 'left'}), ('Checkbutton.focus', {'side': 'left', 'sticky': 'nswe',
                'children': [('Checkbutton.label', {'sticky': 'nswe'})]})]})])
        self.style.configure('TCheckbutton', background=BG, padding=0,
                             indicatormargin=(0, 0, self.px(6), 0))
        self.style.map('TCheckbutton', background=[('active', BG)], foreground=[('disabled', '#A0A0A0')])

    def radio(self):
        def indicator(selected,disabled=False):
            def paint(draw,size,unit):
                _,h=size;w=h
                outline='#BDBDBD' if disabled else ACCENT if selected else '#8A8A8A'
                draw.ellipse((unit,unit,w-unit,h-unit),fill=SURFACE,outline=outline,
                             width=max(1,round(unit*(2 if selected else 1))))
                if selected:draw.ellipse((w*.32,h*.32,w*.68,h*.68),fill=outline)
            return self.raster((20,18),paint)
        name=self.prefix+'.radio'
        self.style.element_create(name,'image',indicator(False),
            ('disabled','selected',indicator(True,True)),('disabled',indicator(False,True)),
            ('selected',indicator(True)),sticky='')
        self.style.layout('TRadiobutton',[('Radiobutton.padding',{'sticky':'nswe','children':[
            (name,{'side':'left','sticky':''}),('Radiobutton.focus',{'side':'left','sticky':'nswe',
                'children':[('Radiobutton.label',{'sticky':'nswe'})]})]})])
        self.style.configure('TRadiobutton',background=SURFACE,
                             indicatormargin=(0,0,self.px(6),0),padding=0)
        self.style.map('TRadiobutton',foreground=[('disabled','#A0A0A0')],background=[('active',SURFACE)])
