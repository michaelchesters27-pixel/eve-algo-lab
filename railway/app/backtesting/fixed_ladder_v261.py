from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal


PathMode = Literal["candle_direction", "open_high_low_close", "open_low_high_close"]


@dataclass(frozen=True)
class FixedLadderParameters:
    fixed_lot: float = 0.01
    levels_per_side: int = 8
    spacing_price: float = 3.0
    fallback_price: float = 2.0
    first_bullet_quick_cut_price: float = 0.75
    break_even_trigger_price: float = 1.5
    break_even_buffer_price: float = 0.15
    profit_target_money: float = 5.0
    peak_protection_activation_money: float = 4.0
    peak_protection_giveback_money: float = 1.0
    emergency_loss_money: float = 5.0
    emergency_loss_percent: float = 1.0
    spread_price: float = 0.05
    commission_per_001_lot: float = 0.08
    slippage_price: float = 0.0
    money_per_price_per_001_lot: float = 1.0
    path_mode: PathMode = "candle_direction"

    def validate(self) -> None:
        if self.fixed_lot <= 0:
            raise ValueError("Fixed lot must be greater than zero")
        if not 1 <= self.levels_per_side <= 50:
            raise ValueError("Levels per side must be between 1 and 50")
        for name in (
            "spacing_price",
            "fallback_price",
            "first_bullet_quick_cut_price",
            "break_even_trigger_price",
            "break_even_buffer_price",
            "profit_target_money",
            "peak_protection_activation_money",
            "peak_protection_giveback_money",
            "emergency_loss_money",
            "spread_price",
            "commission_per_001_lot",
            "slippage_price",
            "money_per_price_per_001_lot",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass
class Candle:
    candle_time: datetime
    open: float
    high: float
    low: float
    close: float

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Candle":
        value = row["candle_time"]
        candle_time = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return cls(
            candle_time=candle_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )


@dataclass
class PendingOrder:
    side: Literal["buy", "sell"]
    level: int
    entry_price: float


@dataclass
class Position:
    position_id: str
    basket_id: str
    side: Literal["buy", "sell"]
    bullet_number: int
    opened_at: datetime
    entry_price: float
    current_sl: float
    initial_sl: float
    lot_size: float
    protected: bool = False
    quick_cut: bool = False
    newest_sequence: int = 0
    peak_favourable_price: float = 0.0
    max_adverse_price: float = 0.0


@dataclass
class CompletedTrade:
    basket_id: str
    position_id: str
    side: Literal["buy", "sell"]
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    lot_size: float
    gross_pnl: float
    costs: float
    net_pnl: float
    exit_reason: str
    bullet_number: int
    protected: bool
    mfe_price: float
    mae_price: float

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
            "take_profit": None,
            "lot_size": round(self.lot_size, 6),
            "gross_pnl": round(self.gross_pnl, 6),
            "costs": round(self.costs, 6),
            "net_pnl": round(self.net_pnl, 6),
            "exit_reason": self.exit_reason,
            "metadata": {
                "bullet_number": self.bullet_number,
                "break_even_protected": self.protected,
                "mfe_price": round(self.mfe_price, 6),
                "mae_price": round(self.mae_price, 6),
                "strategy_version": "2.61",
            },
        }


@dataclass
class CompletedBasket:
    basket_id: str
    opened_at: datetime
    closed_at: datetime
    side: str
    positions: int
    gross_pnl: float
    costs: float
    net_pnl: float
    peak_floating: float
    worst_floating: float
    max_positions: int
    exit_reason: str

    def to_row(self, run_id: str) -> dict[str, Any]:
        return {
            "backtest_run_id": run_id,
            "basket_id": self.basket_id,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "side": self.side.lower(),
            "positions": self.positions,
            "gross_pnl": round(self.gross_pnl, 6),
            "costs": round(self.costs, 6),
            "net_pnl": round(self.net_pnl, 6),
            "peak_floating": round(self.peak_floating, 6),
            "worst_floating": round(self.worst_floating, 6),
            "max_positions": self.max_positions,
            "exit_reason": self.exit_reason,
            "metadata": {"strategy_version": "2.61"},
        }


