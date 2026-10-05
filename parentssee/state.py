"""Учёт израсходованного за день времени. Файл подписан HMAC от подделки."""
from __future__ import annotations

import copy
import hmac
import hashlib
import json
from datetime import date, datetime
from typing import Any

from .paths import STATE_FILE

# Сохраняемые и подписываемые поля. ВАЖНО: "tampered" сюда НЕ входит — это
# результат проверки в текущий момент, а не хранимое значение. Раньше он попадал
# в файл и, единожды став True, читался как True навсегда (ложная блокировка).
EMPTY: dict[str, Any] = {
    "date": "",
    "used_seconds": 0.0,
    "override_until": None,   # ISO-время, до которого родитель снял блокировку
    "lock_until": None,       # ISO-время, до которого родитель включил блокировку вручную
}


def _sign(payload: dict, key_hex: str) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(bytes.fromhex(key_hex), blob, hashlib.sha256).hexdigest()


def _read_signed(retries: int = 5):
    """Читает state.json с повторами. Возвращает dict или None, если после всех
    попыток файл так и не прочитался/не распарсился (пустой при гонке считается
    временным сбоем, а не подделкой)."""
    import time

    for attempt in range(retries):
        try:
            text = STATE_FILE.read_text(encoding="utf-8")
            if not text.strip():
                raise ValueError("пустой файл (гонка записи)")
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            raise ValueError("не объект")
        except FileNotFoundError:
            return None   # файла нет — это уже другой случай (удаление)
        except (OSError, ValueError):
            if attempt < retries - 1:
                time.sleep(0.05)
            else:
                return None
    return None


def load(cfg: dict, today: date | None = None) -> dict:
    """Читает состояние, проверяет подпись и сбрасывает счётчик на новый день."""
    today = today or date.today()
    key = cfg.get("state_key") or ""
    state = copy.deepcopy(EMPTY)
    tampered = False   # результат проверки — не хранится и не подписывается

    if STATE_FILE.exists():
        if not key:
            tampered = True
        else:
            raw = _read_signed()   # с повторами — гасит гонки чтения/записи
            if raw is None:
                # Файл есть, но устойчиво не читается/не парсится — это правка.
                tampered = True
            else:
                payload = raw.get("payload")
                if isinstance(payload, dict) and hmac.compare_digest(
                    _sign(payload, key), raw.get("signature", "")
                ):
                    # Берём только известные поля (без устаревшего tampered).
                    for k in EMPTY:
                        if k in payload:
                            state[k] = payload[k]
                else:
                    tampered = True
    elif cfg.get("state_initialized"):
        # Файл был, а теперь его нет — счётчик пытались обнулить удалением.
        tampered = True

    if state["date"] != today.isoformat():
        state["date"] = today.isoformat()
        state["used_seconds"] = 0.0
        state["override_until"] = None

    state["tampered"] = tampered
    return state


def manual_lock_active(state: dict, now: datetime) -> bool:
    raw = state.get("lock_until")
    if not raw:
        return False
    try:
        return datetime.fromisoformat(raw) > now
    except (ValueError, TypeError):
        return False


def save(cfg: dict, state: dict) -> None:
    import time

    key = cfg.get("state_key") or ""
    if not key:
        return
    payload = {k: state.get(k, EMPTY[k]) for k in EMPTY}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {"payload": payload, "signature": _sign(payload, key)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # os.replace на Windows падает, если файл кем-то открыт (антивирус, другой
    # процесс). Повторяем несколько раз. Если так и не вышло — НЕ пишем файл
    # напрямую (это порвало бы чтение), а пропускаем: на диске остаётся прежний
    # целый файл, а недостающие секунды допишутся на следующем тике.
    for attempt in range(8):
        try:
            tmp.replace(STATE_FILE)
            return
        except PermissionError:
            time.sleep(0.05)

    if not cfg.get("state_initialized"):
        from . import config as config_mod

        cfg["state_initialized"] = True
        config_mod.save(cfg)


def override_active(state: dict, now: datetime) -> bool:
    raw = state.get("override_until")
    if not raw:
        return False
    try:
        return datetime.fromisoformat(raw) > now
    except (ValueError, TypeError):
        return False


# ---------- одноразовые команды родителя работающему агенту ----------
# Пишутся из настроек/трея, применяются агентом один раз и удаляются. Так
# исключены гонки за state.json: его при живом агенте меняет только агент.

def push_command(command: dict) -> None:
    from .paths import COMMAND_FILE

    COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COMMAND_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(command, ensure_ascii=False), encoding="utf-8")
    tmp.replace(COMMAND_FILE)


def pop_command() -> dict | None:
    from .paths import COMMAND_FILE

    if not COMMAND_FILE.exists():
        return None
    try:
        data = json.loads(COMMAND_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    try:
        COMMAND_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return data if isinstance(data, dict) else None
