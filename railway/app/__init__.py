"""EVE Algo Lab Railway service."""

# Twelve Data's XAU/USD H4 candle anchor shifts with the provider/market session
# across DST. Poll H4 frequently and let completed-candle validation decide when
# a new provider bar is safe to store, instead of assuming fixed UTC 4H borders.
from app.services import h4_live_sync_freshness_v1 as _h4_live_sync_freshness_v1  # noqa: F401
