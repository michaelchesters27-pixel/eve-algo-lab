from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf
from typing import Iterable


@dataclass(frozen=True)
class PerformanceMetrics:
    starting_balance: float
    ending_balance: float
    net_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    total_trades: int
    wins: int
    losses: int
    break_even: int
    win_rate_percent: float
    average_win: float
    average_loss: float
    payoff_ratio: float | None
    expectancy: float
    max_drawdown: float
    max_drawdown_percent: float
    recovery_factor: float | None

    def as_dict(self) -> dict:
        result = asdict(self)
        # JSON has no portable Infinity value. A missing ratio means no losing trades occurred.
        for key in ("profit_factor", "payoff_ratio", "recovery_factor"):
            if result[key] == inf:
                result[key] = None
        return result


def calculate_metrics(net_pnls: Iterable[float], starting_balance: float = 10_000.0) -> PerformanceMetrics:
    trades = [float(value) for value in net_pnls]
    if not trades:
        raise ValueError("At least one completed trade or basket is required")
    if starting_balance <= 0:
        raise ValueError("Starting balance must be greater than zero")

    wins = [value for value in trades if value > 0]
    losses = [value for value in trades if value < 0]
    break_even = len(trades) - len(wins) - len(losses)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_profit = sum(trades)
    ending_balance = starting_balance + net_profit

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else inf
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = gross_loss / len(losses) if losses else 0.0
    payoff_ratio = average_win / average_loss if average_loss > 0 else inf
    expectancy = net_profit / len(trades)

    equity = starting_balance
    peak = starting_balance
    max_drawdown = 0.0
    max_drawdown_percent = 0.0
    for pnl in trades:
        equity += pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        drawdown_percent = (drawdown / peak * 100) if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        max_drawdown_percent = max(max_drawdown_percent, drawdown_percent)

    recovery_factor = net_profit / max_drawdown if max_drawdown > 0 else inf

    return PerformanceMetrics(
        starting_balance=round(starting_balance, 2),
        ending_balance=round(ending_balance, 2),
        net_profit=round(net_profit, 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        profit_factor=round(profit_factor, 5) if profit_factor != inf else inf,
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        break_even=break_even,
        win_rate_percent=round(len(wins) / len(trades) * 100, 5),
        average_win=round(average_win, 5),
        average_loss=round(average_loss, 5),
        payoff_ratio=round(payoff_ratio, 5) if payoff_ratio != inf else inf,
        expectancy=round(expectancy, 5),
        max_drawdown=round(max_drawdown, 2),
        max_drawdown_percent=round(max_drawdown_percent, 5),
        recovery_factor=round(recovery_factor, 5) if recovery_factor != inf else inf,
    )
