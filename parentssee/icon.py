"""Иконка приложения: рисуется в рантайме, поэтому работает и в собранном .exe."""
from __future__ import annotations

_refs: dict = {}   # держим ссылки на PhotoImage, чтобы их не собрал GC


def shield_image(size: int = 64, active: bool = False):
    """PIL-изображение щита с галочкой. active=True — красный (идёт блокировка)."""
    from PIL import Image, ImageDraw

    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    outer = (58, 110, 235, 255) if not active else (214, 69, 69, 255)
    inner = (74, 141, 255, 255) if not active else (255, 90, 90, 255)
    m = big * 0.06
    draw.polygon(
        [(big * 0.5, m), (big - m, big * 0.22), (big - m, big * 0.55),
         (big * 0.5, big - m), (m, big * 0.55), (m, big * 0.22)],
        fill=outer,
    )
    m2 = big * 0.14
    draw.polygon(
        [(big * 0.5, m2), (big - m2, big * 0.24), (big - m2, big * 0.54),
         (big * 0.5, big - m2 * 1.1), (m2, big * 0.54), (m2, big * 0.24)],
        fill=inner,
    )
    draw.line(
        [(big * 0.34, big * 0.5), (big * 0.46, big * 0.64), (big * 0.68, big * 0.34)],
        fill=(255, 255, 255, 255), width=int(big * 0.09), joint="curve",
    )
    return img.resize((size, size), Image.LANCZOS)


def set_window_icon(win) -> None:
    """Ставит иконку окну (в заголовке и на панели задач)."""
    try:
        from PIL import ImageTk

        photo = ImageTk.PhotoImage(shield_image(64))
        win.iconphoto(True, photo)
        _refs[str(win)] = photo
    except Exception:
        pass   # без Pillow просто останется стандартная иконка
