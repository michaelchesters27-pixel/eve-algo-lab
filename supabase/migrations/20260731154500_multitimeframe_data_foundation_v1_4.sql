-- EVE Algo Lab v1.4 — Multi-timeframe Data Foundation
-- Run once in Supabase SQL Editor before deploying v1.4.
-- Existing M1/M5 candles, jobs, gaps and backtests are preserved.

create index if not exists ingestion_state_status_interval_idx
  on public.ingestion_state (status, interval, updated_at desc);

create index if not exists ingestion_jobs_interval_recent_idx
  on public.ingestion_jobs (symbol, interval, requested_at desc);

-- Reclassify obvious XAU/USD daily maintenance windows and weekend closures so
-- the dashboard separates expected market closures from gaps needing review.
create or replace function public.scan_market_gaps(
  p_symbol text,
  p_interval text,
  p_interval_seconds integer
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_total integer;
  v_review integer;
  v_expected integer;
  v_repaired integer;
  v_review_missing bigint;
  v_expected_missing bigint;
begin
  delete from public.data_gaps
  where symbol = p_symbol
    and interval = p_interval
    and classification <> 'repaired';

  with ordered as (
    select
      candle_time,
      lead(candle_time) over (order by candle_time) as next_time
    from public.market_candles
    where symbol = p_symbol and interval = p_interval
  ), measured as (
    select
      candle_time as gap_start,
      next_time as gap_end,
      extract(epoch from (next_time - candle_time)) as gap_seconds,
      greatest(
        floor(extract(epoch from (next_time - candle_time)) / p_interval_seconds)::integer - 1,
        1
      ) as missing_bars
    from ordered
    where next_time is not null
      and extract(epoch from (next_time - candle_time)) > (p_interval_seconds * 1.5)
  ), gaps as (
    select
      gap_start,
      gap_end,
      missing_bars,
      case
        -- Long closures are normally weekends or holidays.
        when gap_seconds >= 21600 then 'expected_market_closure'
        -- Explicit Friday/weekend transition protection.
        when extract(isodow from gap_start at time zone 'UTC') in (5,6,7)
          and extract(isodow from gap_end at time zone 'UTC') in (1,2,7)
          then 'expected_market_closure'
        -- Gold commonly has a daily maintenance break around the late UTC evening.
        -- Keep this narrow: 30 minutes to 3 hours and around 20:00–23:59 UTC.
        when gap_seconds between 1800 and 10800
          and (
            extract(hour from gap_start at time zone 'UTC') between 20 and 23
            or extract(hour from gap_end at time zone 'UTC') between 20 and 23
          )
          then 'expected_market_closure'
        else 'review'
      end as classification
    from measured
  )
  insert into public.data_gaps (
    symbol, interval, gap_start, gap_end, missing_bars, classification
  )
  select p_symbol, p_interval, gap_start, gap_end, missing_bars, classification
  from gaps
  on conflict (symbol, interval, gap_start, gap_end) do update set
    missing_bars = excluded.missing_bars,
    classification = case
      when data_gaps.classification = 'repaired' then 'repaired'
      else excluded.classification
    end,
    detected_at = now();

  select
    count(*),
    count(*) filter (where classification = 'review'),
    count(*) filter (where classification = 'expected_market_closure'),
    count(*) filter (where classification = 'repaired'),
    coalesce(sum(missing_bars) filter (where classification = 'review'), 0),
    coalesce(sum(missing_bars) filter (where classification = 'expected_market_closure'), 0)
  into
    v_total,
    v_review,
    v_expected,
    v_repaired,
    v_review_missing,
    v_expected_missing
  from public.data_gaps
  where symbol = p_symbol and interval = p_interval;

  return jsonb_build_object(
    'total', v_total,
    'review', v_review,
    'expected', v_expected,
    'repaired', v_repaired,
    'review_missing_bars', v_review_missing,
    'expected_missing_bars', v_expected_missing
  );
end;
$$;

create or replace function public.get_market_dashboard(p_symbol text, p_interval text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'state', coalesce((
      select to_jsonb(s) from public.ingestion_state s
      where s.symbol = p_symbol and s.interval = p_interval
    ), '{}'::jsonb),
    'latest_job', coalesce((
      select to_jsonb(j) from public.ingestion_jobs j
      where j.symbol = p_symbol and j.interval = p_interval
      order by requested_at desc limit 1
    ), '{}'::jsonb),
    'latest_candle', coalesce((
      select to_jsonb(c) from public.market_candles c
      where c.symbol = p_symbol and c.interval = p_interval
      order by candle_time desc limit 1
    ), '{}'::jsonb),
    'gaps', jsonb_build_object(
      'total', (select count(*) from public.data_gaps g where g.symbol = p_symbol and g.interval = p_interval),
      'review', (select count(*) from public.data_gaps g where g.symbol = p_symbol and g.interval = p_interval and g.classification = 'review'),
      'expected', (select count(*) from public.data_gaps g where g.symbol = p_symbol and g.interval = p_interval and g.classification = 'expected_market_closure'),
      'repaired', (select count(*) from public.data_gaps g where g.symbol = p_symbol and g.interval = p_interval and g.classification = 'repaired'),
      'review_missing_bars', (select coalesce(sum(g.missing_bars), 0) from public.data_gaps g where g.symbol = p_symbol and g.interval = p_interval and g.classification = 'review'),
      'expected_missing_bars', (select coalesce(sum(g.missing_bars), 0) from public.data_gaps g where g.symbol = p_symbol and g.interval = p_interval and g.classification = 'expected_market_closure')
    ),
    'events', coalesce((
      select jsonb_agg(to_jsonb(e) order by e.created_at desc)
      from (
        select * from public.system_events
        order by created_at desc limit 12
      ) e
    ), '[]'::jsonb)
  );
$$;

grant execute on function public.scan_market_gaps(text, text, integer) to service_role;
grant execute on function public.get_market_dashboard(text, text) to service_role;
