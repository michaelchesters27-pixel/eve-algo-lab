-- Repair the v1 state where a recent-candle sync could mark an unstarted historical backfill complete.
update public.ingestion_state
set status = 'not_started',
    progress_percent = 0,
    next_end_time = null,
    updated_at = now()
where status = 'complete'
  and earliest_available is null;
