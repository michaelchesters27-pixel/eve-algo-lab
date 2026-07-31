-- EVE Algo Lab v1.7 — Continuous Historical Research Worker
-- Run this complete file once in Supabase SQL Editor before deploying v1.7.
-- Existing candles, learning snapshots, discoveries, models and backtests are preserved.

create table if not exists public.historical_research_state (
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  status text not null default 'waiting'
    check (status in ('waiting','active','loading','researching','paused','error')),
  worker_id text,
  heartbeat_at timestamptz,
  current_job_id uuid,
  current_question text,
  queue_count integer not null default 0,
  running_count integer not null default 0,
  completed_count bigint not null default 0,
  rejected_count bigint not null default 0,
  promising_count bigint not null default 0,
  validated_count bigint not null default 0,
  failed_count bigint not null default 0,
  rows_scanned_total bigint not null default 0,
  jobs_seeded_total bigint not null default 0,
  generator_generation integer not null default 0,
  last_generation_at timestamptz,
  last_job_started_at timestamptz,
  last_job_finished_at timestamptz,
  last_result text,
  last_error text,
  started_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (symbol, snapshot_interval)
);

create table if not exists public.historical_research_jobs (
  id uuid primary key default gen_random_uuid(),
  job_key text not null unique,
  symbol text not null default 'XAU/USD',
  snapshot_interval text not null default '15min',
  generation integer not null default 1,
  priority integer not null default 50 check (priority between 0 and 100),
  category text not null default 'continuous_historical_research',
  question text not null,
  rationale text,
  test_definition jsonb not null default '{}'::jsonb,
  status text not null default 'queued'
    check (status in ('queued','running','complete','failed')),
  result_status text
    check (result_status is null or result_status in ('rejected','promising','validated')),
  rows_scanned bigint not null default 0,
  sample_count integer not null default 0,
  effect_size double precision,
  confidence_score double precision,
  stability_score double precision,
  summary text,
  evidence jsonb not null default '{}'::jsonb,
  worker_id text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  heartbeat_at timestamptz,
  error text
);

create index if not exists historical_research_jobs_queue_idx
  on public.historical_research_jobs (status, priority desc, requested_at);
create index if not exists historical_research_jobs_recent_idx
  on public.historical_research_jobs (symbol, snapshot_interval, finished_at desc nulls last);
create index if not exists historical_research_jobs_result_idx
  on public.historical_research_jobs (result_status, confidence_score desc nulls last);

insert into public.historical_research_state (
  symbol, snapshot_interval, status, last_result
) values (
  'XAU/USD', '15min', 'active',
  'v1.7 is ready to generate and test historical questions continuously on Railway.'
)
on conflict (symbol, snapshot_interval) do update set
  status = 'active',
  last_error = null,
  updated_at = now();

create or replace function public.claim_next_historical_research_job(p_worker_id text)
returns setof public.historical_research_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  select id into v_id
  from public.historical_research_jobs
  where status = 'queued'
  order by priority desc, requested_at asc
  for update skip locked
  limit 1;

  if v_id is null then
    return;
  end if;

  update public.historical_research_jobs
  set status = 'running',
      worker_id = p_worker_id,
      started_at = coalesce(started_at, now()),
      heartbeat_at = now(),
      error = null
  where id = v_id;

  return query
  select * from public.historical_research_jobs where id = v_id;
end;
$$;

