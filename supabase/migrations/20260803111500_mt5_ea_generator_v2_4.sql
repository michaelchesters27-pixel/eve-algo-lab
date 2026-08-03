-- EVE Algo Lab v2.4 — Automatic MT5 EA Generator
-- Run this entire file once in Supabase SQL Editor before deploying v2.4.
-- Existing candles, learning, research, strategies, evolution and validation are preserved.

create extension if not exists pgcrypto;

create table if not exists public.mt5_generation_state (
  symbol text primary key default 'XAU/USD',
  status text not null default 'waiting',
  worker_id text,
  heartbeat_at timestamptz,
  current_job_id uuid,
  current_job_name text,
  queue_count integer not null default 0,
  running_count integer not null default 0,
  completed_count bigint not null default 0,
  generated_count bigint not null default 0,
  failed_count bigint not null default 0,
  last_generation_at timestamptz,
  last_job_started_at timestamptz,
  last_job_finished_at timestamptz,
  last_result text,
  last_error text,
  started_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists public.mt5_generation_jobs (
  id uuid primary key default gen_random_uuid(),
  generation_key text not null unique,
  symbol text not null default 'XAU/USD',
  frozen_strategy_id uuid not null references public.frozen_strategies(id) on delete restrict,
  strategy_code text not null,
  strategy_name text not null,
  frozen_version text not null default '1.0',
  rule_hash text not null,
  priority integer not null default 90 check (priority between 0 and 100),
  status text not null default 'queued' check (status in ('queued','running','complete','failed')),
  result_status text check (result_status is null or result_status in ('generated','static_validation_failed')),
  package_id uuid,
  file_name text,
  source_sha256 text,
  evidence jsonb not null default '{}'::jsonb,
  worker_id text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  heartbeat_at timestamptz,
  error text
);

create table if not exists public.mt5_packages (
  id uuid primary key default gen_random_uuid(),
  package_code text not null unique,
  symbol text not null default 'XAU/USD',
  frozen_strategy_id uuid not null unique references public.frozen_strategies(id) on delete restrict,
  source_generation_job_id uuid references public.mt5_generation_jobs(id) on delete set null,
  strategy_code text not null,
  strategy_name text not null,
  frozen_version text not null default '1.0',
  rule_hash text not null,
  file_name text not null,
  mq5_source text not null,
  readme_text text not null,
  frozen_rules jsonb not null default '{}'::jsonb,
  validation_report jsonb not null default '{}'::jsonb,
  manifest jsonb not null default '{}'::jsonb,
  source_sha256 text not null,
  static_validation jsonb not null default '{}'::jsonb,
  status text not null default 'ready_for_metaeditor_compile'
    check (status in ('ready_for_metaeditor_compile','compiled','demo_testing','retired')),
  generated_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Add the circular job/package link only after both tables exist.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'mt5_generation_jobs_package_id_fkey'
      and conrelid = 'public.mt5_generation_jobs'::regclass
  ) then
    alter table public.mt5_generation_jobs
      add constraint mt5_generation_jobs_package_id_fkey
      foreign key (package_id) references public.mt5_packages(id) on delete set null;
  end if;
end $$;

create index if not exists mt5_generation_queue_idx
  on public.mt5_generation_jobs (status, priority desc, requested_at);
create index if not exists mt5_generation_result_idx
  on public.mt5_generation_jobs (result_status, finished_at desc nulls last);
create index if not exists mt5_packages_status_idx
  on public.mt5_packages (status, generated_at desc);
create index if not exists mt5_packages_strategy_idx
  on public.mt5_packages (strategy_code, frozen_version);

insert into public.mt5_generation_state (symbol, status, last_result)
values (
  'XAU/USD', 'active',
  'v2.4 is ready to convert frozen strategies into versioned MT5 source packages automatically.'
)
on conflict (symbol) do update set
  status = 'active',
  last_error = null,
  updated_at = now();

create or replace function public.claim_next_mt5_generation_job(p_worker_id text)
returns setof public.mt5_generation_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  select id into v_id
  from public.mt5_generation_jobs
  where status = 'queued'
  order by priority desc, requested_at asc
  for update skip locked
  limit 1;

  if v_id is null then
    return;
  end if;

  update public.mt5_generation_jobs
  set status = 'running',
      worker_id = p_worker_id,
      started_at = coalesce(started_at, now()),
      heartbeat_at = now(),
      error = null
  where id = v_id;

  return query select * from public.mt5_generation_jobs where id = v_id;
end;
$$;

create or replace function public.refresh_mt5_generation_state(p_symbol text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_queue integer;
  v_running integer;
  v_complete bigint;
  v_generated bigint;
  v_failed bigint;
begin
  select
    count(*) filter (where status = 'queued'),
    count(*) filter (where status = 'running'),
    count(*) filter (where status = 'complete'),
    count(*) filter (where result_status = 'generated'),
    count(*) filter (where status = 'failed')
  into v_queue, v_running, v_complete, v_generated, v_failed
  from public.mt5_generation_jobs
  where symbol = p_symbol;

  insert into public.mt5_generation_state (
    symbol, status, queue_count, running_count, completed_count,
    generated_count, failed_count, updated_at
  ) values (
    p_symbol, 'active', coalesce(v_queue,0), coalesce(v_running,0),
    coalesce(v_complete,0), coalesce(v_generated,0), coalesce(v_failed,0), now()
  )
  on conflict (symbol) do update set
    queue_count = excluded.queue_count,
    running_count = excluded.running_count,
    completed_count = excluded.completed_count,
    generated_count = excluded.generated_count,
    failed_count = excluded.failed_count,
    updated_at = now();
end;
$$;

create or replace function public.get_mt5_generation_dashboard(p_symbol text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'state', coalesce((
      select to_jsonb(s) from public.mt5_generation_state s where s.symbol = p_symbol
    ), '{}'::jsonb),
    'current_job', coalesce((
      select to_jsonb(j) from public.mt5_generation_jobs j
      where j.symbol = p_symbol and j.status = 'running'
      order by j.started_at desc limit 1
    ), '{}'::jsonb),
    'best_package', coalesce((
      select to_jsonb(p) - 'mq5_source' - 'readme_text'
      from public.mt5_packages p
      where p.symbol = p_symbol and p.status = 'ready_for_metaeditor_compile'
      order by
        coalesce((p.validation_report #>> '{validation_metrics,standard_cost,locked_test,profit_factor}')::double precision,0) desc,
        p.generated_at desc
      limit 1
    ), '{}'::jsonb),
    'recent_packages', coalesce((
      select jsonb_agg(to_jsonb(p) - 'mq5_source' - 'readme_text' order by p.generated_at desc)
      from (
        select * from public.mt5_packages
        where symbol = p_symbol
        order by generated_at desc limit 20
      ) p
    ), '[]'::jsonb)
  );
$$;

alter table public.mt5_generation_state enable row level security;
alter table public.mt5_generation_jobs enable row level security;
alter table public.mt5_packages enable row level security;

grant all on public.mt5_generation_state to service_role;
grant all on public.mt5_generation_jobs to service_role;
grant all on public.mt5_packages to service_role;

revoke all on function public.claim_next_mt5_generation_job(text) from public, anon, authenticated;
revoke all on function public.refresh_mt5_generation_state(text) from public, anon, authenticated;
revoke all on function public.get_mt5_generation_dashboard(text) from public, anon, authenticated;

grant execute on function public.claim_next_mt5_generation_job(text) to service_role;
grant execute on function public.refresh_mt5_generation_state(text) to service_role;
grant execute on function public.get_mt5_generation_dashboard(text) to service_role;

notify pgrst, 'reload schema';
