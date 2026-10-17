"""Reusable Windows capture surfaces; copy only the requested rectangle."""
import ctypes as c
from ctypes import wintypes as w
import numpy as np

gdi = c.WinDLL('gdi32', use_last_error=True)
user = c.WinDLL('user32', use_last_error=True)
user.GetDC.argtypes = [w.HWND]
user.GetDC.restype = w.HDC
user.ReleaseDC.argtypes = [w.HWND, w.HDC]
gdi.CreateCompatibleDC.argtypes = [w.HDC]
gdi.CreateCompatibleDC.restype = w.HDC
gdi.SelectObject.argtypes = [w.HDC, w.HANDLE]
gdi.SelectObject.restype = w.HANDLE
gdi.DeleteObject.argtypes = [w.HANDLE]
gdi.DeleteDC.argtypes = [w.HDC]
gdi.BitBlt.argtypes = [w.HDC,c.c_int,c.c_int,c.c_int,c.c_int,w.HDC,c.c_int,c.c_int,w.DWORD]


class Header(c.Structure):
    _fields_ = [('size',w.DWORD),('width',w.LONG),('height',w.LONG),
                ('planes',w.WORD),('bits',w.WORD),('compression',w.DWORD),
                ('image_size',w.DWORD),('xppm',w.LONG),('yppm',w.LONG),
                ('colors',w.DWORD),('important',w.DWORD)]


class Info(c.Structure):
    _fields_ = [('header',Header),('colors',w.DWORD*3)]


gdi.CreateDIBSection.argtypes = [w.HDC,c.POINTER(Info),w.UINT,c.POINTER(c.c_void_p),w.HANDLE,w.DWORD]
gdi.CreateDIBSection.restype = w.HANDLE


class RegionCapture:
    def __init__(self):
        self.screen = user.GetDC(None)
        self.dc = gdi.CreateCompatibleDC(self.screen)
        self.bitmap = None
        self.original = None
        self.size = None
        if not self.screen or not self.dc:
            self.close()
            raise RuntimeError('Cannot create screen capture surface')

    def grab(self, bbox):
        x,y,right,bottom = bbox
        width,height = right-x,bottom-y
        if width <= 0 or height <= 0:
            raise ValueError('Invalid capture area')
        if self.size != (width,height):
            if self.bitmap:
                gdi.SelectObject(self.dc,self.original)
                gdi.DeleteObject(self.bitmap)
                self.bitmap = None
            info = Info()
            info.header = Header(c.sizeof(Header),width,-height,1,32,0,width*height*4,0,0,0,0)
            bits = c.c_void_p()
            self.bitmap = gdi.CreateDIBSection(self.screen,c.byref(info),0,c.byref(bits),None,0)
            if not self.bitmap:
                raise c.WinError(c.get_last_error())
            self.original = gdi.SelectObject(self.dc,self.bitmap)
            self.buffer = np.ctypeslib.as_array((c.c_ubyte*(width*height*4)).from_address(bits.value)).reshape(height,width,4)
            self.size = width,height
        if not gdi.BitBlt(self.dc,0,0,width,height,self.screen,x,y,0x00CC0020):
            raise c.WinError(c.get_last_error())
        gdi.GdiFlush()
        return self.buffer[:,:,:3][:,:,::-1].copy()

    def close(self):
        if self.bitmap:
            gdi.SelectObject(self.dc,self.original)
            gdi.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.dc:
            gdi.DeleteDC(self.dc)
            self.dc = None
        if self.screen:
            user.ReleaseDC(None,self.screen)
            self.screen = None