@dataclass
class SimulationSummary:
    starting_balance: float
    ending_balance: float
    position_pnls: list[float]
    basket_pnls: list[float]
    total_positions: int
    total_baskets: int
    winning_positions: int
    losing_positions: int
    break_even_positions: int
    winning_baskets: int
    losing_baskets: int
    break_even_baskets: int
    max_equity_drawdown: float
    max_equity_drawdown_percent: float
    ambiguous_candles: int
    candles_processed: int
    exit_reasons: dict[str, int]
    monthly_net: dict[str, float]
    yearly_net: dict[str, float]
    first_candle: str | None
    last_candle: str | None
    parameters: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _CandidateEvent:
    price: float
    priority: int
    kind: str
    ref: Any = None


class FixedLadderV261Backtester:
    """Candle-path approximation of the exact v2.61 fixed-ladder rules.

    It deliberately does not claim tick accuracy. The engine models bid/ask from a
    configurable fixed spread and records candles where both extremes can make the
    event order material. M1/tick replay is the next accuracy layer.
    """

    EPS = 1e-9

    def __init__(self, starting_balance: float, parameters: FixedLadderParameters) -> None:
        if starting_balance <= 0:
            raise ValueError("Starting balance must be greater than zero")
        parameters.validate()
        self.params = parameters
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self.balance_peak = float(starting_balance)
        self.max_balance_drawdown = 0.0
        self.max_balance_drawdown_percent = 0.0
        self.max_equity_drawdown = 0.0
        self.max_equity_drawdown_percent = 0.0

        self.orders: list[PendingOrder] = []
        self.positions: dict[str, Position] = {}
        self.anchor_price: float | None = None
        self.basket_id: str | None = None
        self.basket_opened_at: datetime | None = None
        self.basket_start_balance = self.balance
        self.basket_peak_floating = 0.0
        self.basket_worst_floating = 0.0
        self.basket_peak_protection_armed = False
        self.basket_peak_floor = 0.0
        self.basket_max_positions = 0
        self.basket_entry_count = 0
        self.basket_buy_count = 0
        self.basket_sell_count = 0
        self.basket_trade_gross = 0.0
        self.basket_trade_costs = 0.0
        self.basket_closed_positions = 0

        self._basket_sequence = 0
        self._position_sequence = 0
        self._fill_sequence = 0

        self.completed_trades: list[CompletedTrade] = []
        self.completed_baskets: list[CompletedBasket] = []
        self.position_pnls: list[float] = []
        self.basket_pnls: list[float] = []
        self.exit_reasons: Counter[str] = Counter()
        self.monthly_net: defaultdict[str, float] = defaultdict(float)
        self.yearly_net: defaultdict[str, float] = defaultdict(float)

        self.candles_processed = 0
        self.ambiguous_candles = 0
        self.first_candle: datetime | None = None
        self.last_candle: datetime | None = None
        self._last_mid: float | None = None

    @property
    def half_spread(self) -> float:
        return self.params.spread_price / 2.0

    @property
    def lot_units(self) -> float:
        return self.params.fixed_lot / 0.01

    @property
    def money_factor(self) -> float:
        return self.params.money_per_price_per_001_lot * self.lot_units

    def _commission_for(self, position: Position) -> float:
        return self.params.commission_per_001_lot * (position.lot_size / 0.01)

    def _bid(self, mid: float) -> float:
        return mid - self.half_spread

    def _ask(self, mid: float) -> float:
        return mid + self.half_spread

    def _mark_position(self, position: Position, mid: float) -> float:
        if position.side == "buy":
            return (self._bid(mid) - position.entry_price) * self.params.money_per_price_per_001_lot * (position.lot_size / 0.01)
        return (position.entry_price - self._ask(mid)) * self.params.money_per_price_per_001_lot * (position.lot_size / 0.01)

    def basket_floating(self, mid: float) -> float:
        return sum(self._mark_position(position, mid) for position in self.positions.values())

    def equity(self, mid: float) -> float:
        return self.balance + self.basket_floating(mid)

    def _update_drawdown(self, mid: float) -> None:
        equity = self.equity(mid)
        self.balance_peak = max(self.balance_peak, self.balance)
        balance_dd = self.balance_peak - self.balance
        self.max_balance_drawdown = max(self.max_balance_drawdown, balance_dd)
        if self.balance_peak > 0:
            self.max_balance_drawdown_percent = max(self.max_balance_drawdown_percent, balance_dd / self.balance_peak * 100.0)

        equity_peak = getattr(self, "_equity_peak", self.starting_balance)
        equity_peak = max(equity_peak, equity)
        self._equity_peak = equity_peak
        equity_dd = equity_peak - equity
        self.max_equity_drawdown = max(self.max_equity_drawdown, equity_dd)
        if equity_peak > 0:
            self.max_equity_drawdown_percent = max(self.max_equity_drawdown_percent, equity_dd / equity_peak * 100.0)

    def _update_position_excursions(self, mid: float) -> None:
        bid = self._bid(mid)
        ask = self._ask(mid)
        for position in self.positions.values():
            if position.side == "buy":
                favourable = max(0.0, bid - position.entry_price)
                adverse = max(0.0, position.entry_price - bid)
            else:
                favourable = max(0.0, position.entry_price - ask)
                adverse = max(0.0, ask - position.entry_price)
            position.peak_favourable_price = max(position.peak_favourable_price, favourable)
            position.max_adverse_price = max(position.max_adverse_price, adverse)

    def _update_basket_extremes(self, mid: float) -> None:
        if not self.positions or self.basket_id is None:
            self._update_drawdown(mid)
            return
        floating = self.basket_floating(mid)
        self.basket_peak_floating = max(self.basket_peak_floating, floating)
        self.basket_worst_floating = min(self.basket_worst_floating, floating)
        if self.basket_peak_protection_armed:
            self.basket_peak_floor = max(0.01, self.basket_peak_floating - self.params.peak_protection_giveback_money)
        self._update_position_excursions(mid)
        self._update_drawdown(mid)

    def _rearm(self, mid: float) -> None:
        self.anchor_price = mid
        self.orders = []
        for level in range(1, self.params.levels_per_side + 1):
            self.orders.append(PendingOrder("buy", level, mid + self.params.spacing_price * level))
            self.orders.append(PendingOrder("sell", level, mid - self.params.spacing_price * level))

    def _start_basket(self, at: datetime) -> None:
        self._basket_sequence += 1
        self.basket_id = f"BT-BASKET-{self._basket_sequence:08d}"
        self.basket_opened_at = at
        self.basket_start_balance = self.balance
        self.basket_peak_floating = 0.0
        self.basket_worst_floating = 0.0
        self.basket_peak_protection_armed = False
        self.basket_peak_floor = 0.0
        self.basket_max_positions = 0
        self.basket_entry_count = 0
        self.basket_buy_count = 0
        self.basket_sell_count = 0
        self.basket_trade_gross = 0.0
        self.basket_trade_costs = 0.0
        self.basket_closed_positions = 0

    def _fill_order(self, order: PendingOrder, at: datetime, mid: float) -> None:
        if self.basket_id is None:
            self._start_basket(at)
        self.orders.remove(order)
        self._position_sequence += 1
        self._fill_sequence += 1
        if order.side == "buy":
            entry = order.entry_price + self.params.slippage_price
            initial_sl = order.entry_price - self.params.fallback_price
            self.basket_buy_count += 1
            bullet_number = self.basket_buy_count
        else:
            entry = order.entry_price - self.params.slippage_price
            initial_sl = order.entry_price + self.params.fallback_price
            self.basket_sell_count += 1
            bullet_number = self.basket_sell_count

        self.basket_entry_count += 1
        position_id = f"BT-POS-{self._position_sequence:010d}"
        current_sl = initial_sl
        if self.basket_entry_count == 1 and self.params.first_bullet_quick_cut_price > 0:
            current_sl = entry - self.params.first_bullet_quick_cut_price if order.side == "buy" else entry + self.params.first_bullet_quick_cut_price

        position = Position(
            position_id=position_id,
            basket_id=self.basket_id or "",
            side=order.side,
            bullet_number=bullet_number,
            opened_at=at,
            entry_price=entry,
            current_sl=current_sl,
            initial_sl=current_sl,
            lot_size=self.params.fixed_lot,
            quick_cut=self.basket_entry_count == 1 and self.params.first_bullet_quick_cut_price > 0,
            newest_sequence=self._fill_sequence,
        )
        self.positions[position_id] = position
        self.basket_max_positions = max(self.basket_max_positions, len(self.positions))
        floating = self.basket_floating(mid)
        if self.basket_entry_count == 1:
            self.basket_peak_floating = floating
            self.basket_worst_floating = floating
        else:
            self.basket_peak_floating = max(self.basket_peak_floating, floating)
            self.basket_worst_floating = min(self.basket_worst_floating, floating)

    def _newest_position_id(self) -> str | None:
        if not self.positions:
            return None
        return max(self.positions.values(), key=lambda item: item.newest_sequence).position_id

    def _exit_price(self, position: Position, mid: float, stop_fill: bool = False) -> float:
        if stop_fill:
            raw = position.current_sl
        elif position.side == "buy":
            raw = self._bid(mid)
        else:
            raw = self._ask(mid)
        if position.side == "buy":
            return raw - self.params.slippage_price
        return raw + self.params.slippage_price

    def _close_position(self, position_id: str, at: datetime, mid: float, reason: str, stop_fill: bool = False) -> CompletedTrade:
        position = self.positions.pop(position_id)
        exit_price = self._exit_price(position, mid, stop_fill=stop_fill)
        if position.side == "buy":
            gross = (exit_price - position.entry_price) * self.params.money_per_price_per_001_lot * (position.lot_size / 0.01)
        else:
            gross = (position.entry_price - exit_price) * self.params.money_per_price_per_001_lot * (position.lot_size / 0.01)
        costs = self._commission_for(position)
        net = gross - costs
        self.balance += net
        self.basket_trade_gross += gross
        self.basket_trade_costs += costs
        self.basket_closed_positions += 1
        self.position_pnls.append(net)
        self.exit_reasons[reason] += 1
        month_key = at.strftime("%Y-%m")
        year_key = at.strftime("%Y")
        self.monthly_net[month_key] += net
        self.yearly_net[year_key] += net
        trade = CompletedTrade(
            basket_id=position.basket_id,
            position_id=position.position_id,
            side=position.side,
            opened_at=position.opened_at,
            closed_at=at,
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_loss=position.current_sl,
            lot_size=position.lot_size,
            gross_pnl=gross,
            costs=costs,
            net_pnl=net,
            exit_reason=reason,
            bullet_number=position.bullet_number,
            protected=position.protected,
            mfe_price=position.peak_favourable_price,
            mae_price=position.max_adverse_price,
        )
        self.completed_trades.append(trade)
        self._update_drawdown(mid)
        return trade

    def _basket_side(self) -> str:
        if self.basket_buy_count and self.basket_sell_count:
            return "mixed"
        if self.basket_buy_count:
            return "buy"
        if self.basket_sell_count:
            return "sell"
        return "none"

    def _finish_basket(self, at: datetime, mid: float, reason: str) -> CompletedBasket | None:
        if self.basket_id is None or self.basket_opened_at is None:
            self._rearm(mid)
            return None
        net = self.balance - self.basket_start_balance
        basket = CompletedBasket(
            basket_id=self.basket_id,
            opened_at=self.basket_opened_at,
            closed_at=at,
            side=self._basket_side(),
            positions=self.basket_closed_positions,
            gross_pnl=self.basket_trade_gross,
            costs=self.basket_trade_costs,
            net_pnl=net,
            peak_floating=self.basket_peak_floating,
            worst_floating=self.basket_worst_floating,
            max_positions=self.basket_max_positions,
            exit_reason=reason,
        )
        self.completed_baskets.append(basket)
        self.basket_pnls.append(net)
        self.exit_reasons[f"BASKET::{reason}"] += 1

        self.basket_id = None
        self.basket_opened_at = None
        self.positions.clear()
        self.orders.clear()
        self.anchor_price = None
        self._rearm(mid)
        return basket

    def _close_basket(self, at: datetime, mid: float, reason: str) -> None:
        for position_id in list(self.positions):
            self._close_position(position_id, at, mid, reason, stop_fill=False)
        self.orders.clear()
        self._finish_basket(at, mid, reason)

    def _floating_coefficients(self) -> tuple[float, float]:
        slope = 0.0
        intercept = 0.0
        for position in self.positions.values():
            factor = self.params.money_per_price_per_001_lot * (position.lot_size / 0.01)
            if position.side == "buy":
                slope += factor
                intercept += (-self.half_spread - position.entry_price) * factor
            else:
                slope -= factor
                intercept += (position.entry_price - self.half_spread) * factor
        return slope, intercept

    def _pnl_cross_price(self, threshold: float, current: float, target: float) -> float | None:
        slope, intercept = self._floating_coefficients()
        if abs(slope) <= self.EPS:
            return None
        price = (threshold - intercept) / slope
        if target > current:
            if current + self.EPS < price <= target + self.EPS:
                return price
        elif target < current:
            if target - self.EPS <= price < current - self.EPS:
                return price
        return None

    def _event_candidates(self, current: float, target: float) -> list[_CandidateEvent]:
        if abs(target - current) <= self.EPS:
            return []
        up = target > current
        candidates: list[_CandidateEvent] = []

        for order in self.orders:
            trigger_mid = order.entry_price - self.half_spread if order.side == "buy" else order.entry_price + self.half_spread
            if (up and order.side == "buy" and current + self.EPS < trigger_mid <= target + self.EPS) or (
                not up and order.side == "sell" and target - self.EPS <= trigger_mid < current - self.EPS
            ):
                candidates.append(_CandidateEvent(trigger_mid, 50, "fill", order))

        for position in self.positions.values():
            if position.side == "buy":
                sl_mid = position.current_sl + self.half_spread
                be_mid = position.entry_price + self.params.break_even_trigger_price + self.half_spread
                if not up and target - self.EPS <= sl_mid < current - self.EPS:
                    candidates.append(_CandidateEvent(sl_mid, 10, "stop", position.position_id))
                if up and not position.protected and current + self.EPS < be_mid <= target + self.EPS:
                    candidates.append(_CandidateEvent(be_mid, 35, "break_even", position.position_id))
            else:
                sl_mid = position.current_sl - self.half_spread
                be_mid = position.entry_price - self.params.break_even_trigger_price - self.half_spread
                if up and current + self.EPS < sl_mid <= target + self.EPS:
                    candidates.append(_CandidateEvent(sl_mid, 10, "stop", position.position_id))
                if not up and not position.protected and target - self.EPS <= be_mid < current - self.EPS:
                    candidates.append(_CandidateEvent(be_mid, 35, "break_even", position.position_id))

        if self.positions:
            floating_now = self.basket_floating(current)
            emergency_limit = self.params.emergency_loss_money
            if self.params.emergency_loss_percent > 0:
                pct = self.balance * self.params.emergency_loss_percent / 100.0
                emergency_limit = min(emergency_limit, pct) if emergency_limit > 0 else pct

            if self.params.profit_target_money > 0:
                price = self._pnl_cross_price(self.params.profit_target_money, current, target)
                if price is not None and floating_now < self.params.profit_target_money - self.EPS:
                    candidates.append(_CandidateEvent(price, 1, "basket_target"))

            if emergency_limit > 0:
                price = self._pnl_cross_price(-emergency_limit, current, target)
                if price is not None and floating_now > -emergency_limit + self.EPS:
                    candidates.append(_CandidateEvent(price, 0, "basket_emergency"))

            if not self.basket_peak_protection_armed and self.params.peak_protection_activation_money > 0:
                price = self._pnl_cross_price(self.params.peak_protection_activation_money, current, target)
                if price is not None and floating_now < self.params.peak_protection_activation_money - self.EPS:
                    candidates.append(_CandidateEvent(price, 20, "peak_activate"))

            if self.basket_peak_protection_armed:
                floor = self.basket_peak_floor
                price = self._pnl_cross_price(floor, current, target)
                if price is not None and floating_now > floor + self.EPS:
                    candidates.append(_CandidateEvent(price, 2, "peak_floor"))

        return candidates

    def _process_event(self, event: _CandidateEvent, at: datetime, mid: float) -> None:
        self._update_basket_extremes(mid)
        if event.kind == "fill":
            order = event.ref
            if order in self.orders:
                self._fill_order(order, at, mid)
                self._update_basket_extremes(mid)
            return

        if event.kind == "break_even":
            position = self.positions.get(str(event.ref))
            if not position or position.protected:
                return
            if position.side == "buy":
                position.current_sl = position.entry_price + self.params.break_even_buffer_price
            else:
                position.current_sl = position.entry_price - self.params.break_even_buffer_price
            position.protected = True
            return

        if event.kind == "stop":
            position_id = str(event.ref)
            position = self.positions.get(position_id)
            if not position:
                return
            newest = self._newest_position_id()
            protected = position.protected
            first_quick_cut = position.quick_cut and not protected
            stop_reason = "BE PROTECTED STOP - BULLET ONLY" if protected else (
                "FIRST BULLET QUICK CUT STOP" if first_quick_cut else "INITIAL STOP LOSS"
            )
            self._close_position(position_id, at, mid, stop_reason, stop_fill=True)
            if protected:
                if not self.positions:
                    self.orders.clear()
                    self._finish_basket(at, mid, "LAST LIVE BULLET CLOSED AT BE PROTECTION")
                return
            if position_id == newest:
                reason = "FIRST BULLET QUICK CUT - CLOSE FULL CAMPAIGN" if first_quick_cut else "NEWEST BULLET FAILED BEFORE HALFWAY - CLOSE FULL CAMPAIGN"
                for other_id in list(self.positions):
                    self._close_position(other_id, at, mid, reason, stop_fill=False)
                self.orders.clear()
                self._finish_basket(at, mid, reason)
            elif not self.positions:
                self.orders.clear()
                self._finish_basket(at, mid, "ALL LIVE BULLETS CLOSED")
            return

        if event.kind == "peak_activate":
            self.basket_peak_protection_armed = True
            self.basket_peak_floating = max(self.basket_peak_floating, self.basket_floating(mid))
            self.basket_peak_floor = max(0.01, self.basket_peak_floating - self.params.peak_protection_giveback_money)
            return

        if event.kind == "basket_target":
            self._close_basket(at, mid, "CAMPAIGN PROFIT TARGET REACHED")
            return
        if event.kind == "peak_floor":
            self._close_basket(at, mid, "BASKET PEAK PROTECTION FLOOR")
            return
        if event.kind == "basket_emergency":
            self._close_basket(at, mid, "HARD BASKET LOSS LIMIT")
            return

    def _process_segment(self, current: float, target: float, at: datetime) -> float:
        if self.anchor_price is None:
            self._rearm(current)
        guard = 0
        while abs(target - current) > self.EPS:
            guard += 1
            if guard > 500:
                raise RuntimeError("Intrabar event loop exceeded safety limit")
            candidates = self._event_candidates(current, target)
            if not candidates:
                current = target
                self._update_basket_extremes(current)
                break
            up = target > current
            nearest_price = min(event.price for event in candidates) if up else max(event.price for event in candidates)
            same_price = [event for event in candidates if abs(event.price - nearest_price) <= 1e-7]
            same_price.sort(key=lambda event: event.priority)
            current = nearest_price
            for event in same_price:
                self._process_event(event, at, current)
            self._update_basket_extremes(current)
        return current

    def _path(self, candle: Candle) -> list[float]:
        if self.params.path_mode == "open_high_low_close":
            return [candle.open, candle.high, candle.low, candle.close]
        if self.params.path_mode == "open_low_high_close":
            return [candle.open, candle.low, candle.high, candle.close]
        if candle.close >= candle.open:
            return [candle.open, candle.low, candle.high, candle.close]
        return [candle.open, candle.high, candle.low, candle.close]

    def _is_ambiguous(self, candle: Candle) -> bool:
        if not self.orders and not self.positions:
            return False
        touched_buy = any(candle.high + self.half_spread >= order.entry_price for order in self.orders if order.side == "buy")
        touched_sell = any(candle.low - self.half_spread <= order.entry_price for order in self.orders if order.side == "sell")
        touched_buy_sl = any(candle.low - self.half_spread <= position.current_sl for position in self.positions.values() if position.side == "buy")
        touched_sell_sl = any(candle.high + self.half_spread >= position.current_sl for position in self.positions.values() if position.side == "sell")
        return (touched_buy and touched_sell) or (touched_buy and touched_buy_sl) or (touched_sell and touched_sell_sl) or (touched_buy_sl and touched_sell_sl)

    def process_candle(self, candle: Candle) -> None:
        if self.first_candle is None:
            self.first_candle = candle.candle_time
        self.last_candle = candle.candle_time
        self.candles_processed += 1
        if self._is_ambiguous(candle):
            self.ambiguous_candles += 1

        path = self._path(candle)
        current = self._last_mid if self._last_mid is not None else path[0]
        # Treat the new candle open as a tradable jump from the previous close.
        if abs(path[0] - current) > self.EPS:
            current = self._process_segment(current, path[0], candle.candle_time)
        for target in path[1:]:
            current = self._process_segment(current, target, candle.candle_time)
        self._last_mid = candle.close
        self._update_basket_extremes(candle.close)

    def drain_trades(self) -> list[CompletedTrade]:
        rows = self.completed_trades
        self.completed_trades = []
        return rows

    def drain_baskets(self) -> list[CompletedBasket]:
        rows = self.completed_baskets
        self.completed_baskets = []
        return rows

    def finalise(self) -> tuple[list[CompletedTrade], list[CompletedBasket]]:
        if self._last_mid is not None and self.positions and self.last_candle is not None:
            self._close_basket(self.last_candle, self._last_mid, "END OF TEST")
        return self.drain_trades(), self.drain_baskets()

    def summary(self) -> SimulationSummary:
        position_wins = sum(value > 0 for value in self.position_pnls)
        position_losses = sum(value < 0 for value in self.position_pnls)
        basket_wins = sum(value > 0 for value in self.basket_pnls)
        basket_losses = sum(value < 0 for value in self.basket_pnls)
        return SimulationSummary(
            starting_balance=round(self.starting_balance, 2),
            ending_balance=round(self.balance, 2),
            position_pnls=list(self.position_pnls),
            basket_pnls=list(self.basket_pnls),
            total_positions=len(self.position_pnls),
            total_baskets=len(self.basket_pnls),
            winning_positions=position_wins,
            losing_positions=position_losses,
            break_even_positions=len(self.position_pnls) - position_wins - position_losses,
            winning_baskets=basket_wins,
            losing_baskets=basket_losses,
            break_even_baskets=len(self.basket_pnls) - basket_wins - basket_losses,
            max_equity_drawdown=round(self.max_equity_drawdown, 6),
            max_equity_drawdown_percent=round(self.max_equity_drawdown_percent, 6),
            ambiguous_candles=self.ambiguous_candles,
            candles_processed=self.candles_processed,
            exit_reasons=dict(self.exit_reasons),
            monthly_net={key: round(value, 6) for key, value in sorted(self.monthly_net.items())},
            yearly_net={key: round(value, 6) for key, value in sorted(self.yearly_net.items())},
            first_candle=self.first_candle.isoformat() if self.first_candle else None,
            last_candle=self.last_candle.isoformat() if self.last_candle else None,
            parameters=asdict(self.params),
        )
