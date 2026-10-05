"""Решение: можно ли сейчас пользоваться компьютером."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta

from . import config as config_mod
from . import state as state_mod

CURFEW = "curfew"
LIMIT = "limit"
TAMPER = "tamper"
MANUAL = "manual"


@dataclass
class Decision:
    blocked: bool
    reason: str                  # CURFEW | LIMIT | TAMPER | ""
    title: str
    detail: str
    unlock_at: datetime | None   # когда блокировка снимется сама
    seconds_left: float | None   # сколько осталось до ближайшей блокировки
    used_seconds: float
    limit_seconds: float | None


def in_curfew(moment: dtime, start: dtime, end: dtime) -> bool:
    """Учитывает переход через полночь (21:00 -> 07:00)."""
    if start == end:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def _next_at(now: datetime, target: dtime) -> datetime:
    """Ближайший момент строго после now, в который на часах будет target."""
    candidate = now.replace(
        hour=target.hour, minute=target.minute, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _next_midnight(now: datetime) -> datetime:
    return datetime.combine(now.date() + timedelta(days=1), dtime(0, 0))


def _limit_seconds(cfg: dict) -> float | None:
    limit = cfg.get("daily_limit", {})
    if not limit.get("enabled"):
        return None
    return max(0.0, float(limit.get("minutes", 0)) * 60.0)


def _used_at(state: dict, moment: datetime) -> float:
    """Счётчик обнуляется в полночь, поэтому в будущем дне израсходовано 0."""
    try:
        tracked = date.fromisoformat(state.get("date") or "")
    except ValueError:
        return float(state.get("used_seconds", 0.0))
    if moment.date() > tracked:
        return 0.0
    return float(state.get("used_seconds", 0.0))


def _blocking_reason(cfg: dict, state: dict, moment: datetime) -> tuple[str, datetime] | None:
    """Причина блокировки в момент moment и время, когда её стоит перепроверить."""
    curfew = cfg.get("curfew", {})
    if curfew.get("enabled"):
        start = config_mod.parse_hhmm(curfew.get("start", "21:00"))
        end = config_mod.parse_hhmm(curfew.get("end", "07:00"))
        if in_curfew(moment.time(), start, end):
            return CURFEW, _next_at(moment, end)

    limit = _limit_seconds(cfg)
    if limit is not None and _used_at(state, moment) >= limit:
        return LIMIT, _next_midnight(moment)
    return None


def _unlock_time(cfg: dict, state: dict, now: datetime) -> datetime:
    """Первый момент, когда ни одно правило больше не блокирует."""
    moment = now
    for _ in range(6):
        found = _blocking_reason(cfg, state, moment)
        if found is None:
            return moment
        moment = found[1]
    return moment


def _fmt_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин"
    return f"{secs} сек"


def evaluate(cfg: dict, state: dict, now: datetime | None = None) -> Decision:
    now = now or datetime.now()
    limit = _limit_seconds(cfg)
    used = float(state.get("used_seconds", 0.0))

    if state.get("tampered") and cfg.get("strict_mode", True):
        return Decision(
            blocked=True,
            reason=TAMPER,
            title="Файл учёта времени изменён",
            detail="Нужен пароль родителя, чтобы продолжить работу.",
            unlock_at=None,
            seconds_left=None,
            used_seconds=used,
            limit_seconds=limit,
        )

    if state_mod.manual_lock_active(state, now):
        until = datetime.fromisoformat(state["lock_until"])
        return Decision(
            blocked=True,
            reason=MANUAL,
            title="Компьютер заблокирован родителем",
            detail=f"Блокировка снимется в {until.strftime('%H:%M')} "
                   f"или раньше — по паролю родителя.",
            unlock_at=until,
            seconds_left=None,
            used_seconds=used,
            limit_seconds=limit,
        )

    if state_mod.override_active(state, now):
        until = datetime.fromisoformat(state["override_until"])
        return Decision(
            blocked=False,
            reason="",
            title="Доступ разрешён родителем",
            detail=f"До {until.strftime('%H:%M')}",
            unlock_at=None,
            seconds_left=(until - now).total_seconds(),
            used_seconds=used,
            limit_seconds=limit,
        )

    found = _blocking_reason(cfg, state, now)
    if found is not None:
        reason, _ = found
        unlock_at = _unlock_time(cfg, state, now)
        if reason == CURFEW:
            title = "Время отдыхать"
            detail = f"Компьютер снова заработает в {unlock_at.strftime('%H:%M')}."
        else:
            title = "Дневной лимит исчерпан"
            spent = _fmt_duration(used)
            detail = (
                f"Сегодня за компьютером уже {spent}. "
                f"Продолжить можно с {unlock_at.strftime('%H:%M')}."
            )
        return Decision(
            blocked=True,
            reason=reason,
            title=title,
            detail=detail,
            unlock_at=unlock_at,
            seconds_left=None,
            used_seconds=used,
            limit_seconds=limit,
        )

    # Не заблокировано — считаем, сколько осталось до ближайшего ограничения.
    candidates: list[float] = []
    curfew = cfg.get("curfew", {})
    if curfew.get("enabled"):
        start = config_mod.parse_hhmm(curfew.get("start", "21:00"))
        candidates.append((_next_at(now, start) - now).total_seconds())
    if limit is not None:
        candidates.append(max(0.0, limit - used))

    return Decision(
        blocked=False,
        reason="",
        title="Доступ разрешён",
        detail="",
        unlock_at=None,
        seconds_left=min(candidates) if candidates else None,
        used_seconds=used,
        limit_seconds=limit,
    )
