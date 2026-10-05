"""Проверка и установка зависимостей (Python-библиотек) для ParentsSee.

Сам Python здесь уже запущен (иначе этот код бы не выполнялся), поэтому тут
проверяются только pip-библиотеки. Установку самого Python берёт на себя
загрузочный bat-файл «Установить ParentsSee.bat», который работает и без Python.
"""
from __future__ import annotations

import importlib
import subprocess
import sys

NO_WINDOW = 0x08000000

# импортируемое имя -> имя пакета в pip
REQUIRED = {
    "pystray": "pystray",
    "PIL": "Pillow",
}


def missing() -> list[str]:
    """Список отсутствующих pip-пакетов (по именам для установки)."""
    if getattr(sys, "frozen", False):
        return []   # в собранном .exe библиотеки уже внутри
    result: list[str] = []
    for module, package in REQUIRED.items():
        try:
            importlib.import_module(module)
        except ImportError:
            result.append(package)
    return result


def install(packages: list[str]) -> tuple[bool, str]:
    """Ставит пакеты через pip текущего интерпретатора."""
    if not packages:
        return True, "Всё уже установлено."
    cmd = [sys.executable, "-m", "pip", "install", "--user", *packages]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=NO_WINDOW, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Не удалось запустить pip: {exc}"

    if proc.returncode != 0:
        # Повтор без --user (в некоторых сборках Python он запрещён).
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", *packages],
                capture_output=True, text=True,
                creationflags=NO_WINDOW, timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"Не удалось запустить pip: {exc}"

    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip()[-1500:]


def ensure(parent=None) -> bool:
    """Проверяет зависимости и, если чего-то нет, предлагает установить.

    Возвращает True, если после проверки все зависимости на месте.
    parent — окно Tk для диалогов (может быть None).
    """
    need = missing()
    if not need:
        return True

    from tkinter import messagebox

    ask = messagebox.askyesno(
        "ParentsSee",
        "Для значка в трее нужны библиотеки:\n  "
        + ", ".join(need)
        + "\n\nУстановить их сейчас? (нужен интернет)",
        parent=parent,
    )
    if not ask:
        return False

    ok, log = install(need)
    still = missing()
    if ok and not still:
        messagebox.showinfo("ParentsSee", "Библиотеки установлены.", parent=parent)
        return True

    messagebox.showwarning(
        "ParentsSee",
        "Не удалось установить автоматически.\n"
        "Программа будет работать, но без значка в трее.\n\n"
        "Можно поставить вручную командой:\n"
        f"  {sys.executable} -m pip install " + " ".join(need),
        parent=parent,
    )
    return False
