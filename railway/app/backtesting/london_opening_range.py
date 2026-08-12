from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from math import floor
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.backtesting.fixed_ladder_v261 import Candle, PathMode


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class LondonOpeningRangeParameters:
    timezone_name: str = "Europe/London"
    range_start_hour: int = 8
    range_start_minute: int = 0
    range_minutes: int = 30
    entry_cutoff_hour: int = 11
    entry_cutoff_minute: int = 30
    force_exit_hour: int = 16
    force_exit_minute: int = 0
    breakout_buffer_fraction: float = 0.10
    reward_risk: float = 2.0
    risk_percent: float = 0.25
    minimum_lot: float = 0.01
    lot_step: float = 0.01
    maximum_lot: float = 1.0
    spread_price: float = 0.05
    commission_per_001_lot: float = 0.08
    slippage_price: float = 0.0
    money_per_price_per_001_lot: float = 1.0
    path_mode: PathMode = "candle_direction"

    @property
    def range_start_total_minutes(self) -> int:
        return self.range_start_hour * 60 + self.range_start_minute

    @property
    def range_end_total_minutes(self) -> int:
        return self.range_start_total_minutes + self.range_minutes

    @property
    def entry_cutoff_total_minutes(self) -> int:
        return self.entry_cutoff_hour * 60 + self.entry_cutoff_minute

    @property
    def force_exit_total_minutes(self) -> int:
        return self.force_exit_hour * 60 + self.force_exit_minute

    def validate(self) -> None:
        if self.timezone_name != "Europe/London":
            raise ValueError("London Opening Range v1 requires Europe/London time")
        for label, hour in (
            ("range start", self.range_start_hour),
            ("entry cutoff", self.entry_cutoff_hour),
            ("force exit", self.force_exit_hour),
        ):
            if not 0 <= hour <= 23:
                raise ValueError(f"{label} hour must be between 0 and 23")
        for label, minute in (
            ("range start", self.range_start_minute),
            ("entry cutoff", self.entry_cutoff_minute),
            ("force exit", self.force_exit_minute),
        ):
            if minute not in range(0, 60, 5):
                raise ValueError(f"{label} minute must align to a five-minute boundary")
        if self.range_minutes < 5 or self.range_minutes % 5:
            raise ValueError("Opening range duration must be a positive multiple of five minutes")
        if not self.range_end_total_minutes < self.entry_cutoff_total_minutes:
            raise ValueError("Entry cutoff must be after the opening range")
        if not self.entry_cutoff_total_minutes < self.force_exit_total_minutes:
            raise ValueError("Force exit must be after the entry cutoff")
        if not 0 <= self.breakout_buffer_fraction <= 2:
            raise ValueError("Breakout buffer fraction must be between 0 and 2")
        if not 0.1 <= self.reward_risk <= 20:
            raise ValueError("Reward-to-risk multiple must be between 0.1 and 20")
        if not 0.01 <= self.risk_percent <= 5:
            raise ValueError("Risk percent must be between 0.01 and 5")
        if self.minimum_lot <= 0 or self.lot_step <= 0 or self.maximum_lot <= 0:
            raise ValueError("Lot sizes and lot step must be greater than zero")
        if self.minimum_lot > self.maximum_lot:
            raise ValueError("Minimum lot cannot exceed maximum lot")
        if self.path_mode not in {"candle_direction", "open_high_low_close", "open_low_high_close"}:
            raise ValueError("Unsupported intrabar path mode")
        for name in (
            "spread_price",
            "commission_per_001_lot",
            "slippage_price",
            "money_per_price_per_001_lot",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.money_per_price_per_001_lot <= 0:
            raise ValueError("Money per price move must be greater than zero")


@dataclass
class FiveMinuteBar:
    candle_time: datetime
    open: float
    high: float
    low: float
    close: float
    m1_count: int = 1

    def add(self, candle: Candle) -> None:
        self.high = max(self.high, candle.high)
        self.low = min(self.low, candle.low)
        self.close = candle.close
        self.m1_count += 1


@dataclass(frozen=True)
class LondonSignal:
    side: Side
    signal_time: datetime
    session_date: str
    range_high: float
    range_low: float
    range_midpoint: float
    breakout_threshold: float
    signal_close: float


@dataclass
class LondonPosition:
    position_id: str
    basket_id: str
    side: Side
    opened_at: datetime
    entry_price: float
    lot_size: float
    stop_mid: float
    target_mid: float
    planned_risk_money: float
    planned_reward_money: float
    signal: LondonSignal


@dataclass
class LondonCompletedTrade:
    basket_id: str
    position_id: str
    side: Side
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    exit_price: float
    stop_mid: float
    target_mid: float
    lot_size: float
    gross_pnl: float
    costs: float
    net_pnl: float
    peak_floating: float
    worst_floating: float
    exit_reason: str
    signal: LondonSignal
    planned_risk_money: float
    planned_reward_money: float

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
            "take_profit": round(self.target_mid, 10),
            "lot_size": round(self.lot_size, 6),
            "gross_pnl": round(self.gross_pnl, 6),
            "costs": round(self.costs, 6),
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
            "costs": round(self.costs, 6),
            "net_pnl": round(self.net_pnl, 6),
            "peak_floating": round(self.peak_floating, 6),
            "worst_floating": round(self.worst_floating, 6),
            "max_positions": 1,
            "exit_reason": self.exit_reason,
            "metadata": self._metadata(),
        }

    def _metadata(self) -> dict[str, Any]:
        return {
            "strategy": "london_opening_range",
            "strategy_version": "1.0",
            "session_date": self.signal.session_date,
            "signal_time": self.signal.signal_time.isoformat(),
            "range_high": round(self.signal.range_high, 10),
            "range_low": round(self.signal.range_low, 10),
            "range_midpoint": round(self.signal.range_midpoint, 10),
            "breakout_threshold": round(self.signal.breakout_threshold, 10),
            "signal_close": round(self.signal.signal_close, 10),
            "planned_risk_money": round(self.planned_risk_money, 6),
            "planned_reward_money": round(self.planned_reward_money, 6),
            "entry_protocol": "first confirmed M5 close beyond the 08:00-08:30 London opening range; entry at next M5 open",
        }


