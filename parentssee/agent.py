"""Фоновый агент: считает время, показывает предупреждения, блокирует экран,
закрывает запрещённые программы и сайты. Значок — в системном трее."""
from __future__ import annotations

import ctypes
import logging
import os
import time
import tkinter as tk
from datetime import datetime, timedelta

from . import cad
from . import config as config_mod
from . import enforcer
from . import rules
from . import state as state_mod
from . import winapi
from .blocker import DesktopBlocker, heal_after_crash
from .lockscreen import LockScreen, WarningToast
from .paths import LOG_FILE, PID_FILE
from .tray import Tray

TICK_SECONDS = 3
PROGRAM_CHECK_SECONDS = 3
ERROR_ALREADY_EXISTS = 183

log = logging.getLogger("parentssee")


def _setup_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s")
    )
    log.setLevel(logging.INFO)
    if not log.handlers:
        log.addHandler(handler)


def _write_pid() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _clear_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _acquire_single_instance() -> int | None:
    """Не даём запустить два агента разом. None, если один уже работает."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "ParentsSeeAgentMutex")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


class Agent:
    def __init__(self) -> None:
        self.cfg = config_mod.load()
        self.state = state_mod.load(self.cfg)
        self.lock: LockScreen | None = None
        self.blocker = DesktopBlocker()
        self.fired_warnings: set[int] = set()
        self._last_monotonic = time.monotonic()
        self._sites_signature: tuple | None = None
        self._cad_applied = False
        self._tamper_strikes = 0

        self.root = tk.Tk()
        self.root.withdraw()

        self.tray = Tray(
            on_open_settings=lambda: self.root.after(0, self._open_settings_entry),
            on_lock_now=lambda: self.root.after(0, self._lock_now_30),
            on_stop=lambda: self.root.after(0, self._stop_requested),
            status_provider=self._tray_status,
        )

    def _open_settings_entry(self) -> None:
        """Открытие настроек: если идёт блокировка — прячем её на это время."""
        if self.lock is not None:
            self.lock._open_settings()   # сам спрячет/вернёт экран блокировки
        else:
            self._open_settings()

    # ---------- учёт времени ----------

    def _elapsed(self) -> float:
        """Секунды с прошлого тика; скачок (сон/гибернация) не засчитываем."""
        now = time.monotonic()
        delta = now - self._last_monotonic
        self._last_monotonic = now
        if delta > TICK_SECONDS * 4:
            return 0.0
        return max(0.0, delta)

    def _user_is_active(self) -> bool:
        if winapi.session_locked():
            return False
        timeout = float(self.cfg.get("idle_timeout_seconds", 120))
        return winapi.idle_seconds() < timeout

    # ---------- предупреждения ----------

    def _maybe_warn(self, seconds_left: float | None) -> None:
        if seconds_left is None:
            return
        thresholds = sorted(
            int(m) for m in self.cfg.get("warn_minutes", []) if int(m) > 0
        )
        if not thresholds:
            return
        if seconds_left > thresholds[-1] * 60 + 60:
            self.fired_warnings.clear()

        minutes_left = seconds_left / 60.0
        for threshold in thresholds:
            if threshold in self.fired_warnings:
                continue
            if minutes_left <= threshold:
                self.fired_warnings.add(threshold)
                word = "минута" if threshold == 1 else "минут"
                WarningToast(
                    self.root,
                    f"До блокировки {threshold} {word}.\nПора сохранить работу.",
                )
                self.tray.notify(f"До блокировки {threshold} {word}.")
                log.info("Предупреждение: осталось %s мин", threshold)
                break

    # ---------- блокировка программ и сайтов ----------

    def _enforce_programs(self) -> None:
        block = self.cfg.get("block_programs", {})
        if block.get("enabled") and block.get("list"):
            enforcer.enforce_programs(list(block.get("list", [])))

    def _sync_sites(self) -> None:
        """Обновляет hosts, только когда список сайтов реально изменился."""
        block = self.cfg.get("block_sites", {})
        enabled = bool(block.get("enabled"))
        items = tuple(block.get("list", [])) if enabled else ()
        signature = (enabled, items)
        if signature == self._sites_signature:
            return

        # Когда блокировка выключена и в hosts ничего нашего нет — не трогаем
        # файл вовсе (иначе без прав администратора будет лишнее предупреждение).
        if not items and not enforcer.sites_currently_blocked():
            self._sites_signature = signature
            return

        self._sites_signature = signature
        ok, msg = enforcer.apply_sites(list(items))
        if not ok:
            log.warning("Сайты: %s", msg)

    def _sync_cad(self) -> None:
        """Усиление Ctrl+Alt+Del при наличии прав администратора."""
        want = bool(self.cfg.get("harden_cad"))
        if want == self._cad_applied:
            return
        ok, _ = cad.harden() if want else cad.unharden()
        if ok:
            self._cad_applied = want

    # ---------- экран блокировки ----------

    def _check_password(self, password: str) -> bool:
        ok = config_mod.check_password(self.cfg, password)
        log.info("Ввод пароля родителя: %s", "успех" if ok else "неверный")
        return ok

    def _grant(self, minutes: int) -> None:
        until = datetime.now() + timedelta(minutes=minutes)
        self.state["override_until"] = until.isoformat()
        self.state["lock_until"] = None
        self.state["tampered"] = False
        state_mod.save(self.cfg, self.state)
        self.fired_warnings.clear()
        log.info("Родитель разрешил работу до %s", until.strftime("%H:%M"))
        self._close_lock()

    def _open_settings(self) -> None:
        from .settings_gui import open_settings_window

        try:
            open_settings_window(
                self.root, already_authenticated=self.lock is not None
            )
        except Exception:
            log.exception("Ошибка при открытии настроек")
        finally:
            self.cfg = config_mod.load()

    def _lock_now_30(self) -> None:
        until = datetime.now() + timedelta(minutes=30)
        self.state["lock_until"] = until.isoformat()
        self.state["override_until"] = None
        state_mod.save(self.cfg, self.state)
        log.info("Ручная блокировка из трея до %s", until.strftime("%H:%M"))

    def _stop_requested(self) -> None:
        from tkinter import simpledialog, messagebox

        pwd = simpledialog.askstring(
            "ParentsSee", "Пароль родителя, чтобы остановить защиту:", show="*"
        )
        if pwd is None:
            return
        if not config_mod.check_password(self.cfg, pwd):
            messagebox.showerror("ParentsSee", "Неверный пароль.")
            return
        log.info("Остановка защиты по паролю из трея")
        self._shutdown()

    def _open_lock(self, decision: rules.Decision) -> None:
        if self.lock is not None:
            return
        log.info("Блокировка: %s (%s)", decision.reason, decision.title)
        self.blocker.engage()
        self.tray.set_active(True)
        self.lock = LockScreen(
            self.root,
            on_password=self._check_password,
            on_grant=self._grant,
            on_open_settings=self._open_settings,
        )
        self.lock.update_text(decision.title, decision.detail, decision.unlock_at)

    def _close_lock(self) -> None:
        if self.lock is None:
            return
        log.info("Блокировка снята")
        self.lock.close()
        self.lock = None
        self.blocker.release()
        self.tray.set_active(False)

    # ---------- статус для трея ----------

    def _tray_status(self) -> str:
        used = int(self.state.get("used_seconds", 0.0))
        text = f"Сегодня: {used // 3600} ч {used % 3600 // 60} мин"
        if self.lock is not None:
            text += " · заблокировано"
        return text

    # ---------- основной цикл ----------

    def tick(self) -> None:
        try:
            self._tick_once()
        except Exception:
            log.exception("Ошибка в цикле агента")
        finally:
            if self._running:
                self.root.after(TICK_SECONDS * 1000, self.tick)

    def _tick_once(self) -> None:
        elapsed = self._elapsed()
        now = datetime.now()

        # Перечитываем настройки с диска — родитель мог их изменить.
        self.cfg = config_mod.load()

        used_memory = float(self.state.get("used_seconds", 0.0))

        # Внешние поля (ручная блокировка, разрешение) берём с диска. Смена
        # даты (новый день) обнуляет счётчик внутри state.load().
        disk = state_mod.load(self.cfg, now.date())
        if disk.get("date") != self.state.get("date"):
            self.fired_warnings.clear()
            used_memory = float(disk.get("used_seconds", 0.0))
        self.state = disk
        self.state["used_seconds"] = used_memory

        # Одноразовые команды из настроек/трея (без гонок за файл состояния).
        self._apply_command(state_mod.pop_command())

        # Время идёт, только пока за компьютером реально работают.
        if self.lock is None and self._user_is_active():
            self.state["used_seconds"] = (
                float(self.state.get("used_seconds", 0.0)) + elapsed
            )

        # Подделку подтверждаем на 2 тиках подряд — одиночный сбой чтения
        # (гонка с записью) не должен вызывать блокировку «Файл учёта изменён».
        if self.state.get("tampered"):
            self._tamper_strikes += 1
            if self._tamper_strikes < 2:
                self.state["tampered"] = False
        else:
            self._tamper_strikes = 0

        # Блокировка программ и синхронизация сайтов/CAD.
        self._enforce_programs()
        self._sync_sites()
        self._sync_cad()

        decision = rules.evaluate(self.cfg, self.state, now)

        if decision.blocked:
            self._open_lock(decision)
            if self.lock is not None:
                self.lock.update_text(
                    decision.title, decision.detail, decision.unlock_at
                )
        else:
            self._close_lock()
            self._maybe_warn(decision.seconds_left)

        self.tray.set_title(self._tray_title(decision))
        state_mod.save(self.cfg, self.state)

    def _tray_title(self, decision: rules.Decision) -> str:
        """Текст подсказки при наведении на значок в трее."""
        if decision.blocked:
            if decision.unlock_at is not None:
                return f"ParentsSee · заблокировано до {decision.unlock_at.strftime('%H:%M')}"
            return "ParentsSee · компьютер заблокирован"
        if decision.seconds_left is not None:
            total = max(0, int(decision.seconds_left))
            hours, minutes = total // 3600, total % 3600 // 60
            if hours:
                left = f"{hours} ч {minutes:02d} мин"
            elif minutes:
                left = f"{minutes} мин"
            else:
                left = "меньше минуты"
            return f"ParentsSee · осталось {left}"
        return "ParentsSee · защита включена"

    def _apply_command(self, command: dict | None) -> None:
        if not command:
            return
        if command.get("reset"):
            self.state["used_seconds"] = 0.0
            self.state["tampered"] = False
            log.info("Команда: счётчик обнулён")
        if "lock_until" in command:
            self.state["lock_until"] = command["lock_until"]
            self.state["override_until"] = None
            log.info("Команда: ручная блокировка до %s", command["lock_until"])
        if "grant_until" in command:
            self.state["override_until"] = command["grant_until"]
            self.state["lock_until"] = None
            self.state["tampered"] = False
            self.fired_warnings.clear()
            log.info("Команда: разрешение до %s", command["grant_until"])
        if command.get("unlock"):
            self.state["lock_until"] = None
            log.info("Команда: ручная блокировка снята")
        if command.get("cancel_grant"):
            self.state["override_until"] = None
            self.fired_warnings.clear()
            log.info("Команда: разрешённое время отменено")
        if command.get("open_settings"):
            self.root.after(0, self._open_settings_entry)
        if command.get("quit"):
            log.info("Команда: корректная остановка защиты")
            self._shutdown()

    def _shutdown(self) -> None:
        self._running = False
        try:
            self.root.quit()
        except tk.TclError:
            pass

    def run(self) -> None:
        self._running = True
        log.info(
            "Агент запущен. Ночь: %s, лимит: %s, программы: %s, сайты: %s",
            self.cfg.get("curfew"),
            self.cfg.get("daily_limit"),
            self.cfg.get("block_programs"),
            self.cfg.get("block_sites"),
        )
        _write_pid()
        state_mod.pop_command()   # выбрасываем возможную залипшую команду (напр. quit)
        self.tray.start()
        self.tray.notify("Защита включена. Значок — в системном трее.")
        self.root.after(500, self.tick)
        try:
            self.root.mainloop()
        finally:
            self.blocker.release()
            if self._sites_signature and self._sites_signature[0]:
                enforcer.clear_sites()   # снимаем блок сайтов из hosts
            state_mod.save(self.cfg, self.state)
            self.tray.stop()
            _clear_pid()
            log.info("Агент остановлен")


def main() -> int:
    _setup_logging()
    winapi.enable_dpi_awareness()
    heal_after_crash()

    if _acquire_single_instance() is None:
        log.info("Агент уже запущен, выходим")
        return 0

    cfg = config_mod.load()
    if not config_mod.is_configured(cfg):
        # Без пароля родителя блокировать нельзя: снять её будет нечем.
        log.warning("Пароль не задан — агент не запускается")
        import tkinter.messagebox as mb

        root = tk.Tk()
        root.withdraw()
        mb.showwarning(
            "ParentsSee",
            "Сначала откройте настройки и задайте пароль родителя.\n"
            "Без пароля защита не включается.",
        )
        root.destroy()
        return 1

    Agent().run()
    return 0
