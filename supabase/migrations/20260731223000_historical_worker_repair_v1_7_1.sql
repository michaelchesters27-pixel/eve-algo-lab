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
