-- EVE Algo Lab v2.2 — Autonomous Strategy Evolution Engine
-- Existing candles, learning data, discoveries, strategy candidates and backtests are preserved.

create table if not exists public.strategy_evolution_state (
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  status text not null default 'waiting'
    check (status in ('waiting','active','loading','generating','testing','paused','error')),
  worker_id text,
  heartbeat_at timestamptz,
  current_child_id uuid,
  current_child_name text,
  queue_count integer not null default 0,
  running_count integer not null default 0,
  completed_count bigint not null default 0,
  rejected_count bigint not null default 0,
  development_count bigint not null default 0,
  champion_count bigint not null default 0,
  elite_count bigint not null default 0,
  failed_count bigint not null default 0,
  rows_scanned_total bigint not null default 0,
  lineages_total integer not null default 0,
  improvements_total bigint not null default 0,
  generator_generation integer not null default 0,
  last_generation_at timestamptz,
  last_child_started_at timestamptz,
  last_child_finished_at timestamptz,
  last_result text,
  last_error text,
  started_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (symbol, snapshot_interval)
);

create table if not exists public.strategy_lineages (
  id uuid primary key default gen_random_uuid(),
  lineage_key text not null unique,
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  family text not null,
  name text not null,
  root_strategy_candidate_id uuid references public.strategy_candidates(id) on delete set null,
  status text not null default 'active'
    check (status in ('active','frozen','retired')),
  current_generation integer not null default 0,
  champion_kind text not null default 'strategy'
    check (champion_kind in ('strategy','evolution')),
  champion_id uuid,
  champion_name text,
  champion_rules jsonb not null default '{}'::jsonb,
  champion_metrics jsonb not null default '{}'::jsonb,
  champion_result_status text,
  champion_profit_factor double precision,
  champion_expectancy_r double precision,
  champion_max_drawdown_r double precision,
  champion_trades integer not null default 0,
  champion_validation_score double precision,
  mutations_tested bigint not null default 0,
  improvements bigint not null default 0,
  last_improved_at timestamptz,
  last_result text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.strategy_evolution_candidates (
  id uuid primary key default gen_random_uuid(),
  child_key text not null unique,
  lineage_id uuid not null references public.strategy_lineages(id) on delete cascade,
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  generation integer not null default 1,
  priority integer not null default 50 check (priority between 0 and 100),
  mutation_type text not null,
  parent_kind text not null default 'strategy'
    check (parent_kind in ('strategy','evolution')),
  parent_candidate_id uuid references public.strategy_candidates(id) on delete set null,
  parent_evolution_candidate_id uuid references public.strategy_evolution_candidates(id) on delete set null,
  secondary_parent_candidate_id uuid references public.strategy_candidates(id) on delete set null,
  secondary_parent_evolution_id uuid references public.strategy_evolution_candidates(id) on delete set null,
  name text not null,
  hypothesis text not null,
  parent_rules jsonb not null default '{}'::jsonb,
  rules jsonb not null default '{}'::jsonb,
  changes jsonb not null default '{}'::jsonb,
  selection_config jsonb not null default '{}'::jsonb,
  status text not null default 'queued'
    check (status in ('queued','running','complete','failed')),
  result_status text
    check (result_status is null or result_status in ('rejected','development','champion','elite')),
  selection_passed boolean not null default false,
  promoted_for_next_generation boolean not null default false,
  locked_test_passed boolean not null default false,
  rows_scanned bigint not null default 0,
  trades_total integer not null default 0,
  profit_factor double precision,
  expectancy_r double precision,
  max_drawdown_r double precision,
  win_rate double precision,
  stability_score double precision,
  validation_score double precision,
  parent_validation_score double precision,
  validation_improvement double precision,
  metrics jsonb not null default '{}'::jsonb,
  parent_comparison jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '{}'::jsonb,
  worker_id text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  heartbeat_at timestamptz,
  error text
);

create index if not exists strategy_lineages_rank_idx
  on public.strategy_lineages (status, champion_validation_score desc nulls last, champion_profit_factor desc nulls last);
create index if not exists strategy_evolution_queue_idx
  on public.strategy_evolution_candidates (status, priority desc, requested_at);
create index if not exists strategy_evolution_result_idx
  on public.strategy_evolution_candidates (result_status, validation_improvement desc nulls last, profit_factor desc nulls last);
create index if not exists strategy_evolution_lineage_idx
  on public.strategy_evolution_candidates (lineage_id, generation desc, finished_at desc nulls last);

insert into public.strategy_evolution_state (
  symbol, snapshot_interval, status, last_result
) values (
  'XAU/USD', '15min', 'active',
  'v2.2 is ready to seed strong strategies, mutate their rules and evolve development champions.'
)
on conflict (symbol, snapshot_interval) do update set
  status = 'active',
  last_error = null,
  updated_at = now();

create or replace function public.claim_next_evolution_candidate(p_worker_id text)
returns setof public.strategy_evolution_candidates
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  select id into v_id
  from public.strategy_evolution_candidates
  where status = 'queued'
  order by priority desc, requested_at asc
  for update skip locked
  limit 1;

  if v_id is null then
    return;
  end if;

  update public.strategy_evolution_candidates
  set status = 'running',
      worker_id = p_worker_id,
      started_at = coalesce(started_at, now()),
      heartbeat_at = now(),
      error = null
  where id = v_id;

  return query select * from public.strategy_evolution_candidates where id = v_id;
end;
$$;

create or replace function public.record_evolution_lineage_result(
  p_lineage_id uuid,
  p_candidate_id uuid,
  p_promoted boolean,
  p_generation integer,
  p_result_status text,
  p_name text,
  p_rules jsonb,
  p_metrics jsonb,
  p_profit_factor double precision,
  p_expectancy_r double precision,
  p_max_drawdown_r double precision,
  p_trades integer,
  p_validation_score double precision,
  p_summary text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.strategy_lineages
  set mutations_tested = mutations_tested + 1,
      current_generation = greatest(current_generation, p_generation),
      improvements = improvements + case when p_promoted then 1 else 0 end,
      champion_kind = case when p_promoted then 'evolution' else champion_kind end,
      champion_id = case when p_promoted then p_candidate_id else champion_id end,
      champion_name = case when p_promoted then p_name else champion_name end,
      champion_rules = case when p_promoted then coalesce(p_rules, '{}'::jsonb) else champion_rules end,
      champion_metrics = case when p_promoted then coalesce(p_metrics, '{}'::jsonb) else champion_metrics end,
      champion_result_status = case when p_promoted then p_result_status else champion_result_status end,
      champion_profit_factor = case when p_promoted then p_profit_factor else champion_profit_factor end,
      champion_expectancy_r = case when p_promoted then p_expectancy_r else champion_expectancy_r end,
      champion_max_drawdown_r = case when p_promoted then p_max_drawdown_r else champion_max_drawdown_r end,
      champion_trades = case when p_promoted then coalesce(p_trades, 0) else champion_trades end,
      champion_validation_score = case when p_promoted then p_validation_score else champion_validation_score end,
      last_improved_at = case when p_promoted then now() else last_improved_at end,
      last_result = p_summary,
      updated_at = now()
  where id = p_lineage_id;
end;
$$;

create or replace function public.refresh_strategy_evolution_state(
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
  v_development bigint;
  v_champion bigint;
  v_elite bigint;
  v_failed bigint;
  v_rows bigint;
  v_lineages integer;
  v_improvements bigint;
begin
  select
    count(*) filter (where status = 'queued'),
    count(*) filter (where status = 'running'),
    count(*) filter (where status = 'complete'),
    count(*) filter (where result_status = 'rejected'),
    count(*) filter (where result_status = 'development'),
    count(*) filter (where result_status = 'champion'),
    count(*) filter (where result_status = 'elite'),
    count(*) filter (where status = 'failed'),
    coalesce(sum(rows_scanned) filter (where status = 'complete'), 0)
  into v_queue, v_running, v_complete, v_rejected, v_development,
       v_champion, v_elite, v_failed, v_rows
  from public.strategy_evolution_candidates
  where symbol = p_symbol and snapshot_interval = p_snapshot_interval;

  select count(*), coalesce(sum(improvements),0)
  into v_lineages, v_improvements
  from public.strategy_lineages
  where symbol = p_symbol and snapshot_interval = p_snapshot_interval;

  insert into public.strategy_evolution_state (
    symbol, snapshot_interval, status, queue_count, running_count,
    completed_count, rejected_count, development_count, champion_count,
    elite_count, failed_count, rows_scanned_total, lineages_total,
    improvements_total, updated_at
  ) values (
    p_symbol, p_snapshot_interval, 'active', coalesce(v_queue,0), coalesce(v_running,0),
    coalesce(v_complete,0), coalesce(v_rejected,0), coalesce(v_development,0),
    coalesce(v_champion,0), coalesce(v_elite,0), coalesce(v_failed,0),
    coalesce(v_rows,0), coalesce(v_lineages,0), coalesce(v_improvements,0), now()
  )
  on conflict (symbol, snapshot_interval) do update set
    queue_count = excluded.queue_count,
    running_count = excluded.running_count,
    completed_count = excluded.completed_count,
    rejected_count = excluded.rejected_count,
    development_count = excluded.development_count,
    champion_count = excluded.champion_count,
    elite_count = excluded.elite_count,
    failed_count = excluded.failed_count,
    rows_scanned_total = excluded.rows_scanned_total,
    lineages_total = excluded.lineages_total,
    improvements_total = excluded.improvements_total,
    updated_at = now();
end;
$$;

create or replace function public.get_strategy_evolution_dashboard(
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
      select to_jsonb(s) from public.strategy_evolution_state s
      where s.symbol = p_symbol and s.snapshot_interval = p_snapshot_interval
    ), '{}'::jsonb),
    'current_child', coalesce((
      select to_jsonb(c) from public.strategy_evolution_candidates c
      where c.symbol = p_symbol and c.snapshot_interval = p_snapshot_interval and c.status = 'running'
      order by c.started_at desc limit 1
    ), '{}'::jsonb),
    'best_lineage', coalesce((
      select to_jsonb(l) from public.strategy_lineages l
      where l.symbol = p_symbol and l.snapshot_interval = p_snapshot_interval and l.status = 'active'
      order by
        case l.champion_result_status when 'elite' then 4 when 'champion' then 3 when 'validated' then 2 when 'promising' then 1 else 0 end desc,
        l.champion_validation_score desc nulls last,
        l.champion_profit_factor desc nulls last
      limit 1
    ), '{}'::jsonb),
    'lineages', coalesce((
      select jsonb_agg(to_jsonb(l) order by l.champion_validation_score desc nulls last, l.updated_at desc)
      from (
        select * from public.strategy_lineages
        where symbol = p_symbol and snapshot_interval = p_snapshot_interval and status = 'active'
        order by champion_validation_score desc nulls last, updated_at desc
        limit 20
      ) l
    ), '[]'::jsonb),
    'recent_children', coalesce((
      select jsonb_agg(to_jsonb(c) order by c.finished_at desc nulls last)
      from (
        select * from public.strategy_evolution_candidates
        where symbol = p_symbol and snapshot_interval = p_snapshot_interval and status = 'complete'
        order by finished_at desc nulls last limit 20
      ) c
    ), '[]'::jsonb)
  );
$$;

alter table public.strategy_evolution_state enable row level security;
alter table public.strategy_lineages enable row level security;
alter table public.strategy_evolution_candidates enable row level security;

grant all on public.strategy_evolution_state to service_role;
grant all on public.strategy_lineages to service_role;
grant all on public.strategy_evolution_candidates to service_role;

revoke all on function public.claim_next_evolution_candidate(text) from public, anon, authenticated;
revoke all on function public.record_evolution_lineage_result(uuid,uuid,boolean,integer,text,text,jsonb,jsonb,double precision,double precision,double precision,integer,double precision,text) from public, anon, authenticated;
revoke all on function public.refresh_strategy_evolution_state(text,text) from public, anon, authenticated;
revoke all on function public.get_strategy_evolution_dashboard(text,text) from public, anon, authenticated;

grant execute on function public.claim_next_evolution_candidate(text) to service_role;
grant execute on function public.record_evolution_lineage_result(uuid,uuid,boolean,integer,text,text,jsonb,jsonb,double precision,double precision,double precision,integer,double precision,text) to service_role;
grant execute on function public.refresh_strategy_evolution_state(text,text) to service_role;
grant execute on function public.get_strategy_evolution_dashboard(text,text) to service_role;

notify pgrst, 'reload schema';
