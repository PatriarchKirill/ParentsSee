"""Окно родителя: расписание, автозапуск, управление защитой."""
from __future__ import annotations

import subprocess
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, simpledialog, ttk

from . import autostart
from . import cad
from . import deps
from . import icon
from . import theme
from .blocker import heal_after_crash
from . import config as config_mod
from . import rules
from . import state as state_mod
from . import winapi
from .paths import PID_FILE

AGENT_MUTEX = "ParentsSeeAgentMutex"
NO_WINDOW = 0x08000000

LOCK_CHOICES = {
    "15 минут": 15,
    "30 минут": 30,
    "1 час": 60,
    "2 часа": 120,
    "До конца дня": None,
}


# ---------- пароль ----------

def _ask_password(parent: tk.Misc, cfg: dict) -> bool:
    """Три попытки ввести пароль родителя."""
    for attempt in range(3):
        prompt = "Пароль родителя:" if attempt == 0 else "Неверно. Попробуйте ещё раз:"
        value = simpledialog.askstring("ParentsSee", prompt, show="*", parent=parent)
        if value is None:
            return False
        if config_mod.check_password(cfg, value):
            return True
    messagebox.showerror("ParentsSee", "Слишком много неудачных попыток.", parent=parent)
    return False


def _setup_password(parent: tk.Misc, cfg: dict) -> bool:
    """Первый запуск или смена пароля."""
    while True:
        first = simpledialog.askstring(
            "ParentsSee", "Новый пароль (минимум 4 символа):", show="*", parent=parent
        )
        if first is None:
            return False
        if len(first) < 4:
            messagebox.showwarning("ParentsSee", "Слишком короткий пароль.", parent=parent)
            continue
        second = simpledialog.askstring(
            "ParentsSee", "Повторите пароль:", show="*", parent=parent
        )
        if second is None:
            return False
        if first != second:
            messagebox.showwarning("ParentsSee", "Пароли не совпадают.", parent=parent)
            continue
        config_mod.set_password(cfg, first)
        config_mod.save(cfg)
        return True


# ---------- управление агентом ----------

def agent_running() -> bool:
    return winapi.mutex_exists(AGENT_MUTEX)


def start_agent() -> None:
    autostart.spawn_agent()


def stop_agent() -> bool:
    """Просит агента корректно завершиться (снимет блок сайтов, вернёт стол).

    Если за отведённое время агент не ответил — снимаем процесс принудительно.
    """
    import time

    state_mod.push_command({"quit": True})
    for _ in range(20):          # до ~5 секунд ждём чистого выхода
        time.sleep(0.25)
        if not agent_running():
            return True

    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return not agent_running()
    subprocess.run(
        ["taskkill", "/F", "/PID", str(pid)],
        capture_output=True, creationflags=NO_WINDOW,
    )
    return True


