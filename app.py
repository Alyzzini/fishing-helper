"""Windows fishing helper. F8 starts/stops; F9 always stops."""
import ctypes
from ctypes import wintypes
import time
import json
import math
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image
from capture import RegionCapture
from control import Tracker
from progress import PercentageReader
from keyboard_input import send_t

log = logging.getLogger('fishing_helper')

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


def _hsv_components(a):
    """Return HSV-like hue (degrees), saturation, and value using NumPy only."""
    x = a.astype(np.float32) / 255.0
    r, g, b = x[:, :, 0], x[:, :, 1], x[:, :, 2]
    mx = x.max(axis=2)
    mn = x.min(axis=2)
    delta = mx - mn
    hue = np.zeros_like(mx)
    nz = delta > 1e-6

    mask = (mx == r) & nz
    hue[mask] = 60.0 * np.mod((g[mask] - b[mask]) / delta[mask], 6.0)
    mask = (mx == g) & nz
    hue[mask] = 60.0 * ((b[mask] - r[mask]) / delta[mask] + 2.0)
    mask = (mx == b) & nz
    hue[mask] = 60.0 * ((r[mask] - g[mask]) / delta[mask] + 4.0)

    sat = np.zeros_like(mx)
    nonblack = mx > 1e-6
    sat[nonblack] = delta[nonblack] / mx[nonblack]
    return hue, sat, mx


