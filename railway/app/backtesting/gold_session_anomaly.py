from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.backtesting.fixed_ladder_v261 import Candle, PathMode


SessionLeg = Literal["overnight_long", "day_short", "asia_long", "shanghai_day_long"]
Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class GoldSessionAnomalyParameters:
    session_leg: SessionLeg = "overnight_long"
    timezone_name: str = "America/New_York"
    day_open_hour: int = 8
    day_open_minute: int = 20
    settlement_hour: int = 13
    settlement_minute: int = 30
    asia_entry_hour: int = 18
    asia_entry_minute: int = 0
    asia_exit_timezone_name: str = "Asia/Shanghai"
    shanghai_entry_hour: int = 9
    shanghai_entry_minute: int = 0
    asia_exit_hour: int = 15
    asia_exit_minute: int = 30
    fixed_lot: float = 0.01
    maximum_loss_percent: float = 0.25
    long_overnight_cost_per_001_lot: float = 0.70
    triple_swap_weekday: int = 2
    spread_price: float = 0.05
    commission_per_001_lot: float = 0.08
    slippage_price: float = 0.0
    money_per_price_per_001_lot: float = 1.0
    path_mode: PathMode = "candle_direction"

    @property
    def day_open_total_minutes(self) -> int:
        return self.day_open_hour * 60 + self.day_open_minute

    @property
    def settlement_total_minutes(self) -> int:
        return self.settlement_hour * 60 + self.settlement_minute

    @property
    def entry_total_minutes(self) -> int:
        if self.session_leg == "overnight_long":
            return self.settlement_total_minutes
        if self.session_leg == "asia_long":
            return self.asia_entry_hour * 60 + self.asia_entry_minute
        if self.session_leg == "shanghai_day_long":
            return self.shanghai_entry_hour * 60 + self.shanghai_entry_minute
        return self.day_open_total_minutes

    @property
    def exit_total_minutes(self) -> int:
        if self.session_leg == "overnight_long":
            return self.day_open_total_minutes
        if self.session_leg in {"asia_long", "shanghai_day_long"}:
            return self.asia_exit_hour * 60 + self.asia_exit_minute
        return self.settlement_total_minutes

    @property
    def side(self) -> Side:
        return "sell" if self.session_leg == "day_short" else "buy"

    @property
    def strategy_code(self) -> str:
        if self.session_leg == "overnight_long":
            return "gold_overnight_long"
        if self.session_leg == "asia_long":
            return "asia_session_long"
        if self.session_leg == "shanghai_day_long":
            return "shanghai_day_long"
        return "comex_day_short"

    def validate(self) -> None:
        if self.session_leg not in {"overnight_long", "day_short", "asia_long", "shanghai_day_long"}:
            raise ValueError("Unsupported gold session-anomaly leg")
        if self.timezone_name != "America/New_York":
            raise ValueError("Gold Session Anomaly v1 requires America/New_York time")
        if (self.day_open_hour, self.day_open_minute) != (8, 20):
            raise ValueError("The documented COMEX day open must remain 08:20 New York")
        if (self.settlement_hour, self.settlement_minute) != (13, 30):
            raise ValueError("The COMEX settlement boundary must remain 13:30 New York")
        if (self.asia_entry_hour, self.asia_entry_minute) != (18, 0):
            raise ValueError("Asia Session Long v1 must enter at 18:00 New York")
        if self.asia_exit_timezone_name != "Asia/Shanghai":
            raise ValueError("Asia Session Long v1 must use Asia/Shanghai for its exit")
        if (self.shanghai_entry_hour, self.shanghai_entry_minute) != (9, 0):
            raise ValueError("Shanghai Day Long v1 must enter at 09:00 Shanghai")
        if (self.asia_exit_hour, self.asia_exit_minute) != (15, 30):
            raise ValueError("Asia Session Long v1 must exit at 15:30 Shanghai")
        if self.fixed_lot <= 0:
            raise ValueError("Fixed lot must be greater than zero")
        if not 0.01 <= self.maximum_loss_percent <= 5.0:
            raise ValueError("Maximum loss percent must be between 0.01 and 5")
        if not 0 <= self.triple_swap_weekday <= 4:
            raise ValueError("Triple-swap weekday must be Monday through Friday")
        if self.path_mode not in {"candle_direction", "open_high_low_close", "open_low_high_close"}:
            raise ValueError("Unsupported intrabar path mode")
        for name in (
            "long_overnight_cost_per_001_lot",
            "spread_price",
            "commission_per_001_lot",
            "slippage_price",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.money_per_price_per_001_lot <= 0:
            raise ValueError("Money per price move must be greater than zero")


@dataclass(frozen=True)
class GoldSessionSignal:
    side: Side
    signal_time: datetime
    trade_date: str
    session_leg: SessionLeg


@dataclass
class GoldSessionPosition:
    position_id: str
    basket_id: str
    side: Side
    opened_at: datetime
    entry_price: float
    lot_size: float
    stop_mid: float
    planned_risk_money: float
    signal: GoldSessionSignal
    financing_costs: float = 0.0
    charged_rollover_dates: set[str] = field(default_factory=set)


@dataclass
class GoldSessionCompletedTrade:
    basket_id: str
    position_id: str
    side: Side
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    exit_price: float
    stop_mid: float
    lot_size: float
    gross_pnl: float
    commission_costs: float
    financing_costs: float
    net_pnl: float
    peak_floating: float
    worst_floating: float
    exit_reason: str
    signal: GoldSessionSignal
    planned_risk_money: float

    @property
    def total_costs(self) -> float:
        return self.commission_costs + self.financing_costs

    @property
    def strategy_code(self) -> str:
        if self.signal.session_leg == "overnight_long":
            return "gold_overnight_long"
        if self.signal.session_leg == "asia_long":
            return "asia_session_long"
        if self.signal.session_leg == "shanghai_day_long":
            return "shanghai_day_long"
        return "comex_day_short"

    def to_trade_row(self, run_id: str) -> dict[str, Any]:
        return {
            "backtest_run_id": run_id,
            "basket_id": self.basket_id,
            "position_id": self.position_id,
            "side": self.side,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "entry_price": round(self.entry_price, 10),
            "exit_price": round(self.exit_price, 10),
            "stop_loss": round(self.stop_mid, 10),
            "take_profit": None,
            "lot_size": round(self.lot_size, 6),
            "gross_pnl": round(self.gross_pnl, 6),
            "costs": round(self.total_costs, 6),
            "net_pnl": round(self.net_pnl, 6),
            "exit_reason": self.exit_reason,
            "metadata": self._metadata(),
        }

    def to_basket_row(self, run_id: str) -> dict[str, Any]:
        return {
            "backtest_run_id": run_id,
            "basket_id": self.basket_id,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "side": self.side,
            "positions": 1,
            "gross_pnl": round(self.gross_pnl, 6),
            "costs": round(self.total_costs, 6),
            "net_pnl": round(self.net_pnl, 6),
            "peak_floating": round(self.peak_floating, 6),
            "worst_floating": round(self.worst_floating, 6),
            "max_positions": 1,
            "exit_reason": self.exit_reason,
            "metadata": self._metadata(),
        }

    def _metadata(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy_code,
            "strategy_version": "1.0",
            "session_leg": self.signal.session_leg,
            "trade_date": self.signal.trade_date,
            "signal_time": self.signal.signal_time.isoformat(),
            "planned_risk_money": round(self.planned_risk_money, 6),
            "commission_costs": round(self.commission_costs, 6),
            "financing_costs": round(self.financing_costs, 6),
            "entry_protocol": (
                "buy the 13:30 America/New_York M1 open and hold to the next eligible 08:20 open"
                if self.signal.session_leg == "overnight_long"
                else (
                    "buy the 18:00 America/New_York M1 open and hold to the 15:30 Asia/Shanghai open"
                    if self.signal.session_leg == "asia_long"
                    else (
                        "buy the 09:00 Asia/Shanghai M1 open and hold to the 15:30 Asia/Shanghai open"
                        if self.signal.session_leg == "shanghai_day_long"
                        else "sell the 08:20 America/New_York M1 open and hold to the 13:30 open"
                    )
                )
            ),
            "exit_protocol": "0.25% hard money stop or the frozen session boundary",
        }


@dataclass
class GoldSessionSimulationSummary:
    starting_balance: float
    ending_balance: float
    position_pnls: list[float]
    basket_pnls: list[float]
    total_positions: int
    total_baskets: int
    winning_baskets: int
    losing_baskets: int
    break_even_baskets: int
    max_equity_drawdown: float
    max_equity_drawdown_percent: float
    candles_processed: int
    sessions_seen: int
    eligible_sessions: int
    sessions_traded: int
    missing_entry_skips: int
    missing_exit_fallbacks: int
    incomplete_end_discards: int
    financing_events: int
    financing_costs: float
    gap_stop_fills: int
    account_ruined: bool
    ruin_time: str | None
    exit_reasons: dict[str, int]
    monthly_net: dict[str, float]
    yearly_net: dict[str, float]
    first_candle: str | None
    last_candle: str | None
    parameters: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GoldSessionAnomalyBacktester:
    """One frozen gold overnight-long or COMEX-day-short trade per weekday."""

    EPS = 1e-9

    def __init__(self, starting_balance: float, parameters: GoldSessionAnomalyParameters) -> None:
        if starting_balance <= 0:
            raise ValueError("Starting balance must be greater than zero")
        parameters.validate()
        self.params = parameters
        self.timezone = ZoneInfo(parameters.timezone_name)
        self.asia_exit_timezone = ZoneInfo(parameters.asia_exit_timezone_name)
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self._equity_peak = float(starting_balance)
        self.max_equity_drawdown = 0.0
        self.max_equity_drawdown_percent = 0.0

        self.position: GoldSessionPosition | None = None
        self._session_date: date | None = None
        self._day_signal_consumed = False
        self._last_mid: float | None = None
        self._sequence = 0
        self._trade_peak_floating = 0.0
        self._trade_worst_floating = 0.0

        self.completed_trades: list[GoldSessionCompletedTrade] = []
        self.completed_baskets: list[GoldSessionCompletedTrade] = []
        self.position_pnls: list[float] = []
        self.basket_pnls: list[float] = []
        self.exit_reasons: Counter[str] = Counter()
        self.monthly_net: defaultdict[str, float] = defaultdict(float)
        self.yearly_net: defaultdict[str, float] = defaultdict(float)
        self.sessions_seen = 0
        self.eligible_sessions = 0
        self.sessions_traded = 0
        self.missing_entry_skips = 0
        self.missing_exit_fallbacks = 0
        self.incomplete_end_discards = 0
        self.financing_events = 0
        self.financing_costs = 0.0
        self.gap_stop_fills = 0
        self.candles_processed = 0
        self.first_candle: datetime | None = None
        self.last_candle: datetime | None = None
        self.account_ruined = False
        self.ruin_time: datetime | None = None

    @property
    def half_spread(self) -> float:
        return self.params.spread_price / 2.0

    def _local(self, at: datetime) -> datetime:
        return at.astimezone(self.timezone)

    def _entry_local(self, at: datetime) -> datetime:
        if self.params.session_leg == "shanghai_day_long":
            return at.astimezone(self.asia_exit_timezone)
        return self._local(at)

    @staticmethod
    def _minute_of_day(at: datetime) -> int:
        return at.hour * 60 + at.minute

    def _entry_price(self, side: Side, mid: float) -> float:
        if side == "buy":
            return mid + self.half_spread + self.params.slippage_price
        return mid - self.half_spread - self.params.slippage_price

    def _exit_price(self, side: Side, mid: float) -> float:
        if side == "buy":
            return mid - self.half_spread - self.params.slippage_price
        return mid + self.half_spread + self.params.slippage_price

    def _factor(self, lot_size: float) -> float:
        return self.params.money_per_price_per_001_lot * (lot_size / 0.01)

    def _commission(self, lot_size: float) -> float:
        return self.params.commission_per_001_lot * (lot_size / 0.01)

    def position_net(self, mid: float) -> float:
        if self.position is None:
            return 0.0
        exit_price = self._exit_price(self.position.side, mid)
        factor = self._factor(self.position.lot_size)
        gross = (
            (exit_price - self.position.entry_price) * factor
            if self.position.side == "buy"
            else (self.position.entry_price - exit_price) * factor
        )
        return gross - self._commission(self.position.lot_size) - self.position.financing_costs

    def _threshold_mid(self, net_money: float) -> float:
        if self.position is None:
            raise RuntimeError("Cannot calculate a threshold without an open gold-session trade")
        factor = self._factor(self.position.lot_size)
        required_gross = net_money + self._commission(self.position.lot_size) + self.position.financing_costs
        if self.position.side == "buy":
            exit_price = self.position.entry_price + required_gross / factor
            return exit_price + self.half_spread + self.params.slippage_price
        exit_price = self.position.entry_price - required_gross / factor
        return exit_price - self.half_spread - self.params.slippage_price

    def _update_extremes(self, mid: float) -> None:
        equity = max(0.0, self.balance + self.position_net(mid))
        self._equity_peak = max(self._equity_peak, equity)
        drawdown = self._equity_peak - equity
        self.max_equity_drawdown = max(self.max_equity_drawdown, drawdown)
        if self._equity_peak > 0:
            self.max_equity_drawdown_percent = max(
                self.max_equity_drawdown_percent,
                drawdown / self._equity_peak * 100.0,
            )
        if self.position is not None:
            floating = self.position_net(mid)
            self._trade_peak_floating = max(self._trade_peak_floating, floating)
            self._trade_worst_floating = min(self._trade_worst_floating, floating)

    def _reset_session(self, session_date: date) -> None:
        self._session_date = session_date
        self._day_signal_consumed = False
        self.sessions_seen += 1
        if self._entry_day_is_eligible(session_date.weekday()):
            self.eligible_sessions += 1

    def _entry_day_is_eligible(self, weekday: int) -> bool:
        if self.params.session_leg == "asia_long":
            return weekday in {6, 0, 1, 2, 3}
        return weekday < 5

    def _open_daily_trade(self, at: datetime, mid: float, local: datetime) -> bool:
        if (
            self._day_signal_consumed
            or not self._entry_day_is_eligible(local.weekday())
            or self.account_ruined
            or self.position is not None
        ):
            return False
        self._day_signal_consumed = True
        side = self.params.side
        signal = GoldSessionSignal(
            side=side,
            signal_time=at,
            trade_date=(
                at.astimezone(self.asia_exit_timezone).date().isoformat()
                if self.params.session_leg in {"asia_long", "shanghai_day_long"}
                else local.date().isoformat()
            ),
            session_leg=self.params.session_leg,
        )
        self._sequence += 1
        entry_price = self._entry_price(side, mid)
        planned_risk = self.balance * self.params.maximum_loss_percent / 100.0
        prefix = (
            "OVERNIGHT"
            if self.params.session_leg == "overnight_long"
            else (
                "ASIA-LONG"
                if self.params.session_leg == "asia_long"
                else ("SHANGHAI-LONG" if self.params.session_leg == "shanghai_day_long" else "DAY-SHORT")
            )
        )
        self.position = GoldSessionPosition(
            position_id=f"{prefix}-POS-{self._sequence:08d}",
            basket_id=f"{prefix}-TRADE-{self._sequence:08d}",
            side=side,
            opened_at=at,
            entry_price=entry_price,
            lot_size=self.params.fixed_lot,
            stop_mid=mid,
            planned_risk_money=planned_risk,
            signal=signal,
        )
        self.position.stop_mid = self._threshold_mid(-planned_risk)
        opening_floating = self.position_net(mid)
        self._trade_peak_floating = opening_floating
        self._trade_worst_floating = opening_floating
        self.sessions_traded += 1
        self._update_extremes(mid)
        return True

    def _close_position(self, at: datetime, mid: float, reason: str) -> None:
        position = self.position
        if position is None:
            return
        exit_price = self._exit_price(position.side, mid)
        factor = self._factor(position.lot_size)
        gross = (
            (exit_price - position.entry_price) * factor
            if position.side == "buy"
            else (position.entry_price - exit_price) * factor
        )
        commission = self._commission(position.lot_size)
        net = gross - commission - position.financing_costs
        if reason == "ACCOUNT RUIN LIMIT" or net <= -self.balance + self.EPS:
            reason = "ACCOUNT RUIN LIMIT"
            net = -self.balance
            gross = net + commission + position.financing_costs
            self.balance = 0.0
            self.account_ruined = True
            self.ruin_time = at
        else:
            self.balance += net

        completed = GoldSessionCompletedTrade(
            basket_id=position.basket_id,
            position_id=position.position_id,
            side=position.side,
            opened_at=position.opened_at,
            closed_at=at,
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_mid=position.stop_mid,
            lot_size=position.lot_size,
            gross_pnl=gross,
            commission_costs=commission,
            financing_costs=position.financing_costs,
            net_pnl=net,
            peak_floating=self._trade_peak_floating,
            worst_floating=self._trade_worst_floating,
            exit_reason=reason,
            signal=position.signal,
            planned_risk_money=position.planned_risk_money,
        )
        self.completed_trades.append(completed)
        self.completed_baskets.append(completed)
        self.position_pnls.append(net)
        self.basket_pnls.append(net)
        self.exit_reasons[reason] += 1
        local = self._local(at)
        self.monthly_net[local.strftime("%Y-%m")] += net
        self.yearly_net[local.strftime("%Y")] += net
        self.position = None
        self._trade_peak_floating = 0.0
        self._trade_worst_floating = 0.0
        self._update_extremes(mid)

    @staticmethod
    def _crosses(current: float, target: float, level: float) -> bool:
        if target > current:
            return current < level <= target
        if target < current:
            return target <= level < current
        return False

    def _process_segment(self, current: float, target: float, at: datetime, *, gap: bool = False) -> float:
        position = self.position
        if position is None or abs(target - current) <= self.EPS:
            self._update_extremes(target)
            return target
        ruin_mid = self._threshold_mid(-self.balance)
        if gap and self.position_net(target) <= -self.balance + self.EPS:
            self._update_extremes(target)
            self._close_position(at, target, "ACCOUNT RUIN LIMIT")
            return target
        if gap and (
            (position.side == "buy" and target <= position.stop_mid)
            or (position.side == "sell" and target >= position.stop_mid)
        ):
            self.gap_stop_fills += 1
            self._update_extremes(target)
            self._close_position(at, target, "HARD MONEY STOP")
            return target

        events: list[tuple[float, str]] = []
        if self._crosses(current, target, ruin_mid):
            events.append((ruin_mid, "ACCOUNT RUIN LIMIT"))
        if self._crosses(current, target, position.stop_mid):
            events.append((position.stop_mid, "HARD MONEY STOP"))
        if not events:
            self._update_extremes(target)
            return target
        up = target > current
        event_mid, reason = min(events, key=lambda item: item[0]) if up else max(events, key=lambda item: item[0])
        self._update_extremes(event_mid)
        self._close_position(at, event_mid, reason)
        return target

    def _path(self, candle: Candle) -> list[float]:
        if self.params.path_mode == "open_high_low_close":
            return [candle.open, candle.high, candle.low, candle.close]
        if self.params.path_mode == "open_low_high_close":
            return [candle.open, candle.low, candle.high, candle.close]
        if candle.close >= candle.open:
            return [candle.open, candle.low, candle.high, candle.close]
        return [candle.open, candle.high, candle.low, candle.close]

    def _apply_due_financing(self, at: datetime, mid: float) -> None:
        position = self.position
        if position is None or position.signal.session_leg != "overnight_long":
            return
        opened_local = self._local(position.opened_at)
        current_local = self._local(at)
        cursor = opened_local.date()
        while cursor <= current_local.date():
            key = cursor.isoformat()
            rollover = datetime.combine(cursor, time(17, 0), tzinfo=self.timezone)
            if (
                cursor.weekday() < 5
                and key not in position.charged_rollover_dates
                and position.opened_at < rollover.astimezone(position.opened_at.tzinfo)
                and rollover <= current_local
            ):
                multiplier = 3 if cursor.weekday() == self.params.triple_swap_weekday else 1
                cost = (
                    self.params.long_overnight_cost_per_001_lot
                    * (position.lot_size / 0.01)
                    * multiplier
                )
                position.financing_costs += cost
                position.charged_rollover_dates.add(key)
                self.financing_events += 1
                self.financing_costs += cost
                position.stop_mid = self._threshold_mid(-position.planned_risk_money)
            cursor += timedelta(days=1)
        if self.position is not None and self.position_net(mid) <= -self.position.planned_risk_money + self.EPS:
            self._update_extremes(mid)
            self._close_position(at, mid, "HARD MONEY STOP")

    def _should_exit(self, local: datetime) -> bool:
        if self.position is None:
            return False
        if self.params.session_leg in {"asia_long", "shanghai_day_long"}:
            exit_local = local.astimezone(self.asia_exit_timezone)
            target = datetime.combine(
                date.fromisoformat(self.position.signal.trade_date),
                time(self.params.asia_exit_hour, self.params.asia_exit_minute),
                tzinfo=self.asia_exit_timezone,
            )
            return exit_local >= target
        if local.weekday() >= 5:
            return False
        opened_local = self._local(self.position.opened_at)
        minute = self._minute_of_day(local)
        if self.params.session_leg == "overnight_long":
            return local.date() > opened_local.date() and minute >= self.params.exit_total_minutes
        return local.date() == opened_local.date() and minute >= self.params.exit_total_minutes

    def process_candle(self, candle: Candle) -> None:
        if self.account_ruined:
            return
        previous_candle_time = self.last_candle
        if self.first_candle is None:
            self.first_candle = candle.candle_time
        self.last_candle = candle.candle_time
        self.candles_processed += 1
        local = self._entry_local(candle.candle_time)
        session_date = local.date()

        if self._session_date != session_date:
            if self.position is not None and self.params.session_leg == "day_short":
                self._close_position(
                    previous_candle_time or candle.candle_time,
                    self._last_mid if self._last_mid is not None else candle.open,
                    "LAST AVAILABLE SESSION BAR",
                )
            self._reset_session(session_date)

        path = self._path(candle)
        current = self._last_mid if self._last_mid is not None else path[0]
        if self.position is not None and abs(path[0] - current) > self.EPS:
            current = self._process_segment(current, path[0], candle.candle_time, gap=True)
        else:
            current = path[0]

        if self.position is not None:
            self._apply_due_financing(candle.candle_time, candle.open)

        minute = self._minute_of_day(local)
        if self.position is not None and self._should_exit(local):
            if self.params.session_leg in {"asia_long", "shanghai_day_long"}:
                exit_local = candle.candle_time.astimezone(self.asia_exit_timezone)
                exact_exit = (
                    exit_local.date() == date.fromisoformat(self.position.signal.trade_date)
                    and self._minute_of_day(exit_local) == self.params.exit_total_minutes
                )
            else:
                exact_exit = minute == self.params.exit_total_minutes
            if exact_exit:
                self._close_position(candle.candle_time, candle.open, "FROZEN SESSION EXIT")
            else:
                self.missing_exit_fallbacks += 1
                self._close_position(
                    previous_candle_time or candle.candle_time,
                    self._last_mid if self._last_mid is not None else candle.open,
                    "LAST AVAILABLE PRE-EXIT BAR",
                )

        opened = False
        if minute == self.params.entry_total_minutes:
            opened = self._open_daily_trade(candle.candle_time, candle.open, local)
            if opened:
                current = path[0]
        elif (
            self._entry_day_is_eligible(local.weekday())
            and minute > self.params.entry_total_minutes
            and not self._day_signal_consumed
        ):
            self._day_signal_consumed = True
            self.missing_entry_skips += 1

        for target in path[1:]:
            current = self._process_segment(current, target, candle.candle_time)

        self._last_mid = candle.close
        self._update_extremes(candle.close)

    def drain_trades(self) -> list[GoldSessionCompletedTrade]:
        rows = self.completed_trades
        self.completed_trades = []
        return rows

    def drain_baskets(self) -> list[GoldSessionCompletedTrade]:
        rows = self.completed_baskets
        self.completed_baskets = []
        return rows

    def finalise(self) -> tuple[list[GoldSessionCompletedTrade], list[GoldSessionCompletedTrade]]:
        # The test boundary can land inside a session. Counting a synthetic
        # boundary exit would change the frozen rule, so exclude that one
        # incomplete trade from both P/L and the evidence count.
        if self.position is not None:
            self.position = None
            self._trade_peak_floating = 0.0
            self._trade_worst_floating = 0.0
            self.incomplete_end_discards += 1
        return self.drain_trades(), self.drain_baskets()

    def summary(self) -> GoldSessionSimulationSummary:
        wins = sum(value > 0 for value in self.basket_pnls)
        losses = sum(value < 0 for value in self.basket_pnls)
        return GoldSessionSimulationSummary(
            starting_balance=round(self.starting_balance, 2),
            ending_balance=round(self.balance, 2),
            position_pnls=list(self.position_pnls),
            basket_pnls=list(self.basket_pnls),
            total_positions=len(self.position_pnls),
            total_baskets=len(self.basket_pnls),
            winning_baskets=wins,
            losing_baskets=losses,
            break_even_baskets=len(self.basket_pnls) - wins - losses,
            max_equity_drawdown=round(self.max_equity_drawdown, 6),
            max_equity_drawdown_percent=round(self.max_equity_drawdown_percent, 6),
            candles_processed=self.candles_processed,
            sessions_seen=self.sessions_seen,
            eligible_sessions=self.eligible_sessions,
            sessions_traded=self.sessions_traded,
            missing_entry_skips=self.missing_entry_skips,
            missing_exit_fallbacks=self.missing_exit_fallbacks,
            incomplete_end_discards=self.incomplete_end_discards,
            financing_events=self.financing_events,
            financing_costs=round(self.financing_costs, 6),
            gap_stop_fills=self.gap_stop_fills,
            account_ruined=self.account_ruined,
            ruin_time=self.ruin_time.isoformat() if self.ruin_time else None,
            exit_reasons=dict(self.exit_reasons),
            monthly_net={key: round(value, 6) for key, value in sorted(self.monthly_net.items())},
            yearly_net={key: round(value, 6) for key, value in sorted(self.yearly_net.items())},
            first_candle=self.first_candle.isoformat() if self.first_candle else None,
            last_candle=self.last_candle.isoformat() if self.last_candle else None,
            parameters=asdict(self.params),
        )
