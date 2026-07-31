-- EVE Algo Lab v1.6 — Autonomous Learning Engine
-- Run this entire file once in Supabase SQL Editor before deploying v1.6.
-- Existing candles, learning snapshots, research, discoveries and backtests are preserved.

alter table public.learning_state
  add column if not exists autonomous_learning_enabled boolean not null default true,
  add column if not exists autonomous_status text not null default 'waiting',
  add column if not exists auto_cycle_interval_minutes integer not null default 15,
  add column if not exists last_auto_cycle_at timestamptz,
  add column if not exists next_auto_cycle_at timestamptz,
  add column if not exists last_incremental_learning_at timestamptz,
  add column if not exists last_research_cycle_at timestamptz,
  add column if not exists last_model_training_at timestamptz,
  add column if not exists pending_outcomes_count bigint not null default 0,
  add column if not exists predictions_pending_count bigint not null default 0,
  add column if not exists questions_tested_total bigint not null default 0,
  add column if not exists questions_tested_last_cycle integer not null default 0,
  add column if not exists discoveries_promising_count integer not null default 0,
  add column if not exists discoveries_validated_count integer not null default 0,
  add column if not exists discoveries_rejected_count integer not null default 0,
  add column if not exists model_promotions_count integer not null default 0,
  add column if not exists last_auto_message text,
  add column if not exists last_auto_error text;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'learning_state_autonomous_status_check'
      and conrelid = 'public.learning_state'::regclass
  ) then
    alter table public.learning_state
      add constraint learning_state_autonomous_status_check
      check (autonomous_status in ('waiting','active','researching','training','paused','error'));
  end if;
end $$;

alter table public.model_registry
  add column if not exists artifact jsonb not null default '{}'::jsonb,
  add column if not exists training_rows bigint not null default 0,
  add column if not exists validation_rows bigint not null default 0,
  add column if not exists test_rows bigint not null default 0,
  add column if not exists promotable boolean not null default false,
  add column if not exists promotion_reason text,
  add column if not exists parent_model_key text,
  add column if not exists promoted_at timestamptz,
  add column if not exists evaluation_period jsonb not null default '{}'::jsonb;

create unique index if not exists prediction_ledger_unique_prediction_idx
  on public.prediction_ledger (symbol, model_key, snapshot_time, horizon_minutes);

create table if not exists public.autonomous_runs (
  id uuid primary key default gen_random_uuid(),
  symbol text not null default 'XAU/USD',
  cycle_type text not null default 'full_cycle'
    check (cycle_type in ('full_cycle','incremental_learning','research','model_training','prediction','diagnostic')),
  trigger_source text not null default 'scheduled'
    check (trigger_source in ('scheduled','manual','startup','recovery')),
  status text not null default 'running'
    check (status in ('queued','running','complete','failed','skipped')),
  stage text not null default 'starting',
  message text,
  metrics jsonb not null default '{}'::jsonb,
  worker_id text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  heartbeat_at timestamptz,
  error text
);

create index if not exists autonomous_runs_recent_idx
  on public.autonomous_runs (symbol, started_at desc);
create index if not exists autonomous_runs_status_idx
  on public.autonomous_runs (status, started_at desc);

create table if not exists public.autonomous_research_reports (
  id uuid primary key default gen_random_uuid(),
  symbol text not null default 'XAU/USD',
  report_date date not null,
  cycle_started_at timestamptz not null default now(),
  questions_tested integer not null default 0,
  questions_rejected integer not null default 0,
  discoveries_promising integer not null default 0,
  discoveries_validated integer not null default 0,
  summary text not null,
  metrics jsonb not null default '{}'::jsonb,
  findings jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (symbol, report_date)
);

create index if not exists autonomous_research_reports_recent_idx
  on public.autonomous_research_reports (symbol, report_date desc);

drop trigger if exists autonomous_research_reports_updated_at on public.autonomous_research_reports;
create trigger autonomous_research_reports_updated_at
before update on public.autonomous_research_reports
for each row execute function public.set_updated_at();

