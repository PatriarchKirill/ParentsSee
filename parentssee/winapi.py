"""Тонкая обёртка над WinAPI: простой (idle), состояние сессии, границы экранов."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
kernel32.GetTickCount.restype = wintypes.DWORD
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

_DESKTOP_SWITCHDESKTOP = 0x0100
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


def idle_seconds() -> float:
    """Сколько секунд не было ввода с клавиатуры/мыши."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # GetTickCount и dwTime — 32-битные, считаем разницу с учётом переполнения.
    delta = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return delta / 1000.0


def session_locked() -> bool:
    """True, если активен экран блокировки Windows или переключение пользователя."""
    handle = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not handle:
        return True
    user32.CloseDesktop(handle)
    return False


def lock_workstation() -> None:
    """Штатная блокировка Windows (Win+L)."""
    user32.LockWorkStation()


def virtual_screen() -> tuple[int, int, int, int]:
    """(x, y, width, height) прямоугольника, покрывающего все мониторы."""
    return (
        user32.GetSystemMetrics(_SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(_SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN),
    )


def enable_dpi_awareness() -> None:
    """Без этого полноэкранное окно на HiDPI считает размеры неверно."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def mutex_exists(name: str) -> bool:
    """Проверка «процесс с таким мьютексом уже запущен»."""
    SYNCHRONIZE = 0x00100000
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True