class SettingsWindow:
    def __init__(self, master: tk.Misc, cfg: dict) -> None:
        self.cfg = cfg
        self.win = tk.Toplevel(master)
        self.win.title("ParentsSee — родительский контроль")
        self.win.resizable(False, False)
        theme.apply(self.win)
        self.win.configure(bg=theme.BG)
        icon.set_window_icon(self.win)

        curfew = cfg.get("curfew", {})
        limit = cfg.get("daily_limit", {})
        start = config_mod.parse_hhmm(curfew.get("start", "21:00"))
        end = config_mod.parse_hhmm(curfew.get("end", "07:00"))
        total = int(limit.get("minutes", 180))

        self.v_curfew = tk.BooleanVar(value=bool(curfew.get("enabled", True)))
        self.v_start_h = tk.StringVar(value=f"{start.hour:02d}")
        self.v_start_m = tk.StringVar(value=f"{start.minute:02d}")
        self.v_end_h = tk.StringVar(value=f"{end.hour:02d}")
        self.v_end_m = tk.StringVar(value=f"{end.minute:02d}")
        self.v_limit = tk.BooleanVar(value=bool(limit.get("enabled", True)))
        self.v_limit_h = tk.StringVar(value=str(total // 60))
        self.v_limit_m = tk.StringVar(value=str(total % 60))
        self.v_idle = tk.StringVar(value=str(int(cfg.get("idle_timeout_seconds", 120))))
        self.v_run_key = tk.BooleanVar(value=autostart.is_enabled())
        self.v_lock_for = tk.StringVar(value="30 минут")

        programs = cfg.get("block_programs", {})
        sites = cfg.get("block_sites", {})
        self.v_block_prog = tk.BooleanVar(value=bool(programs.get("enabled")))
        self.v_block_sites = tk.BooleanVar(value=bool(sites.get("enabled")))
        self._prog_initial = list(programs.get("list", []))
        self._sites_initial = list(sites.get("list", []))
        self.v_cad = tk.BooleanVar(value=bool(cfg.get("harden_cad")))

        self._build()
        self._fit_to_screen()
        self._refresh()

    def _fit_to_screen(self) -> None:
        """Фиксированный размер окна, по центру экрана. Содержимое вкладок, если
        не влезло, прокручивается — поэтому окно можно не растягивать."""
        self.win.update_idletasks()
        # Фиксированная ширина, чтобы широкие ряды кнопок не обрезались.
        width = max(self.win.winfo_reqwidth(), 700)
        height = self.win.winfo_reqheight()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        width = min(width, screen_w - 40)
        height = min(height, screen_h - 60)   # страховка на очень низких экранах
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.win.resizable(False, False)   # фиксированный размер

    # ---------- построение ----------

    def _build(self) -> None:
        outer = ttk.Frame(self.win, padding=16)
        outer.pack(fill="both", expand=True)

        # --- шапка с иконкой ---
        header = ttk.Frame(outer)
        header.pack(side="top", fill="x", pady=(0, 14))
        try:
            from PIL import ImageTk
            self._logo = ImageTk.PhotoImage(icon.shield_image(40))
            tk.Label(header, image=self._logo, bg=theme.BG).pack(side="left")
        except Exception:
            pass
        titles = ttk.Frame(header)
        titles.pack(side="left", padx=12)
        ttk.Label(titles, text="ParentsSee", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            titles, text="Родительский контроль", style="Sub.TLabel"
        ).pack(anchor="w")

        # Подпись — в самый низ (пакуем первой среди нижних).
        from . import __version__, __author__
        ttk.Label(
            outer, text=f"ParentsSee {__version__}  ·  Разработчик: {__author__}",
            style="Sub.TLabel",
        ).pack(side="bottom", anchor="e", pady=(8, 0))

        # Панель кнопок пакуем снизу — так она видна всегда, даже если окно
        # ниже содержимого (при большом масштабе экрана).
        buttons = ttk.Frame(outer)
        buttons.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(
            buttons, text="Сохранить", style="Accent.TButton", command=self._save
        ).pack(side="left")
        ttk.Button(
            buttons, text="Сменить пароль", command=self._change_password
        ).pack(side="left", padx=8)
        ttk.Button(buttons, text="Закрыть", command=self.win.destroy).pack(side="right")

        self.status_box = ttk.LabelFrame(outer, text=" Состояние ", padding=12)
        self.status_box.pack(side="bottom", fill="x", pady=(14, 0))
        self.status_label = ttk.Label(self.status_box, text="", justify="left")
        self.status_label.pack(anchor="w")

        # Notebook занимает оставшееся место и сжимается, если окно короткое.
        notebook = ttk.Notebook(outer)
        notebook.pack(side="top", fill="both", expand=True)
        notebook.add(self._tab_schedule(notebook), text="  Расписание  ")
        notebook.add(self._tab_blocking(notebook), text="  Программы и сайты  ")
        notebook.add(self._tab_protection(notebook), text="  Защита и запуск  ")

    def _scrollable_tab(self, parent: ttk.Notebook) -> tuple[ttk.Frame, ttk.Frame]:
        """Возвращает (страницу для notebook, внутреннюю прокручиваемую рамку).

        Содержимое, которое не влезло по высоте, можно прокрутить колесом мыши
        или полосой справа — вкладка больше не обрезается на низких экранах.
        """
        page = ttk.Frame(parent)
        # Фиксированная высота вьюпорта -> окно всегда одного размера. На очень
        # низких экранах немного уменьшаем. Полоса прокрутки — страховка.
        vh = min(430, self.win.winfo_screenheight() - 380)
        canvas = tk.Canvas(page, background=theme.BG, highlightthickness=0,
                           height=vh)
        vsb = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas, padding=14)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _on_body(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        body.bind("<Configure>", _on_body)
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(body_id, width=e.width))

        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return page, body

    def _tab_header(self, tab: ttk.Frame) -> None:
        """Кнопка «Сохранить» прямо на вкладке — у всех настроек одна общая."""
        header = ttk.Frame(tab)
        header.pack(fill="x", pady=(0, 10))
        ttk.Button(
            header, text="Сохранить настройки", style="Accent.TButton",
            command=self._save,
        ).pack(side="right")

    def _tab_schedule(self, parent: ttk.Notebook) -> ttk.Frame:
        page, tab = self._scrollable_tab(parent)
        self._tab_header(tab)

        night = ttk.LabelFrame(tab, text=" Ночной режим ", padding=12)
        night.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(
            night, text="Блокировать компьютер ночью", variable=self.v_curfew,
            command=self._toggle_states,
        ).grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 10))
        ttk.Label(night, text="с").grid(row=1, column=0, padx=(0, 6))
        self.sp_start_h = self._spin(night, 0, 23, self.v_start_h, 1, 1)
        ttk.Label(night, text=":").grid(row=1, column=2)
        self.sp_start_m = self._spin(night, 0, 59, self.v_start_m, 1, 3)
        ttk.Label(night, text="до").grid(row=1, column=4, padx=(16, 6))
        self.sp_end_h = self._spin(night, 0, 23, self.v_end_h, 1, 5)
        ttk.Label(night, text=":").grid(row=1, column=6)
        self.sp_end_m = self._spin(night, 0, 59, self.v_end_m, 1, 7)

        day = ttk.LabelFrame(tab, text=" Лимит времени за день ", padding=12)
        day.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(
            day, text="Ограничить время за компьютером", variable=self.v_limit,
            command=self._toggle_states,
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 10))
        ttk.Label(day, text="Не больше").grid(row=1, column=0, padx=(0, 6))
        self.sp_limit_h = self._spin(day, 0, 23, self.v_limit_h, 1, 1)
        ttk.Label(day, text="ч").grid(row=1, column=2, padx=(4, 12))
        self.sp_limit_m = self._spin(day, 0, 59, self.v_limit_m, 1, 3)
        ttk.Label(day, text="мин в сутки").grid(row=1, column=4, padx=(4, 0))
        ttk.Label(
            day, text="Счётчик обнуляется в полночь. Время не идёт, пока\n"
                      "за компьютером не работают — бездействие через (сек):",
            foreground="#5a5a5a",
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(10, 4))
        ttk.Spinbox(
            day, from_=30, to=1800, increment=30, width=6, textvariable=self.v_idle
        ).grid(row=3, column=0, sticky="w")

        ttk.Button(
            tab, text="Обнулить время за сегодня", command=self._reset_counter
        ).pack(anchor="w")
        return page

    def _list_editor(self, parent, title, toggle_var, toggle_text, items, hint):
        box = ttk.LabelFrame(parent, text=title, padding=10)
        box.pack(fill="both", expand=True, pady=(0, 10))
        ttk.Checkbutton(box, text=toggle_text, variable=toggle_var).pack(anchor="w")
        ttk.Label(box, text=hint, foreground="#5a5a5a").pack(anchor="w", pady=(2, 6))

        row = ttk.Frame(box)
        row.pack(fill="both", expand=True)
        listbox = tk.Listbox(row, height=4, activestyle="none")
        listbox.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(row, orient="vertical", command=listbox.yview)
        scroll.pack(side="left", fill="y")
        listbox.configure(yscrollcommand=scroll.set)
        for value in items:
            listbox.insert("end", value)

        entry_row = ttk.Frame(box)
        entry_row.pack(fill="x", pady=(6, 0))
        entry = ttk.Entry(entry_row)
        entry.pack(side="left", fill="x", expand=True)

        def add(_e=None):
            value = entry.get().strip()
            if value and value not in listbox.get(0, "end"):
                listbox.insert("end", value)
            entry.delete(0, "end")

        def remove():
            for index in reversed(listbox.curselection()):
                listbox.delete(index)

        entry.bind("<Return>", add)
        ttk.Button(entry_row, text="Добавить", command=add).pack(side="left", padx=(8, 0))
        ttk.Button(entry_row, text="Убрать", command=remove).pack(side="left", padx=(8, 0))
        return listbox

    def _tab_blocking(self, parent: ttk.Notebook) -> ttk.Frame:
        page, tab = self._scrollable_tab(parent)
        self._tab_header(tab)
        self.lst_programs = self._list_editor(
            tab, " Запрещённые программы ", self.v_block_prog,
            "Закрывать запрещённые программы",
            self._prog_initial,
            "Закроются сразу при запуске. Пример: chrome.exe, steam.exe",
        )
        self.lst_sites = self._list_editor(
            tab, " Запрещённые сайты ", self.v_block_sites,
            "Блокировать сайты (нужны права администратора)",
            self._sites_initial,
            "Не будут открываться в браузере. Пример: youtube.com, vk.com",
        )
        return page

    def _tab_protection(self, parent: ttk.Notebook) -> ttk.Frame:
        page, tab = self._scrollable_tab(parent)
        self._tab_header(tab)

        auto = ttk.LabelFrame(tab, text=" Автозапуск ", padding=12)
        auto.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(
            auto, text="Запускать при входе в Windows (без прав администратора)",
            variable=self.v_run_key,
        ).pack(anchor="w")

        ttk.Separator(auto, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(
            auto, text="Принудительный запуск вместе с Windows",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            auto,
            text="Задача в Планировщике с наивысшими правами. Так защиту\n"
                 "нельзя выключить из автозагрузки, а диспетчер задач\n"
                 "блокируется полностью. Потребуется подтверждение UAC.",
            foreground="#5a5a5a",
        ).pack(anchor="w", pady=(2, 8))
        self.task_status = ttk.Label(auto, text="")
        self.task_status.pack(anchor="w", pady=(0, 8))
        task_row = ttk.Frame(auto)
        task_row.pack(anchor="w")
        ttk.Button(
            task_row, text="Включить", command=self._install_task
        ).pack(side="left")
        ttk.Button(
            task_row, text="Отключить", command=self._remove_task
        ).pack(side="left", padx=8)

        guard = ttk.LabelFrame(tab, text=" Защита ", padding=12)
        guard.pack(fill="x", pady=(0, 12))
        self.guard_status = ttk.Label(guard, text="")
        self.guard_status.pack(anchor="w", pady=(0, 8))
        guard_row = ttk.Frame(guard)
        guard_row.pack(anchor="w")
        ttk.Button(
            guard_row, text="Запустить защиту", command=self._start_agent
        ).pack(side="left")
        ttk.Button(
            guard_row, text="Остановить", command=self._stop_agent
        ).pack(side="left", padx=8)

        ttk.Separator(guard, orient="horizontal").pack(fill="x", pady=10)
        lock_row = ttk.Frame(guard)
        lock_row.pack(anchor="w")
        ttk.Label(lock_row, text="Заблокировать сейчас на").pack(side="left")
        ttk.Combobox(
            lock_row, values=list(LOCK_CHOICES), textvariable=self.v_lock_for,
            state="readonly", width=13,
        ).pack(side="left", padx=8)
        ttk.Button(
            lock_row, text="Заблокировать", command=self._lock_now
        ).pack(side="left")
        ttk.Button(
            lock_row, text="Проверить (15 сек)", command=self._test_lock
        ).pack(side="left", padx=8)

        grant_row = ttk.Frame(guard)
        grant_row.pack(anchor="w", pady=(8, 0))
        ttk.Button(
            grant_row, text="Отменить разрешённое время",
            command=self._cancel_grant,
        ).pack(side="left")
        ttk.Label(
            grant_row, text="снять выданное «ещё N минут» и вернуть блокировку",
            foreground="#5a5a5a",
        ).pack(side="left", padx=8)

        cad_box = ttk.LabelFrame(tab, text=" Ctrl+Alt+Del ", padding=12)
        cad_box.pack(fill="x", pady=(4, 0))
        ttk.Label(
            cad_box,
            text="Саму комбинацию Ctrl+Alt+Del не может перехватить ни одна\n"
                 "программа — её обрабатывает ядро Windows. Но с её экрана\n"
                 "можно убрать всё опасное: диспетчер задач, «Сменить\n"
                 "пользователя», «Выйти», «Заблокировать», «Сменить пароль».\n"
                 "Тогда экран станет бесполезным. Нужны права администратора.",
            foreground="#5a5a5a",
        ).pack(anchor="w", pady=(0, 8))
        self.cad_status = ttk.Label(cad_box, text="")
        self.cad_status.pack(anchor="w", pady=(0, 8))
        cad_row = ttk.Frame(cad_box)
        cad_row.pack(anchor="w")
        ttk.Button(
            cad_row, text="Усилить Ctrl+Alt+Del", command=self._harden_cad
        ).pack(side="left")
        ttk.Button(
            cad_row, text="Сбросить", command=self._unharden_cad
        ).pack(side="left", padx=8)

        upd = ttk.LabelFrame(tab, text=" Обновления ", padding=12)
        upd.pack(fill="x", pady=(12, 0))
        from . import __version__
        ttk.Label(upd, text=f"Текущая версия: {__version__}").pack(anchor="w")
        url_row = ttk.Frame(upd)
        url_row.pack(fill="x", pady=(8, 0))
        ttk.Label(url_row, text="Адрес обновлений:").pack(side="left")
        self.v_update_url = tk.StringVar(value=self.cfg.get("update_url", ""))
        ttk.Entry(url_row, textvariable=self.v_update_url).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )
        upd_row = ttk.Frame(upd)
        upd_row.pack(anchor="w", pady=(8, 0))
        ttk.Button(
            upd_row, text="Проверить обновления", command=self._check_updates
        ).pack(side="left")
        ttk.Label(
            upd, text="Можно указать GitHub: https://api.github.com/repos/ВЛАДЕЛЕЦ/"
                      "РЕПО/releases/latest",
            foreground="#5a5a5a",
        ).pack(anchor="w", pady=(8, 0))

        ttk.Label(
            tab,
            text="\nВо время блокировки скрывается панель задач и не работают\n"
                 "Win, Alt+Tab, Alt+F4, Ctrl+Esc и Ctrl+Shift+Esc.",
            foreground="#5a5a5a",
        ).pack(anchor="w")
        return page

    def _spin(self, parent, low, high, var, row, column) -> ttk.Spinbox:
        widget = ttk.Spinbox(
            parent, from_=low, to=high, width=4, textvariable=var,
            format="%02.0f", wrap=True,
        )
        widget.grid(row=row, column=column, sticky="w")
        return widget

    def _toggle_states(self) -> None:
        curfew_state = "normal" if self.v_curfew.get() else "disabled"
        for widget in (self.sp_start_h, self.sp_start_m, self.sp_end_h, self.sp_end_m):
            widget.configure(state=curfew_state)
        limit_state = "normal" if self.v_limit.get() else "disabled"
        for widget in (self.sp_limit_h, self.sp_limit_m):
            widget.configure(state=limit_state)

    # ---------- действия ----------

    def _install_task(self) -> None:
        if not messagebox.askyesno(
            "ParentsSee",
            "Windows запросит права администратора.\n\n"
            "После этого ParentsSee будет запускаться вместе с Windows "
            "с наивысшими правами. Продолжить?",
            parent=self.win,
        ):
            return
        autostart.install_task_elevated()
        self.win.after(2500, self._refresh_task_status)

    def _remove_task(self) -> None:
        if not messagebox.askyesno(
            "ParentsSee", "Убрать ParentsSee из Планировщика задач?", parent=self.win
        ):
            return
        autostart.remove_task_elevated()
        self.win.after(2500, self._refresh_task_status)

    def _start_agent(self) -> None:
        if agent_running():
            messagebox.showinfo("ParentsSee", "Защита уже работает.", parent=self.win)
            return
        if not config_mod.is_configured(config_mod.load()):
            messagebox.showwarning("ParentsSee", "Сначала задайте пароль.", parent=self.win)
            return
        start_agent()
        self.win.after(2000, self._refresh)

    def _stop_agent(self) -> None:
        if not agent_running():
            messagebox.showinfo("ParentsSee", "Защита не запущена.", parent=self.win)
            return
        if not messagebox.askyesno(
            "ParentsSee",
            "Остановить защиту? Ограничения перестанут действовать.",
            parent=self.win,
        ):
            return
        if not stop_agent():
            messagebox.showerror(
                "ParentsSee",
                "Не удалось остановить. Снимите процесс pythonw.exe вручную.",
                parent=self.win,
            )
        self.win.after(1500, self._refresh)

    def _lock_now(self) -> None:
        if not agent_running():
            messagebox.showwarning(
                "ParentsSee", "Сначала запустите защиту.", parent=self.win
            )
            return
        minutes = LOCK_CHOICES.get(self.v_lock_for.get(), 30)
        now = datetime.now()
        until = (
            datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
            if minutes is None
            else now + timedelta(minutes=minutes)
        )
        # Живому агенту — командой (без гонок за файл состояния).
        state_mod.push_command({"lock_until": until.isoformat()})
        messagebox.showinfo(
            "ParentsSee",
            f"Компьютер заблокируется в течение нескольких секунд.\n"
            f"Разблокировка в {until.strftime('%H:%M')} или по паролю.",
            parent=self.win,
        )
        self.win.after(1500, self._refresh)

    def _test_lock(self) -> None:
        """Показывает экран блокировки на 15 секунд для проверки."""
        if not agent_running():
            messagebox.showwarning(
                "ParentsSee", "Сначала запустите защиту.", parent=self.win
            )
            return
        until = datetime.now() + timedelta(seconds=15)
        state_mod.push_command({"lock_until": until.isoformat()})
        messagebox.showinfo(
            "ParentsSee",
            "Сейчас на 15 секунд появится экран блокировки — так вы увидите,\n"
            "как это выглядит для ребёнка. Он снимется сам.",
            parent=self.win,
        )

    def _cancel_grant(self) -> None:
        cfg = config_mod.load()
        st = state_mod.load(cfg)
        if not state_mod.override_active(st, datetime.now()):
            messagebox.showinfo(
                "ParentsSee", "Сейчас нет выданного разрешения.", parent=self.win
            )
            return
        if not messagebox.askyesno(
            "ParentsSee",
            "Отменить выданное разрешение? Если действуют ограничения "
            "по времени, компьютер снова заблокируется.",
            parent=self.win,
        ):
            return
        if agent_running():
            state_mod.push_command({"cancel_grant": True})
        else:
            st["override_until"] = None
            state_mod.save(cfg, st)
        messagebox.showinfo("ParentsSee", "Разрешение отменено.", parent=self.win)
        self.win.after(1500, self._refresh)

    def _collect(self) -> dict | None:
        try:
            start_h, start_m = int(self.v_start_h.get()), int(self.v_start_m.get())
            end_h, end_m = int(self.v_end_h.get()), int(self.v_end_m.get())
            limit_minutes = int(self.v_limit_h.get()) * 60 + int(self.v_limit_m.get())
            idle = int(self.v_idle.get())
        except ValueError:
            messagebox.showerror("ParentsSee", "Проверьте числовые поля.", parent=self.win)
            return None

        if not (0 <= start_h < 24 and 0 <= end_h < 24
                and 0 <= start_m < 60 and 0 <= end_m < 60):
            messagebox.showerror("ParentsSee", "Время указано неверно.", parent=self.win)
            return None
        if self.v_curfew.get() and (start_h, start_m) == (end_h, end_m):
            messagebox.showerror(
                "ParentsSee", "Начало и конец ночного режима совпадают.", parent=self.win
            )
            return None
        if self.v_limit.get() and limit_minutes <= 0:
            messagebox.showerror(
                "ParentsSee", "Лимит должен быть больше нуля.", parent=self.win
            )
            return None

        cfg = config_mod.load()
        cfg["curfew"] = {
            "enabled": self.v_curfew.get(),
            "start": f"{start_h:02d}:{start_m:02d}",
            "end": f"{end_h:02d}:{end_m:02d}",
        }
        cfg["daily_limit"] = {"enabled": self.v_limit.get(), "minutes": limit_minutes}
        cfg["idle_timeout_seconds"] = max(30, idle)
        cfg["block_programs"] = {
            "enabled": self.v_block_prog.get(),
            "list": list(self.lst_programs.get(0, "end")),
        }
        cfg["block_sites"] = {
            "enabled": self.v_block_sites.get(),
            "list": list(self.lst_sites.get(0, "end")),
        }
        cfg["harden_cad"] = self.v_cad.get()
        cfg["update_url"] = self.v_update_url.get().strip()
        return cfg

    def _save(self) -> None:
        cfg = self._collect()
        if cfg is None:
            return
        config_mod.save(cfg)
        self.cfg = cfg
        if self.v_run_key.get():
            autostart.enable()
        else:
            autostart.disable()
        messagebox.showinfo(
            "ParentsSee", "Настройки сохранены. Защита подхватит их сама.",
            parent=self.win,
        )
        self._refresh()

    def _reset_counter(self) -> None:
        if not messagebox.askyesno(
            "ParentsSee", "Обнулить время, потраченное сегодня?", parent=self.win
        ):
            return
        if agent_running():
            state_mod.push_command({"reset": True})
        else:
            cfg = config_mod.load()
            st = state_mod.load(cfg)
            st["used_seconds"] = 0.0
            st["tampered"] = False
            state_mod.save(cfg, st)
        messagebox.showinfo("ParentsSee", "Счётчик обнулён.", parent=self.win)
        self._refresh()

    def _check_updates(self) -> None:
        from . import updater

        url = self.v_update_url.get().strip()
        if not url:
            messagebox.showinfo(
                "ParentsSee",
                "Адрес обновлений не задан.\n\n"
                "Впишите ссылку на манифест обновления (JSON) в поле выше и "
                "нажмите «Сохранить».",
                parent=self.win,
            )
            return
        # Сохраняем адрес, чтобы не потерялся.
        cfg = config_mod.load()
        cfg["update_url"] = url
        config_mod.save(cfg)

        try:
            info = updater.check(url)
        except Exception as exc:
            messagebox.showerror(
                "ParentsSee", f"Не удалось проверить обновления:\n{exc}",
                parent=self.win,
            )
            return
        if not info:
            messagebox.showinfo(
                "ParentsSee", "У вас установлена последняя версия.", parent=self.win
            )
            return

        notes = info.get("notes", "")
        if not messagebox.askyesno(
            "ParentsSee",
            f"Доступна версия {info['version']}.\n\n{notes}\n\nОбновить сейчас?",
            parent=self.win,
        ):
            return
        if not updater.is_frozen():
            messagebox.showinfo(
                "ParentsSee",
                "Скачайте новую версию вручную:\n" + info.get("url", ""),
                parent=self.win,
            )
            return
        try:
            new_exe = updater.download(info["url"], info.get("sha256"))
        except Exception as exc:
            messagebox.showerror(
                "ParentsSee", f"Не удалось скачать обновление:\n{exc}",
                parent=self.win,
            )
            return
        messagebox.showinfo(
            "ParentsSee",
            "Обновление загружено. Программа закроется и обновится за пару секунд.",
            parent=self.win,
        )
        updater.install_and_restart(new_exe)

    def _harden_cad(self) -> None:
        if not messagebox.askyesno(
            "ParentsSee",
            "Windows запросит права администратора.\n\n"
            "С экрана Ctrl+Alt+Del будут убраны диспетчер задач,\n"
            "«Сменить пользователя», «Выйти», «Заблокировать» и\n"
            "«Сменить пароль». Продолжить?",
            parent=self.win,
        ):
            return
        cad.harden_elevated()
        self.win.after(2500, self._refresh_cad_status)

    def _unharden_cad(self) -> None:
        cad.unharden_elevated()
        self.win.after(2500, self._refresh_cad_status)

    def _refresh_cad_status(self) -> None:
        try:
            self.cad_status.configure(
                text=("Ctrl+Alt+Del: усилен" if cad.is_hardened()
                      else "Ctrl+Alt+Del: обычный")
            )
        except tk.TclError:
            pass

    def _change_password(self) -> None:
        cfg = config_mod.load()
        if _setup_password(self.win, cfg):
            self.cfg = cfg
            messagebox.showinfo("ParentsSee", "Пароль изменён.", parent=self.win)

    # ---------- обновление статуса ----------

    def _refresh_task_status(self) -> None:
        exists = autostart.task_exists()
        self.task_status.configure(
            text=("Запуск с Windows: включён" if exists
                  else "Запуск с Windows: выключен")
        )

    def _refresh(self) -> None:
        if not self.win.winfo_exists():
            return
        try:
            self._refresh_once()
            self.win.after(4000, self._refresh)
        except tk.TclError:
            return   # окно закрыли между тиками

    def _refresh_once(self) -> None:
        cfg = config_mod.load()
        st = state_mod.load(cfg)
        now = datetime.now()
        decision = rules.evaluate(cfg, st, now)

        used = int(decision.used_seconds)
        lines = [f"Сегодня за компьютером: {used // 3600} ч {used % 3600 // 60} мин"]
        if decision.limit_seconds is not None:
            left = max(0, int(decision.limit_seconds - decision.used_seconds))
            lines.append(f"Осталось по лимиту: {left // 3600} ч {left % 3600 // 60} мин")
        if state_mod.manual_lock_active(st, now):
            lines.append("Сейчас включена ручная блокировка")
        elif state_mod.override_active(st, now):
            until = datetime.fromisoformat(st["override_until"])
            lines.append(f"Разрешение родителя действует до {until.strftime('%H:%M')}")
        if st.get("tampered"):
            lines.append("Внимание: файл учёта времени изменяли вручную")

        running = agent_running()
        lines.append("Защита: работает" if running else "Защита: НЕ запущена")
        self.status_label.configure(text="\n".join(lines))
        self.guard_status.configure(
            text=("Защита работает" if running else "Защита остановлена")
        )
        self._refresh_task_status()
        self._refresh_cad_status()


