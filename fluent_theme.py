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


class FluentTheme:
    def __init__(self, root, px):
        self.root, self.px, self.images = root, px, []
        self.prefix = f'JumpFluent{next(_instances)}'
        self.style = s = ttk.Style(root)
        s.theme_use('clam')
        s.configure('.', font=('Segoe UI', 10), background=BG, foreground=TEXT)
        s.configure('TFrame', background=BG)
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
