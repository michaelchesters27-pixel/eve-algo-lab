-- EVE Algo Lab v2.0 — Autonomous Strategy Idea Factory
-- Existing candles, learning data, discoveries, models and backtests are preserved.

create table if not exists public.strategy_lab_state (
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  status text not null default 'waiting'
    check (status in ('waiting','active','loading','generating','testing','paused','error')),
  worker_id text,
  heartbeat_at timestamptz,
  current_candidate_id uuid,
  current_candidate_name text,
  queue_count integer not null default 0,
  running_count integer not null default 0,
  completed_count bigint not null default 0,
  rejected_count bigint not null default 0,
  promising_count bigint not null default 0,
  validated_count bigint not null default 0,
  elite_count bigint not null default 0,
  failed_count bigint not null default 0,
  rows_scanned_total bigint not null default 0,
  candidates_seeded_total bigint not null default 0,
  generator_generation integer not null default 0,
  last_generation_at timestamptz,
  last_candidate_started_at timestamptz,
  last_candidate_finished_at timestamptz,
  last_result text,
  last_error text,
  started_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (symbol, snapshot_interval)
);

create table if not exists public.strategy_candidates (
  id uuid primary key default gen_random_uuid(),
  candidate_key text not null unique,
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  generation integer not null default 1,
  priority integer not null default 50 check (priority between 0 and 100),
  source_research_job_id uuid references public.historical_research_jobs(id) on delete set null,
  source_job_key text,
  source_question text,
  name text not null,
  family text not null,
  hypothesis text not null,
  rules jsonb not null default '{}'::jsonb,
  backtest_config jsonb not null default '{}'::jsonb,
  status text not null default 'queued'
    check (status in ('queued','running','complete','failed')),
  result_status text
    check (result_status is null or result_status in ('rejected','promising','validated','elite')),
  rows_scanned bigint not null default 0,
  trades_total integer not null default 0,
  profit_factor double precision,
  expectancy_r double precision,
  max_drawdown_r double precision,
  win_rate double precision,
  stability_score double precision,
  baseline_profit_factor double precision,
  improvement_score double precision,
  metrics jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '{}'::jsonb,
  worker_id text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  heartbeat_at timestamptz,
  error text
);

create index if not exists strategy_candidates_queue_idx
  on public.strategy_candidates (status, priority desc, requested_at);
create index if not exists strategy_candidates_result_idx
  on public.strategy_candidates (result_status, profit_factor desc nulls last, expectancy_r desc nulls last);
create index if not exists strategy_candidates_source_idx
  on public.strategy_candidates (source_job_key, family, requested_at desc);

insert into public.strategy_lab_state (
  symbol, snapshot_interval, status, last_result
) values (
  'XAU/USD', '15min', 'active',
  'v2.0 is ready to convert validated research into testable strategy candidates.'
)
on conflict (symbol, snapshot_interval) do update set
  status = 'active',
  last_error = null,
  updated_at = now();

create or replace function public.claim_next_strategy_candidate(p_worker_id text)
returns setof public.strategy_candidates
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  select id into v_id
  from public.strategy_candidates
  where status = 'queued'
  order by priority desc, requested_at asc
  for update skip locked
  limit 1;

  if v_id is null then
    return;
  end if;

  update public.strategy_candidates
  set status = 'running',
      worker_id = p_worker_id,
      started_at = coalesce(started_at, now()),
      heartbeat_at = now(),
      error = null
  where id = v_id;

  return query select * from public.strategy_candidates where id = v_id;
end;
$$;

