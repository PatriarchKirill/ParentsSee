"""Жёсткая блокировка рабочего стола: панель задач, системные клавиши, диспетчер задач.

Всё, что здесь включается, обязано выключаться: release() вызывается из
finally и дополнительно регистрируется в atexit.
"""
from __future__ import annotations

import atexit
import ctypes
import logging
import threading
import winreg
from ctypes import wintypes

from .paths import DATA_DIR

log = logging.getLogger("parentssee")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong
LRESULT = ctypes.c_ssize_t

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012
LLKHF_ALTDOWN = 0x20

VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_APPS = 0x5D
VK_F4 = 0x73
VK_CONTROL = 0x11
VK_SHIFT = 0x10

SW_HIDE = 0
SW_SHOW = 5

POLICY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
DISABLE_TASKMGR = "DisableTaskMgr"

# Метка «блокировка была включена». Если процесс убили через taskkill,
# finally и atexit не отработают — файл останется и подскажет, что чинить.
ENGAGED_FLAG = DATA_DIR / "blocker.flag"


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.CFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT)
)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [
    wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR
]
user32.FindWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


def _pressed(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class KeyboardBlocker:
    """Низкоуровневый хук: гасит Win, Alt+Tab, Alt+Esc, Ctrl+Esc, Alt+F4, Ctrl+Shift+Esc.

    Ctrl+Alt+Del перехватить нельзя — эту комбинацию обрабатывает само ядро
    Windows. Поэтому дополнительно отключается сам диспетчер задач.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hook = None
        self._proc = HOOKPROC(self._callback)   # ссылку нельзя терять
        self._ready = threading.Event()

    def _callback(self, code, wparam, lparam):
        if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            info = lparam.contents
            vk = info.vkCode
            alt = bool(info.flags & LLKHF_ALTDOWN)
            ctrl = _pressed(VK_CONTROL)

            blocked = (
                vk in (VK_LWIN, VK_RWIN, VK_APPS)
                or (vk == VK_TAB and alt)
                or (vk == VK_ESCAPE and (alt or ctrl))
                or (vk == VK_F4 and alt)
            )
            if blocked:
                return 1   # проглатываем нажатие
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not self._hook:
            log.warning("Не удалось поставить хук клавиатуры (код %s)", ctypes.get_last_error())
            self._ready.set()
            return
        self._ready.set()

        # Низкоуровневому хуку нужен цикл сообщений в своём потоке.
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def start(self) -> bool:
        if self._thread is not None:
            return True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ParentsSeeHook")
        self._thread.start()
        self._ready.wait(timeout=3)
        return self._hook is not None

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=3)
        self._thread = None
        self._thread_id = None


class TaskbarHider:
    """Прячет панель задач на всех мониторах."""

    CLASSES = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")

    def __init__(self) -> None:
        self._hidden: list[int] = []

    def _handles(self) -> list[int]:
        found: list[int] = []
        for cls in self.CLASSES:
            hwnd = user32.FindWindowW(cls, None)
            while hwnd:
                found.append(hwnd)
                hwnd = user32.FindWindowExW(None, hwnd, cls, None)
        return found

    def hide(self) -> None:
        for hwnd in self._handles():
            user32.ShowWindow(hwnd, SW_HIDE)
            self._hidden.append(hwnd)

    def show(self) -> None:
        for hwnd in self._hidden or self._handles():
            user32.ShowWindow(hwnd, SW_SHOW)
        self._hidden.clear()


class TaskManagerPolicy:
    """Временно отключает диспетчер задач (политика текущего пользователя)."""

    def __init__(self) -> None:
        self._previous: int | None = None
        self._applied = False

    def disable(self) -> None:
        if self._applied:
            return
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, POLICY_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
            ) as key:
                try:
                    self._previous, _ = winreg.QueryValueEx(key, DISABLE_TASKMGR)
                except OSError:
                    self._previous = None
                winreg.SetValueEx(key, DISABLE_TASKMGR, 0, winreg.REG_DWORD, 1)
            self._applied = True
        except OSError as exc:
            log.warning("Не удалось отключить диспетчер задач: %s", exc)

    def restore(self) -> None:
        if not self._applied:
            return
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, POLICY_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                if self._previous is None:
                    winreg.DeleteValue(key, DISABLE_TASKMGR)
                else:
                    winreg.SetValueEx(
                        key, DISABLE_TASKMGR, 0, winreg.REG_DWORD, self._previous
                    )
        except OSError as exc:
            log.warning("Не удалось вернуть диспетчер задач: %s", exc)
        finally:
            self._applied = False
            self._previous = None


class DesktopBlocker:
    """Всё вместе. engage() при показе экрана блокировки, release() при снятии."""

    def __init__(self) -> None:
        self.keyboard = KeyboardBlocker()
        self.taskbar = TaskbarHider()
        self.taskmgr = TaskManagerPolicy()
        self._engaged = False
        atexit.register(self.release)

    @property
    def engaged(self) -> bool:
        return self._engaged

    def engage(self) -> None:
        if self._engaged:
            return
        self._engaged = True
        try:
            ENGAGED_FLAG.write_text("1", encoding="utf-8")
        except OSError:
            pass
        hooked = self.keyboard.start()
        self.taskbar.hide()
        self.taskmgr.disable()
        log.info("Жёсткая блокировка включена (хук клавиатуры: %s)", "да" if hooked else "нет")

    def release(self) -> None:
        if not self._engaged:
            return
        self._engaged = False
        try:
            self.keyboard.stop()
        finally:
            self.taskbar.show()
            self.taskmgr.restore()
            try:
                ENGAGED_FLAG.unlink(missing_ok=True)
            except OSError:
                pass
        log.info("Жёсткая блокировка снята")


def heal_after_crash() -> bool:
    """Возвращает рабочий стол, если прошлый агент был убит во время блокировки.

    Вызывается при старте агента и при открытии окна настроек.
    """
    if not ENGAGED_FLAG.exists():
        return False
    TaskbarHider().show()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, POLICY_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, DISABLE_TASKMGR)
    except OSError:
        pass
    try:
        ENGAGED_FLAG.unlink(missing_ok=True)
    except OSError:
        pass
    log.info("Рабочий стол восстановлен после аварийного завершения")
    return True
