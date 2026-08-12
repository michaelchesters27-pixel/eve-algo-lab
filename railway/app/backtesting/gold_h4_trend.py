from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from math import floor
from typing import Any, Literal

from app.backtesting.fixed_ladder_v261 import Candle, PathMode


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class GoldH4TrendParameters:
    entry_lookback_h4: int = 55
    exit_lookback_h4: int = 20
    daily_trend_lookback: int = 60
    atr_period_h4: int = 20
    atr_multiplier: float = 2.0
    risk_percent: float = 0.25
    minimum_lot: float = 0.01
    lot_step: float = 0.01
    maximum_lot: float = 1.0
    spread_price: float = 0.05
    commission_per_001_lot: float = 0.08
    slippage_price: float = 0.0
    money_per_price_per_001_lot: float = 1.0
    overnight_long_cost_per_001_lot: float = 0.70
    overnight_short_cost_per_001_lot: float = 0.70
    triple_swap_weekday: int = 2
    path_mode: PathMode = "candle_direction"

    def validate(self) -> None:
        if self.entry_lookback_h4 < 2:
            raise ValueError("H4 entry lookback must be at least two bars")
        if self.exit_lookback_h4 < 2:
            raise ValueError("H4 exit lookback must be at least two bars")
        if self.daily_trend_lookback < 2:
            raise ValueError("Daily trend lookback must be at least two bars")
        if self.atr_period_h4 < 2:
            raise ValueError("H4 ATR period must be at least two bars")
        if self.atr_multiplier <= 0:
            raise ValueError("ATR multiplier must be greater than zero")
        if not 0.01 <= self.risk_percent <= 5:
            raise ValueError("Risk percent must be between 0.01 and 5")
        if self.minimum_lot <= 0 or self.lot_step <= 0 or self.maximum_lot <= 0:
            raise ValueError("Lot sizes and lot step must be greater than zero")
        if self.minimum_lot > self.maximum_lot:
            raise ValueError("Minimum lot cannot exceed maximum lot")
        if self.path_mode not in {"candle_direction", "open_high_low_close", "open_low_high_close"}:
            raise ValueError("Unsupported intrabar path mode")
        if not 0 <= self.triple_swap_weekday <= 6:
            raise ValueError("Triple-swap weekday must be between zero and six")
        for name in (
            "spread_price",
            "commission_per_001_lot",
            "slippage_price",
            "money_per_price_per_001_lot",
            "overnight_long_cost_per_001_lot",
            "overnight_short_cost_per_001_lot",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.money_per_price_per_001_lot <= 0:
            raise ValueError("Money per price move must be greater than zero")


@dataclass(frozen=True)
class TrendBarEvent:
    event_time: datetime
    h4_bar_time: datetime
    h4_close: float
    raw_breakout_side: Side | None
    entry_side: Side | None
    atr_h4: float
    entry_channel_high: float
    entry_channel_low: float
    exit_channel_high: float
    exit_channel_low: float
    daily_close: float | None
    daily_reference_close: float | None


@dataclass(frozen=True)
class GoldTrendSignal:
    side: Side
    event_time: datetime
    h4_bar_time: datetime
    signal_close: float
    atr_h4: float
    entry_channel_high: float
    entry_channel_low: float
    daily_close: float
    daily_reference_close: float


@dataclass
class GoldTrendPosition:
    position_id: str
    basket_id: str
    side: Side
    opened_at: datetime
    entry_price: float
    entry_mid: float
    lot_size: float
    stop_mid: float
    planned_risk_money: float
    signal: GoldTrendSignal
    balance_at_entry: float
    financing_costs: float = 0.0


@dataclass
class GoldTrendCompletedTrade:
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
    commission: float
    financing_costs: float
    net_pnl: float
    peak_floating: float
    worst_floating: float
    exit_reason: str
    signal: GoldTrendSignal
    planned_risk_money: float

    @property
    def costs(self) -> float:
        return self.commission + self.financing_costs

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
            "strategy": "gold_h4_trend",
            "strategy_version": "1.0",
            "signal_time": self.signal.event_time.isoformat(),
            "h4_bar_time": self.signal.h4_bar_time.isoformat(),
            "signal_close": round(self.signal.signal_close, 10),
            "entry_channel_high": round(self.signal.entry_channel_high, 10),
            "entry_channel_low": round(self.signal.entry_channel_low, 10),
            "daily_close": round(self.signal.daily_close, 10),
            "daily_reference_close": round(self.signal.daily_reference_close, 10),
            "atr_h4": round(self.signal.atr_h4, 10),
            "planned_risk_money": round(self.planned_risk_money, 6),
            "overnight_financing": round(self.financing_costs, 6),
            "entry_protocol": "completed H4 55-bar breakout with matching 60-trading-day direction; entry at first available M1 open",
            "exit_protocol": "hard 2x H4 ATR stop or completed H4 close through the opposite 20-bar channel",
        }


