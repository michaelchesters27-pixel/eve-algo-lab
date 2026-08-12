from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from app.backtesting.fixed_ladder_v261 import Candle, PathMode


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class LiquidityBasketParameters:
    positions_per_basket: int = 4
    fixed_lot: float = 0.02
    lookback_candles: int = 20
    trend_period: int = 50
    use_trend_filter: bool = True
    minimum_sweep_price: float = 0.05
    profit_target_money: float = 4.0
    basket_stop_money: float = 8.0
    maximum_hold_minutes: int = 180
    cooldown_candles: int = 5
    spread_price: float = 0.05
    commission_per_001_lot: float = 0.08
    slippage_price: float = 0.0
    money_per_price_per_001_lot: float = 1.0
    path_mode: PathMode = "candle_direction"

    def validate(self) -> None:
        if not 1 <= self.positions_per_basket <= 20:
            raise ValueError("Positions per basket must be between 1 and 20")
        if self.fixed_lot <= 0:
            raise ValueError("Fixed lot must be greater than zero")
        if not 3 <= self.lookback_candles <= 500:
            raise ValueError("Liquidity lookback must be between 3 and 500 candles")
        if not 2 <= self.trend_period <= 1000:
            raise ValueError("Trend period must be between 2 and 1000 candles")
        if self.profit_target_money <= 0:
            raise ValueError("Basket profit target must be greater than zero")
        if self.basket_stop_money <= 0:
            raise ValueError("Basket loss limit must be greater than zero")
        if not 1 <= self.maximum_hold_minutes <= 10_080:
            raise ValueError("Maximum hold must be between 1 minute and 7 days")
        if not 0 <= self.cooldown_candles <= 10_000:
            raise ValueError("Cooldown candles cannot be negative")
        if self.path_mode not in {"candle_direction", "open_high_low_close", "open_low_high_close"}:
            raise ValueError("Unsupported intrabar path mode")
        for name in (
            "minimum_sweep_price",
            "spread_price",
            "commission_per_001_lot",
            "slippage_price",
            "money_per_price_per_001_lot",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class LiquiditySignal:
    side: Side
    signal_time: datetime
    swept_level: float
    signal_close: float
    ema_value: float | None


@dataclass
class LiquidityPosition:
    position_id: str
    basket_id: str
    side: Side
    opened_at: datetime
    entry_price: float
    lot_size: float


@dataclass
class LiquidityCompletedTrade:
    basket_id: str
    position_id: str
    side: Side
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    gross_pnl: float
    costs: float
    net_pnl: float
    exit_reason: str
    signal: LiquiditySignal

    def to_row(self, run_id: str) -> dict[str, Any]:
        return {
            "backtest_run_id": run_id,
            "basket_id": self.basket_id,
            "position_id": self.position_id,
            "side": self.side,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "entry_price": round(self.entry_price, 10),
            "exit_price": round(self.exit_price, 10),
            "stop_loss": round(self.stop_loss, 10),
            "take_profit": round(self.take_profit, 10),
            "lot_size": round(self.lot_size, 6),
            "gross_pnl": round(self.gross_pnl, 6),
            "costs": round(self.costs, 6),
            "net_pnl": round(self.net_pnl, 6),
            "exit_reason": self.exit_reason,
            "metadata": {
                "strategy": "liquidity_basket",
                "strategy_version": "1.0",
                "signal_time": self.signal.signal_time.isoformat(),
                "swept_level": round(self.signal.swept_level, 10),
                "signal_close": round(self.signal.signal_close, 10),
                "ema_value": round(self.signal.ema_value, 10) if self.signal.ema_value is not None else None,
                "entry_protocol": "confirmed M1 liquidity sweep; entry at next candle open",
            },
        }


@dataclass
class LiquidityCompletedBasket:
    basket_id: str
    opened_at: datetime
    closed_at: datetime
    side: Side
    positions: int
    gross_pnl: float
    costs: float
    net_pnl: float
    peak_floating: float
    worst_floating: float
    exit_reason: str
    signal: LiquiditySignal

    def to_row(self, run_id: str) -> dict[str, Any]:
        return {
            "backtest_run_id": run_id,
            "basket_id": self.basket_id,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "side": self.side,
            "positions": self.positions,
            "gross_pnl": round(self.gross_pnl, 6),
            "costs": round(self.costs, 6),
            "net_pnl": round(self.net_pnl, 6),
            "peak_floating": round(self.peak_floating, 6),
            "worst_floating": round(self.worst_floating, 6),
            "max_positions": self.positions,
            "exit_reason": self.exit_reason,
            "metadata": {
                "strategy": "liquidity_basket",
                "strategy_version": "1.0",
                "signal_time": self.signal.signal_time.isoformat(),
                "swept_level": round(self.signal.swept_level, 10),
                "signal_close": round(self.signal.signal_close, 10),
                "ema_value": round(self.signal.ema_value, 10) if self.signal.ema_value is not None else None,
            },
        }


@dataclass
class LiquiditySimulationSummary:
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
    exit_reasons: dict[str, int]
    monthly_net: dict[str, float]
    yearly_net: dict[str, float]
    first_candle: str | None
    last_candle: str | None
    parameters: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiquidityBasketBacktester:
    """Deterministic M1 replay for the four-position liquidity-sweep experiment.

    A signal is created only after a candle has closed. The basket opens at the
    following candle's open, which prevents the replay from using future data.
    OHLC bars still cannot prove the true tick order when both the basket target
    and loss limit are touched in the same minute; those bars are counted as
    ambiguous and resolved with the selected path mode.
    """

    EPS = 1e-9

    def __init__(self, starting_balance: float, parameters: LiquidityBasketParameters) -> None:
        if starting_balance <= 0:
            raise ValueError("Starting balance must be greater than zero")
        parameters.validate()
        self.params = parameters
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self._equity_peak = float(starting_balance)
        self.max_equity_drawdown = 0.0
        self.max_equity_drawdown_percent = 0.0

        self.positions: list[LiquidityPosition] = []
        self.basket_id: str | None = None
        self.basket_opened_at: datetime | None = None
        self.basket_start_balance = self.balance
        self.basket_peak_floating = 0.0
        self.basket_worst_floating = 0.0
        self.basket_signal: LiquiditySignal | None = None
        self._basket_sequence = 0
        self._position_sequence = 0

        self._lookback: deque[Candle] = deque(maxlen=parameters.lookback_candles)
        self._ema: float | None = None
        self._ema_samples = 0
        self._pending_signal: LiquiditySignal | None = None
        self._cooldown_remaining = 0
        self._last_mid: float | None = None

        self.completed_trades: list[LiquidityCompletedTrade] = []
        self.completed_baskets: list[LiquidityCompletedBasket] = []
        self.position_pnls: list[float] = []
        self.basket_pnls: list[float] = []
        self.exit_reasons: Counter[str] = Counter()
        self.monthly_net: defaultdict[str, float] = defaultdict(float)
        self.yearly_net: defaultdict[str, float] = defaultdict(float)
        self.signals_detected = 0
        self.signals_filtered = 0
        self.ambiguous_candles = 0
        self.candles_processed = 0
        self.first_candle: datetime | None = None
        self.last_candle: datetime | None = None

    @property
    def half_spread(self) -> float:
        return self.params.spread_price / 2.0

    @property
    def total_money_factor(self) -> float:
        return (
            self.params.money_per_price_per_001_lot
            * (self.params.fixed_lot / 0.01)
            * self.params.positions_per_basket
        )

    @property
    def total_commission(self) -> float:
        return (
            self.params.commission_per_001_lot
            * (self.params.fixed_lot / 0.01)
            * self.params.positions_per_basket
        )

    def _bid(self, mid: float) -> float:
        return mid - self.half_spread

    def _ask(self, mid: float) -> float:
        return mid + self.half_spread

    def _entry_price(self, side: Side, mid: float) -> float:
        if side == "buy":
            return self._ask(mid) + self.params.slippage_price
        return self._bid(mid) - self.params.slippage_price

    def _exit_price(self, side: Side, mid: float) -> float:
        if side == "buy":
            return self._bid(mid) - self.params.slippage_price
        return self._ask(mid) + self.params.slippage_price

    def basket_net(self, mid: float) -> float:
        if not self.positions:
            return 0.0
        side = self.positions[0].side
        entry = self.positions[0].entry_price
        exit_price = self._exit_price(side, mid)
        if side == "buy":
            gross = (exit_price - entry) * self.total_money_factor
        else:
            gross = (entry - exit_price) * self.total_money_factor
        return gross - self.total_commission

    def equity(self, mid: float) -> float:
        return self.balance + self.basket_net(mid)

    def _update_extremes(self, mid: float) -> None:
        equity = self.equity(mid)
        self._equity_peak = max(self._equity_peak, equity)
        drawdown = self._equity_peak - equity
        self.max_equity_drawdown = max(self.max_equity_drawdown, drawdown)
        if self._equity_peak > 0:
            self.max_equity_drawdown_percent = max(
                self.max_equity_drawdown_percent,
                drawdown / self._equity_peak * 100.0,
            )
        if self.positions:
            floating = self.basket_net(mid)
            self.basket_peak_floating = max(self.basket_peak_floating, floating)
            self.basket_worst_floating = min(self.basket_worst_floating, floating)

    def _threshold_price(self, threshold_money: float) -> float:
        if not self.positions:
            raise RuntimeError("Cannot calculate a basket threshold without open positions")
        side = self.positions[0].side
        entry = self.positions[0].entry_price
        required_gross = threshold_money + self.total_commission
        if side == "buy":
            exit_price = entry + required_gross / self.total_money_factor
            return exit_price + self.half_spread + self.params.slippage_price
        exit_price = entry - required_gross / self.total_money_factor
        return exit_price - self.half_spread - self.params.slippage_price

    def _open_basket(self, at: datetime, mid: float, signal: LiquiditySignal) -> None:
        self._basket_sequence += 1
        self.basket_id = f"LIQ-BASKET-{self._basket_sequence:08d}"
        self.basket_opened_at = at
        self.basket_start_balance = self.balance
        self.basket_signal = signal
        entry = self._entry_price(signal.side, mid)
        self.positions = []
        for _ in range(self.params.positions_per_basket):
            self._position_sequence += 1
            self.positions.append(
                LiquidityPosition(
                    position_id=f"LIQ-POS-{self._position_sequence:010d}",
                    basket_id=self.basket_id,
                    side=signal.side,
                    opened_at=at,
                    entry_price=entry,
                    lot_size=self.params.fixed_lot,
                )
            )
        opening_floating = self.basket_net(mid)
        self.basket_peak_floating = opening_floating
        self.basket_worst_floating = opening_floating
        self._update_extremes(mid)

    def _close_basket(self, at: datetime, mid: float, reason: str) -> None:
        if not self.positions or self.basket_id is None or self.basket_opened_at is None or self.basket_signal is None:
            return
        side = self.positions[0].side
        exit_price = self._exit_price(side, mid)
        target_price = self._threshold_price(self.params.profit_target_money)
        stop_price = self._threshold_price(-self.params.basket_stop_money)
        trade_rows: list[LiquidityCompletedTrade] = []
        for position in self.positions:
            factor = self.params.money_per_price_per_001_lot * (position.lot_size / 0.01)
            gross = (exit_price - position.entry_price) * factor if side == "buy" else (position.entry_price - exit_price) * factor
            costs = self.params.commission_per_001_lot * (position.lot_size / 0.01)
            net = gross - costs
            trade_rows.append(
                LiquidityCompletedTrade(
                    basket_id=self.basket_id,
                    position_id=position.position_id,
                    side=side,
                    opened_at=position.opened_at,
                    closed_at=at,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    stop_loss=stop_price,
                    take_profit=target_price,
                    lot_size=position.lot_size,
                    gross_pnl=gross,
                    costs=costs,
                    net_pnl=net,
                    exit_reason=reason,
                    signal=self.basket_signal,
                )
            )

        gross_total = sum(item.gross_pnl for item in trade_rows)
        costs_total = sum(item.costs for item in trade_rows)
        net_total = gross_total - costs_total
        self.balance += net_total
        self.completed_trades.extend(trade_rows)
        self.position_pnls.extend(item.net_pnl for item in trade_rows)
        basket = LiquidityCompletedBasket(
            basket_id=self.basket_id,
            opened_at=self.basket_opened_at,
            closed_at=at,
            side=side,
            positions=len(trade_rows),
            gross_pnl=gross_total,
            costs=costs_total,
            net_pnl=net_total,
            peak_floating=self.basket_peak_floating,
            worst_floating=self.basket_worst_floating,
            exit_reason=reason,
            signal=self.basket_signal,
        )
        self.completed_baskets.append(basket)
        self.basket_pnls.append(net_total)
        self.exit_reasons[reason] += 1
        self.monthly_net[at.strftime("%Y-%m")] += net_total
        self.yearly_net[at.strftime("%Y")] += net_total

        self.positions = []
        self.basket_id = None
        self.basket_opened_at = None
        self.basket_signal = None
        self.basket_peak_floating = 0.0
        self.basket_worst_floating = 0.0
        self._cooldown_remaining = self.params.cooldown_candles
        self._update_extremes(mid)

    @staticmethod
    def _crosses(current: float, target: float, level: float) -> bool:
        if target > current:
            return current < level <= target
        if target < current:
            return target <= level < current
        return False

    def _process_segment(self, current: float, target: float, at: datetime, *, gap: bool = False) -> float:
        if not self.positions or abs(target - current) <= self.EPS:
            self._update_extremes(target)
            return target
        profit_price = self._threshold_price(self.params.profit_target_money)
        stop_price = self._threshold_price(-self.params.basket_stop_money)
        events: list[tuple[float, str]] = []
        if self._crosses(current, target, profit_price):
            events.append((profit_price, "BASKET PROFIT TARGET"))
        if self._crosses(current, target, stop_price):
            events.append((stop_price, "HARD BASKET LOSS LIMIT"))
        if not events:
            self._update_extremes(target)
            return target

        up = target > current
        event_price, reason = min(events, key=lambda item: item[0]) if up else max(events, key=lambda item: item[0])
        fill_mid = target if gap else event_price
        self._update_extremes(fill_mid)
        self._close_basket(at, fill_mid, reason)
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
        if not self.positions:
            return False
        profit_price = self._threshold_price(self.params.profit_target_money)
        stop_price = self._threshold_price(-self.params.basket_stop_money)
        return candle.low <= profit_price <= candle.high and candle.low <= stop_price <= candle.high

    def _update_ema(self, close: float) -> float:
        self._ema_samples += 1
        if self._ema is None:
            self._ema = close
        else:
            alpha = 2.0 / (self.params.trend_period + 1.0)
            self._ema = close * alpha + self._ema * (1.0 - alpha)
        return self._ema

    def _detect_signal(self, candle: Candle, ema_value: float) -> LiquiditySignal | None:
        if len(self._lookback) < self.params.lookback_candles:
            return None
        prior_high = max(item.high for item in self._lookback)
        prior_low = min(item.low for item in self._lookback)
        high_sweep = (
            candle.high >= prior_high + self.params.minimum_sweep_price
            and candle.close < prior_high
            and candle.close < candle.open
        )
        low_sweep = (
            candle.low <= prior_low - self.params.minimum_sweep_price
            and candle.close > prior_low
            and candle.close > candle.open
        )
        if high_sweep and low_sweep:
            self.signals_filtered += 1
            return None
        if not high_sweep and not low_sweep:
            return None

        self.signals_detected += 1
        if self.params.use_trend_filter and self._ema_samples < self.params.trend_period:
            self.signals_filtered += 1
            return None
        if high_sweep:
            if self.params.use_trend_filter and candle.close > ema_value:
                self.signals_filtered += 1
                return None
            return LiquiditySignal("sell", candle.candle_time, prior_high, candle.close, ema_value)
        if self.params.use_trend_filter and candle.close < ema_value:
            self.signals_filtered += 1
            return None
        return LiquiditySignal("buy", candle.candle_time, prior_low, candle.close, ema_value)

    def process_candle(self, candle: Candle) -> None:
        if self.first_candle is None:
            self.first_candle = candle.candle_time
        self.last_candle = candle.candle_time
        self.candles_processed += 1

        if not self.positions and self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        opened_this_candle = False
        pending = self._pending_signal
        self._pending_signal = None
        if pending is not None and not self.positions and self._cooldown_remaining == 0:
            self._open_basket(candle.candle_time, candle.open, pending)
            opened_this_candle = True

        path = self._path(candle)
        current = path[0] if opened_this_candle or self._last_mid is None else self._last_mid
        if not opened_this_candle and abs(path[0] - current) > self.EPS:
            current = self._process_segment(current, path[0], candle.candle_time, gap=True)

        # Candle timestamps represent their opening time. Once the configured
        # duration has elapsed, close at this candle's open instead of granting
        # the basket another complete minute of favourable price movement.
        if self.positions and self.basket_opened_at is not None:
            held_for = candle.candle_time - self.basket_opened_at
            if held_for >= timedelta(minutes=self.params.maximum_hold_minutes):
                self._close_basket(candle.candle_time, candle.open, "MAXIMUM HOLD TIME")

        if self.positions and self._bar_is_ambiguous(candle):
            self.ambiguous_candles += 1
        for target in path[1:]:
            current = self._process_segment(current, target, candle.candle_time)

        self._last_mid = candle.close
        self._update_extremes(candle.close)
        ema_value = self._update_ema(candle.close)
        if not self.positions and self._cooldown_remaining == 0:
            self._pending_signal = self._detect_signal(candle, ema_value)
        self._lookback.append(candle)

    def drain_trades(self) -> list[LiquidityCompletedTrade]:
        rows = self.completed_trades
        self.completed_trades = []
        return rows

    def drain_baskets(self) -> list[LiquidityCompletedBasket]:
        rows = self.completed_baskets
        self.completed_baskets = []
        return rows

    def finalise(self) -> tuple[list[LiquidityCompletedTrade], list[LiquidityCompletedBasket]]:
        if self.positions and self.last_candle is not None and self._last_mid is not None:
            self._close_basket(self.last_candle, self._last_mid, "END OF TEST")
        return self.drain_trades(), self.drain_baskets()

    def summary(self) -> LiquiditySimulationSummary:
        wins = sum(value > 0 for value in self.basket_pnls)
        losses = sum(value < 0 for value in self.basket_pnls)
        return LiquiditySimulationSummary(
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
            exit_reasons=dict(self.exit_reasons),
            monthly_net={key: round(value, 6) for key, value in sorted(self.monthly_net.items())},
            yearly_net={key: round(value, 6) for key, value in sorted(self.yearly_net.items())},
            first_candle=self.first_candle.isoformat() if self.first_candle else None,
            last_candle=self.last_candle.isoformat() if self.last_candle else None,
            parameters=asdict(self.params),
        )
