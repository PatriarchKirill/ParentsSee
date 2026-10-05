"""Обновление программы.

Проверяет по адресу `update_url` (из настроек) JSON-манифест вида:

    {
      "version": "1.1.0",
      "url": "https://.../ParentsSee.exe",
      "sha256": "…",              # необязательно, но желательно
      "notes": "Что нового"
    }

Если версия новее текущей — скачивает новый .exe, проверяет хэш и заменяет
собой работающий файл через маленький .bat (запущенный exe сам себя переписать
не может). Работает для собранного .exe; в виде скрипта только сообщает адрес.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

from . import __version__

NO_WINDOW = 0x08000000


def _ver_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(value).strip().split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts) or (0,)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _normalize(data: dict) -> dict | None:
    """Приводит ответ к единому виду {version, url, sha256, notes}.

    Понимает и свой манифест, и ответ GitHub Releases API.
    """
    if not isinstance(data, dict):
        return None
    if "tag_name" in data:                     # GitHub Releases API
        version = str(data.get("tag_name", "")).lstrip("vV").strip()
        exe_url = ""
        for asset in data.get("assets", []):
            name = str(asset.get("name", "")).lower()
            if name.endswith(".exe"):
                exe_url = asset.get("browser_download_url", "")
                break
        return {"version": version, "url": exe_url,
                "sha256": None, "notes": data.get("body", "") or ""}
    if "version" in data:                      # свой манифест
        return {"version": str(data["version"]), "url": data.get("url", ""),
                "sha256": data.get("sha256"), "notes": data.get("notes", "")}
    return None


def check(url: str) -> dict | None:
    """Возвращает сведения об обновлении, если версия новее, иначе None.

    url — либо ссылка на свой JSON-манифест, либо на GitHub Releases API вида
    https://api.github.com/repos/ВЛАДЕЛЕЦ/РЕПО/releases/latest
    """
    if not url:
        return None
    req = urllib.request.Request(
        url, headers={"User-Agent": "ParentsSee",
                      "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    manifest = _normalize(data)
    if not manifest or not manifest.get("version"):
        raise ValueError("Не удалось разобрать сведения об обновлении")
    if _ver_tuple(manifest["version"]) > _ver_tuple(__version__):
        return manifest
    return None


def download(url: str, sha256: str | None = None) -> str:
    """Скачивает новый файл во временную папку, проверяет хэш, возвращает путь."""
    dest = os.path.join(tempfile.gettempdir(), "ParentsSee_new.exe")
    req = urllib.request.Request(url, headers={"User-Agent": "ParentsSee"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
    if sha256 and digest.hexdigest().lower() != sha256.strip().lower():
        os.remove(dest)
        raise ValueError("Контрольная сумма не совпала — файл повреждён")
    return dest


def install_and_restart(new_exe: str) -> None:
    """Заменяет текущий .exe новым и перезапускает (через вспомогательный .bat)."""
    if not is_frozen():
        raise RuntimeError("Автозамена доступна только для собранного .exe")

    current = os.path.abspath(sys.executable)
    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), "ParentsSee_update.bat")
    # Только ASCII, чтобы не зависеть от кодировки консоли.
    script = (
        "@echo off\r\n"
        "set PID=%d\r\n"
        ":wait\r\n"
        'tasklist /FI "PID eq %%PID%%" 2>nul | find "%%PID%%" >nul '
        "&& ( ping -n 2 127.0.0.1 >nul & goto wait )\r\n"
        'copy /y "%s" "%s" >nul\r\n'
        'start "" "%s" open\r\n'
        'del "%%~f0"\r\n'
    ) % (pid, new_exe, current, current)
    with open(bat, "w", encoding="ascii", errors="ignore") as f:
        f.write(script)

    subprocess.Popen(
        ["cmd", "/c", bat],
        creationflags=NO_WINDOW | 0x00000008,   # DETACHED_PROCESS
        close_fds=True,
    )
    # Выходим, чтобы .bat смог заменить файл.
    os._exit(0)
