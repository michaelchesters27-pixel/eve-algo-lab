from datetime import datetime, timezone

from app.backtesting.fixed_ladder_v261 import Candle, FixedLadderParameters, FixedLadderV261Backtester
from app.models.schemas import FixedLadderBacktestRequest


def test_request_accepts_m1_replay_resolution() -> None:
    request = FixedLadderBacktestRequest(resolution="m1_replay")
    assert request.resolution == "m1_replay"
    assert request.interval == "5min"


def test_m1_bar_can_remove_m5_two_sided_ambiguity() -> None:
    engine = FixedLadderV261Backtester(
        1000,
        FixedLadderParameters(spread_price=0.0, path_mode="open_high_low_close"),
    )
    engine._rearm(100.0)  # deliberate white-box test of replay uncertainty classification

    m5 = Candle(datetime(2026, 1, 1, tzinfo=timezone.utc), 100.0, 104.0, 96.0, 100.0)
    m1_directional = Candle(datetime(2026, 1, 1, tzinfo=timezone.utc), 100.0, 104.0, 99.0, 103.0)

    assert engine._is_ambiguous(m5) is True
    assert engine._is_ambiguous(m1_directional) is False
