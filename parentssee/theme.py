"""Единое оформление окна: цвета, шрифты, стили ttk."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Палитра
BG = "#eef1f8"          # фон окна
CARD = "#ffffff"        # карточки/рамки
INK = "#1b2333"         # основной текст
MUTED = "#6b7688"       # второстепенный текст
ACCENT = "#3a6eeb"      # акцент (кнопки, выделение)
ACCENT_DK = "#2f5bd0"
DANGER = "#d64545"
LINE = "#dbe0ec"        # разделители/границы

FONT = "Segoe UI"


def apply(root: tk.Misc) -> None:
    """Настраивает ttk-стили. Вызывать один раз для окна."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=BG)

    style.configure(".", background=BG, foreground=INK,
                    font=(FONT, 10), fieldbackground=CARD, bordercolor=LINE)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=INK, font=(FONT, 10))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
    style.configure("Title.TLabel", background=BG, foreground=INK, font=(FONT, 16, "bold"))
    style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
    style.configure("H2.TLabel", background=BG, foreground=INK, font=(FONT, 10, "bold"))

    # Рамки-«карточки»
    style.configure("TLabelframe", background=BG, bordercolor=LINE,
                    relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED,
                    font=(FONT, 9, "bold"))

    # Кнопки
    style.configure("TButton", background="#e6eaf3", foreground=INK,
                    font=(FONT, 10), relief="flat", borderwidth=0, padding=(12, 7))
    style.map("TButton",
              background=[("active", "#dae0ee"), ("pressed", "#cdd5e8")])

    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    font=(FONT, 10, "bold"), relief="flat", borderwidth=0,
                    padding=(16, 8))
    style.map("Accent.TButton",
              background=[("active", ACCENT_DK), ("pressed", ACCENT_DK)],
              foreground=[("disabled", "#e8ecf6")])

    style.configure("Danger.TButton", background="#f6e3e3", foreground=DANGER,
                    font=(FONT, 10), relief="flat", borderwidth=0, padding=(12, 7))
    style.map("Danger.TButton", background=[("active", "#f0d3d3")])

    # Поля ввода
    for widget in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(widget, fieldbackground=CARD, background=CARD,
                        foreground=INK, bordercolor=LINE, arrowcolor=INK,
                        relief="flat", padding=4)
        style.map(widget, bordercolor=[("focus", ACCENT)])

    style.configure("TCheckbutton", background=BG, foreground=INK, font=(FONT, 10))
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("Card.TCheckbutton", background=CARD, foreground=INK, font=(FONT, 10))
    style.map("Card.TCheckbutton", background=[("active", CARD)])

    # Вкладки
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 6, 2, 0))
    style.configure("TNotebook.Tab", background="#e2e7f2", foreground=MUTED,
                    font=(FONT, 10), padding=(16, 8), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", CARD)],
              foreground=[("selected", INK)],
              expand=[("selected", (0, 0, 0, 0))])

    style.configure("TSeparator", background=LINE)
    style.configure("Vertical.TScrollbar", background="#d7dcea",
                    troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)
