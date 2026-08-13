from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.backtesting.fixed_ladder_v261 import Candle, PathMode


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class ComexClosingMomentumParameters:
    timezone_name: str = "America/New_York"
    reference_hour: int = 13
    reference_minute: int = 29
    entry_hour: int = 13
    entry_minute: int = 0
    exit_hour: int = 13
    exit_minute: int = 30
    fixed_lot: float = 0.01
    maximum_loss_percent: float = 0.25
    spread_price: float = 0.05
    commission_per_001_lot: float = 0.08
    slippage_price: float = 0.0
    money_per_price_per_001_lot: float = 1.0
    path_mode: PathMode = "candle_direction"

    @property
    def reference_total_minutes(self) -> int:
        return self.reference_hour * 60 + self.reference_minute

    @property
    def entry_total_minutes(self) -> int:
        return self.entry_hour * 60 + self.entry_minute

    @property
    def exit_total_minutes(self) -> int:
        return self.exit_hour * 60 + self.exit_minute

    def validate(self) -> None:
        if self.timezone_name != "America/New_York":
            raise ValueError("COMEX Closing Momentum v1 requires America/New_York time")
        if (self.reference_hour, self.reference_minute) != (13, 29):
            raise ValueError("The reference must be the 13:29 M1 close for the 13:30 COMEX settlement")
        if (self.entry_hour, self.entry_minute) != (13, 0):
            raise ValueError("Entry must be the 13:00 New York M1 open")
        if (self.exit_hour, self.exit_minute) != (13, 30):
            raise ValueError("Exit must be the 13:30 New York M1 open")
        if self.fixed_lot <= 0:
            raise ValueError("Fixed lot must be greater than zero")
        if not 0.01 <= self.maximum_loss_percent <= 5.0:
            raise ValueError("Maximum loss percent must be between 0.01 and 5")
        if self.path_mode not in {"candle_direction", "open_high_low_close", "open_low_high_close"}:
            raise ValueError("Unsupported intrabar path mode")
        for name in ("spread_price", "commission_per_001_lot", "slippage_price"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.money_per_price_per_001_lot <= 0:
            raise ValueError("Money per price move must be greater than zero")


@dataclass(frozen=True)
class ComexClosingSignal:
    side: Side
    signal_time: datetime
    session_date: str
    reference_time: datetime
    reference_price: float
    signal_price: float

    @property
    def signal_move(self) -> float:
        return self.signal_price - self.reference_price


@dataclass
class ComexClosingPosition:
    position_id: str
    basket_id: str
    side: Side
    opened_at: datetime
    entry_price: float
    lot_size: float
    stop_mid: float
    planned_risk_money: float
    signal: ComexClosingSignal


@dataclass
class ComexClosingCompletedTrade:
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
    costs: float
    net_pnl: float
    peak_floating: float
    worst_floating: float
    exit_reason: str
    signal: ComexClosingSignal
    planned_risk_money: float

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
            "strategy": "comex_closing_momentum",
            "strategy_version": "1.0",
            "session_date": self.signal.session_date,
            "signal_time": self.signal.signal_time.isoformat(),
            "reference_time": self.signal.reference_time.isoformat(),
            "reference_price": round(self.signal.reference_price, 10),
            "signal_price": round(self.signal.signal_price, 10),
            "signal_move": round(self.signal.signal_move, 10),
            "planned_risk_money": round(self.planned_risk_money, 6),
            "entry_protocol": "follow the move since the prior 13:30 America/New_York COMEX settlement at the 13:00 M1 open",
            "exit_protocol": "0.25% hard money stop or 13:30 America/New_York M1 open",
        }


@dataclass
class ComexClosingSimulationSummary:
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
    settlement_references: int
    sessions_traded: int
    missing_reference_skips: int
    doji_skips: int
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