create or replace function public.refresh_strategy_lab_state(
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
  v_promising bigint;
  v_validated bigint;
  v_elite bigint;
  v_failed bigint;
  v_rows bigint;
  v_seeded bigint;
begin
  select
    count(*) filter (where status = 'queued'),
    count(*) filter (where status = 'running'),
    count(*) filter (where status = 'complete'),
    count(*) filter (where result_status = 'rejected'),
    count(*) filter (where result_status = 'promising'),
    count(*) filter (where result_status = 'validated'),
    count(*) filter (where result_status = 'elite'),
    count(*) filter (where status = 'failed'),
    coalesce(sum(rows_scanned) filter (where status = 'complete'), 0),
    count(*)
  into v_queue, v_running, v_complete, v_rejected, v_promising,
       v_validated, v_elite, v_failed, v_rows, v_seeded
  from public.strategy_candidates
  where symbol = p_symbol and snapshot_interval = p_snapshot_interval;

  insert into public.strategy_lab_state (
    symbol, snapshot_interval, status, queue_count, running_count,
    completed_count, rejected_count, promising_count, validated_count,
    elite_count, failed_count, rows_scanned_total, candidates_seeded_total, updated_at
  ) values (
    p_symbol, p_snapshot_interval, 'active', coalesce(v_queue,0), coalesce(v_running,0),
    coalesce(v_complete,0), coalesce(v_rejected,0), coalesce(v_promising,0),
    coalesce(v_validated,0), coalesce(v_elite,0), coalesce(v_failed,0),
    coalesce(v_rows,0), coalesce(v_seeded,0), now()
  )
  on conflict (symbol, snapshot_interval) do update set
    queue_count = excluded.queue_count,
    running_count = excluded.running_count,
    completed_count = excluded.completed_count,
    rejected_count = excluded.rejected_count,
    promising_count = excluded.promising_count,
    validated_count = excluded.validated_count,
    elite_count = excluded.elite_count,
    failed_count = excluded.failed_count,
    rows_scanned_total = excluded.rows_scanned_total,
    candidates_seeded_total = excluded.candidates_seeded_total,
    updated_at = now();
end;
$$;

create or replace function public.get_strategy_lab_dashboard(
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
      select to_jsonb(s) from public.strategy_lab_state s
      where s.symbol = p_symbol and s.snapshot_interval = p_snapshot_interval
    ), '{}'::jsonb),
    'current_candidate', coalesce((
      select to_jsonb(c) from public.strategy_candidates c
      where c.symbol = p_symbol and c.snapshot_interval = p_snapshot_interval and c.status = 'running'
      order by c.started_at desc limit 1
    ), '{}'::jsonb),
    'best_candidate', coalesce((
      select to_jsonb(c) from public.strategy_candidates c
      where c.symbol = p_symbol and c.snapshot_interval = p_snapshot_interval
        and c.status = 'complete' and c.result_status in ('elite','validated','promising')
      order by
        case c.result_status when 'elite' then 4 when 'validated' then 3 when 'promising' then 2 else 1 end desc,
        c.profit_factor desc nulls last,
        c.expectancy_r desc nulls last
      limit 1
    ), '{}'::jsonb),
    'recent_candidates', coalesce((
      select jsonb_agg(to_jsonb(c) order by c.finished_at desc nulls last)
      from (
        select * from public.strategy_candidates
        where symbol = p_symbol and snapshot_interval = p_snapshot_interval and status = 'complete'
        order by finished_at desc nulls last limit 12
      ) c
    ), '[]'::jsonb)
  );
$$;

alter table public.strategy_lab_state enable row level security;
alter table public.strategy_candidates enable row level security;

grant all on public.strategy_lab_state to service_role;
grant all on public.strategy_candidates to service_role;

revoke all on function public.claim_next_strategy_candidate(text) from public, anon, authenticated;
revoke all on function public.refresh_strategy_lab_state(text, text) from public, anon, authenticated;
revoke all on function public.get_strategy_lab_dashboard(text, text) from public, anon, authenticated;

grant execute on function public.claim_next_strategy_candidate(text) to service_role;
grant execute on function public.refresh_strategy_lab_state(text, text) to service_role;
grant execute on function public.get_strategy_lab_dashboard(text, text) to service_role;

notify pgrst, 'reload schema';
