"""Значок ParentsSee в системном трее.

Работает поверх pystray в отдельном потоке. Все действия, которым нужен
Tkinter, отправляются в главный поток через root.after().
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("parentssee")

try:
    import pystray
    from PIL import Image, ImageDraw
    AVAILABLE = True
except ImportError:      # pragma: no cover
    AVAILABLE = False


def _make_icon(active: bool) -> "Image.Image":
    """Рисуем щит: синий, когда всё спокойно, красный — когда идёт блокировка."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    body = (76, 141, 255, 255) if not active else (255, 90, 90, 255)
    points = [(32, 6), (56, 16), (56, 34), (32, 60), (8, 34), (8, 16)]
    draw.polygon(points, fill=body)
    # Галочка внутри щита.
    draw.line([(22, 32), (30, 42), (44, 22)], fill=(255, 255, 255, 255), width=5)
    return img


class Tray:
    def __init__(
        self,
        *,
        on_open_settings: Callable[[], None],
        on_lock_now: Callable[[], None],
        on_stop: Callable[[], None],
        status_provider: Callable[[], str],
    ) -> None:
        self._on_open_settings = on_open_settings
        self._on_lock_now = on_lock_now
        self._on_stop = on_stop
        self._status_provider = status_provider
        self._icon: "pystray.Icon | None" = None
        self._active = False

    def _menu(self) -> "pystray.Menu":
        return pystray.Menu(
            pystray.MenuItem(lambda _i: self._status_provider(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Открыть настройки", lambda: self._on_open_settings(), default=True
            ),
            pystray.MenuItem("Заблокировать сейчас", lambda: self._on_lock_now()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Остановить защиту…", lambda: self._on_stop()),
        )

    def start(self) -> None:
        if not AVAILABLE:
            log.warning("pystray недоступен — значок в трее не показан")
            return
        self._icon = pystray.Icon(
            "ParentsSee",
            icon=_make_icon(active=False),
            title="ParentsSee — защита включена",
            menu=self._menu(),
        )
        self._icon.run_detached()
        log.info("Значок в трее показан")

    def set_active(self, active: bool) -> None:
        """Меняет цвет значка при входе/выходе из блокировки (подсказку — set_title)."""
        if self._icon is None or active == self._active:
            return
        self._active = active
        try:
            self._icon.icon = _make_icon(active)
        except Exception:      # pragma: no cover — трей может быть ещё не готов
            pass

    def set_title(self, text: str) -> None:
        """Подсказка при наведении на значок (например, сколько осталось)."""
        if self._icon is None:
            return
        try:
            if self._icon.title != text:
                self._icon.title = text
        except Exception:      # pragma: no cover
            pass

    def notify(self, message: str, title: str = "ParentsSee") -> None:
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except Exception:      # pragma: no cover
            pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:      # pragma: no cover
                pass
            self._icon = None