def _bring_to_front(win: tk.Toplevel) -> None:
    """Выводит окно на передний план (иначе фоновый агент открывает его позади)."""
    try:
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        win.focus_force()
        # Снимаем «поверх всех» через мгновение, чтобы окно вело себя обычно.
        win.after(500, lambda: _drop_topmost(win))
    except tk.TclError:
        pass


def _drop_topmost(win: tk.Toplevel) -> None:
    try:
        win.attributes("-topmost", False)
    except tk.TclError:
        pass


def open_settings_window(
    master: tk.Misc | None = None, *, already_authenticated: bool = False
) -> None:
    """Открывает окно родителя. Без master создаёт собственное приложение."""
    winapi.enable_dpi_awareness()
    # Восстанавливаем стол только если живого агента нет (иначе бы сняли
    # активную блокировку при открытии настроек из-под неё).
    if not agent_running():
        heal_after_crash()
    own_root = master is None
    root = tk.Tk() if own_root else master
    if own_root:
        root.withdraw()

    cfg = config_mod.load()
    if not config_mod.is_configured(cfg):
        messagebox.showinfo(
            "ParentsSee",
            "Первый запуск.\n\nПридумайте пароль родителя — им снимается "
            "блокировка и открываются настройки. Ребёнок знать его не должен.",
            parent=root,
        )
        if not _setup_password(root, cfg):
            if own_root:
                root.destroy()
            return
        cfg = config_mod.load()
        # Включаем автозапуск, чтобы защита возвращалась после перезагрузки.
        try:
            autostart.enable()
        except OSError:
            pass
    elif not already_authenticated:
        if not _ask_password(root, cfg):
            if own_root:
                root.destroy()
            return

    # Проверяем нужные библиотеки (для значка в трее) при каждом входе.
    deps.ensure(root)

    window = SettingsWindow(root, cfg)
    if own_root:
        _bring_to_front(window.win)
        window.win.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    else:
        # Открыто фоновым агентом: держим поверх всех, пока не закроют, иначе
        # окно теряется за блокировкой/другими окнами. transient к СКРЫТОМУ
        # корню тут не используем — из-за него окно само пряталось.
        def _raise():
            try:
                window.win.deiconify()
                window.win.attributes("-topmost", True)
                window.win.lift()
                window.win.focus_force()
            except tk.TclError:
                pass
        _raise()
        window.win.after(150, _raise)   # повторно, когда окно уже отрисовано
        try:
            window.win.grab_set()
        except tk.TclError:
            pass
        root.wait_window(window.win)


def main() -> int:
    open_settings_window()
    return 0
