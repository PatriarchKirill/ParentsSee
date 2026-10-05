"""Точка входа: python -m parentssee [open|settings|agent|install|uninstall|status]"""
from __future__ import annotations

import sys


def _ensure_agent_running() -> None:
    """Запускает фонового агента (значок в трее), если он ещё не работает."""
    from . import autostart, config as config_mod, winapi

    if winapi.mutex_exists("ParentsSeeAgentMutex"):
        return
    if not config_mod.is_configured(config_mod.load()):
        return
    autostart.spawn_agent()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0].lower() if argv else "open"

    if command == "agent":
        from .agent import main as run_agent
        return run_agent()

    if command == "open":
        # Двойной клик: включаем защиту (значок в трее) и открываем окно.
        # Закрытие окна оставляет защиту работать в трее.
        from . import config as config_mod
        from .settings_gui import main as run_settings

        was_configured = config_mod.is_configured(config_mod.load())
        _ensure_agent_running()
        result = run_settings()
        # Только первый запуск: пароль задан прямо сейчас — включаем защиту.
        # Если родитель сам остановил защиту, повторно её не поднимаем.
        if not was_configured:
            _ensure_agent_running()
        return result

    if command == "settings":
        from .settings_gui import main as run_settings
        return run_settings()

    if command == "install":
        from . import autostart
        autostart.enable()
        print("Автозапуск включён:", autostart.command())
        return 0

    if command == "uninstall":
        from . import autostart
        autostart.disable()
        print("Автозапуск выключен.")
        return 0

    if command in ("install-task", "remove-task"):
        from . import autostart
        import tkinter as tk
        import tkinter.messagebox as mb

        if command == "install-task":
            ok, msg = autostart.install_task(highest=True)
            title = "Запуск с Windows включён" if ok else "Не удалось включить"
        else:
            ok, msg = autostart.remove_task()
            title = "Запуск с Windows выключен" if ok else "Не удалось выключить"

        root = tk.Tk()
        root.withdraw()
        (mb.showinfo if ok else mb.showerror)("ParentsSee", f"{title}.\n\n{msg}")
        root.destroy()
        return 0 if ok else 1

    if command == "harden":
        from . import cad
        ok, msg = cad.harden()
        print(msg)
        return 0 if ok else 1

    if command == "unharden":
        from . import cad
        ok, msg = cad.unharden()
        print(msg)
        return 0 if ok else 1

    if command == "status":
        from datetime import datetime
        from . import config as config_mod, rules, state as state_mod, winapi
        from .paths import DATA_DIR

        cfg = config_mod.load()
        st = state_mod.load(cfg)
        decision = rules.evaluate(cfg, st, datetime.now())
        used = int(decision.used_seconds)
        print(f"Данные:      {DATA_DIR}")
        print(f"Пароль:      {'задан' if config_mod.is_configured(cfg) else 'НЕ задан'}")
        print(f"Ночь:        {cfg['curfew']}")
        print(f"Лимит:       {cfg['daily_limit']}")
        print(f"Сегодня:     {used // 3600} ч {used % 3600 // 60} мин")
        print(f"Блокировка:  {decision.blocked} ({decision.reason or '-'})")
        print(f"Агент:       {'работает' if winapi.mutex_exists('ParentsSeeAgentMutex') else 'остановлен'}")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
