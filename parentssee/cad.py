"""Усиление экрана безопасности Windows (Ctrl+Alt+Del).

Саму комбинацию Ctrl+Alt+Del (Secure Attention Sequence) не может перехватить
ни одна обычная программа — её обрабатывает ядро Windows через Winlogon, и в
обход этого нужен драйвер/credential provider уровня системы. Это защита
Windows от вредоносных программ, которые притворяются экраном входа.

Что реально можно сделать без драйвера — убрать со ЭТОГО экрана всё, чем мог бы
воспользоваться ребёнок: диспетчер задач, «Сменить пользователя», «Выйти»,
«Заблокировать», «Сменить пароль». Тогда Ctrl+Alt+Del ведёт на голый экран,
с которого можно только вернуться назад. Все ключи ниже — машинные (HKLM) и
требуют прав администратора.
"""
from __future__ import annotations

import logging
import winreg

log = logging.getLogger("parentssee")

_SYSTEM = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
_EXPLORER = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer"

# (подключ, имя, значение-при-усилении)
_POLICIES = [
    (_SYSTEM, "DisableTaskMgr", 1),        # диспетчер задач
    (_SYSTEM, "DisableLockWorkstation", 1),# кнопка «Заблокировать»
    (_SYSTEM, "DisableChangePassword", 1), # «Сменить пароль»
    (_SYSTEM, "HideFastUserSwitching", 1), # «Сменить пользователя»
    (_EXPLORER, "NoLogoff", 1),            # «Выйти»
]


def _set(subkey: str, name: str, value: int | None) -> None:
    if value is None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, name)
        except OSError:
            pass
        return
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def harden() -> tuple[bool, str]:
    """Прячет опасные пункты с экрана Ctrl+Alt+Del. Нужен администратор."""
    try:
        for subkey, name, value in _POLICIES:
            _set(subkey, name, value)
    except PermissionError:
        return False, "Нужны права администратора."
    except OSError as exc:
        return False, f"Ошибка: {exc}"
    log.info("Экран Ctrl+Alt+Del усилен")
    return True, "Экран Ctrl+Alt+Del усилен."


def unharden() -> tuple[bool, str]:
    """Возвращает экран Ctrl+Alt+Del в обычное состояние."""
    try:
        for subkey, name, _ in _POLICIES:
            _set(subkey, name, None)
    except PermissionError:
        return False, "Нужны права администратора."
    except OSError as exc:
        return False, f"Ошибка: {exc}"
    log.info("Экран Ctrl+Alt+Del возвращён к обычному виду")
    return True, "Настройки Ctrl+Alt+Del сброшены."


def is_hardened() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _SYSTEM) as key:
            value, _ = winreg.QueryValueEx(key, "DisableTaskMgr")
            return bool(value)
    except OSError:
        return False


def harden_elevated() -> bool:
    from .autostart import is_admin, run_elevated

    return harden()[0] if is_admin() else run_elevated("harden")


def unharden_elevated() -> bool:
    from .autostart import is_admin, run_elevated

    return unharden()[0] if is_admin() else run_elevated("unharden")