create or replace function public.refresh_historical_research_state(
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
  v_completed bigint;
  v_rejected bigint;
  v_promising bigint;
  v_validated bigint;
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
    count(*) filter (where status = 'failed'),
    coalesce(sum(rows_scanned) filter (where status = 'complete'), 0),
    count(*)
  into
    v_queue, v_running, v_completed, v_rejected, v_promising,
    v_validated, v_failed, v_rows, v_seeded
  from public.historical_research_jobs
  where symbol = p_symbol and snapshot_interval = p_snapshot_interval;

  insert into public.historical_research_state (
    symbol, snapshot_interval, status, queue_count, running_count,
    completed_count, rejected_count, promising_count, validated_count,
    failed_count, rows_scanned_total, jobs_seeded_total, updated_at
  ) values (
    p_symbol, p_snapshot_interval, 'active', coalesce(v_queue,0), coalesce(v_running,0),
    coalesce(v_completed,0), coalesce(v_rejected,0), coalesce(v_promising,0),
    coalesce(v_validated,0), coalesce(v_failed,0), coalesce(v_rows,0),
    coalesce(v_seeded,0), now()
  )
  on conflict (symbol, snapshot_interval) do update set
    queue_count = excluded.queue_count,
    running_count = excluded.running_count,
    completed_count = excluded.completed_count,
    rejected_count = excluded.rejected_count,
    promising_count = excluded.promising_count,
    validated_count = excluded.validated_count,
    failed_count = excluded.failed_count,
    rows_scanned_total = excluded.rows_scanned_total,
    jobs_seeded_total = excluded.jobs_seeded_total,
    updated_at = now();
end;
$$;

create or replace function public.get_historical_research_dashboard(
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
      select to_jsonb(s)
      from public.historical_research_state s
      where s.symbol = p_symbol and s.snapshot_interval = p_snapshot_interval
    ), '{}'::jsonb),
    'current_job', coalesce((
      select to_jsonb(j)
      from public.historical_research_jobs j
      where j.symbol = p_symbol
        and j.snapshot_interval = p_snapshot_interval
        and j.status = 'running'
      order by j.started_at desc limit 1
    ), '{}'::jsonb),
    'latest_job', coalesce((
      select to_jsonb(j)
      from public.historical_research_jobs j
      where j.symbol = p_symbol
        and j.snapshot_interval = p_snapshot_interval
        and j.status in ('complete','failed')
      order by j.finished_at desc nulls last limit 1
    ), '{}'::jsonb),
    'recent_jobs', coalesce((
      select jsonb_agg(to_jsonb(j) order by j.finished_at desc nulls last)
      from (
        select * from public.historical_research_jobs
        where symbol = p_symbol
          and snapshot_interval = p_snapshot_interval
          and status in ('complete','failed')
        order by finished_at desc nulls last
        limit 12
      ) j
    ), '[]'::jsonb)
  );
$$;

alter table public.historical_research_state enable row level security;
alter table public.historical_research_jobs enable row level security;

revoke all on function public.claim_next_historical_research_job(text) from public, anon, authenticated;
revoke all on function public.refresh_historical_research_state(text, text) from public, anon, authenticated;
revoke all on function public.get_historical_research_dashboard(text, text) from public, anon, authenticated;

grant execute on function public.claim_next_historical_research_job(text) to service_role;
grant execute on function public.refresh_historical_research_state(text, text) to service_role;
grant execute on function public.get_historical_research_dashboard(text, text) to service_role;
-- EVE Algo Lab v1.7.1 — Historical worker startup repair
-- Run this complete file once in Supabase SQL Editor.
-- It preserves all candles, learning snapshots, questions, findings and backtests.

-- The v1.7 worker writes heartbeat and job progress through PostgREST using the
-- service-role key. Explicit grants ensure the two new RLS tables are visible to
-- that role instead of returning REST 404 responses.
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.historical_research_state to service_role;
grant select, insert, update, delete on table public.historical_research_jobs to service_role;

-- Recover jobs left running by a Railway restart through a security-definer RPC.
-- v1.7.1 calls this RPC during startup rather than issuing the failing direct PATCH.
create or replace function public.reset_stale_historical_research_jobs(
  p_stale_minutes integer default 20
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer;
begin
  update public.historical_research_jobs
  set status = 'queued',
      worker_id = null,
      started_at = null,
      heartbeat_at = null,
      error = 'Recovered automatically after Railway restart'
  where status = 'running'
    and (
      heartbeat_at is null
      or heartbeat_at < now() - make_interval(mins => greatest(1, p_stale_minutes))
    );

  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

revoke all on function public.reset_stale_historical_research_jobs(integer)
  from public, anon, authenticated;
grant execute on function public.reset_stale_historical_research_jobs(integer)
  to service_role;

-- Ensure the state row exists and clear the failed startup message.
insert into public.historical_research_state (
  symbol, snapshot_interval, status, last_result, last_error, updated_at
) values (
  'XAU/USD', '15min', 'active',
  'v1.7.1 storage permissions repaired. Waiting for Railway worker heartbeat.',
  null, now()
)
on conflict (symbol, snapshot_interval) do update set
  status = 'active',
  last_error = null,
  last_result = 'v1.7.1 storage permissions repaired. Waiting for Railway worker heartbeat.',
  updated_at = now();

-- Force Supabase PostgREST to refresh its table/function schema immediately.
notify pgrst, 'reload schema';
