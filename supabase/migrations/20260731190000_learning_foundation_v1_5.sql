-- EVE Algo Lab v1.5 — Learning Foundation
-- Run this entire file once in Supabase SQL Editor before deploying v1.5.
-- Existing candles, ingestion history and backtests are preserved.

create table if not exists public.learning_runs (
  id uuid primary key default gen_random_uuid(),
  symbol text not null default 'XAU/USD',
  source_interval text not null default '5min',
  snapshot_interval text not null default '15min',
  status text not null default 'queued'
    check (status in ('queued','running','complete','failed','cancelled')),
  stage text not null default 'queued',
  progress_percent numeric(7,3) not null default 0,
  message text,
  full_rebuild boolean not null default false,
  cursor_time timestamptz,
  source_rows_scanned bigint not null default 0,
  snapshots_written bigint not null default 0,
  outcome_labels_written bigint not null default 0,
  questions_generated integer not null default 0,
  discoveries_created integer not null default 0,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  heartbeat_at timestamptz,
  worker_id text,
  error text
);

create index if not exists learning_runs_queue_idx
  on public.learning_runs (status, requested_at);
create index if not exists learning_runs_recent_idx
  on public.learning_runs (symbol, snapshot_interval, requested_at desc);

create table if not exists public.learning_state (
  symbol text not null,
  snapshot_interval text not null default '15min',
  status text not null default 'not_started'
    check (status in ('not_started','queued','building','ready','error')),
  feature_version text not null default 'eve-features-v1',
  initial_build_complete boolean not null default false,
  auto_update_enabled boolean not null default true,
  last_snapshot_time timestamptz,
  source_latest_time timestamptz,
  snapshots_count bigint not null default 0,
  complete_outcomes_count bigint not null default 0,
  outcome_labels_count bigint not null default 0,
  calendar_stat_count integer not null default 0,
  question_count integer not null default 0,
  discovery_count integer not null default 0,
  prediction_count bigint not null default 0,
  graded_prediction_count bigint not null default 0,
  approved_model_key text,
  challenger_model_key text,
  last_run_id uuid references public.learning_runs(id) on delete set null,
  last_success_at timestamptz,
  last_error text,
  updated_at timestamptz not null default now(),
  primary key (symbol, snapshot_interval)
);

drop trigger if exists learning_state_updated_at on public.learning_state;
create trigger learning_state_updated_at
before update on public.learning_state
for each row execute function public.set_updated_at();

create table if not exists public.market_learning_snapshots (
  symbol text not null,
  snapshot_interval text not null default '15min',
  source_interval text not null default '5min',
  candle_time timestamptz not null,
  open double precision not null,
  high double precision not null,
  low double precision not null,
  close double precision not null,
  volume double precision,
  weekday smallint not null check (weekday between 1 and 7),
  month smallint not null check (month between 1 and 12),
  quarter smallint not null check (quarter between 1 and 4),
  hour_utc smallint not null check (hour_utc between 0 and 23),
  week_of_month smallint not null check (week_of_month between 1 and 6),
  session text not null,
  direction smallint not null check (direction between -1 and 1),
  range_price double precision not null,
  body_price double precision not null,
  upper_wick double precision not null,
  lower_wick double precision not null,
  close_location double precision,
  atr_14 double precision,
  average_range_12 double precision,
  volatility_12 double precision,
  compression_ratio double precision,
  return_1_pct double precision,
  return_3_pct double precision,
  return_12_pct double precision,
  return_48_pct double precision,
  return_288_pct double precision,
  context_m15_return_pct double precision,
  context_h1_return_pct double precision,
  context_h4_return_pct double precision,
  context_d1_return_pct double precision,
  trend_12_atr double precision,
  trend_48_atr double precision,
  streak smallint not null default 0,
  regime text not null,
  alignment_score smallint not null default 0,
  outcomes jsonb not null default '{}'::jsonb,
  outcome_horizons smallint[] not null default '{}'::smallint[],
  outcome_complete boolean not null default false,
  feature_version text not null default 'eve-features-v1',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (symbol, snapshot_interval, candle_time)
);

