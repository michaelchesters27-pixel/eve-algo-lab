-- EVE Algo Lab v2.3 — Automatic High-Resolution Validation Pipeline
-- Existing candles, learning, research, strategies, evolution lineages and backtests are preserved.

create table if not exists public.strategy_validation_state (
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  status text not null default 'waiting'
    check (status in ('waiting','active','loading','replaying','paused','error')),
  worker_id text,
  heartbeat_at timestamptz,
  current_job_id uuid,
  current_job_name text,
  queue_count integer not null default 0,
  running_count integer not null default 0,
  completed_count bigint not null default 0,
  rejected_count bigint not null default 0,
  needs_evidence_count bigint not null default 0,
  replay_validated_count bigint not null default 0,
  mt5_ready_count bigint not null default 0,
  failed_count bigint not null default 0,
  rows_scanned_total bigint not null default 0,
  m1_windows_scanned_total bigint not null default 0,
  last_generation_at timestamptz,
  last_job_started_at timestamptz,
  last_job_finished_at timestamptz,
  last_result text,
  last_error text,
  started_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (symbol, snapshot_interval)
);

create table if not exists public.strategy_validation_jobs (
  id uuid primary key default gen_random_uuid(),
  validation_key text not null unique,
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  source_kind text not null check (source_kind in ('strategy','evolution')),
  source_strategy_candidate_id uuid references public.strategy_candidates(id) on delete set null,
  source_evolution_candidate_id uuid references public.strategy_evolution_candidates(id) on delete set null,
  source_lineage_id uuid references public.strategy_lineages(id) on delete set null,
  name text not null,
  family text not null default 'unknown',
  rules jsonb not null default '{}'::jsonb,
  source_result_status text,
  source_profit_factor double precision,
  source_expectancy_r double precision,
  source_metrics jsonb not null default '{}'::jsonb,
  priority integer not null default 50 check (priority between 0 and 100),
  status text not null default 'queued'
    check (status in ('queued','running','complete','failed')),
  result_status text
    check (result_status is null or result_status in ('rejected','needs_more_evidence','replay_validated','ready_for_mt5_generation')),
  rows_scanned bigint not null default 0,
  m1_windows_scanned bigint not null default 0,
  trades_total integer not null default 0,
  profit_factor double precision,
  expectancy_r double precision,
  max_drawdown_r double precision,
  win_rate double precision,
  year_stability double precision,
  resolved_rate double precision,
  robust_profile_ratio double precision,
  rules_hash text,
  frozen_rules jsonb not null default '{}'::jsonb,
  metrics jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '{}'::jsonb,
  progress_done integer not null default 0,
  progress_total integer not null default 0,
  worker_id text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  heartbeat_at timestamptz,
  error text
);

