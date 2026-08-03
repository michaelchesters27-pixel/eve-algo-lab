-- EVE Command Centre v3.1 — Organised Bot Library + Live Demo Fleet
-- Run this entire file once in Supabase SQL Editor before deploying v3.1.
-- This adds live MT5 heartbeat storage only. Existing candles, research,
-- strategy creation, mutation, validation and generated packages are untouched.

create table if not exists public.mt5_fleet_instances (
  instance_key text primary key,
  package_id uuid references public.mt5_packages(id) on delete set null,
  strategy_code text not null,
  rule_hash text not null,
  account_login bigint not null,
  account_type text not null default 'unknown'
    check (account_type in ('demo','contest','real','unknown')),
  broker_server text not null default '',
  broker_company text not null default '',
  symbol text not null,
  timeframe text not null,
  chart_id text not null default '',
  trading_enabled boolean not null default false,
  algo_trading_enabled boolean not null default false,
  state text not null default 'starting',
  state_detail text not null default '',
  open_positions integer not null default 0,
  open_profit double precision not null default 0,
  closed_profit_today double precision not null default 0,
  terminal_time timestamptz,
  last_trade_time timestamptz,
  heartbeat_at timestamptz not null default now(),
  detached_at timestamptz,
  client_version text not null default '',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists mt5_fleet_heartbeat_idx
  on public.mt5_fleet_instances (heartbeat_at desc);
create index if not exists mt5_fleet_strategy_idx
  on public.mt5_fleet_instances (strategy_code, account_login, symbol, timeframe);
create index if not exists mt5_fleet_package_idx
  on public.mt5_fleet_instances (package_id, heartbeat_at desc);

alter table public.mt5_fleet_instances enable row level security;
grant all on public.mt5_fleet_instances to service_role;

comment on table public.mt5_fleet_instances is
  'Latest best-effort MT5 heartbeat per attached EVE EA chart. Trading never depends on telemetry.';