create index if not exists market_learning_snapshot_time_idx
  on public.market_learning_snapshots (symbol, snapshot_interval, candle_time desc);
create index if not exists market_learning_calendar_idx
  on public.market_learning_snapshots (weekday, month, hour_utc, session);
create index if not exists market_learning_regime_idx
  on public.market_learning_snapshots (regime, alignment_score, candle_time desc);

drop trigger if exists market_learning_snapshots_updated_at on public.market_learning_snapshots;
create trigger market_learning_snapshots_updated_at
before update on public.market_learning_snapshots
for each row execute function public.set_updated_at();

create table if not exists public.calendar_statistics (
  id bigint generated by default as identity primary key,
  symbol text not null default 'XAU/USD',
  dimension text not null,
  bucket_key text not null,
  bucket_label text not null,
  sample_count integer not null default 0,
  average_range double precision,
  median_range double precision,
  average_range_pct double precision,
  median_range_pct double precision,
  average_return_pct double precision,
  average_absolute_return_pct double precision,
  positive_close_rate double precision,
  directional_day_rate double precision,
  effect_vs_baseline_pct double precision,
  metrics jsonb not null default '{}'::jsonb,
  calculated_from timestamptz,
  calculated_to timestamptz,
  updated_at timestamptz not null default now(),
  unique (symbol, dimension, bucket_key)
);

create index if not exists calendar_statistics_lookup_idx
  on public.calendar_statistics (symbol, dimension, effect_vs_baseline_pct desc);

create table if not exists public.prediction_ledger (
  id uuid primary key default gen_random_uuid(),
  symbol text not null default 'XAU/USD',
  model_key text not null,
  source text not null default 'eve',
  snapshot_time timestamptz not null,
  horizon_minutes integer not null check (horizon_minutes > 0),
  predicted_direction text check (predicted_direction in ('up','down','flat','unclear')),
  probability_up double precision,
  probability_down double precision,
  probability_flat double precision,
  expected_move_atr double precision,
  explanation jsonb not null default '{}'::jsonb,
  status text not null default 'pending'
    check (status in ('pending','graded','void')),
  actual_direction text check (actual_direction in ('up','down','flat','unclear')),
  actual_return_pct double precision,
  actual_max_up_atr double precision,
  actual_max_down_atr double precision,
  brier_score double precision,
  grade jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  graded_at timestamptz
);

create index if not exists prediction_ledger_pending_idx
  on public.prediction_ledger (status, snapshot_time);
create index if not exists prediction_ledger_model_idx
  on public.prediction_ledger (model_key, created_at desc);