def detect(image):
    """Locate the yellow/green target and the moving bright dot in the selected bar.

    The real game changes the target between yellow and green and can tint the
    white dot green while it overlaps the target.  Detection therefore uses
    hue + shape instead of requiring a single lime-green color.
    """
    a = (np.asarray(image.convert('RGB')) if isinstance(image, Image.Image) else np.asarray(image)).astype(np.uint8)
    height, width = a.shape[:2]
    hue, sat, value = _hsv_components(a)

    # The target outline/fill lives from yellow through green.  Water is blue,
    # the bar is mostly gray, and wood/sand are generally below this hue range.
    target_mask = (hue >= 35.0) & (hue <= 185.0) & (sat >= .20) & (value >= .28)
    rows = np.flatnonzero(target_mask.sum(axis=1) >= max(2, int(width * .03)))
    if len(rows) == 0:
        return None

    bands = np.split(rows, np.flatnonzero(np.diff(rows) > 2) + 1)
    candidates = []
    for band in bands:
        if len(band) == 0:
            continue
        y0, y1 = int(band[0]), int(band[-1])
        band_height = y1 - y0 + 1
        if not 5 <= band_height <= max(14, int(height * .25)):
            continue
        xs = np.flatnonzero(target_mask[y0:y1 + 1].sum(axis=0) >= 2)
        if len(xs) < max(8, int(width * .25)):
            continue
        x0, x1 = int(xs[0]), int(xs[-1])
        span = x1 - x0 + 1
        if span < width * .35:
            continue

        # Verify that the colored rectangle sits on the tall meter rather than
        # on similarly colored scenery.  The meter interior is dark/neutral
        # even when the world behind it is bright; this also keeps synthetic
        # bright-scenery false positives out.
        strip_left = x0 + int(span * .30)
        strip_right = x1 - int(span * .30)
        if strip_right <= strip_left:
            continue
        strip = a[:, strip_left:strip_right + 1].astype(np.int16)
        strip_max = strip.max(axis=2)
        strip_spread = strip.max(axis=2) - strip.min(axis=2)
        bar_like = (strip_max < 205) & (strip_spread < 85)
        sr, sg, sb = strip[:, :, 0], strip[:, :, 1], strip[:, :, 2]
        bar_like |= (strip_max < 165) & (sb > sr * .90) & (sb > sg * .75)
        if bar_like.mean() < .28:
            continue

        candidates.append((int(target_mask[y0:y1 + 1].sum()), y0, y1, x0, x1))
    if not candidates:
        return None

    _, y0, y1, x0, x1 = max(candidates)
    target_y = (y0 + y1) / 2.0

    # Search for the dot only inside the central portion of the target/bar.
    # This ignores the white vertical border of the meter itself.
    span = x1 - x0 + 1
    left = max(0, x0 + int(span * .18))
    right = min(width - 1, x1 - int(span * .18))
    if right <= left:
        return None
    middle = a[:, left:right + 1]
    dot_hue, dot_sat, dot_value = _hsv_components(middle)
    middle_i = middle.astype(np.int16)
    dot_min = middle_i.min(axis=2)
    dot_spread = middle_i.max(axis=2) - dot_min

    # Normally the dot is white/gray.  When it overlaps the target it becomes
    # pale green.  The stricter brightness check prevents a warm gray meter
    # background from being mistaken for one giant dot.
    dot_mask = ((dot_min > 172) & (dot_spread < 85)) | (
        (dot_min > 155)
        & (dot_hue >= 35.0) & (dot_hue <= 185.0)
        & (dot_value >= .70) & (dot_sat < .45)
    )
    row_score = dot_mask.sum(axis=1)
    dot_rows = np.flatnonzero(row_score >= max(4, int(middle.shape[1] * .20)))
    if len(dot_rows) == 0:
        return None

    dot_groups = np.split(dot_rows, np.flatnonzero(np.diff(dot_rows) > 1) + 1)
    dots = []
    for group in dot_groups:
        if len(group) == 0:
            continue
        dot_height = int(group[-1] - group[0] + 1)
        if max(5, int(height * .015)) <= dot_height <= max(45, int(height * .15)):
            dots.append((int(row_score[group].sum()), int(group[0]), int(group[-1])))
    if not dots:
        return None

    _, d0, d1 = max(dots)
    dot_y = (d0 + d1) / 2.0
    return target_y, dot_y


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Fishing Helper')
        self.root.geometry('450x440+40+80')
        self.root.attributes('-topmost', True)
        self.root.configure(bg='#111827')
        if not log.handlers:
            handler = RotatingFileHandler(Path(__file__).with_name('pickup.log'),maxBytes=150000,backupCount=1)
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            log.addHandler(handler)
            log.setLevel(logging.INFO)
        self.paused_state = None
        self.last_progress_value = None
        self.progress_log_due = 0
        self.bar_absent_since = None
        self.new_bar_frames = 0
        self.awaiting_new_bar = False
        self.pickups = 0
        self.session_text = tk.StringVar(value='Pickup sequences: 0')
        self.test_hold = False
        self.running = False
        self.held = False
        self.t_held = False
        self.region = None
        self.progress_region = None
        self.progress_overlay = None
        self.reader = PercentageReader()
        self.capture = RegionCapture()
        self.percent_capture = RegionCapture()
        self.tracker = Tracker()
        self.frames = 0
        self.fps_started = time.monotonic()
        self.detail_due = 0
        self.last_label = None
        self.timer_active = False
        self.performance = tk.StringVar(value='Tracking rate: stopped')
        self.progress_value = None
        self.progress_due = 0
        self.finish_reads = 0
        self.progress_armed = True
        self.progress_text = tk.StringVar(value='Progress: select the % text below the game')
        self.overlay = None
        self.state = 'idle'
        self.seen = 0
        self.last_keys = {}
        self.status = tk.StringVar(value='STOPPED')
        self.detail = tk.StringVar(value='Select the narrow fishing bar before starting.')
        self.up = tk.BooleanVar(value=True)
        self.tolerance = tk.DoubleVar(value=5)
        self.cast_seconds = tk.DoubleVar(value=.8)
        self.settings_path = Path(__file__).with_name('settings.json')
        self.setting_specs = {
            'finish_percent': ('Finish percentage (%)', 50, 100, 1, 98),
            'wait_seconds': ('Wait before T (seconds)', 0, 10, .1, 1.5),
            'hold_seconds': ('Hold T (seconds)', .1, 10, .1, 3.5),
        }
        try:
            saved = json.loads(self.settings_path.read_text())
            if not isinstance(saved,dict):
                saved = {}
        except (OSError,ValueError):
            saved = {}
        self.finish_settings = {}
        for key,(_,low,high,step,default) in self.setting_specs.items():
            value = saved.get(key,default)
            if not isinstance(value,(float,int)) or not math.isfinite(value):
                value = default
            self.finish_settings[key] = tk.DoubleVar(value=max(low,min(high,round(value/step)*step)))
        cast = saved.get('cast_seconds', .8)
        if isinstance(cast, (int, float)) and math.isfinite(cast):
            self.cast_seconds.set(max(.1, min(5, cast)))
        self.settings_window = None
        self.save_job = None
        self.sequence_text = tk.StringVar()
        self.settings_note = tk.StringVar(value='Saved automatically. Timing changes apply to the next pickup.')
        for variable in self.finish_settings.values():
            variable.trace_add('write',self.settings_changed)
        self.cast_seconds.trace_add('write',self.settings_changed)
        self.update_sequence_text()
        self.build_interface()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(30, self.tick)

    def build_interface(self):
        self.ui_scale = max(1.0, float(self.root.tk.call('tk', 'scaling')) / (96/72))
        self.content_width = int(360*self.ui_scale)
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#111827', foreground='#e2e8f0')
        style.configure('TFrame', background='#111827')
        style.configure('TButton', background='#263449', foreground='#f8fafc', borderwidth=0, padding=(12, 9))
        style.map('TButton', background=[('active', '#354862')])
        style.configure('Accent.TButton', background='#2563eb', font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#3b82f6')])
        style.configure('TCheckbutton', background='#111827', foreground='#cbd5e1')
        style.map('TCheckbutton', background=[('active', '#111827')])
        style.configure('TNotebook', background='#111827', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(18, 8), background='#1e293b')
        style.map('TNotebook.Tab', background=[('selected', '#334155')])
        tk.Label(self.root, text='Fishing Helper', fg='#f8fafc', bg='#111827',
                 font=('Segoe UI', 20, 'bold')).pack(anchor='w', padx=24, pady=(18, 2))
        tk.Label(self.root, text='Track. Collect. Repeat.', fg='#94a3b8', bg='#111827').pack(anchor='w', padx=24, pady=(0, 14))
        self.badge = tk.Label(self.root, textvariable=self.status, wraplength=self.content_width,
                             bg='#b91c1c', fg='white', font=('Segoe UI', 12, 'bold'), pady=12)
        self.badge.pack(fill='x', padx=24)
        tk.Label(self.root, textvariable=self.detail, wraplength=self.content_width, height=4,
                 justify='left', anchor='w', fg='#cbd5e1', bg='#111827').pack(fill='x', padx=24, pady=10)
        tabs = ttk.Notebook(self.root)
        tabs.pack(fill='both', expand=True, padx=24)
        run, tuning = ttk.Frame(tabs), ttk.Frame(tabs)
        tabs.add(run, text='Session')
        tabs.add(tuning, text='Settings')
        ttk.Button(run, text='1   Select fishing bar', command=self.select).pack(fill='x', pady=(12, 6))
        ttk.Button(run, text='2   Select percentage text', command=lambda:self.select(True)).pack(fill='x', pady=6)
        ttk.Label(run, textvariable=self.progress_text, wraplength=self.content_width, foreground='#fbbf24').pack(anchor='w', pady=6)
        ttk.Button(run, text='Start / Pause    F8', style='Accent.TButton', command=self.toggle).pack(fill='x', pady=6)
        ttk.Label(run, textvariable=self.session_text).pack(anchor='w', pady=(10, 3))
        ttk.Label(run, textvariable=self.performance, foreground='#94a3b8').pack(anchor='w')
        ttk.Label(run, text='Cyan = dot   ·   Orange = target', foreground='#94a3b8').pack(anchor='w', pady=6)
        ttk.Label(run, textvariable=self.sequence_text, wraplength=self.content_width, foreground='#93c5fd').pack(anchor='w', pady=10)
        ttk.Checkbutton(tuning, text='Holding click moves the dot up', variable=self.up).pack(anchor='w', pady=(14, 8))
        ttk.Label(tuning, text='Tracking tolerance').pack(anchor='w')
        ttk.Scale(tuning, from_=2, to=20, variable=self.tolerance).pack(fill='x', pady=8)
        ttk.Label(tuning, text='Cast hold duration (seconds)').pack(anchor='w')
        # A bounded scale cannot temporarily become empty like the old spinbox.
        tk.Scale(tuning, from_=.1, to=5, resolution=.1, orient='horizontal', variable=self.cast_seconds,
                 bg='#111827', fg='#93c5fd', troughcolor='#334155', highlightthickness=0).pack(fill='x')
        ttk.Button(tuning, text='Pickup timing…', command=self.show_settings).pack(fill='x', pady=8)
        ttk.Button(tuning, text='Test T hold    F7', command=self.test_t_hold).pack(fill='x', pady=4)
        ttk.Label(tuning, text='F7 holds T without casting. Keep Roblox focused.', wraplength=self.content_width, foreground='#94a3b8').pack(anchor='w', pady=10)
        ttk.Button(self.root, text='Stop and release inputs    F9', command=self.stop).pack(fill='x', padx=24, pady=(12, 6))
        tk.Label(self.root, text='Keep Roblox visible and focused', fg='#94a3b8', bg='#111827').pack(pady=(0, 12))
        self.root.update_idletasks()
        self.root.geometry(f'{max(int(420*self.ui_scale),self.root.winfo_reqwidth())}x{self.root.winfo_reqheight()}+40+60')
        self.root.resizable(False, False)

    def update_sequence_text(self):
        v = {key:variable.get() for key,variable in self.finish_settings.items()}
        self.sequence_text.set(
            f'{v["finish_percent"]:.0f}% → wait {v["wait_seconds"]:g}s → hold T {v["hold_seconds"]:g}s '
            f'→ cast again ({self.cast_seconds.get():g}s left click)'
        )

    def settings_changed(self,*args):
        self.update_sequence_text()
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(400,self.save_settings)

    def save_settings(self):
        self.save_job = None
        try:
            temp = self.settings_path.with_suffix('.tmp')
            temp.write_text(json.dumps({**{key:v.get() for key,v in self.finish_settings.items()}, 'cast_seconds': self.cast_seconds.get()},indent=2))
            temp.replace(self.settings_path)
            self.settings_note.set('Saved automatically. Timing changes apply to the next pickup.')
        except OSError:
            self.settings_note.set('Settings work now, but could not be saved to disk.')

    def show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        win = self.settings_window = tk.Toplevel(self.root)
        win.title('Customize finish sequence')
        win.configure(bg='#111827')
        win.attributes('-topmost',True)
        for key,(label,low,high,step,_) in self.setting_specs.items():
            tk.Label(win,text=label,fg='white',bg='#111827',font=('Segoe UI',11)).pack(anchor='w',padx=22,pady=(12,0))
            tk.Scale(win,from_=low,to=high,resolution=step,orient='horizontal',variable=self.finish_settings[key],
                     length=int(420*self.ui_scale),bg='#111827',fg='#93c5fd',troughcolor='#334155',highlightthickness=0).pack(fill='x',padx=22)
        tk.Label(win,textvariable=self.settings_note,wraplength=int(430*self.ui_scale),fg='#cbd5e1',bg='#111827').pack(padx=22,pady=12)
        ttk.Button(win,text='Restore defaults',command=self.reset_settings).pack(fill='x',padx=22,pady=5)
        ttk.Button(win,text='Done',command=win.destroy).pack(fill='x',padx=22,pady=(5,16))

    def reset_settings(self):
        for key,spec in self.setting_specs.items():
            self.finish_settings[key].set(spec[4])

    def mouse(self, down):
        if down != self.held:
            user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)
            self.held = down

    def begin_cast(self, now, label='CASTING — holding left click'):
        """Start one cast using the same click duration every time."""
        self.mouse(True)
        self.deadline = now + max(.1, min(5, self.cast_seconds.get()))
        self.state = 'click'
        self.label(label)

    def key_t(self, down, force=False):
        if down != self.t_held or force:
            send_t(down)
            self.t_held = down
            log.info('T %s%s', 'DOWN' if down else 'UP', ' reasserted' if force else '')

    def test_t_hold(self):
        self.stop()
        self.test_hold = True
        self.running = True
        self.timer_active = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        self.pickup_hold_seconds = self.finish_settings['hold_seconds'].get()
        self.state = 'finish_wait'
        self.deadline = time.monotonic()+2
        self.label('T TEST — focus Roblox')
        self.detail.set('Focus Roblox within 2 seconds. This tests T only; no cast click follows.')
        log.info('Manual T test requested, duration %.2fs', self.pickup_hold_seconds)

    def label(self, text, active=False):
        if self.last_label == (text,active):
            return
        self.last_label = (text,active)
        self.status.set(text)
        color = '#15803d' if active else '#b91c1c'
        self.badge.configure(bg=color)
        if self.overlay:
            self.canvas.itemconfigure(self.border, outline=color)
            self.canvas.itemconfigure(self.caption, fill=color)

    def stop(self):
        self.running = False
        self.test_hold = False
        if self.timer_active:
            ctypes.windll.winmm.timeEndPeriod(1)
            self.timer_active = False
        self.mouse(False)
        self.key_t(False)
        self.state = 'idle'
        self.paused_state = None
        self.awaiting_new_bar = False
        self.bar_absent_since = None
        self.new_bar_frames = 0
        self.seen = 0
        self.finish_reads = 0
        self.progress_due = 0
        self.progress_armed = True
        self.tracker.reset()
        self.performance.set('Tracking rate: stopped')
        self.tracking_lines(None)
        self.label('STOPPED')

    def toggle(self):
        if self.running:
            self.stop()
        elif self.region and self.progress_region:
            self.running = True
            self.timer_active = ctypes.windll.winmm.timeBeginPeriod(1) == 0
            self.frames = 0
            self.fps_started = time.monotonic()
            self.state = 'cast_delay'
            self.deadline = time.monotonic() + 2
            self.detail.set('Focus Roblox and put your mouse over the game. Starting in 2 seconds.')
        else:
            self.detail.set('Select the fishing bar, then the percentage text.')

    def select(self, progress=False):
        self.stop()
        if not progress and self.overlay:
            self.overlay.destroy()
            self.overlay = None
        self.root.withdraw()
        picker = tk.Toplevel(self.root)
        picker.attributes('-fullscreen', True)
        picker.attributes('-topmost', True)
        picker.attributes('-alpha', .30)
        picker.configure(bg='black', cursor='crosshair')
        c = tk.Canvas(picker, bg='black', highlightthickness=0)
        c.pack(fill='both', expand=True)
        instruction = 'Drag tightly around ONLY the bottom percentage text, including %. Exclude Exit.' if progress else 'Drag tightly around the ENTIRE vertical fishing bar. Esc cancels.'
        c.create_text(30, 35, anchor='nw', text=instruction, fill='white', font=('Segoe UI', 19))
        start = []
        rect = []
        def press(e):
            start[:] = [e.x_root, e.y_root]
            rect[:] = [c.create_rectangle(e.x, e.y, e.x, e.y, outline='red', width=3)]
        def drag(e):
            if rect:
                c.coords(rect[0], start[0], start[1], e.x_root, e.y_root)
        def finish(e):
            if start:
                x1, x2 = sorted([start[0], e.x_root])
                y1, y2 = sorted([start[1], e.y_root])
                if x2-x1 > 15 and y2-y1 > (8 if progress else 70):
                    if progress:
                        self.progress_region = (x1, y1, x2, y2)
                    else:
                        self.region = (x1, y1, x2, y2)
            picker.destroy()
            self.root.deiconify()
            if progress and self.progress_region:
                self.progress_text.set('Progress area selected. Waiting to read %.')
                self.draw_progress_overlay()
            elif self.region:
                self.draw_overlay()
                self.detail.set('Area selected. F8 starts; F9 stops. Focus Roblox during play.')
        c.bind('<ButtonPress-1>', press)
        c.bind('<B1-Motion>', drag)
        c.bind('<ButtonRelease-1>', finish)
        picker.bind('<Escape>', lambda e: (picker.destroy(), self.root.deiconify()))

    def draw_overlay(self):
        x1, y1, x2, y2 = self.region
        w, h = x2-x1, y2-y1
        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.geometry(f'{w+12}x{h+38}+{x1-6}+{y1-30}')
        self.overlay.attributes('-topmost', True)
        self.overlay.attributes('-transparentcolor', '#010101')
        self.canvas = tk.Canvas(self.overlay, bg='#010101', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.border = self.canvas.create_rectangle(2, 26, w+10, h+36, outline='#b91c1c', width=3)
        self.caption = self.canvas.create_text(4, 10, anchor='w', text='FISHING', fill='#b91c1c', font=('Segoe UI', 9, 'bold'))
        self.dot_line = self.canvas.create_line(5,30,w+7,30,fill='#00e5ff',width=3,state='hidden')
        self.target_line = self.canvas.create_line(5,30,w+7,30,fill='#ff8800',width=3,state='hidden')
        self.overlay.update_idletasks()
        hwnd = user32.GetParent(self.overlay.winfo_id())
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x08000000)
        user32.SetWindowDisplayAffinity(hwnd, 0x11)

    def draw_progress_overlay(self):
        existing = self.progress_overlay
        if existing:
            existing.destroy()
        x1,y1,x2,y2 = self.progress_region
        win = tk.Toplevel(self.root)
        self.progress_overlay = win
        win.overrideredirect(True)
        win.geometry(f'{x2-x1+8}x{y2-y1+8}+{x1-4}+{y1-4}')
        win.attributes('-topmost',True)
        win.attributes('-transparentcolor','#010101')
        c = tk.Canvas(win,bg='#010101',highlightthickness=0)
        c.pack(fill='both',expand=True)
        c.create_rectangle(1,1,x2-x1+6,y2-y1+6,outline='#fbbf24',width=2)
        win.update_idletasks()
        hwnd = user32.GetParent(win.winfo_id())
        user32.SetWindowLongW(hwnd,-20,user32.GetWindowLongW(hwnd,-20)|0x80000|0x20|0x08000000)
        user32.SetWindowDisplayAffinity(hwnd,0x11)

    def tracking_lines(self, result):
        if not self.overlay:
            return
        for item,y in ((self.target_line,result[0] if result else 0),(self.dot_line,result[1] if result else 0)):
            self.canvas.coords(item,5,y+30,self.region[2]-self.region[0]+7,y+30)
            self.canvas.itemconfigure(item,state='normal' if result else 'hidden')

    def game_focused(self):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(user32.GetForegroundWindow(), buf, 512)
        return 'roblox' in buf.value.lower()

    def tick(self):
        started = time.perf_counter()
        try:
            for key in (0x76, 0x77, 0x78):
                down = bool(user32.GetAsyncKeyState(key) & 0x8000)
                if down and not self.last_keys.get(key):
                    if key == 0x78:
                        self.stop()
                    elif key == 0x76:
                        self.test_t_hold()
                    else:
                        self.toggle()
                self.last_keys[key] = down
            if self.running:
                self.step()
        except Exception as exc:
            log.exception('Helper stopped after input or capture error')
            self.stop()
            self.detail.set(f'Stopped: {exc}')
        finally:
            elapsed_ms = (time.perf_counter()-started)*1000
            self.root.after(max(1,int(1000/60-elapsed_ms)) if self.running else 30, self.tick)

    def step(self):
        now = time.monotonic()
        if not self.game_focused():
            if self.paused_state is None:
                self.paused_state = self.state
                log.info('Focus paused in %s', self.state)
            self.tracker.reset()
            self.mouse(False)
            self.key_t(False)
            self.label('PAUSED — focus Roblox')
            self.detail.set('Waiting for Roblox focus. A paused pickup restarts its full wait and hold; no cast is sent early.')
            return
        if self.paused_state is not None:
            previous = self.paused_state
            self.paused_state = None
            log.info('Focus restored; resuming %s', previous)
            if previous in ('finish', 'finish_pending', 'finish_wait'):
                self.state = 'finish_wait'
                self.deadline = now + self.finish_settings['wait_seconds'].get()
            elif previous == 'click':
                self.state = 'recast'
                self.deadline = now + .5
            self.label('RESUMING')
        if self.state in ('cast_delay', 'recast'):
            if now >= self.deadline:
                # Starting during a live minigame should track, not cast into it.
                if detect(self.capture.grab(self.region)) is not None:
                    self.state = 'waiting'
                    return
                self.begin_cast(now)
            return
        if self.state == 'click':
            if now >= self.deadline:
                self.mouse(False)
                self.state = 'waiting'
                self.label('NO FISH — waiting')
                self.detail.set('Waiting for the green target and white dot to appear.')
            return
        if self.state == 'finish_wait':
            if now < self.deadline:
                self.detail.set(f'Waiting {self.deadline-now:.1f}s before holding T.')
                return
            self.state = 'finish_pending'
        if self.state == 'finish_pending':
            self.key_t(True)
            self.deadline = None
            self.confirm_deadline = time.monotonic()+.25
            self.hold_retries = 0
            self.state = 'finish'
            self.label('FINISHED — holding T',True)
            self.detail.set(f'Holding T for {self.pickup_hold_seconds:g} seconds, then clicking once.')
        if self.state == 'finish':
            observed_down = bool(user32.GetAsyncKeyState(0x54) & 0x8000)
            if not observed_down:
                if self.deadline is not None:
                    log.info('Windows reported T UP during hold; continuous hold timer reset')
                    self.deadline = None
                    self.confirm_deadline = now
                if now >= self.confirm_deadline:
                    if self.hold_retries >= 2:
                        self.stop()
                        self.detail.set('T did not stay DOWN in Windows. Stopped without casting. Try F7 to test T by itself.')
                        log.info('T hold failed after two retries; no cast sent')
                        return
                    self.key_t(True,force=True)
                    self.hold_retries += 1
                    self.confirm_deadline = now+.25
                self.label('VERIFYING T — waiting')
                self.detail.set('Waiting for Windows to confirm T is DOWN. Hold timer has not started.')
                return
            if self.deadline is None:
                now = time.monotonic()
                self.deadline = now+self.pickup_hold_seconds
                log.info('Windows confirmed T DOWN; continuous hold %.2fs',self.pickup_hold_seconds)
                self.label('T CONFIRMED — holding',True)
            if now >= self.detail_due:
                self.detail_due = now+.1
                self.detail.set(f'T held: {max(0,self.deadline-now):.1f}s remaining. Windows key state: DOWN.')
            if now >= self.deadline:
                self.key_t(False)
                log.info('Verified hold completed')
                if self.test_hold:
                    self.stop()
                    self.detail.set('T test complete: Windows reported DOWN for the full hold. No cast click was sent.')
                    return
                self.pickups += 1
                self.session_text.set(f'Pickup sequences: {self.pickups}')
                self.awaiting_new_bar = True
                self.bar_absent_since = None
                self.new_bar_frames = 0
                self.seen = 0
                self.tracker.reset()
                self.begin_cast(now, 'CASTING — next cast')
                self.finish_reads = 0
                self.progress_value = None
            return
        if now >= self.progress_due and self.progress_region:
            self.progress_due = now + .012
            self.progress_value = self.reader.read(Image.fromarray(self.percent_capture.grab(self.progress_region)))
            self.progress_text.set(f'Progress: {self.progress_value}%' if self.progress_value is not None else 'Progress: unreadable — check % selection')
            if self.progress_value is not None:
                self.last_progress_value = self.progress_value
            if now >= self.progress_log_due:
                self.progress_log_due = now + 2
                log.info('Progress=%s armed=%s state=%s', self.progress_value, self.progress_armed, self.state)
            threshold = self.finish_settings['finish_percent'].get()
            if self.progress_value is not None and self.progress_value < threshold-3:
                self.progress_armed = True
            if self.progress_armed and self.progress_value is not None and self.progress_value >= threshold:
                self.finish_reads = 1
                log.info('Completion reached at %s%% (threshold %s%%)',self.progress_value,threshold)
                self.begin_pickup(now,f'{self.progress_value}% reached')
                return
            self.finish_reads = 0
        result = detect(self.capture.grab(self.region))
        # A genuinely new meter can re-arm pickup even if early % reads failed.
        # Require disappearance followed by several visible frames, never a timer alone.
        if self.awaiting_new_bar:
            if result is None:
                if self.bar_absent_since is None:
                    self.bar_absent_since = now
                self.new_bar_frames = 0
            elif self.bar_absent_since is not None and now-self.bar_absent_since >= .4:
                self.new_bar_frames += 1
                if self.new_bar_frames >= 3:
                    self.progress_armed = True
                    self.awaiting_new_bar = False
                    log.info('New fishing meter confirmed; pickup re-armed')
            else:
                self.bar_absent_since = None
        observed = time.monotonic()
        self.frames += 1
        if observed-self.fps_started >= 1:
            self.performance.set(f'Tracking: {self.frames/(observed-self.fps_started):.0f} FPS | frame work: {(observed-now)*1000:.0f} ms')
            self.frames = 0
            self.fps_started = observed
        self.tracking_lines(result)
        if result:
            self.seen += 1
            if self.seen >= 3:
                self.state = 'tracking'
                self.label('FISH ON — tracking', True)
                target, dot = result
                error = dot - target
                self.mouse(self.tracker.decide(target,dot,observed,self.tolerance.get(),self.up.get(),self.held,self.region[3]-self.region[1]))
                action = 'HOLDING left click' if self.held else 'RELEASING left click'
                if observed >= self.detail_due:
                    self.detail_due = observed+.15
                    self.detail.set(f'{action}. Dot offset: {error:.0f}px. If it moves away from the box, reverse the UP option.')
        else:
            self.tracker.reset()
            self.seen = 0
            self.mouse(False)
            self.label('NO FISH — waiting')
            last = self.last_progress_value
            if last is not None and self.progress_armed:
                self.detail.set(f'Bar not detected. Last progress: {last}%. Pickup needs {self.finish_settings["finish_percent"].get():g}%. If a catch is waiting, check the % selection; F7 tests collection.')
            else:
                self.detail.set('Waiting for the fishing bar. If a catch is already on the rod, use F7 to collect it before restarting.')
            # Losing visual tracking never means the catch is complete.

    def begin_pickup(self,now,reason):
        log.info('Pickup trigger: %s',reason)
        self.progress_armed = False
        self.mouse(False)
        self.state = 'finish_wait'
        wait_seconds = self.finish_settings['wait_seconds'].get()
        self.pickup_hold_seconds = self.finish_settings['hold_seconds'].get()
        self.deadline = now+wait_seconds
        self.tracking_lines(None)
        self.label('FINISHED — waiting',True)
        ending = f'for {self.pickup_hold_seconds:g}s'
        self.detail.set(f'{reason}. Waiting {wait_seconds:g}s before holding T {ending}.')

    def close(self):
        try:
            self.stop()
            if self.save_job:
                self.root.after_cancel(self.save_job)
                self.save_settings()
        finally:
            self.capture.close()
            self.percent_capture.close()
            self.root.destroy()


def main():
    # Keep the handle alive for the entire process; Windows releases it on exit.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, False, r'Local\AlyzziniFishingHelper')
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    already_running = ctypes.get_last_error() == 183
    try:
        if already_running:
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            hwnd = user32.FindWindowW(None, 'Fishing Helper')
            if hwnd:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
            return
        helper = App()
        try:
            helper.root.mainloop()
        finally:
            helper.mouse(False)
            helper.key_t(False)
    finally:
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    main()
