from app.backtesting.metrics import calculate_metrics


def test_profit_factor_and_drawdown() -> None:
    result = calculate_metrics([100, -50, 150, -100], starting_balance=1000)
    assert result.net_profit == 100
    assert result.gross_profit == 250
    assert result.gross_loss == 150
    assert result.profit_factor == 1.66667
    assert result.total_trades == 4
    assert result.win_rate_percent == 50
    assert result.max_drawdown == 100


def test_no_losses_returns_null_safe_dict() -> None:
    result = calculate_metrics([10, 20, 30], starting_balance=1000)
    assert result.as_dict()["profit_factor"] is None
