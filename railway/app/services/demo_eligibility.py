from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services.autonomy import alignment_band, compression_band, number, streak_band, trend_band

UTC = timezone.utc
UK = ZoneInfo("Europe/London")
NY = ZoneInfo("America/New_York")

CALENDAR_FIELDS = {"weekday", "month", "quarter", "week_of_month", "hour_utc", "session"}
PERIOD_FIELDS = {"weekday", "month", "quarter", "week_of_month"}
WINDOW_FIELDS = {"hour_utc", "session"}
DYNAMIC_FIELDS = {"regime", "direction", "alignment_band", "compression_band", "trend_band", "streak_band"}

STATUS_PRIORITY = {
    "active_now": 0,
    "attach_now_waiting_market_condition": 1,
    "waiting_for_trading_window": 2,
    "waiting_for_period": 3,
    "market_closed": 4,
    "data_unavailable": 5,
}

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}
WEEKDAY_NAMES = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
SESSION_NAMES = {"asia": "Asian session", "london": "London session", "new_york": "New York session", "off_session": "outside the main sessions"}


@dataclass(frozen=True)
class ConditionResult:
    field: str
    expected: Any
    actual: Any
    matched: bool
    kind: str
    label: str


def as_utc(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def current_session(value: datetime) -> str:
    utc = value.astimezone(UTC)
    london_hour = utc.astimezone(UK).hour
    ny_hour = utc.astimezone(NY).hour
    if 8 <= ny_hour < 17:
        return "new_york"
    if 8 <= london_hour < 13:
        return "london"
    if 0 <= utc.hour < 7:
        return "asia"
    return "off_session"


def calendar_context(value: datetime) -> dict[str, Any]:
    utc = value.astimezone(UTC)
    return {
        "weekday": utc.isoweekday(),
        "month": utc.month,
        "quarter": ((utc.month - 1) // 3) + 1,
        "week_of_month": ((utc.day - 1) // 7) + 1,
        "hour_utc": utc.hour,
        "session": current_session(utc),
    }


def snapshot_context(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(snapshot or {})
    return {
        "regime": row.get("regime"),
        "direction": int(number(row.get("direction"))),
        "alignment_band": alignment_band(row.get("alignment_score")),
        "compression_band": compression_band(row.get("compression_ratio")),
        "trend_band": trend_band(row.get("trend_12_atr")),
        "streak_band": streak_band(row.get("streak")),
        "alignment_score": int(number(row.get("alignment_score"))),
        "candle_time": row.get("candle_time"),
    }


def market_is_open(value: datetime) -> bool:
    utc = value.astimezone(UTC)
    weekday = utc.weekday()  # Monday=0
    if weekday <= 3:
        return True
    if weekday == 4:
        return utc.hour < 22
    if weekday == 5:
        return False
    return utc.hour >= 22


def next_market_open(value: datetime) -> datetime:
    probe = value.astimezone(UTC).replace(second=0, microsecond=0)
    for _ in range(8 * 24 * 4):
        if market_is_open(probe):
            return probe
        probe += timedelta(minutes=15)
    return probe


def next_anchor(value: datetime) -> datetime:
    utc = value.astimezone(UTC).replace(second=0, microsecond=0)
    minute = ((utc.minute // 15) + 1) * 15
    if minute >= 60:
        return utc.replace(minute=0) + timedelta(hours=1)
    return utc.replace(minute=minute)


def source_fields_at(value: datetime, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = calendar_context(value)
    fields.update(snapshot_context(snapshot))
    return fields


def condition_value_matches(field: str, actual: Any, expected: Any) -> bool:
    if field in {"weekday", "month", "quarter", "week_of_month", "hour_utc", "direction"}:
        return int(number(actual, -9999)) == int(number(expected, -9998))
    return str(actual or "") == str(expected or "")


def condition_label(field: str, expected: Any) -> str:
    if field == "weekday":
        return WEEKDAY_NAMES.get(int(number(expected)), f"weekday {expected}")
    if field == "month":
        return MONTH_NAMES.get(int(number(expected)), f"month {expected}")
    if field == "quarter":
        quarter = int(number(expected))
        ranges = {1: "January–March", 2: "April–June", 3: "July–September", 4: "October–December"}
        return ranges.get(quarter, f"quarter {quarter}")
    if field == "week_of_month":
        return f"week {int(number(expected))} of the month"
    if field == "hour_utc":
        return f"{int(number(expected)):02d}:00 UTC"
    if field == "session":
        return SESSION_NAMES.get(str(expected), str(expected).replace("_", " "))
    if field == "direction":
        return {1: "bullish candle direction", -1: "bearish candle direction", 0: "neutral candle direction"}.get(int(number(expected)), str(expected))
    return f"{field.replace('_', ' ')} = {str(expected).replace('_', ' ')}"


def evaluate_conditions(
    conditions: list[dict[str, Any]], fields: dict[str, Any]
) -> list[ConditionResult]:
    results: list[ConditionResult] = []
    for condition in conditions:
        field = str(condition.get("field") or "")
        expected = condition.get("value")
        actual = fields.get(field)
        results.append(
            ConditionResult(
                field=field,
                expected=expected,
                actual=actual,
                matched=condition_value_matches(field, actual, expected),
                kind="calendar" if field in CALENDAR_FIELDS else "dynamic",
                label=condition_label(field, expected),
            )
        )
    return results


def direction_is_ready(direction_rule: str, fields: dict[str, Any]) -> bool:
    if direction_rule in {"fixed_long", "fixed_short"}:
        return True
    if direction_rule == "alignment_direction":
        return int(number(fields.get("alignment_score"))) != 0
    return int(number(fields.get("direction"))) != 0


def calendar_matches_at(conditions: list[dict[str, Any]], condition_mode: str, value: datetime) -> bool:
    relevant = [item for item in conditions if str(item.get("field") or "") in CALENDAR_FIELDS]
    if not relevant:
        return True
    fields = calendar_context(value)
    all_match = all(condition_value_matches(str(item.get("field") or ""), fields.get(str(item.get("field") or "")), item.get("value")) for item in relevant)
    return all_match if condition_mode == "include" else not all_match


def next_calendar_window(
    conditions: list[dict[str, Any]], condition_mode: str, now: datetime, max_days: int = 400
) -> datetime | None:
    probe = next_anchor(now)
    max_steps = max_days * 24 * 4
    for _ in range(max_steps):
        if market_is_open(probe) and calendar_matches_at(conditions, condition_mode, probe):
            return probe
        probe += timedelta(minutes=15)
    return None


def describe_current_time(value: datetime) -> dict[str, str]:
    utc = value.astimezone(UTC)
    uk = utc.astimezone(UK)
    return {
        "utc": utc.isoformat(),
        "utc_label": utc.strftime("%d %b %Y %H:%M UTC"),
        "uk": uk.isoformat(),
        "uk_label": uk.strftime("%d %b %Y %H:%M %Z"),
    }


def plain_rule_summary(rules: dict[str, Any]) -> str:
    conditions = list(rules.get("source_conditions") or [])
    mode = str(rules.get("condition_mode") or "include")
    if not conditions:
        condition_text = "No calendar restriction"
    else:
        joined = " and ".join(condition_label(str(item.get("field") or ""), item.get("value")) for item in conditions)
        condition_text = f"Trade when {joined}" if mode == "include" else f"Trade except when {joined}"
    direction = {
        "alignment_direction": "follow multi-timeframe alignment",
        "current_direction": "follow the current M5 candle direction",
        "fixed_long": "long only",
        "fixed_short": "short only",
    }.get(str(rules.get("direction_rule") or "current_direction"), "use the frozen direction rule")
    return f"{condition_text}; {direction}."


def _locked_metrics(package: dict[str, Any]) -> dict[str, Any]:
    report = dict(package.get("validation_report") or {})
    metrics = dict(report.get("validation_metrics") or {})
    standard = dict(metrics.get("standard_cost") or {})
    return dict(standard.get("locked_test") or {})


def _rank_score(status: str, package: dict[str, Any]) -> tuple[int, float, float]:
    locked = _locked_metrics(package)
    pf = number(locked.get("profit_factor"))
    expectancy = number(locked.get("expectancy_r"))
    return (STATUS_PRIORITY.get(status, 99), -pf, -expectancy)


def evaluate_package(
    package: dict[str, Any], snapshot: dict[str, Any] | None, now: datetime | None = None
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    rules = dict(package.get("frozen_rules") or {})
    conditions = list(rules.get("source_conditions") or [])
    condition_mode = str(rules.get("condition_mode") or "include")
    direction_rule = str(rules.get("direction_rule") or "current_direction")
    fields = source_fields_at(current, snapshot)
    results = evaluate_conditions(conditions, fields)
    calendar_results = [item for item in results if item.field in CALENDAR_FIELDS]
    dynamic_results = [item for item in results if item.field in DYNAMIC_FIELDS]
    all_match = all(item.matched for item in results) if results else True
    calendar_all_match = all(item.matched for item in calendar_results) if calendar_results else True
    dynamic_all_match = all(item.matched for item in dynamic_results) if dynamic_results else True
    source_eligible = all_match if condition_mode == "include" else not all_match
    calendar_eligible = calendar_all_match if condition_mode == "include" else not calendar_all_match
    direction_ready = direction_is_ready(direction_rule, fields)
    open_now = market_is_open(current)
    snapshot_time = as_utc((snapshot or {}).get("candle_time"))
    snapshot_age_minutes = ((current - snapshot_time).total_seconds() / 60) if snapshot_time else None
    snapshot_fresh = snapshot_age_minutes is not None and (snapshot_age_minutes <= 30 or not open_now)

    next_window = next_calendar_window(conditions, condition_mode, current)
    next_open = next_market_open(current)
    period_mismatch = any(not item.matched and item.field in PERIOD_FIELDS for item in calendar_results)
    window_mismatch = any(not item.matched and item.field in WINDOW_FIELDS for item in calendar_results)

    if not open_now:
        status = "market_closed"
        label = "MARKET CLOSED"
        headline = "Gold is closed; EVE has preserved this bot's next practical window"
        if calendar_eligible:
            next_action = f"Earliest demo action: attach after the estimated market open at {next_open.astimezone(UK).strftime('%d %b %H:%M %Z')}."
        elif next_window:
            next_action = f"Do not choose it at the reopen. Its next estimated eligible window is {next_window.astimezone(UK).strftime('%d %b %Y %H:%M %Z')}."
        else:
            next_action = f"Next estimated market open: {next_open.astimezone(UK).strftime('%d %b %H:%M %Z')}."
    elif not snapshot:
        status = "data_unavailable"
        label = "CHECK DATA"
        headline = "Live market context is not available yet"
        next_action = "Wait for EVE's next M5 sync before choosing this bot."
    elif source_eligible and direction_ready and snapshot_fresh:
        status = "active_now"
        label = "TEST NOW"
        headline = "This bot is currently eligible for demo testing"
        next_action = "Attach it to an XAUUSD M5 demo chart, set InpEnableTrading=true, then enable Algo Trading."
    elif calendar_eligible:
        status = "attach_now_waiting_market_condition"
        label = "ATTACH AND LEAVE"
        headline = "The calendar window is open; EVE is waiting for the market setup"
        if not snapshot_fresh:
            next_action = "Attach on demo and wait for fresh M5 data. The EA will remain idle until its frozen setup appears."
        elif not direction_ready:
            next_action = "Attach on demo and leave it running. It is waiting for a non-neutral direction/alignment signal."
        elif condition_mode == "include" and not dynamic_all_match:
            next_action = "Attach on demo and leave it running. It is waiting for the remaining market-condition filter."
        else:
            next_action = "Attach on demo and leave it running. The EA will check again at each new M5 bar."
    elif period_mismatch:
        status = "waiting_for_period"
        label = "WAIT FOR PERIOD"
        headline = "This bot is outside its tested day, week, month or quarter"
        next_action = "Do not choose it for immediate testing. " + (
            f"Next estimated eligible window: {next_window.astimezone(UK).strftime('%d %b %Y %H:%M %Z')}." if next_window else "No eligible window was found in the next 400 days."
        )
    elif window_mismatch or not calendar_all_match:
        status = "waiting_for_trading_window"
        label = "WAIT FOR TIME"
        headline = "This bot is waiting for its tested hour or session"
        next_action = (
            f"Next estimated eligible window: {next_window.astimezone(UK).strftime('%d %b %Y %H:%M %Z')}."
            if next_window else "No eligible window was found in the next 400 days."
        )
    else:
        status = "attach_now_waiting_market_condition"
        label = "ATTACH AND LEAVE"
        headline = "The EA can be attached now and will wait for its frozen setup"
        next_action = "Attach on demo and leave it running. It will only trade when every frozen condition is satisfied."

    current_matches = [item.label for item in results if item.matched]
    current_missing = [item.label for item in results if not item.matched]
    locked = _locked_metrics(package)
    output = {
        "package_id": package.get("id"),
        "package_code": package.get("package_code"),
        "strategy_code": package.get("strategy_code"),
        "strategy_name": package.get("strategy_name"),
        "frozen_version": package.get("frozen_version"),
        "rule_hash": package.get("rule_hash"),
        "status": status,
        "status_label": label,
        "headline": headline,
        "next_action": next_action,
        "attach_to": "XAUUSD M5",
        "demo_switch": "Set InpEnableTrading=true after attaching to a demo chart",
        "algo_trading": "Enable MT5 Algo Trading",
        "condition_mode": condition_mode,
        "direction_rule": direction_rule,
        "rule_summary": plain_rule_summary(rules),
        "conditions": [
            {
                "field": item.field,
                "expected": item.expected,
                "actual": item.actual,
                "matched": item.matched,
                "kind": item.kind,
                "label": item.label,
            }
            for item in results
        ],
        "matched_conditions": current_matches,
        "missing_conditions": current_missing,
        "source_eligible_now": source_eligible,
        "direction_ready_now": direction_ready,
        "market_open_estimate": open_now,
        "snapshot_time": snapshot_time.isoformat() if snapshot_time else None,
        "snapshot_age_minutes": round(snapshot_age_minutes, 1) if snapshot_age_minutes is not None else None,
        "snapshot_fresh": snapshot_fresh,
        "next_eligible_utc": next_window.isoformat() if next_window else None,
        "next_eligible_uk": next_window.astimezone(UK).isoformat() if next_window else None,
        "locked_profit_factor": number(locked.get("profit_factor")),
        "locked_expectancy_r": number(locked.get("expectancy_r")),
        "locked_trades": int(number(locked.get("trades"))),
        "generated_at": package.get("generated_at"),
        "download_url": f"/api/mt5/packages/{package.get('id')}/download" if package.get("id") else None,
        "source_url": f"/api/mt5/packages/{package.get('id')}/source" if package.get("id") else None,
    }
    if status == "market_closed":
        if source_eligible and direction_ready and snapshot_fresh:
            availability_status = "active_now"
        elif calendar_eligible:
            availability_status = "attach_now_waiting_market_condition"
        elif period_mismatch:
            availability_status = "waiting_for_period"
        else:
            availability_status = "waiting_for_trading_window"
    else:
        availability_status = status
    output["availability_status"] = availability_status
    output["rank_score"] = _rank_score(availability_status, package)
    return output


def build_demo_dashboard(
    packages: list[dict[str, Any]], snapshot: dict[str, Any] | None, now: datetime | None = None
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    items = [evaluate_package(package, snapshot, current) for package in packages]
    items.sort(key=lambda item: tuple(item.pop("rank_score")))
    counts = {
        "test_now": sum(1 for item in items if item["status"] == "active_now"),
        "attach_and_leave": sum(1 for item in items if item["status"] == "attach_now_waiting_market_condition"),
        "waiting_for_time": sum(1 for item in items if item["status"] == "waiting_for_trading_window"),
        "waiting_for_period": sum(1 for item in items if item["status"] == "waiting_for_period"),
        "market_closed": sum(1 for item in items if item["status"] == "market_closed"),
        "total": len(items),
    }
    recommended = next((item for item in items if item["status"] in {"active_now", "attach_now_waiting_market_condition"}), None)
    if recommended is None and items:
        recommended = items[0]
    time_info = describe_current_time(current)
    return {
        "time": time_info,
        "market_open_estimate": market_is_open(current),
        "latest_snapshot_time": (snapshot or {}).get("candle_time"),
        "counts": counts,
        "recommended": recommended or {},
        "items": items,
        "disclaimer": "Eligibility is based on EVE's frozen rules, current UTC/UK time and the latest stored M5 context. Broker session times can differ slightly. Demo only.",
    }
