"""Полноэкранный оверлей блокировки и всплывающие предупреждения."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from typing import Callable

from . import winapi

BG = "#0e1320"
PANEL = "#182033"
FG = "#f2f5fb"
MUTED = "#8b9ab5"
ACCENT = "#4c8dff"
DANGER = "#ff6b6b"

FONT = "Segoe UI"
BULLET = "•"


class LockScreen:
    """Окно поверх всех окон, закрывающее все мониторы.

    Само себя не закрывает: агент вызывает update_text() и close().
    """

    def __init__(
        self,
        root: tk.Tk,
        *,
        on_password: Callable[[str], bool],
        on_grant: Callable[[int], None],
        on_open_settings: Callable[[], None],
    ) -> None:
        self._root = root
        self._on_password = on_password
        self._on_grant = on_grant
        self._on_open_settings = on_open_settings
        self._paused = False
        self._closed = False
        self._form_shown = False
        self._unlock_at: datetime | None = None

        x, y, width, height = winapi.virtual_screen()
        win = tk.Toplevel(root)
        self.win = win
        win.overrideredirect(True)
        win.configure(bg=BG)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        for seq in ("<Alt-F4>", "<Control-w>", "<Escape>"):
            win.bind(seq, lambda _e: "break")

        self._build(win)
        win.after(100, self._stay_on_top)
        win.after(200, self._tick_clock)

    # ---------- построение интерфейса ----------

    def _build(self, win: tk.Toplevel) -> None:
        center = tk.Frame(win, bg=BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        # Логотип-щит над часами (если доступен Pillow).
        try:
            from PIL import ImageTk
            from . import icon
            self._logo = ImageTk.PhotoImage(icon.shield_image(72))
            tk.Label(center, image=self._logo, bg=BG).pack(pady=(0, 10))
        except Exception:
            pass

        self.clock_label = tk.Label(
            center, text="", font=(FONT, 72, "bold"), bg=BG, fg=FG
        )
        self.clock_label.pack(pady=(0, 4))

        self.title_label = tk.Label(
            center, text="", font=(FONT, 28, "bold"), bg=BG, fg=FG
        )
        self.title_label.pack(pady=(16, 8))

        self.detail_label = tk.Label(
            center, text="", font=(FONT, 15), bg=BG, fg=MUTED,
            wraplength=760, justify="center",
        )
        self.detail_label.pack()

        self.countdown_label = tk.Label(
            center, text="", font=(FONT, 13), bg=BG, fg=MUTED
        )
        self.countdown_label.pack(pady=(18, 0))

        # Панель родителя свёрнута, пока не нажали кнопку.
        self.parent_area = tk.Frame(center, bg=BG)
        self.parent_area.pack(pady=(40, 0))

        self.reveal_btn = tk.Button(
            self.parent_area,
            text="Я родитель",
            font=(FONT, 11),
            bg=PANEL, fg=MUTED, activebackground=PANEL, activeforeground=FG,
            relief="flat", bd=0, padx=18, pady=8, cursor="hand2",
            command=self._show_password_form,
        )
        self.reveal_btn.pack()

        self.form = tk.Frame(self.parent_area, bg=BG)
        self.entry = tk.Entry(
            self.form, show=BULLET, font=(FONT, 14), width=22,
            bg=PANEL, fg=FG, insertbackground=FG, relief="flat", justify="center",
        )
        self.entry.pack(ipady=8, pady=(0, 8))
        self.entry.bind("<Return>", lambda _e: self._submit_password())

        tk.Button(
            self.form, text="Войти", font=(FONT, 11, "bold"),
            bg=ACCENT, fg="#ffffff", activebackground=ACCENT,
            activeforeground="#ffffff",
            relief="flat", bd=0, padx=22, pady=7, cursor="hand2",
            command=self._submit_password,
        ).pack()

        self.error_label = tk.Label(
            self.form, text="", font=(FONT, 10), bg=BG, fg=DANGER
        )
        self.error_label.pack(pady=(8, 0))

        self.actions = tk.Frame(self.parent_area, bg=BG)

    def _build_actions(self) -> None:
        for child in self.actions.winfo_children():
            child.destroy()
        tk.Label(
            self.actions, text="Разрешить работу:", font=(FONT, 11), bg=BG, fg=MUTED
        ).pack(pady=(0, 10))
        row = tk.Frame(self.actions, bg=BG)
        row.pack()
        for label, minutes in (
            ("15 минут", 15), ("30 минут", 30), ("1 час", 60), ("2 часа", 120)
        ):
            tk.Button(
                row, text=label, font=(FONT, 11),
                bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground="#ffffff",
                relief="flat", bd=0, padx=16, pady=8, cursor="hand2",
                command=lambda m=minutes: self._on_grant(m),
            ).pack(side="left", padx=5)
        tk.Button(
            self.actions, text="Открыть настройки", font=(FONT, 11),
            bg=BG, fg=ACCENT, activebackground=BG, activeforeground=FG,
            relief="flat", bd=0, pady=10, cursor="hand2",
            command=self._open_settings,
        ).pack(pady=(14, 0))

    # ---------- поведение ----------

    def _show_password_form(self) -> None:
        self.reveal_btn.pack_forget()
        self.form.pack()
        self._form_shown = True
        self.entry.focus_set()
        self.entry.focus_force()

    def _submit_password(self) -> None:
        password = self.entry.get()
        self.entry.delete(0, "end")
        if not self._on_password(password):
            self.error_label.configure(text="Неверный пароль")
            return
        self.form.pack_forget()
        self._build_actions()
        self.actions.pack()

    def _open_settings(self) -> None:
        # Прячем экран блокировки, пока открыты настройки, иначе окно настроек
        # оказывается ЗА полноэкранной блокировкой и его не видно.
        self._paused = True
        try:
            self.win.attributes("-topmost", False)
            self.win.withdraw()
            self._on_open_settings()
        finally:
            if not self._closed:
                self._paused = False
                try:
                    self.win.deiconify()
                    self.win.attributes("-topmost", True)
                    self.win.lift()
                    self.win.focus_force()
                except tk.TclError:
                    pass

    def _stay_on_top(self) -> None:
        if self._closed:
            return
        if not self._paused:
            try:
                self.win.attributes("-topmost", True)
                self.win.lift()
                # Возвращаем фокус, ТОЛЬКО если приложение потеряло его целиком.
                # Иначе focus_force каждые 0.7 с воровал бы фокус у поля пароля,
                # и ввод шёл лишь при зажатой кнопке мыши.
                try:
                    focused = self.win.focus_get()
                except (KeyError, tk.TclError):
                    focused = None
                if focused is None:
                    self.win.focus_force()
                    if self._form_shown:
                        self.entry.focus_set()
            except tk.TclError:
                return
        self.win.after(700, self._stay_on_top)

    def _tick_clock(self) -> None:
        if self._closed:
            return
        now = datetime.now()
        try:
            self.clock_label.configure(text=now.strftime("%H:%M"))
            if self._unlock_at:
                left = (self._unlock_at - now).total_seconds()
                if left > 0:
                    hours, rest = divmod(int(left), 3600)
                    minutes, seconds = divmod(rest, 60)
                    text = (
                        f"Осталось {hours} ч {minutes:02d} мин"
                        if hours
                        else f"Осталось {minutes} мин {seconds:02d} сек"
                    )
                    self.countdown_label.configure(text=text)
            self.win.after(1000, self._tick_clock)
        except tk.TclError:
            return

    def update_text(
        self, title: str, detail: str, unlock_at: datetime | None
    ) -> None:
        if self._closed:
            return
        self.title_label.configure(text=title)
        self.detail_label.configure(text=detail)
        self._unlock_at = unlock_at
        if unlock_at is None:
            self.countdown_label.configure(text="")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class WarningToast:
    """Ненавязчивое уведомление в правом нижнем углу."""

    def __init__(self, root: tk.Tk, text: str, seconds: int = 8) -> None:
        x, y, width, height = winapi.virtual_screen()
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=ACCENT)

        frame = tk.Frame(win, bg=PANEL, padx=22, pady=16)
        frame.pack(padx=2, pady=2)
        tk.Label(
            frame, text="ParentsSee", font=(FONT, 9, "bold"), bg=PANEL, fg=ACCENT
        ).pack(anchor="w")
        tk.Label(
            frame, text=text, font=(FONT, 12), bg=PANEL, fg=FG, justify="left"
        ).pack(anchor="w", pady=(4, 0))

        win.update_idletasks()
        win_w = win.winfo_reqwidth()
        win_h = win.winfo_reqheight()
        win.geometry(f"+{x + width - win_w - 28}+{y + height - win_h - 70}")
        win.after(seconds * 1000, lambda: self._safe_destroy(win))

    @staticmethod
    def _safe_destroy(win: tk.Toplevel) -> None:
        try:
            win.destroy()
        except tk.TclError:
            pass