create table if not exists public.research_questions (
  id uuid primary key default gen_random_uuid(),
  question_key text not null unique,
  symbol text not null default 'XAU/USD',
  category text not null,
  question text not null,
  rationale text,
  priority integer not null default 50 check (priority between 0 and 100),
  status text not null default 'queued'
    check (status in ('queued','testing','promising','answered','rejected','archived')),
  generated_by text not null default 'eve-learning-foundation',
  evidence jsonb not null default '{}'::jsonb,
  test_definition jsonb not null default '{}'::jsonb,
  sample_count integer,
  effect_size double precision,
  confidence_score double precision,
  generated_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists research_questions_queue_idx
  on public.research_questions (status, priority desc, generated_at desc);

drop trigger if exists research_questions_updated_at on public.research_questions;
create trigger research_questions_updated_at
before update on public.research_questions
for each row execute function public.set_updated_at();

create table if not exists public.discoveries (
  id uuid primary key default gen_random_uuid(),
  discovery_key text not null unique,
  symbol text not null default 'XAU/USD',
  question_id uuid references public.research_questions(id) on delete set null,
  title text not null,
  summary text not null,
  category text not null,
  status text not null default 'exploratory'
    check (status in ('exploratory','promising','validated','rejected','retired')),
  sample_count integer not null default 0,
  effect_size double precision,
  confidence_score double precision,
  stability_score double precision,
  evidence jsonb not null default '{}'::jsonb,
  first_observed_at timestamptz,
  last_observed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists discoveries_status_idx
  on public.discoveries (status, confidence_score desc, created_at desc);

drop trigger if exists discoveries_updated_at on public.discoveries;
create trigger discoveries_updated_at
before update on public.discoveries
for each row execute function public.set_updated_at();

create table if not exists public.model_registry (
  id uuid primary key default gen_random_uuid(),
  model_key text not null unique,
  name text not null,
  model_type text not null,
  role text not null check (role in ('approved','challenger','retired','foundation')),
  status text not null default 'ready'
    check (status in ('building','testing','ready','failed','retired')),
  version text not null,
  trained_from timestamptz,
  trained_to timestamptz,
  feature_version text,
  metrics jsonb not null default '{}'::jsonb,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists model_registry_updated_at on public.model_registry;
create trigger model_registry_updated_at
before update on public.model_registry
for each row execute function public.set_updated_at();

insert into public.model_registry (
  model_key, name, model_type, role, status, version, feature_version, metrics, notes
) values (
  'baseline-statistics-v1',
  'EVE Statistical Baseline',
  'descriptive_statistics',
  'approved',
  'ready',
  '1.0',
  'eve-features-v1',
  '{"purpose":"calibration baseline","predictions_enabled":false}'::jsonb,
  'Foundation model used to measure future challengers. It does not issue live predictions in v1.5.'
)
on conflict (model_key) do update set
  name = excluded.name,
  model_type = excluded.model_type,
  role = excluded.role,
  status = excluded.status,
  version = excluded.version,
  feature_version = excluded.feature_version,
  metrics = excluded.metrics,
  notes = excluded.notes,
  updated_at = now();

insert into public.learning_state (
  symbol, snapshot_interval, approved_model_key
) values (
  'XAU/USD', '15min', 'baseline-statistics-v1'
)
on conflict (symbol, snapshot_interval) do update set
  approved_model_key = coalesce(learning_state.approved_model_key, excluded.approved_model_key),
  updated_at = now();

create or replace function public.claim_next_learning_run(p_worker_id text)
returns setof public.learning_runs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  select id into v_id
  from public.learning_runs
  where status = 'queued'
  order by requested_at
  for update skip locked
  limit 1;

  if v_id is null then
    return;
  end if;

  return query
  update public.learning_runs
  set status = 'running',
      stage = case when stage = 'queued' then 'preparing' else stage end,
      started_at = coalesce(started_at, now()),
      heartbeat_at = now(),
      worker_id = p_worker_id,
      message = 'Learning run claimed by Railway worker'
  where id = v_id
  returning *;
end;
$$;

create or replace function public.refresh_learning_state(p_symbol text, p_snapshot_interval text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_snapshots bigint;
  v_complete bigint;
  v_labels bigint;
  v_latest timestamptz;
  v_source_latest timestamptz;
  v_calendar integer;
  v_questions integer;
  v_discoveries integer;
  v_predictions bigint;
  v_graded bigint;
begin
  select
    count(*),
    count(*) filter (where outcome_complete),
    coalesce(sum(cardinality(outcome_horizons)), 0),
    max(candle_time)
  into v_snapshots, v_complete, v_labels, v_latest
  from public.market_learning_snapshots
  where symbol = p_symbol and snapshot_interval = p_snapshot_interval;

  select max(candle_time) into v_source_latest
  from public.market_candles
  where symbol = p_symbol and interval = '5min';

  select count(*) into v_calendar
  from public.calendar_statistics where symbol = p_symbol;
  select count(*) into v_questions
  from public.research_questions where symbol = p_symbol;
  select count(*) into v_discoveries
  from public.discoveries where symbol = p_symbol;
  select count(*), count(*) filter (where status = 'graded')
  into v_predictions, v_graded
  from public.prediction_ledger where symbol = p_symbol;

  insert into public.learning_state (
    symbol, snapshot_interval, snapshots_count, complete_outcomes_count,
    outcome_labels_count, last_snapshot_time, source_latest_time,
    calendar_stat_count, question_count, discovery_count,
    prediction_count, graded_prediction_count, updated_at
  ) values (
    p_symbol, p_snapshot_interval, v_snapshots, v_complete,
    v_labels, v_latest, v_source_latest,
    v_calendar, v_questions, v_discoveries,
    v_predictions, v_graded, now()
  )
  on conflict (symbol, snapshot_interval) do update set
    snapshots_count = excluded.snapshots_count,
    complete_outcomes_count = excluded.complete_outcomes_count,
    outcome_labels_count = excluded.outcome_labels_count,
    last_snapshot_time = excluded.last_snapshot_time,
    source_latest_time = excluded.source_latest_time,
    calendar_stat_count = excluded.calendar_stat_count,
    question_count = excluded.question_count,
    discovery_count = excluded.discovery_count,
    prediction_count = excluded.prediction_count,
    graded_prediction_count = excluded.graded_prediction_count,
    updated_at = now();
end;
$$;

create or replace function public.get_learning_dashboard(p_symbol text, p_snapshot_interval text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'state', coalesce((
      select to_jsonb(s) from public.learning_state s
      where s.symbol = p_symbol and s.snapshot_interval = p_snapshot_interval
    ), '{}'::jsonb),
    'latest_run', coalesce((
      select to_jsonb(r) from public.learning_runs r
      where r.symbol = p_symbol and r.snapshot_interval = p_snapshot_interval
      order by requested_at desc limit 1
    ), '{}'::jsonb),
    'approved_model', coalesce((
      select to_jsonb(m) from public.model_registry m
      where m.model_key = (
        select approved_model_key from public.learning_state
        where symbol = p_symbol and snapshot_interval = p_snapshot_interval
      ) limit 1
    ), '{}'::jsonb),
    'challenger_model', coalesce((
      select to_jsonb(m) from public.model_registry m
      where m.model_key = (
        select challenger_model_key from public.learning_state
        where symbol = p_symbol and snapshot_interval = p_snapshot_interval
      ) limit 1
    ), '{}'::jsonb),
    'calendar_statistics', coalesce((
      select jsonb_agg(to_jsonb(c) order by c.dimension, c.bucket_key)
      from public.calendar_statistics c
      where c.symbol = p_symbol
    ), '[]'::jsonb),
    'questions', coalesce((
      select jsonb_agg(to_jsonb(q) order by q.priority desc, q.generated_at desc)
      from (
        select * from public.research_questions
        where symbol = p_symbol and status <> 'archived'
        order by priority desc, generated_at desc limit 12
      ) q
    ), '[]'::jsonb),
    'discoveries', coalesce((
      select jsonb_agg(to_jsonb(d) order by d.confidence_score desc nulls last, d.created_at desc)
      from (
        select * from public.discoveries
        where symbol = p_symbol and status not in ('rejected','retired')
        order by confidence_score desc nulls last, created_at desc limit 12
      ) d
    ), '[]'::jsonb)
  );
$$;

alter table public.learning_runs enable row level security;
alter table public.learning_state enable row level security;
alter table public.market_learning_snapshots enable row level security;
alter table public.calendar_statistics enable row level security;
alter table public.prediction_ledger enable row level security;
alter table public.research_questions enable row level security;
alter table public.discoveries enable row level security;
alter table public.model_registry enable row level security;

revoke all on function public.claim_next_learning_run(text) from public, anon, authenticated;
revoke all on function public.refresh_learning_state(text, text) from public, anon, authenticated;
revoke all on function public.get_learning_dashboard(text, text) from public, anon, authenticated;

grant execute on function public.claim_next_learning_run(text) to service_role;
grant execute on function public.refresh_learning_state(text, text) to service_role;
grant execute on function public.get_learning_dashboard(text, text) to service_role;
