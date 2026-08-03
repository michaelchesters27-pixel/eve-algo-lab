from __future__ import annotations

import hashlib
import hmac
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.autonomy import number
from app.services.demo_eligibility import describe_bot_usage

UTC = timezone.utc
ONLINE_SECONDS = 95
STALE_SECONDS = 10 * 60
VISIBLE_HISTORY_SECONDS = 24 * 60 * 60


def utc_now() -> datetime:
    return datetime.now(UTC)


def fleet_token(secret: str, package_id: str, rule_hash: str) -> str:
    message = f"{package_id}:{rule_hash}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_fleet_token(secret: str, package_id: str, rule_hash: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    expected = fleet_token(secret, package_id, rule_hash)
    return hmac.compare_digest(expected, supplied.strip())


def epoch_iso(value: int | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def instance_key(payload: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(payload.get("package_id") or ""),
            str(payload.get("account_login") or ""),
            str(payload.get("broker_server") or ""),
            str(payload.get("symbol") or ""),
            str(payload.get("timeframe") or ""),
            str(payload.get("chart_id") or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def heartbeat_row(payload: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = now or utc_now()
    detached = str(payload.get("state") or "").lower() == "detached"
    return {
        "instance_key": instance_key(payload),
        "package_id": payload.get("package_id"),
        "strategy_code": payload.get("strategy_code"),
        "rule_hash": payload.get("rule_hash"),
        "account_login": int(payload.get("account_login") or 0),
        "account_type": payload.get("account_type") or "unknown",
        "broker_server": payload.get("broker_server") or "",
        "broker_company": payload.get("broker_company") or "",
        "symbol": payload.get("symbol") or "",
        "timeframe": payload.get("timeframe") or "",
        "chart_id": payload.get("chart_id") or "",
        "trading_enabled": bool(payload.get("trading_enabled")),
        "algo_trading_enabled": bool(payload.get("algo_trading_enabled")),
        "state": payload.get("state") or "starting",
        "state_detail": payload.get("state_detail") or "",
        "open_positions": int(payload.get("open_positions") or 0),
        "open_profit": float(payload.get("open_profit") or 0),
        "closed_profit_today": float(payload.get("closed_profit_today") or 0),
        "terminal_time": epoch_iso(payload.get("terminal_time")),
        "last_trade_time": epoch_iso(payload.get("last_trade_time")),
        "heartbeat_at": current.isoformat(),
        "detached_at": current.isoformat() if detached else None,
        "client_version": payload.get("client_version") or "",
        "payload": payload,
        "updated_at": current.isoformat(),
    }


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _package_lookup(packages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in packages if item.get("id")}


def build_fleet_dashboard(
    rows: list[dict[str, Any]],
    packages: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(UTC)
    package_map = _package_lookup(packages)
    items: list[dict[str, Any]] = []

    for row in rows:
        heartbeat = parse_dt(row.get("heartbeat_at"))
        age = (current - heartbeat).total_seconds() if heartbeat else 10**9
        detached = bool(row.get("detached_at")) or str(row.get("state") or "").lower() == "detached"
        if detached:
            connection = "detached"
        elif age <= ONLINE_SECONDS:
            connection = "online"
        elif age <= STALE_SECONDS:
            connection = "stale"
        else:
            connection = "offline"

        # Keep the live screen useful: very old detached/offline charts remain in
        # Supabase for audit but do not clutter the operational Demo Fleet.
        if connection in {"offline", "detached"} and age > VISIBLE_HISTORY_SECONDS:
            continue

        package = package_map.get(str(row.get("package_id"))) or {}
        rules = dict(package.get("frozen_rules") or {})
        usage = describe_bot_usage(rules) if rules else {
            "usage_tags": ["all"],
            "usage_title": "Schedule unavailable",
            "schedule_explanation": "Download a fleet-ready package to restore the frozen schedule.",
            "attach_guidance": "Check the matching package in Bot Library.",
        }
        login_text = str(row.get("account_login") or "")
        items.append(
            {
                **row,
                "_account_login_raw": row.get("account_login"),
                "account_login_masked": ("••••" + login_text[-4:]) if login_text else "—",
                **usage,
                "connection": connection,
                "heartbeat_age_seconds": round(age, 1) if age < 10**8 else None,
                "strategy_name": package.get("strategy_name") or row.get("strategy_code"),
                "package_code": package.get("package_code"),
                "frozen_version": package.get("frozen_version"),
                "duplicate": False,
                "needs_attention": connection != "online"
                or not bool(row.get("trading_enabled"))
                or not bool(row.get("algo_trading_enabled"))
                or str(row.get("account_type")) == "real",
            }
        )

    duplicate_keys = Counter(
        (
            item.get("strategy_code"),
            item.get("_account_login_raw"),
            item.get("broker_server"),
            item.get("symbol"),
            item.get("timeframe"),
        )
        for item in items
        if item.get("connection") == "online"
    )
    for item in items:
        key = (
            item.get("strategy_code"),
            item.get("_account_login_raw"),
            item.get("broker_server"),
            item.get("symbol"),
            item.get("timeframe"),
        )
        item["duplicate"] = item.get("connection") == "online" and duplicate_keys[key] > 1
        if item["duplicate"]:
            item["needs_attention"] = True

    for item in items:
        # The raw login is stored server-side for stable instance and duplicate detection,
        # but the public dashboard exposes only the masked form. The original heartbeat
        # payload also contains the login, so it must never be returned by this endpoint.
        item.pop("account_login", None)
        item.pop("_account_login_raw", None)
        item.pop("payload", None)

    order = {"online": 0, "stale": 1, "offline": 2, "detached": 3}
    items.sort(key=lambda item: (order.get(str(item.get("connection")), 9), -number(item.get("closed_profit_today"))))
    online_items = [item for item in items if item.get("connection") == "online"]
    counts = {
        "online": len(online_items),
        "stale": sum(1 for item in items if item.get("connection") == "stale"),
        "offline": sum(1 for item in items if item.get("connection") == "offline"),
        "detached": sum(1 for item in items if item.get("connection") == "detached"),
        "in_trade": sum(1 for item in online_items if int(item.get("open_positions") or 0) > 0),
        "attention": sum(1 for item in items if item.get("needs_attention")),
        "duplicates": sum(1 for item in items if item.get("duplicate")),
        "total": len(items),
    }
    combined_closed = sum(number(item.get("closed_profit_today")) for item in online_items)
    combined_open = sum(number(item.get("open_profit")) for item in online_items)
    return {
        "generated_at": current.isoformat(),
        "counts": counts,
        "combined_closed_profit_today": round(combined_closed, 2),
        "combined_open_profit": round(combined_open, 2),
        "items": items,
        "heartbeat_timeout_seconds": ONLINE_SECONDS,
        "message": "Demo Fleet is live. A bot is online only while its MT5 heartbeat is arriving.",
    }
