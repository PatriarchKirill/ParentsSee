"""Расположение файлов данных ParentsSee."""
from __future__ import annotations

import os
from pathlib import Path


def _pick_data_dir() -> Path:
    """ProgramData, если он доступен на запись, иначе LocalAppData."""
    candidates = []
    program_data = os.environ.get("ProgramData") or os.environ.get("PROGRAMDATA")
    if program_data:
        candidates.append(Path(program_data) / "ParentsSee")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "ParentsSee")
    candidates.append(Path.home() / ".parentssee")

    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return path
        except OSError:
            continue
    raise RuntimeError("Не удалось найти каталог для данных ParentsSee")


DATA_DIR = _pick_data_dir()
CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "parentssee.log"

APP_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = APP_ROOT / "ParentsSee.pyw"
PID_FILE = DATA_DIR / "agent.pid"
COMMAND_FILE = DATA_DIR / "command.json"