class ComexClosingMomentumBacktester:
    """One 13:00-13:30 New York momentum trade per weekday.

    The signal is the sign of the move from the previous valid 13:29 M1 close
    (a spot proxy for the 13:30 COMEX settlement) to the current 13:00 M1 open.
    Missing references fail closed and no late entry or same-day re-entry exists.
    """

    EPS = 1e-9

    def __init__(self, starting_balance: float, parameters: ComexClosingMomentumParameters) -> None:
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

        self.position: ComexClosingPosition | None = None
        self._session_date: date | None = None
        self._last_eligible_market_date: date | None = None
        self._reference_date: date | None = None
        self._reference_time: datetime | None = None
        self._reference_price: float | None = None
        self._day_signal_consumed = False
        self._last_mid: float | None = None
        self._sequence = 0
        self._trade_peak_floating = 0.0
        self._trade_worst_floating = 0.0

        self.completed_trades: list[ComexClosingCompletedTrade] = []
        self.completed_baskets: list[ComexClosingCompletedTrade] = []
        self.position_pnls: list[float] = []
        self.basket_pnls: list[float] = []
        self.exit_reasons: Counter[str] = Counter()
        self.monthly_net: defaultdict[str, float] = defaultdict(float)
        self.yearly_net: defaultdict[str, float] = defaultdict(float)
        self.sessions_seen = 0
        self.eligible_sessions = 0
        self.settlement_references = 0
        self.sessions_traded = 0
        self.missing_reference_skips = 0
        self.doji_skips = 0
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
        return gross - self._commission(self.position.lot_size)

    def _threshold_mid(self, net_money: float) -> float:
        if self.position is None:
            raise RuntimeError("Cannot calculate a threshold without an open COMEX trade")
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
        self._day_signal_consumed = False
        self.sessions_seen += 1
        if session_date.weekday() < 5:
            self.eligible_sessions += 1

    def _open_daily_trade(self, at: datetime, mid: float, local: datetime) -> bool:
        if self._day_signal_consumed or local.weekday() >= 5 or self.account_ruined:
            return False
        self._day_signal_consumed = True
        if (
            self._reference_price is None
            or self._reference_time is None
            or self._reference_date is None
            or self._reference_date != self._last_eligible_market_date
        ):
            self.missing_reference_skips += 1
            return False
        if mid > self._reference_price:
            side: Side = "buy"
        elif mid < self._reference_price:
            side = "sell"
        else:
            self.doji_skips += 1
            return False

        signal = ComexClosingSignal(
            side=side,
            signal_time=at,
            session_date=local.date().isoformat(),
            reference_time=self._reference_time,
            reference_price=self._reference_price,
            signal_price=mid,
        )
        self._sequence += 1
        entry_price = self._entry_price(side, mid)
        planned_risk = self.balance * self.params.maximum_loss_percent / 100.0
        self.position = ComexClosingPosition(
            position_id=f"COMEX-MOM-POS-{self._sequence:08d}",
            basket_id=f"COMEX-MOM-TRADE-{self._sequence:08d}",
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

        completed = ComexClosingCompletedTrade(
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
            costs=costs,
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

    def process_candle(self, candle: Candle) -> None:
        if self.account_ruined:
            return
        previous_candle_time = self.last_candle
        if self.first_candle is None:
            self.first_candle = candle.candle_time
        self.last_candle = candle.candle_time
        self.candles_processed += 1
        local = self._local(candle.candle_time)
        session_date = local.date()

        if self._session_date != session_date:
            if self.position is not None:
                self._close_position(
                    previous_candle_time or candle.candle_time,
                    self._last_mid if self._last_mid is not None else candle.open,
                    "LAST AVAILABLE SESSION BAR",
                )
            if self._session_date is not None and self._session_date.weekday() < 5:
                self._last_eligible_market_date = self._session_date
            self._reset_session(session_date)
            self._last_mid = None

        minute = self._minute_of_day(local)
        opened = False
        if minute == self.params.entry_total_minutes:
            opened = self._open_daily_trade(candle.candle_time, candle.open, local)

        path = self._path(candle)
        current = path[0] if opened or self._last_mid is None else self._last_mid
        if not opened and self.position is not None and abs(path[0] - current) > self.EPS:
            current = self._process_segment(current, path[0], candle.candle_time, gap=True)

        if self.position is not None and minute >= self.params.exit_total_minutes:
            self._close_position(candle.candle_time, candle.open, "COMEX 13:30 EXIT")

        for target in path[1:]:
            current = self._process_segment(current, target, candle.candle_time)

        if local.weekday() < 5 and minute == self.params.reference_total_minutes:
            self._reference_date = session_date
            self._reference_time = candle.candle_time
            self._reference_price = candle.close
            self.settlement_references += 1

        self._last_mid = candle.close
        self._update_extremes(candle.close)

    def drain_trades(self) -> list[ComexClosingCompletedTrade]:
        rows = self.completed_trades
        self.completed_trades = []
        return rows

    def drain_baskets(self) -> list[ComexClosingCompletedTrade]:
        rows = self.completed_baskets
        self.completed_baskets = []
        return rows

    def finalise(self) -> tuple[list[ComexClosingCompletedTrade], list[ComexClosingCompletedTrade]]:
        if self.position is not None and self.last_candle is not None and self._last_mid is not None:
            self._close_position(self.last_candle, self._last_mid, "END OF TEST")
        return self.drain_trades(), self.drain_baskets()

    def summary(self) -> ComexClosingSimulationSummary:
        wins = sum(value > 0 for value in self.basket_pnls)
        losses = sum(value < 0 for value in self.basket_pnls)
        return ComexClosingSimulationSummary(
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
            settlement_references=self.settlement_references,
            sessions_traded=self.sessions_traded,
            missing_reference_skips=self.missing_reference_skips,
            doji_skips=self.doji_skips,
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
