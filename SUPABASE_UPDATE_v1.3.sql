-- EVE Algo Lab v1.3 — M1 Market Memory and high-resolution replay
-- Run this one file once in Supabase SQL Editor before deploying v1.3.
-- No existing candles or backtest results are deleted or altered.

-- The existing primary key already separates M1 and M5 by interval.
-- This covering index improves forward chronological replay across millions of M1 rows.
create index if not exists market_candles_forward_replay_idx
  on public.market_candles (symbol, interval, candle_time asc)
  include (open, high, low, close, volume);

-- Speed up retrieval of the newest completed run for each resolution.
create index if not exists backtest_runs_resolution_recent_idx
  on public.backtest_runs (resolution, created_at desc);

-- Speed up active-run checks and dashboard polling.
create index if not exists backtest_runs_active_idx
  on public.backtest_runs (status, created_at desc)
  where status in ('queued', 'running');