@dataclass
class GoldTrendSimulationSummary:
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
    h4_events_processed: int
    raw_breakouts: int
    daily_filter_rejections: int
    signals_detected: int
    signals_filtered: int
    risk_size_skips: int
    channel_exits: int
    gap_stop_fills: int
    overnight_rollovers: int
    financing_costs: float
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


def _normalise_candles(candles: list[Candle]) -> list[Candle]:
    return sorted(candles, key=lambda item: item.candle_time)


def _true_range(current: Candle, previous: Candle) -> float:
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def build_trend_events(
    h4_candles: list[Candle],
    daily_candles: list[Candle],
    parameters: GoldH4TrendParameters,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[TrendBarEvent]:
    """Build completed-bar decisions without using any future candle.

    Twelve Data timestamps identify the start of H4 and D1 candles. An H4
    decision therefore becomes tradable four hours later, and a daily close
    becomes available one day after its stored start timestamp.
    """

    parameters.validate()
    h4 = _normalise_candles(h4_candles)
    daily = _normalise_candles(daily_candles)
    if not h4 or not daily:
        return []

    daily_completion_times = [item.candle_time + timedelta(days=1) for item in daily]
    warmup = max(parameters.entry_lookback_h4, parameters.exit_lookback_h4, parameters.atr_period_h4)
    events: list[TrendBarEvent] = []

    for index in range(warmup, len(h4)):
        current = h4[index]
        event_time = current.candle_time + timedelta(hours=4)
        if date_from is not None and event_time < date_from:
            continue
        if date_to is not None and event_time > date_to:
            break

        entry_window = h4[index - parameters.entry_lookback_h4 : index]
        exit_window = h4[index - parameters.exit_lookback_h4 : index]
        entry_high = max(item.high for item in entry_window)
        entry_low = min(item.low for item in entry_window)
        exit_high = max(item.high for item in exit_window)
        exit_low = min(item.low for item in exit_window)

        raw_side: Side | None = None
        if current.close > entry_high:
            raw_side = "buy"
        elif current.close < entry_low:
            raw_side = "sell"

        daily_index = bisect_right(daily_completion_times, event_time) - 1
        daily_close: float | None = None
        daily_reference: float | None = None
        daily_side: Side | None = None
        if daily_index >= parameters.daily_trend_lookback:
            daily_close = daily[daily_index].close
            daily_reference = daily[daily_index - parameters.daily_trend_lookback].close
            if daily_close > daily_reference:
                daily_side = "buy"
            elif daily_close < daily_reference:
                daily_side = "sell"

        atr_start = index - parameters.atr_period_h4 + 1
        true_ranges = [_true_range(h4[position], h4[position - 1]) for position in range(atr_start, index + 1)]
        atr_h4 = sum(true_ranges) / len(true_ranges)
        entry_side = raw_side if raw_side is not None and raw_side == daily_side else None
        events.append(
            TrendBarEvent(
                event_time=event_time,
                h4_bar_time=current.candle_time,
                h4_close=current.close,
                raw_breakout_side=raw_side,
                entry_side=entry_side,
                atr_h4=atr_h4,
                entry_channel_high=entry_high,
                entry_channel_low=entry_low,
                exit_channel_high=exit_high,
                exit_channel_low=exit_low,
                daily_close=daily_close,
                daily_reference_close=daily_reference,
            )
        )
    return events


class GoldH4TrendBacktester:
    """H4/D1 trend decisions with M1 execution, gap and stop replay."""

    EPS = 1e-9

    def __init__(
        self,
        starting_balance: float,
        parameters: GoldH4TrendParameters,
        events: list[TrendBarEvent],
    ) -> None:
        if starting_balance <= 0:
            raise ValueError("Starting balance must be greater than zero")
        parameters.validate()
        self.params = parameters
        self.events = sorted(events, key=lambda item: item.event_time)
        self._event_index = 0
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self._equity_peak = float(starting_balance)
        self.max_equity_drawdown = 0.0
        self.max_equity_drawdown_percent = 0.0

        self.position: GoldTrendPosition | None = None
        self._last_mid: float | None = None
        self._last_candle_date: date | None = None
        self._sequence = 0
        self._trade_peak_floating = 0.0
        self._trade_worst_floating = 0.0

        self.completed_trades: list[GoldTrendCompletedTrade] = []
        self.completed_baskets: list[GoldTrendCompletedTrade] = []
        self.position_pnls: list[float] = []
        self.basket_pnls: list[float] = []
        self.exit_reasons: Counter[str] = Counter()
        self.monthly_net: defaultdict[str, float] = defaultdict(float)
        self.yearly_net: defaultdict[str, float] = defaultdict(float)
        self.candles_processed = 0
        self.h4_events_processed = 0
        self.raw_breakouts = 0
        self.daily_filter_rejections = 0
        self.signals_detected = 0
        self.signals_filtered = 0
        self.risk_size_skips = 0
        self.channel_exits = 0
        self.gap_stop_fills = 0
        self.overnight_rollovers = 0
        self.financing_costs = 0.0
        self.first_candle: datetime | None = None
        self.last_candle: datetime | None = None
        self.account_ruined = False
        self.ruin_time: datetime | None = None

    @property
    def half_spread(self) -> float:
        return self.params.spread_price / 2.0

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

    def _position_cash_change(self, mid: float) -> float:
        if self.position is None:
            return 0.0
        exit_price = self._exit_price(self.position.side, mid)
        factor = self._factor(self.position.lot_size)
        gross = (
            (exit_price - self.position.entry_price) * factor
            if self.position.side == "buy"
            else (self.position.entry_price - exit_price) * factor
        )
        return gross - self._commission(self.position.lot_size)

    def position_net(self, mid: float) -> float:
        if self.position is None:
            return 0.0
        return self._position_cash_change(mid) - self.position.financing_costs

    def _threshold_mid(self, cash_change: float) -> float:
        if self.position is None:
            raise RuntimeError("Cannot calculate a threshold without an open trend trade")
        factor = self._factor(self.position.lot_size)
        required_gross = cash_change + self._commission(self.position.lot_size)
        if self.position.side == "buy":
            exit_price = self.position.entry_price + required_gross / factor
            return exit_price + self.half_spread + self.params.slippage_price
        exit_price = self.position.entry_price - required_gross / factor
        return exit_price - self.half_spread - self.params.slippage_price

    def _update_extremes(self, mid: float) -> None:
        equity = max(0.0, self.balance + self._position_cash_change(mid))
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

    def _open_from_event(self, event: TrendBarEvent, at: datetime, mid: float) -> bool:
        side = event.entry_side
        if side is None or self.position is not None or self.account_ruined:
            return False
        if event.daily_close is None or event.daily_reference_close is None or event.atr_h4 <= self.EPS:
            self.signals_filtered += 1
            return False

        entry_price = self._entry_price(side, mid)
        stop_distance = event.atr_h4 * self.params.atr_multiplier
        stop_mid = mid - stop_distance if side == "buy" else mid + stop_distance
        stop_exit = self._exit_price(side, stop_mid)
        price_risk = entry_price - stop_exit if side == "buy" else stop_exit - entry_price
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
        self._sequence += 1
        signal = GoldTrendSignal(
            side=side,
            event_time=event.event_time,
            h4_bar_time=event.h4_bar_time,
            signal_close=event.h4_close,
            atr_h4=event.atr_h4,
            entry_channel_high=event.entry_channel_high,
            entry_channel_low=event.entry_channel_low,
            daily_close=event.daily_close,
            daily_reference_close=event.daily_reference_close,
        )
        self.position = GoldTrendPosition(
            position_id=f"GOLD-H4-POS-{self._sequence:08d}",
            basket_id=f"GOLD-H4-TRADE-{self._sequence:08d}",
            side=side,
            opened_at=at,
            entry_price=entry_price,
            entry_mid=mid,
            lot_size=lot_size,
            stop_mid=stop_mid,
            planned_risk_money=planned_risk,
            signal=signal,
            balance_at_entry=self.balance,
        )
        opening_floating = self.position_net(mid)
        self._trade_peak_floating = opening_floating
        self._trade_worst_floating = opening_floating
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
        cash_change = gross - commission
        costs = commission + position.financing_costs
        net = gross - costs
        if reason == "ACCOUNT RUIN LIMIT" or self.balance + cash_change <= self.EPS:
            reason = "ACCOUNT RUIN LIMIT"
            net = -position.balance_at_entry
            gross = net + costs
            self.balance = 0.0
            self.account_ruined = True
            self.ruin_time = at
        else:
            self.balance += cash_change

        completed = GoldTrendCompletedTrade(
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
            commission=commission,
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
        self.monthly_net[at.strftime("%Y-%m")] += net
        self.yearly_net[at.strftime("%Y")] += net
        self.position = None
        self._trade_peak_floating = 0.0
        self._trade_worst_floating = 0.0
        self._update_extremes(mid)

    def _apply_overnight_cost(self, rollover_date: date, at: datetime, mid: float) -> None:
        position = self.position
        if position is None or rollover_date.weekday() > 3:
            return
        rate = (
            self.params.overnight_long_cost_per_001_lot
            if position.side == "buy"
            else self.params.overnight_short_cost_per_001_lot
        )
        multiplier = 3 if rollover_date.weekday() == self.params.triple_swap_weekday else 1
        cost = rate * (position.lot_size / 0.01) * multiplier
        if cost <= self.EPS:
            return
        charged = min(self.balance, cost)
        self.balance -= charged
        position.financing_costs += charged
        self.financing_costs += charged
        self.overnight_rollovers += 1
        self._update_extremes(mid)
        if self.balance + self._position_cash_change(mid) <= self.EPS:
            self._close_position(at, mid, "ACCOUNT RUIN LIMIT")

    def _apply_crossed_rollovers(self, current_date: date, at: datetime, mid: float) -> None:
        if self._last_candle_date is None or current_date <= self._last_candle_date:
            self._last_candle_date = current_date
            return
        rollover_date = self._last_candle_date
        while rollover_date < current_date and self.position is not None:
            self._apply_overnight_cost(rollover_date, at, mid)
            rollover_date += timedelta(days=1)
        self._last_candle_date = current_date

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
        if gap and self._position_cash_change(target) <= -self.balance + self.EPS:
            self._update_extremes(target)
            self._close_position(at, target, "ACCOUNT RUIN LIMIT")
            return target

        events: list[tuple[float, str]] = []
        if self._crosses(current, target, position.stop_mid):
            events.append((position.stop_mid, "2 ATR STOP"))
        if self._crosses(current, target, ruin_mid):
            events.append((ruin_mid, "ACCOUNT RUIN LIMIT"))
        if not events:
            self._update_extremes(target)
            return target
        up = target > current
        event_mid, reason = min(events, key=lambda item: item[0]) if up else max(events, key=lambda item: item[0])
        fill_mid = target if gap else event_mid
        if gap and reason == "2 ATR STOP":
            self.gap_stop_fills += 1
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

    def _process_due_events(self, at: datetime, mid: float) -> None:
        while self._event_index < len(self.events) and self.events[self._event_index].event_time <= at:
            event = self.events[self._event_index]
            self._event_index += 1
            self.h4_events_processed += 1
            if event.raw_breakout_side is not None:
                self.raw_breakouts += 1
                if event.entry_side is None:
                    self.daily_filter_rejections += 1

            if self.position is not None:
                channel_exit = (
                    self.position.side == "buy" and event.h4_close < event.exit_channel_low
                ) or (
                    self.position.side == "sell" and event.h4_close > event.exit_channel_high
                )
                if channel_exit:
                    self.channel_exits += 1
                    self._close_position(at, mid, "20-H4 CHANNEL EXIT")

            if event.entry_side is not None:
                self.signals_detected += 1
                if self.position is None:
                    self._open_from_event(event, at, mid)
                else:
                    self.signals_filtered += 1

    def process_candle(self, candle: Candle) -> None:
        if self.account_ruined:
            return
        if self.first_candle is None:
            self.first_candle = candle.candle_time
        self.last_candle = candle.candle_time
        self.candles_processed += 1

        self._apply_crossed_rollovers(candle.candle_time.date(), candle.candle_time, candle.open)
        if self.account_ruined:
            return

        current = candle.open
        if self.position is not None and self._last_mid is not None and abs(candle.open - self._last_mid) > self.EPS:
            self._process_segment(self._last_mid, candle.open, candle.candle_time, gap=True)
        self._process_due_events(candle.candle_time, candle.open)

        path = self._path(candle)
        current = path[0]
        for target in path[1:]:
            current = self._process_segment(current, target, candle.candle_time)
        self._last_mid = candle.close
        self._update_extremes(candle.close)

    def drain_trades(self) -> list[GoldTrendCompletedTrade]:
        rows = self.completed_trades
        self.completed_trades = []
        return rows

    def drain_baskets(self) -> list[GoldTrendCompletedTrade]:
        rows = self.completed_baskets
        self.completed_baskets = []
        return rows

    def finalise(self) -> tuple[list[GoldTrendCompletedTrade], list[GoldTrendCompletedTrade]]:
        if self.position is not None and self.last_candle is not None and self._last_mid is not None:
            self._close_position(self.last_candle, self._last_mid, "END OF TEST")
        return self.drain_trades(), self.drain_baskets()

    def summary(self) -> GoldTrendSimulationSummary:
        wins = sum(value > 0 for value in self.basket_pnls)
        losses = sum(value < 0 for value in self.basket_pnls)
        return GoldTrendSimulationSummary(
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
            h4_events_processed=self.h4_events_processed,
            raw_breakouts=self.raw_breakouts,
            daily_filter_rejections=self.daily_filter_rejections,
            signals_detected=self.signals_detected,
            signals_filtered=self.signals_filtered,
            risk_size_skips=self.risk_size_skips,
            channel_exits=self.channel_exits,
            gap_stop_fills=self.gap_stop_fills,
            overnight_rollovers=self.overnight_rollovers,
            financing_costs=round(self.financing_costs, 6),
            account_ruined=self.account_ruined,
            ruin_time=self.ruin_time.isoformat() if self.ruin_time else None,
            exit_reasons=dict(self.exit_reasons),
            monthly_net={key: round(value, 6) for key, value in sorted(self.monthly_net.items())},
            yearly_net={key: round(value, 6) for key, value in sorted(self.yearly_net.items())},
            first_candle=self.first_candle.isoformat() if self.first_candle else None,
            last_candle=self.last_candle.isoformat() if self.last_candle else None,
            parameters=asdict(self.params),
        )