@dataclass
class LondonSimulationSummary:
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
    ambiguous_candles: int
    candles_processed: int
    signals_detected: int
    signals_filtered: int
    sessions_seen: int
    sessions_with_complete_range: int
    sessions_traded: int
    risk_size_skips: int
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


class LondonOpeningRangeBacktester:
    """M5 London opening-range signals with M1 execution replay.

    Six completed M5 bars form the 08:00-08:30 Europe/London range. The
    first directional M5 close beyond the configured buffer creates a signal,
    and entry waits for the following M5 open. Only one risk-sized position is
    permitted per London date. M1 OHLC paths model stop and target ordering.
    """

    EPS = 1e-9

    def __init__(self, starting_balance: float, parameters: LondonOpeningRangeParameters) -> None:
        if starting_balance <= 0:
            raise ValueError("Starting balance must be greater than zero")
        parameters.validate()
        self.params = parameters
        self.timezone = ZoneInfo(parameters.timezone_name)
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self._equity_peak = float(starting_balance)
        self.max_equity_drawdown = 0.0
        self.max_equity_drawdown_percent = 0.0

        self.position: LondonPosition | None = None
        self._pending_signal: LondonSignal | None = None
        self._m5: FiveMinuteBar | None = None
        self._session_date: date | None = None
        self._range_high: float | None = None
        self._range_low: float | None = None
        self._range_bars = 0
        self._range_counted = False
        self._day_signal_consumed = False
        self._last_mid: float | None = None
        self._sequence = 0
        self._trade_peak_floating = 0.0
        self._trade_worst_floating = 0.0

        self.completed_trades: list[LondonCompletedTrade] = []
        self.completed_baskets: list[LondonCompletedTrade] = []
        self.position_pnls: list[float] = []
        self.basket_pnls: list[float] = []
        self.exit_reasons: Counter[str] = Counter()
        self.monthly_net: defaultdict[str, float] = defaultdict(float)
        self.yearly_net: defaultdict[str, float] = defaultdict(float)
        self.signals_detected = 0
        self.signals_filtered = 0
        self.sessions_seen = 0
        self.sessions_with_complete_range = 0
        self.sessions_traded = 0
        self.risk_size_skips = 0
        self.ambiguous_candles = 0
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

    @staticmethod
    def _minute_of_day(at: datetime) -> int:
        return at.hour * 60 + at.minute

    @staticmethod
    def _bucket_start(at: datetime) -> datetime:
        return at.replace(minute=(at.minute // 5) * 5, second=0, microsecond=0)

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
        if self.position.side == "buy":
            gross = (exit_price - self.position.entry_price) * factor
        else:
            gross = (self.position.entry_price - exit_price) * factor
        return gross - self._commission(self.position.lot_size)

    def _threshold_mid(self, net_money: float) -> float:
        if self.position is None:
            raise RuntimeError("Cannot calculate a threshold without an open London trade")
        factor = self._factor(self.position.lot_size)
        required_gross = net_money + self._commission(self.position.lot_size)
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
        self._range_high = None
        self._range_low = None
        self._range_bars = 0
        self._range_counted = False
        self._day_signal_consumed = False
        self._pending_signal = None
        self._m5 = None
        self.sessions_seen += 1

    def _finalise_m5(self) -> None:
        bar = self._m5
        if bar is None or self.account_ruined:
            return
        local = self._local(bar.candle_time)
        minute = self._minute_of_day(local)
        session_date = local.date()
        if session_date != self._session_date:
            return
        # Never invent a signal from an incomplete M5 candle. The stored M1
        # history is normally complete, but this guard makes any data gap
        # fail closed instead of changing the strategy silently.
        if bar.m1_count != 5:
            return

        if self.params.range_start_total_minutes <= minute < self.params.range_end_total_minutes:
            self._range_high = bar.high if self._range_high is None else max(self._range_high, bar.high)
            self._range_low = bar.low if self._range_low is None else min(self._range_low, bar.low)
            self._range_bars += 1
            required = self.params.range_minutes // 5
            if self._range_bars >= required and not self._range_counted:
                self._range_counted = True
                self.sessions_with_complete_range += 1
            return

        if not self.params.range_end_total_minutes <= minute < self.params.entry_cutoff_total_minutes:
            return
        if (
            not self._range_counted
            or self._range_high is None
            or self._range_low is None
            or self._day_signal_consumed
            or self.position is not None
            or self._pending_signal is not None
        ):
            return
        width = self._range_high - self._range_low
        if width <= self.EPS:
            self.signals_filtered += 1
            return
        buffer = width * self.params.breakout_buffer_fraction
        buy_threshold = self._range_high + buffer
        sell_threshold = self._range_low - buffer
        side: Side | None = None
        threshold = 0.0
        if bar.close >= buy_threshold and bar.close > bar.open:
            side = "buy"
            threshold = buy_threshold
        elif bar.close <= sell_threshold and bar.close < bar.open:
            side = "sell"
            threshold = sell_threshold
        if side is None:
            return

        self.signals_detected += 1
        self._day_signal_consumed = True
        midpoint = (self._range_high + self._range_low) / 2.0
        self._pending_signal = LondonSignal(
            side=side,
            signal_time=bar.candle_time + timedelta(minutes=5),
            session_date=session_date.isoformat(),
            range_high=self._range_high,
            range_low=self._range_low,
            range_midpoint=midpoint,
            breakout_threshold=threshold,
            signal_close=bar.close,
        )

    def _open_pending(self, at: datetime, mid: float) -> bool:
        signal = self._pending_signal
        self._pending_signal = None
        if signal is None or self.position is not None or self.account_ruined:
            return False
        local = self._local(at)
        if local.date().isoformat() != signal.session_date or self._minute_of_day(local) > self.params.entry_cutoff_total_minutes:
            self.signals_filtered += 1
            return False

        entry_price = self._entry_price(signal.side, mid)
        stop_exit = self._exit_price(signal.side, signal.range_midpoint)
        price_risk = entry_price - stop_exit if signal.side == "buy" else stop_exit - entry_price
        if price_risk <= self.EPS:
            self.signals_filtered += 1
            return False
        risk_per_001 = price_risk * self.params.money_per_price_per_001_lot + self.params.commission_per_001_lot
        risk_budget = self.balance * self.params.risk_percent / 100.0
        raw_lot = risk_budget / risk_per_001 * 0.01
        lot_size = floor((raw_lot + self.EPS) / self.params.lot_step) * self.params.lot_step
        lot_size = min(lot_size, self.params.maximum_lot)
        if lot_size + self.EPS < self.params.minimum_lot:
            self.signals_filtered += 1
            self.risk_size_skips += 1
            return False

        planned_risk = risk_per_001 * (lot_size / 0.01)
        planned_reward = planned_risk * self.params.reward_risk
        self._sequence += 1
        self.position = LondonPosition(
            position_id=f"LONDON-POS-{self._sequence:08d}",
            basket_id=f"LONDON-TRADE-{self._sequence:08d}",
            side=signal.side,
            opened_at=at,
            entry_price=entry_price,
            lot_size=lot_size,
            stop_mid=signal.range_midpoint,
            target_mid=0.0,
            planned_risk_money=planned_risk,
            planned_reward_money=planned_reward,
            signal=signal,
        )
        self.position.target_mid = self._threshold_mid(planned_reward)
        opening_floating = self.position_net(mid)
        self._trade_peak_floating = opening_floating
        self._trade_worst_floating = opening_floating
        self.sessions_traded += 1
        self._update_extremes(mid)
        if opening_floating <= -self.balance + self.EPS:
            self._close_position(at, mid, "ACCOUNT RUIN LIMIT")
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
        costs = self._commission(position.lot_size)
        net = gross - costs
        if reason == "ACCOUNT RUIN LIMIT" or net <= -self.balance + self.EPS:
            reason = "ACCOUNT RUIN LIMIT"
            net = -self.balance
            gross = net + costs
            self.balance = 0.0
            self.account_ruined = True
            self.ruin_time = at
        else:
            self.balance += net
        completed = LondonCompletedTrade(
            basket_id=position.basket_id,
            position_id=position.position_id,
            side=position.side,
            opened_at=position.opened_at,
            closed_at=at,
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_mid=position.stop_mid,
            target_mid=position.target_mid,
            lot_size=position.lot_size,
            gross_pnl=gross,
            costs=costs,
            net_pnl=net,
            peak_floating=self._trade_peak_floating,
            worst_floating=self._trade_worst_floating,
            exit_reason=reason,
            signal=position.signal,
            planned_risk_money=position.planned_risk_money,
            planned_reward_money=position.planned_reward_money,
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
            self._update_extremes(ruin_mid)
            self._close_position(at, ruin_mid, "ACCOUNT RUIN LIMIT")
            return target

        events: list[tuple[float, str]] = []
        if self._crosses(current, target, ruin_mid):
            events.append((ruin_mid, "ACCOUNT RUIN LIMIT"))
        if self._crosses(current, target, position.stop_mid):
            events.append((position.stop_mid, "STOP LOSS"))
        if self._crosses(current, target, position.target_mid):
            events.append((position.target_mid, "TAKE PROFIT 2R"))
        if not events:
            self._update_extremes(target)
            return target
        up = target > current
        event_mid, reason = min(events, key=lambda item: item[0]) if up else max(events, key=lambda item: item[0])
        fill_mid = event_mid if reason == "ACCOUNT RUIN LIMIT" else (target if gap else event_mid)
        self._update_extremes(fill_mid)
        self._close_position(at, fill_mid, reason)
        return target

    def _path(self, candle: Candle) -> list[float]:
        if self.params.path_mode == "open_high_low_close":
            return [candle.open, candle.high, candle.low, candle.close]
        if self.params.path_mode == "open_low_high_close":
            return [candle.open, candle.low, candle.high, candle.close]
        if candle.close >= candle.open:
            return [candle.open, candle.low, candle.high, candle.close]
        return [candle.open, candle.high, candle.low, candle.close]

    def _bar_is_ambiguous(self, candle: Candle) -> bool:
        if self.position is None:
            return False
        stop = self.position.stop_mid
        target = self.position.target_mid
        return candle.low <= stop <= candle.high and candle.low <= target <= candle.high

    def _start_or_add_m5(self, candle: Candle) -> None:
        bucket = self._bucket_start(candle.candle_time)
        if self._m5 is None:
            self._m5 = FiveMinuteBar(bucket, candle.open, candle.high, candle.low, candle.close)
        else:
            self._m5.add(candle)

    def process_candle(self, candle: Candle) -> None:
        if self.first_candle is None:
            self.first_candle = candle.candle_time
        self.last_candle = candle.candle_time
        self.candles_processed += 1
        local = self._local(candle.candle_time)
        session_date = local.date()

        if self._session_date != session_date:
            if self.position is not None:
                self._close_position(candle.candle_time, candle.open, "SESSION FORCE EXIT GAP")
            self._reset_session(session_date)
            self._last_mid = None

        bucket = self._bucket_start(candle.candle_time)
        if self._m5 is not None and bucket != self._m5.candle_time:
            self._finalise_m5()
            self._m5 = None

        opened = self._open_pending(candle.candle_time, candle.open)
        path = self._path(candle)
        current = path[0] if opened or self._last_mid is None else self._last_mid
        if not opened and self.position is not None and abs(path[0] - current) > self.EPS:
            current = self._process_segment(current, path[0], candle.candle_time, gap=True)

        if self.position is not None and self._minute_of_day(local) >= self.params.force_exit_total_minutes:
            self._close_position(candle.candle_time, candle.open, "SESSION FORCE EXIT")

        if self.position is not None and self._bar_is_ambiguous(candle):
            self.ambiguous_candles += 1
        for target in path[1:]:
            current = self._process_segment(current, target, candle.candle_time)

        self._last_mid = candle.close
        self._update_extremes(candle.close)
        self._start_or_add_m5(candle)

    def drain_trades(self) -> list[LondonCompletedTrade]:
        rows = self.completed_trades
        self.completed_trades = []
        return rows

    def drain_baskets(self) -> list[LondonCompletedTrade]:
        rows = self.completed_baskets
        self.completed_baskets = []
        return rows

    def finalise(self) -> tuple[list[LondonCompletedTrade], list[LondonCompletedTrade]]:
        if self.position is not None and self.last_candle is not None and self._last_mid is not None:
            self._close_position(self.last_candle, self._last_mid, "END OF TEST")
        return self.drain_trades(), self.drain_baskets()

    def summary(self) -> LondonSimulationSummary:
        wins = sum(value > 0 for value in self.basket_pnls)
        losses = sum(value < 0 for value in self.basket_pnls)
        return LondonSimulationSummary(
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
            ambiguous_candles=self.ambiguous_candles,
            candles_processed=self.candles_processed,
            signals_detected=self.signals_detected,
            signals_filtered=self.signals_filtered,
            sessions_seen=self.sessions_seen,
            sessions_with_complete_range=self.sessions_with_complete_range,
            sessions_traded=self.sessions_traded,
            risk_size_skips=self.risk_size_skips,
            account_ruined=self.account_ruined,
            ruin_time=self.ruin_time.isoformat() if self.ruin_time else None,
            exit_reasons=dict(self.exit_reasons),
            monthly_net={key: round(value, 6) for key, value in sorted(self.monthly_net.items())},
            yearly_net={key: round(value, 6) for key, value in sorted(self.yearly_net.items())},
            first_candle=self.first_candle.isoformat() if self.first_candle else None,
            last_candle=self.last_candle.isoformat() if self.last_candle else None,
            parameters=asdict(self.params),
        )
