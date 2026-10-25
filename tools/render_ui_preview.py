"""Render only a test UI with disabled global shortcuts and a fake session."""
import argparse,ctypes,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tkinter as tk
import main_ui,win32gui,win32ui
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args()
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    root=tk.Tk()
    with patch('main_ui.window_dpi',return_value=120),patch('main_ui.window_work_area',return_value=(2560,1400)),patch('main_ui.GlobalHotkey',return_value=SimpleNamespace(start=Mock(),configure=Mock(),close=Mock())):
        app=main_ui.JumpRopeApp(root,session_factory=Mock())
    root.geometry('+160+60');root.update()
    assert (root.winfo_width(),root.winfo_height())==(517,1055)
    hwnd=win32gui.GetParent(root.winfo_id());l,t,r,b=win32gui.GetWindowRect(hwnd)
    dc=win32gui.GetWindowDC(hwnd);source=win32ui.CreateDCFromHandle(dc)
    memory=source.CreateCompatibleDC();bitmap=win32ui.CreateBitmap();bitmap.CreateCompatibleBitmap(source,r-l,b-t)
    old=memory.SelectObject(bitmap)
    try:
        # Flag 2 renders the entire own window. Flag 3 is CLIENTONLY and would
        # make a second client crop incorrectly cut off the top padding.
        if not ctypes.windll.user32.PrintWindow(hwnd,memory.GetSafeHdc(),2):raise RuntimeError('Preview failed')
        im=Image.frombuffer('RGB',(r-l,b-t),bitmap.GetBitmapBits(True),'raw','BGRX',0,1)
        x,y=root.winfo_rootx()-l,root.winfo_rooty()-t
        im.crop((x,y,x+517,y+1055)).save(a.output)
    finally:
        memory.SelectObject(old);win32gui.DeleteObject(bitmap.GetHandle());memory.DeleteDC();win32gui.ReleaseDC(hwnd,dc)
        app.logger.removeHandler(app.log_handler);root.destroy()

if __name__=='__main__':main()
