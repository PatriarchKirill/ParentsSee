"""Настройки ParentsSee и пароль родителя."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
from datetime import time as dtime
from typing import Any

from .paths import CONFIG_FILE

PBKDF2_ROUNDS = 240_000

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "password_salt": "",
    "password_hash": "",
    "state_key": "",
    "state_initialized": False,
    "curfew": {"enabled": True, "start": "21:00", "end": "07:00"},
    "daily_limit": {"enabled": True, "minutes": 180},
    "idle_timeout_seconds": 120,
    "warn_minutes": [15, 5, 1],
    "strict_mode": True,
    "block_programs": {"enabled": False, "list": []},   # ["chrome.exe", "steam.exe"]
    "block_sites": {"enabled": False, "list": []},      # ["youtube.com", "vk.com"]
    "harden_cad": False,   # прятать кнопки на экране Ctrl+Alt+Del (нужен админ)
    "update_url": "",      # адрес JSON-манифеста обновления (см. updater.py)
}


def parse_hhmm(value: str) -> dtime:
    hours, _, minutes = value.partition(":")
    return dtime(int(hours), int(minutes))


def format_hhmm(value: dtime) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _merge(base: dict, override: dict) -> dict:
    """Глубокое слияние: незнакомые/отсутствующие ключи берём из умолчаний."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load() -> dict:
    if not CONFIG_FILE.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return copy.deepcopy(DEFAULTS)
    return _merge(DEFAULTS, raw)


def save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("password_hash"))


def _hash_password(password: str, salt_hex: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ROUNDS
    )
    return digest.hex()


def set_password(cfg: dict, password: str) -> None:
    salt = secrets.token_bytes(16).hex()
    cfg["password_salt"] = salt
    cfg["password_hash"] = _hash_password(password, salt)
    if not cfg.get("state_key"):
        cfg["state_key"] = secrets.token_bytes(32).hex()


def check_password(cfg: dict, password: str) -> bool:
    salt = cfg.get("password_salt") or ""
    stored = cfg.get("password_hash") or ""
    if not salt or not stored:
        return False
    return hmac.compare_digest(_hash_password(password, salt), stored)
