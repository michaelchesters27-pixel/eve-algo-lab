from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import floor
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.backtesting.fixed_ladder_v261 import Candle, PathMode


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class NewYorkMorningMomentumParameters:
    timezone_name: str = "America/New_York"
    signal_start_hour: int = 8
    signal_start_minute: int = 30
    signal_minutes: int = 30
    entry_hour: int = 9
    entry_minute: int = 0
    force_exit_hour: int = 15
    force_exit_minute: int = 55
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
    def signal_start_total_minutes(self) -> int:
        return self.signal_start_hour * 60 + self.signal_start_minute

    @property
    def signal_end_total_minutes(self) -> int:
        return self.signal_start_total_minutes + self.signal_minutes

    @property
    def entry_total_minutes(self) -> int:
        return self.entry_hour * 60 + self.entry_minute

    @property
    def force_exit_total_minutes(self) -> int:
        return self.force_exit_hour * 60 + self.force_exit_minute

    def validate(self) -> None:
        if self.timezone_name != "America/New_York":
            raise ValueError("New York Morning Momentum v1 requires America/New_York time")
        for label, hour in (
            ("signal start", self.signal_start_hour),
            ("entry", self.entry_hour),
            ("force exit", self.force_exit_hour),
        ):
            if not 0 <= hour <= 23:
                raise ValueError(f"{label} hour must be between 0 and 23")
        for label, minute in (
            ("signal start", self.signal_start_minute),
            ("entry", self.entry_minute),
            ("force exit", self.force_exit_minute),
        ):
            if not 0 <= minute <= 59:
                raise ValueError(f"{label} minute must be between 0 and 59")
        if self.signal_minutes != 30:
            raise ValueError("New York Morning Momentum v1 requires an exact 30-minute signal window")
        if self.signal_end_total_minutes != self.entry_total_minutes:
            raise ValueError("Entry must occur immediately after the signal window")
        if self.force_exit_total_minutes <= self.entry_total_minutes:
            raise ValueError("Force exit must be after entry")
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


@dataclass(frozen=True)
class MorningMomentumSignal:
    side: Side
    signal_time: datetime
    session_date: str
    impulse_open: float
    impulse_high: float
    impulse_low: float
    impulse_close: float

    @property
    def impulse_width(self) -> float:
        return self.impulse_high - self.impulse_low

    @property
    def impulse_move(self) -> float:
        return self.impulse_close - self.impulse_open


@dataclass
class MorningMomentumPosition:
    position_id: str
    basket_id: str
    side: Side
    opened_at: datetime
    entry_price: float
    lot_size: float
    stop_mid: float
    planned_risk_money: float
    signal: MorningMomentumSignal


@dataclass
class MorningMomentumCompletedTrade:
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
    signal: MorningMomentumSignal
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
            "strategy": "new_york_morning_momentum",
            "strategy_version": "1.0",
            "session_date": self.signal.session_date,
            "signal_time": self.signal.signal_time.isoformat(),
            "impulse_open": round(self.signal.impulse_open, 10),
            "impulse_high": round(self.signal.impulse_high, 10),
            "impulse_low": round(self.signal.impulse_low, 10),
            "impulse_close": round(self.signal.impulse_close, 10),
            "impulse_width": round(self.signal.impulse_width, 10),
            "impulse_move": round(self.signal.impulse_move, 10),
            "planned_risk_money": round(self.planned_risk_money, 6),
            "entry_protocol": "follow the completed 08:30-09:00 America/New_York impulse at the 09:00 M1 open",
            "exit_protocol": "opposite impulse edge hard stop or 15:55 America/New_York force exit",
        }


@dataclass
class MorningMomentumSimulationSummary:
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
    complete_signal_windows: int
    sessions_traded: int
    incomplete_window_skips: int
    doji_skips: int
    risk_size_skips: int
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