create table if not exists public.frozen_strategies (
  id uuid primary key default gen_random_uuid(),
  strategy_code text not null unique,
  rule_hash text not null unique,
  symbol text not null default 'XAU/USD',
  source_validation_job_id uuid not null references public.strategy_validation_jobs(id) on delete restrict,
  source_kind text not null,
  source_id uuid,
  name text not null,
  family text not null default 'unknown',
  version text not null,
  rules jsonb not null,
  validation_metrics jsonb not null default '{}'::jsonb,
  validation_evidence jsonb not null default '{}'::jsonb,
  status text not null default 'ready_for_mt5_generation'
    check (status in ('ready_for_mt5_generation','mt5_generated','demo_testing','retired')),
  frozen_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists strategy_validation_queue_idx
  on public.strategy_validation_jobs (status, priority desc, requested_at);
create index if not exists strategy_validation_result_idx
  on public.strategy_validation_jobs (result_status, profit_factor desc nulls last, expectancy_r desc nulls last);
create index if not exists strategy_validation_source_idx
  on public.strategy_validation_jobs (source_kind, source_strategy_candidate_id, source_evolution_candidate_id);
create index if not exists frozen_strategies_status_idx
  on public.frozen_strategies (status, frozen_at desc);

insert into public.strategy_validation_state (symbol, snapshot_interval, status, last_result)
values (
  'XAU/USD', '15min', 'active',
  'v2.3 is ready to take surviving strategies through automatic M1 replay, execution-cost stress and parameter-neighbour validation.'
)
on conflict (symbol, snapshot_interval) do update set
  status = 'active',
  last_error = null,
  updated_at = now();

create or replace function public.claim_next_validation_job(p_worker_id text)
returns setof public.strategy_validation_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  select id into v_id
  from public.strategy_validation_jobs
  where status = 'queued'
  order by priority desc, requested_at asc
  for update skip locked
  limit 1;

  if v_id is null then
    return;
  end if;

  update public.strategy_validation_jobs
  set status = 'running',
      worker_id = p_worker_id,
      started_at = coalesce(started_at, now()),
      heartbeat_at = now(),
      error = null
  where id = v_id;

  return query select * from public.strategy_validation_jobs where id = v_id;
end;
$$;

create or replace function public.refresh_strategy_validation_state(
  p_symbol text,
  p_snapshot_interval text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_queue integer;
  v_running integer;
  v_complete bigint;
  v_rejected bigint;
  v_needs bigint;
  v_replay bigint;
  v_ready bigint;
  v_failed bigint;
  v_rows bigint;
  v_windows bigint;
begin
  select
    count(*) filter (where status = 'queued'),
    count(*) filter (where status = 'running'),
    count(*) filter (where status = 'complete'),
    count(*) filter (where result_status = 'rejected'),
    count(*) filter (where result_status = 'needs_more_evidence'),
    count(*) filter (where result_status = 'replay_validated'),
    count(*) filter (where result_status = 'ready_for_mt5_generation'),
    count(*) filter (where status = 'failed'),
    coalesce(sum(rows_scanned) filter (where status = 'complete'), 0),
    coalesce(sum(m1_windows_scanned) filter (where status = 'complete'), 0)
  into v_queue, v_running, v_complete, v_rejected, v_needs,
       v_replay, v_ready, v_failed, v_rows, v_windows
  from public.strategy_validation_jobs
  where symbol = p_symbol and snapshot_interval = p_snapshot_interval;

  insert into public.strategy_validation_state (
    symbol, snapshot_interval, status, queue_count, running_count,
    completed_count, rejected_count, needs_evidence_count,
    replay_validated_count, mt5_ready_count, failed_count,
    rows_scanned_total, m1_windows_scanned_total, updated_at
  ) values (
    p_symbol, p_snapshot_interval, 'active', coalesce(v_queue,0), coalesce(v_running,0),
    coalesce(v_complete,0), coalesce(v_rejected,0), coalesce(v_needs,0),
    coalesce(v_replay,0), coalesce(v_ready,0), coalesce(v_failed,0),
    coalesce(v_rows,0), coalesce(v_windows,0), now()
  )
  on conflict (symbol, snapshot_interval) do update set
    queue_count = excluded.queue_count,
    running_count = excluded.running_count,
    completed_count = excluded.completed_count,
    rejected_count = excluded.rejected_count,
    needs_evidence_count = excluded.needs_evidence_count,
    replay_validated_count = excluded.replay_validated_count,
    mt5_ready_count = excluded.mt5_ready_count,
    failed_count = excluded.failed_count,
    rows_scanned_total = excluded.rows_scanned_total,
    m1_windows_scanned_total = excluded.m1_windows_scanned_total,
    updated_at = now();
end;
$$;

create or replace function public.get_strategy_validation_dashboard(
  p_symbol text,
  p_snapshot_interval text
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'state', coalesce((
      select to_jsonb(s) from public.strategy_validation_state s
      where s.symbol = p_symbol and s.snapshot_interval = p_snapshot_interval
    ), '{}'::jsonb),
    'current_job', coalesce((
      select to_jsonb(j) from public.strategy_validation_jobs j
      where j.symbol = p_symbol and j.snapshot_interval = p_snapshot_interval and j.status = 'running'
      order by j.started_at desc limit 1
    ), '{}'::jsonb),
    'best_ready', coalesce((
      select to_jsonb(j) from public.strategy_validation_jobs j
      where j.symbol = p_symbol and j.snapshot_interval = p_snapshot_interval
        and j.status = 'complete' and j.result_status = 'ready_for_mt5_generation'
      order by j.profit_factor desc nulls last, j.expectancy_r desc nulls last
      limit 1
    ), '{}'::jsonb),
    'recent_jobs', coalesce((
      select jsonb_agg(to_jsonb(j) order by j.finished_at desc nulls last)
      from (
        select * from public.strategy_validation_jobs
        where symbol = p_symbol and snapshot_interval = p_snapshot_interval and status = 'complete'
        order by finished_at desc nulls last limit 20
      ) j
    ), '[]'::jsonb),
    'frozen_strategies', coalesce((
      select jsonb_agg(to_jsonb(f) order by f.frozen_at desc)
      from (
        select * from public.frozen_strategies
        where symbol = p_symbol and status = 'ready_for_mt5_generation'
        order by frozen_at desc limit 20
      ) f
    ), '[]'::jsonb)
  );
$$;

alter table public.strategy_validation_state enable row level security;
alter table public.strategy_validation_jobs enable row level security;
alter table public.frozen_strategies enable row level security;

grant all on public.strategy_validation_state to service_role;
grant all on public.strategy_validation_jobs to service_role;
grant all on public.frozen_strategies to service_role;

revoke all on function public.claim_next_validation_job(text) from public, anon, authenticated;
revoke all on function public.refresh_strategy_validation_state(text,text) from public, anon, authenticated;
revoke all on function public.get_strategy_validation_dashboard(text,text) from public, anon, authenticated;

grant execute on function public.claim_next_validation_job(text) to service_role;
grant execute on function public.refresh_strategy_validation_state(text,text) to service_role;
grant execute on function public.get_strategy_validation_dashboard(text,text) to service_role;

notify pgrst, 'reload schema';