create or replace function public.refresh_autonomous_learning_state(
  p_symbol text,
  p_snapshot_interval text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_pending_outcomes bigint;
  v_pending_predictions bigint;
  v_questions_tested bigint;
  v_questions_last integer;
  v_promising integer;
  v_validated integer;
  v_rejected integer;
  v_last_cycle timestamptz;
  v_last_message text;
begin
  select count(*) into v_pending_outcomes
  from public.market_learning_snapshots
  where symbol = p_symbol
    and snapshot_interval = p_snapshot_interval
    and outcome_complete = false;

  select count(*) into v_pending_predictions
  from public.prediction_ledger
  where symbol = p_symbol and status = 'pending';

  select coalesce(sum(coalesce((metrics->>'questions_tested')::bigint, 0)), 0)
  into v_questions_tested
  from public.autonomous_runs
  where symbol = p_symbol and status = 'complete';

  select
    coalesce((metrics->>'questions_tested')::integer, 0),
    started_at,
    message
  into v_questions_last, v_last_cycle, v_last_message
  from public.autonomous_runs
  where symbol = p_symbol
  order by started_at desc
  limit 1;

  select count(*) filter (where status = 'promising'),
         count(*) filter (where status = 'validated'),
         count(*) filter (where status = 'rejected')
  into v_promising, v_validated, v_rejected
  from public.discoveries
  where symbol = p_symbol;

  update public.learning_state
  set pending_outcomes_count = coalesce(v_pending_outcomes, 0),
      predictions_pending_count = coalesce(v_pending_predictions, 0),
      questions_tested_total = coalesce(v_questions_tested, 0),
      questions_tested_last_cycle = coalesce(v_questions_last, 0),
      discoveries_promising_count = coalesce(v_promising, 0),
      discoveries_validated_count = coalesce(v_validated, 0),
      discoveries_rejected_count = coalesce(v_rejected, 0),
      last_auto_cycle_at = coalesce(v_last_cycle, last_auto_cycle_at),
      last_auto_message = coalesce(v_last_message, last_auto_message),
      updated_at = now()
  where symbol = p_symbol and snapshot_interval = p_snapshot_interval;
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
    'latest_autonomous_run', coalesce((
      select to_jsonb(a) from public.autonomous_runs a
      where a.symbol = p_symbol
      order by started_at desc limit 1
    ), '{}'::jsonb),
    'approved_model', coalesce((
      select to_jsonb(m) - 'artifact' from public.model_registry m
      where m.model_key = (
        select approved_model_key from public.learning_state
        where symbol = p_symbol and snapshot_interval = p_snapshot_interval
      ) limit 1
    ), '{}'::jsonb),
    'challenger_model', coalesce((
      select to_jsonb(m) - 'artifact' from public.model_registry m
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
        order by priority desc, generated_at desc limit 20
      ) q
    ), '[]'::jsonb),
    'discoveries', coalesce((
      select jsonb_agg(to_jsonb(d) order by d.confidence_score desc nulls last, d.created_at desc)
      from (
        select * from public.discoveries
        where symbol = p_symbol and status not in ('retired')
        order by
          case status when 'validated' then 1 when 'promising' then 2 when 'exploratory' then 3 else 4 end,
          confidence_score desc nulls last,
          created_at desc
        limit 20
      ) d
    ), '[]'::jsonb),
    'research_reports', coalesce((
      select jsonb_agg(to_jsonb(r) order by r.report_date desc)
      from (
        select * from public.autonomous_research_reports
        where symbol = p_symbol
        order by report_date desc limit 7
      ) r
    ), '[]'::jsonb),
    'recent_predictions', coalesce((
      select jsonb_agg(to_jsonb(p) order by p.snapshot_time desc, p.horizon_minutes)
      from (
        select * from public.prediction_ledger
        where symbol = p_symbol
        order by snapshot_time desc, horizon_minutes
        limit 18
      ) p
    ), '[]'::jsonb)
  );
$$;

update public.learning_state
set autonomous_learning_enabled = true,
    autonomous_status = case when initial_build_complete then 'active' else 'waiting' end,
    auto_cycle_interval_minutes = 15,
    last_auto_message = case
      when initial_build_complete then 'Autonomous v1.6 learning will start after Railway redeploys.'
      else 'Build the initial learning foundation once; autonomy starts immediately afterwards.'
    end,
    updated_at = now()
where symbol = 'XAU/USD' and snapshot_interval = '15min';

alter table public.autonomous_runs enable row level security;
alter table public.autonomous_research_reports enable row level security;

revoke all on function public.refresh_autonomous_learning_state(text, text) from public, anon, authenticated;
revoke all on function public.get_learning_dashboard(text, text) from public, anon, authenticated;

grant execute on function public.refresh_autonomous_learning_state(text, text) to service_role;
grant execute on function public.get_learning_dashboard(text, text) to service_role;