class NewYorkMorningMomentumBacktester:
    """One M1-replayed position per New York weekday.

    The completed 08:30-09:00 New York impulse supplies direction and the
    opposite edge supplies the hard stop. Entry is the 09:00 M1 open and any
    surviving trade is closed at the 15:55 M1 open. Missing signal-window
    minutes fail closed; the engine never invents candles or enters late.
    """

    EPS = 1e-9

    def __init__(self, starting_balance: float, parameters: NewYorkMorningMomentumParameters) -> None:
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

        self.position: MorningMomentumPosition | None = None
        self._session_date: date | None = None
        self._window_open: float | None = None
        self._window_high: float | None = None
        self._window_low: float | None = None
        self._window_close: float | None = None
        self._window_minutes: set[int] = set()
        self._day_signal_consumed = False
        self._last_mid: float | None = None
        self._sequence = 0
        self._trade_peak_floating = 0.0
        self._trade_worst_floating = 0.0

        self.completed_trades: list[MorningMomentumCompletedTrade] = []
        self.completed_baskets: list[MorningMomentumCompletedTrade] = []
        self.position_pnls: list[float] = []
        self.basket_pnls: list[float] = []
        self.exit_reasons: Counter[str] = Counter()
        self.monthly_net: defaultdict[str, float] = defaultdict(float)
        self.yearly_net: defaultdict[str, float] = defaultdict(float)
        self.sessions_seen = 0
        self.eligible_sessions = 0
        self.complete_signal_windows = 0
        self.sessions_traded = 0
        self.incomplete_window_skips = 0
        self.doji_skips = 0
        self.risk_size_skips = 0
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
            raise RuntimeError("Cannot calculate a threshold without an open New York trade")
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
        self._window_open = None
        self._window_high = None
        self._window_low = None
        self._window_close = None
        self._window_minutes.clear()
        self._day_signal_consumed = False
        self.sessions_seen += 1
        if session_date.weekday() < 5:
            self.eligible_sessions += 1

    def _collect_signal_window(self, candle: Candle, local: datetime) -> None:
        if local.weekday() >= 5:
            return
        minute = self._minute_of_day(local)
        if not self.params.signal_start_total_minutes <= minute < self.params.signal_end_total_minutes:
            return
        if minute in self._window_minutes:
            return
        self._window_minutes.add(minute)
        if self._window_open is None:
            self._window_open = candle.open
            self._window_high = candle.high
            self._window_low = candle.low
        else:
            self._window_high = max(float(self._window_high), candle.high)
            self._window_low = min(float(self._window_low), candle.low)
        self._window_close = candle.close

    def _open_daily_trade(self, at: datetime, mid: float, local: datetime) -> bool:
        if self._day_signal_consumed or local.weekday() >= 5 or self.account_ruined:
            return False
        self._day_signal_consumed = True
        required_minutes = set(range(self.params.signal_start_total_minutes, self.params.signal_end_total_minutes))
        if self._window_minutes != required_minutes:
            self.incomplete_window_skips += 1
            return False
        if None in (self._window_open, self._window_high, self._window_low, self._window_close):
            self.incomplete_window_skips += 1
            return False
        self.complete_signal_windows += 1
        impulse_open = float(self._window_open)
        impulse_high = float(self._window_high)
        impulse_low = float(self._window_low)
        impulse_close = float(self._window_close)
        if impulse_close > impulse_open:
            side: Side = "buy"
            stop_mid = impulse_low
        elif impulse_close < impulse_open:
            side = "sell"
            stop_mid = impulse_high
        else:
            self.doji_skips += 1
            return False

        entry_price = self._entry_price(side, mid)
        stop_exit = self._exit_price(side, stop_mid)
        price_risk = entry_price - stop_exit if side == "buy" else stop_exit - entry_price
        if price_risk <= self.EPS:
            self.risk_size_skips += 1
            return False
        risk_per_001 = price_risk * self.params.money_per_price_per_001_lot + self.params.commission_per_001_lot
        risk_budget = self.balance * self.params.risk_percent / 100.0
        raw_lot = risk_budget / risk_per_001 * 0.01
        lot_size = floor((raw_lot + self.EPS) / self.params.lot_step) * self.params.lot_step
        lot_size = min(lot_size, self.params.maximum_lot)
        if lot_size + self.EPS < self.params.minimum_lot:
            self.risk_size_skips += 1
            return False

        planned_risk = risk_per_001 * (lot_size / 0.01)
        signal = MorningMomentumSignal(
            side=side,
            signal_time=at,
            session_date=local.date().isoformat(),
            impulse_open=impulse_open,
            impulse_high=impulse_high,
            impulse_low=impulse_low,
            impulse_close=impulse_close,
        )
        self._sequence += 1
        self.position = MorningMomentumPosition(
            position_id=f"NY-MOM-POS-{self._sequence:08d}",
            basket_id=f"NY-MOM-TRADE-{self._sequence:08d}",
            side=side,
            opened_at=at,
            entry_price=entry_price,
            lot_size=lot_size,
            stop_mid=stop_mid,
            planned_risk_money=planned_risk,
            signal=signal,
        )
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

        completed = MorningMomentumCompletedTrade(
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
            self._close_position(at, target, "MORNING RANGE STOP")
            return target

        events: list[tuple[float, str]] = []
        if self._crosses(current, target, ruin_mid):
            events.append((ruin_mid, "ACCOUNT RUIN LIMIT"))
        if self._crosses(current, target, position.stop_mid):
            events.append((position.stop_mid, "MORNING RANGE STOP"))
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
            self._reset_session(session_date)
            self._last_mid = None

        self._collect_signal_window(candle, local)
        minute = self._minute_of_day(local)
        opened = False
        if minute == self.params.entry_total_minutes:
            opened = self._open_daily_trade(candle.candle_time, candle.open, local)

        path = self._path(candle)
        current = path[0] if opened or self._last_mid is None else self._last_mid
        if not opened and self.position is not None and abs(path[0] - current) > self.EPS:
            current = self._process_segment(current, path[0], candle.candle_time, gap=True)

        if self.position is not None and minute >= self.params.force_exit_total_minutes:
            self._close_position(candle.candle_time, candle.open, "NEW YORK FORCE EXIT")

        for target in path[1:]:
            current = self._process_segment(current, target, candle.candle_time)

        self._last_mid = candle.close
        self._update_extremes(candle.close)

    def drain_trades(self) -> list[MorningMomentumCompletedTrade]:
        rows = self.completed_trades
        self.completed_trades = []
        return rows

    def drain_baskets(self) -> list[MorningMomentumCompletedTrade]:
        rows = self.completed_baskets
        self.completed_baskets = []
        return rows

    def finalise(self) -> tuple[list[MorningMomentumCompletedTrade], list[MorningMomentumCompletedTrade]]:
        if self.position is not None and self.last_candle is not None and self._last_mid is not None:
            self._close_position(self.last_candle, self._last_mid, "END OF TEST")
        return self.drain_trades(), self.drain_baskets()

    def summary(self) -> MorningMomentumSimulationSummary:
        wins = sum(value > 0 for value in self.basket_pnls)
        losses = sum(value < 0 for value in self.basket_pnls)
        return MorningMomentumSimulationSummary(
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
            complete_signal_windows=self.complete_signal_windows,
            sessions_traded=self.sessions_traded,
            incomplete_window_skips=self.incomplete_window_skips,
            doji_skips=self.doji_skips,
            risk_size_skips=self.risk_size_skips,
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
