"""Автозапуск агента.

Два независимых способа:
  * ветка реестра Run   — простой автозапуск при входе, прав администратора не нужно;
  * Планировщик задач   — запуск вместе с Windows с наивысшими правами (нужен
    администратор). В этом режиме агент может отключать диспетчер задач и
    перехватывать клавиши даже поверх окон с повышенными правами.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ParentsSee"
TASK_NAME = "ParentsSee"

# Прячем консольное окно у вызовов schtasks.
_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def is_frozen() -> bool:
    """True, если программа собрана в один .exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def _python_exe() -> Path:
    """pythonw.exe, чтобы у фонового агента не было чёрного окна консоли."""
    current = Path(sys.executable)
    windowless = current.with_name("pythonw.exe")
    return windowless if windowless.exists() else current


def app_argv(action: str) -> list[str]:
    """Аргументы для запуска приложения с командой action.

    В собранном .exe это [ParentsSee.exe, action]; в виде скрипта —
    [pythonw.exe, ParentsSee.pyw, action]. Благодаря этому автозапуск и
    Планировщик работают и после переноса на другой ПК без Python.
    """
    if is_frozen():
        return [sys.executable, action]
    from .paths import LAUNCHER

    return [str(_python_exe()), str(LAUNCHER), action]


def _work_dir() -> str:
    from .paths import LAUNCHER

    return str(Path(sys.executable).parent if is_frozen() else LAUNCHER.parent)


def spawn_agent() -> None:
    """Запускает фонового агента полностью отдельным процессом.

    DETACHED_PROCESS + отвязка от группы/задания гарантируют, что агент
    продолжит работать после закрытия окна, из которого его запустили.
    """
    args = app_argv("agent")
    base = _NO_WINDOW | _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            args, cwd=_work_dir(), close_fds=True,
            creationflags=base | _CREATE_BREAKAWAY_FROM_JOB,
        )
    except OSError:
        # Задание может запрещать отвязку — запускаем без неё.
        subprocess.Popen(
            args, cwd=_work_dir(), close_fds=True, creationflags=base
        )


def command() -> str:
    return " ".join(f'"{part}"' for part in app_argv("agent"))


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


# ---------- способ 1: ветка реестра Run ----------

def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def enable() -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())


def disable() -> None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except OSError:
        pass


# ---------- способ 2: Планировщик задач ----------

def _oem_decode(data: bytes | None) -> str:
    """schtasks печатает в OEM-кодировке консоли, а не в кодировке Python."""
    if not data:
        return ""
    try:
        codepage = ctypes.windll.kernel32.GetOEMCP()
        return data.decode(f"cp{codepage}", errors="replace").strip()
    except (OSError, LookupError):
        return data.decode("utf-8", errors="replace").strip()


def task_exists() -> bool:
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, creationflags=_NO_WINDOW,
        )
        return result.returncode == 0
    except OSError:
        return False


def _create_task_args(highest: bool) -> str:
    """Строка параметров для schtasks.exe."""
    # Внутри /TR "..." каждый путь берём в экранированные кавычки.
    action = " ".join(f'\\"{part}\\"' for part in app_argv("agent"))
    args = f'/Create /TN "{TASK_NAME}" /TR "{action}" /SC ONLOGON /F'
    if highest:
        args += " /RL HIGHEST"
    return args


def install_task(highest: bool = True) -> tuple[bool, str]:
    """Создаёт задачу напрямую (нужны уже полученные права администратора)."""
    args = _create_task_args(highest)
    result = subprocess.run(
        f"schtasks {args}", capture_output=True,
        shell=True, creationflags=_NO_WINDOW,
    )
    ok = result.returncode == 0
    return ok, _oem_decode(result.stdout) or _oem_decode(result.stderr)


def remove_task() -> tuple[bool, str]:
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, creationflags=_NO_WINDOW,
    )
    ok = result.returncode == 0
    return ok, _oem_decode(result.stdout) or _oem_decode(result.stderr)


def run_elevated(action: str) -> bool:
    """Перезапускает приложение с командой action от имени администратора (UAC).

    Работает и как .exe, и как скрипт: разбором кавычек занимается уже сам
    поднятый процесс, а не ShellExecute.
    """
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
    ]
    argv = app_argv(action)
    exe, rest = argv[0], argv[1:]
    params = " ".join(f'"{part}"' for part in rest)
    try:
        rc = shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return int(rc) > 32   # >32 = UAC показан и процесс запущен
    except OSError:
        return False


# Совместимость со старым именем.
_run_python_elevated = run_elevated


def install_task_elevated() -> bool:
    """Показывает окно UAC и создаёт задачу с наивысшими правами."""
    if is_admin():
        return install_task(highest=True)[0]
    return _run_python_elevated("install-task")


def remove_task_elevated() -> bool:
    if is_admin():
        return remove_task()[0]
    return _run_python_elevated("remove-task")
