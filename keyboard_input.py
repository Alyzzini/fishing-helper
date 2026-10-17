"""Send physical scan-code key transitions through Windows SendInput."""
import ctypes as c
from ctypes import wintypes as w


class MouseInput(c.Structure):
    _fields_ = [('dx',w.LONG),('dy',w.LONG),('mouseData',w.DWORD),
                ('dwFlags',w.DWORD),('time',w.DWORD),('dwExtraInfo',c.c_size_t)]


class KeyboardInput(c.Structure):
    _fields_ = [('wVk',w.WORD),('wScan',w.WORD),('dwFlags',w.DWORD),
                ('time',w.DWORD),('dwExtraInfo',c.c_size_t)]


class HardwareInput(c.Structure):
    _fields_ = [('uMsg',w.DWORD),('wParamL',w.WORD),('wParamH',w.WORD)]


class InputUnion(c.Union):
    _fields_ = [('mi',MouseInput),('ki',KeyboardInput),('hi',HardwareInput)]


class Input(c.Structure):
    _fields_ = [('type',w.DWORD),('data',InputUnion)]


user = c.WinDLL('user32',use_last_error=True)
user.SendInput.argtypes = [w.UINT,c.POINTER(Input),c.c_int]
user.SendInput.restype = w.UINT


def t_event(down):
    event = Input()
    event.type = 1
    event.data.ki = KeyboardInput(0,0x14,0x0008 | (0 if down else 0x0002),0,0)
    return event


def send_t(down):
    event = t_event(down)
    if user.SendInput(1,c.byref(event),c.sizeof(Input)) != 1:
        raise RuntimeError('Windows did not accept the T key input. Pickup stopped.')
