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


def detect(image):
    """Locate the lime target and white dot inside a tightly selected bar."""
    a = (np.asarray(image.convert('RGB')) if isinstance(image,Image.Image) else image).astype(np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    green = (g > 150) & (g > b * 1.12) & (r < g * 1.40)
    rows = np.flatnonzero(green.sum(axis=1) >= max(3, a.shape[1] * .035))
    if len(rows) < 4:
        return None
    bands = np.split(rows, np.flatnonzero(np.diff(rows) > 3) + 1)
    for band in bands:
        if not 5 <= band[-1]-band[0] <= a.shape[0]*.24:
            continue
        xs = np.flatnonzero(green[band[0]:band[-1]+1].sum(axis=0) >= 2)
        if len(xs) < 8:
            continue
        left, right = int(xs[0]), int(xs[-1])
        width = right-left+1
        if not .65 <= width/(band[-1]-band[0]+1) <= 4:
            continue
        # The translucent bar also becomes warm gray against sand/wood.
        # Keep bright scenery and saturated cyan water out of this check.
        mid = a[:, left+int(width*.28):left+max(int(width*.72), 1)]
        if mid.size == 0:
            continue
        mr, mg, mb = mid[:,:,0], mid[:,:,1], mid[:,:,2]
        neutral_bar = (mid.max(axis=2) < 210) & (np.ptp(mid, axis=2) < 45)
        bar_background = (mid.max(axis=2) < 150) | neutral_bar | ((mb > 50) & (mg < mb*.90) & (mr < mb*.75))
        if bar_background.mean() < .40:
            continue
        white = (mid.min(axis=2) > 175) & (np.ptp(mid, axis=2) < 55)
        scores = white.mean(axis=1)
        candidates = np.flatnonzero(scores > .45)
        groups = np.split(candidates, np.flatnonzero(np.diff(candidates) > 1) + 1)
        groups = [v for v in groups if max(3, width*.08) <= len(v) <= width*.85]
        if groups:
            dot = max(groups, key=lambda v: float(scores[v].sum()))
            return (float(band[0])+float(band[-1]))/2, float(dot.mean())
    return None


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
        self.lost = None
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
            'click_seconds': ('Final single click duration (seconds)', .05, 2, .05, .1),
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
        self.settings_window = None
        self.save_job = None
        self.sequence_text = tk.StringVar()
        self.settings_note = tk.StringVar(value='Saved automatically. Timing changes apply to the next pickup.')
        for variable in self.finish_settings.values():
            variable.trace_add('write',self.settings_changed)
        self.update_sequence_text()
        tk.Label(self.root, text='FISHING HELPER', fg='white', bg='#111827', font=('Segoe UI', 21, 'bold')).pack(pady=(20, 12))
        self.badge = tk.Label(self.root, textvariable=self.status, wraplength=380, height=2, bg='#b91c1c', fg='white', font=('Segoe UI', 14, 'bold'), pady=12)
        self.badge.pack(fill='x', padx=22)
        tk.Label(self.root, textvariable=self.detail, wraplength=395, height=5, fg='#cbd5e1', bg='#111827', font=('Segoe UI', 10)).pack(pady=12)
        ttk.Button(self.root, text='1. Select fishing bar area', command=self.select).pack(fill='x', padx=22, pady=5)
        ttk.Button(self.root, text='2. Select bottom % text', command=lambda: self.select(True)).pack(fill='x', padx=22, pady=5)
        tk.Label(self.root, textvariable=self.progress_text, fg='#fbbf24', bg='#111827').pack()
        ttk.Button(self.root, text='3. Start / Stop (F8)', command=self.toggle).pack(fill='x', padx=22, pady=5)
        tk.Label(self.root, text='Cyan line = dot   |   Orange line = target', fg='#cbd5e1', bg='#111827').pack()
        tk.Label(self.root, textvariable=self.performance, fg='#93c5fd', bg='#111827').pack()
        ttk.Checkbutton(self.root, text='Holding click moves the white dot UP', variable=self.up).pack(pady=9)
        tk.Label(self.root, text='Tracking tolerance (pixels)', fg='white', bg='#111827').pack()
        ttk.Scale(self.root, from_=2, to=20, variable=self.tolerance).pack(fill='x', padx=40)
        cast_row = ttk.Frame(self.root)
        cast_row.pack(pady=8)
        ttk.Label(cast_row, text='Cast click hold (seconds): ').pack(side='left')
        ttk.Spinbox(cast_row, from_=.1, to=5, increment=.1, textvariable=self.cast_seconds, width=5).pack(side='left')
        ttk.Button(self.root,text='Customize finish sequence…',command=self.show_settings).pack(fill='x',padx=22,pady=5)
        ttk.Button(self.root,text='Test T hold only (F7)',command=self.test_t_hold).pack(fill='x',padx=22,pady=5)
        tk.Label(self.root,textvariable=self.sequence_text,wraplength=400,fg='#93c5fd',bg='#111827').pack(pady=5)
        tk.Label(self.root, text='F9: emergency stop  •  Keep Roblox focused', fg='#94a3b8', bg='#111827').pack(pady=8)
        # Tk fonts scale with Windows DPI; size the window from its actual contents.
        self.root.update_idletasks()
        width = max(450, self.root.winfo_reqwidth() + 32)
        height = max(440, self.root.winfo_reqheight() + 24)
        self.root.geometry(f'{width}x{height}+40+80')
        self.root.minsize(width, height)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(30, self.tick)

    def update_sequence_text(self):
        v = {key:variable.get() for key,variable in self.finish_settings.items()}
        self.sequence_text.set(f'{v["finish_percent"]:.0f}% → wait {v["wait_seconds"]:g}s → hold T {v["hold_seconds"]:g}s → one {v["click_seconds"]:g}s click')

    def settings_changed(self,*args):
        self.update_sequence_text()
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(400,self.save_settings)

    def save_settings(self):
        self.save_job = None
        try:
            temp = self.settings_path.with_suffix('.tmp')
            temp.write_text(json.dumps({key:v.get() for key,v in self.finish_settings.items()},indent=2))
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
                     length=420,bg='#111827',fg='#93c5fd',troughcolor='#334155',highlightthickness=0).pack(fill='x',padx=22)
        tk.Label(win,textvariable=self.settings_note,wraplength=430,fg='#cbd5e1',bg='#111827').pack(padx=22,pady=12)
        ttk.Button(win,text='Restore defaults',command=self.reset_settings).pack(fill='x',padx=22,pady=5)
        ttk.Button(win,text='Done',command=win.destroy).pack(fill='x',padx=22,pady=(5,16))

    def reset_settings(self):
        for key,spec in self.setting_specs.items():
            self.finish_settings[key].set(spec[4])

    def mouse(self, down):
        if down != self.held:
            user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)
            self.held = down

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
        self.seen = 0
        self.lost = None
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
            if self.state == 'finish':
                log.info('Pickup interrupted by focus loss')
                self.stop()
                self.detail.set('Pickup interrupted: Roblox lost focus while T was held. Stopped before the next click.')
                return
            self.tracker.reset()
            self.mouse(False)
            self.key_t(False)
            self.label('PAUSED — focus Roblox')
            return
        if self.state in ('cast_delay', 'recast'):
            if now >= self.deadline:
                # Starting during a live minigame should track, not cast into it.
                if detect(self.capture.grab(self.region)) is not None:
                    self.state = 'waiting'
                    return
                self.mouse(True)
                self.deadline = now + max(.1, min(5, self.cast_seconds.get()))
                self.state = 'click'
                self.label('CASTING — holding click')
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
                self.mouse(True)
                self.state = 'click'
                self.deadline = now + self.pickup_click_seconds
                self.label('CASTING — one click')
                self.finish_reads = 0
                self.progress_value = None
            return
        if now >= self.progress_due and self.progress_region:
            self.progress_due = now + .05
            self.progress_value = self.reader.read(Image.fromarray(self.percent_capture.grab(self.progress_region)))
            self.progress_text.set(f'Progress: {self.progress_value}%' if self.progress_value is not None else 'Progress: unreadable — check % selection')
            threshold = self.finish_settings['finish_percent'].get()
            if self.progress_value is not None and self.progress_value < threshold-3:
                self.progress_armed = True
            self.finish_reads = self.finish_reads+1 if self.progress_armed and self.progress_value is not None and self.progress_value >= threshold else 0
            if self.finish_reads >= 2:
                log.info('Completion confirmed at %s%% (threshold %s%%)',self.progress_value,threshold)
                self.begin_pickup(now,f'{self.progress_value}% confirmed')
                return
        result = detect(self.capture.grab(self.region))
        observed = time.monotonic()
        self.frames += 1
        if observed-self.fps_started >= 1:
            self.performance.set(f'Tracking: {self.frames/(observed-self.fps_started):.0f} FPS | frame work: {(observed-now)*1000:.0f} ms')
            self.frames = 0
            self.fps_started = observed
        self.tracking_lines(result)
        if result:
            self.seen += 1
            self.lost = None
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
            self.detail.set('Mouse released: no fishing bar detected. Select tightly around the visible bar, not the water.')
            # Losing visual tracking never means the catch is complete.

    def begin_pickup(self,now,reason):
        log.info('Pickup trigger: %s',reason)
        self.progress_armed = False
        self.mouse(False)
        self.state = 'finish_wait'
        wait_seconds = self.finish_settings['wait_seconds'].get()
        self.pickup_hold_seconds = self.finish_settings['hold_seconds'].get()
        self.pickup_click_seconds = self.finish_settings['click_seconds'].get()
        self.deadline = now+wait_seconds
        self.tracking_lines(None)
        self.label('FINISHED — waiting',True)
        ending = f'for {self.pickup_hold_seconds:g}s'
        self.detail.set(f'{reason}. Waiting {wait_seconds:g}s before holding T {ending}.')

    def close(self):
        self.stop()
        if self.save_job:
            self.root.after_cancel(self.save_job)
            self.save_settings()
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
        App().root.mainloop()
    finally:
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    main()
