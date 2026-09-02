-- Run this once in the Supabase SQL editor for a new project.
-- Mirrors the local SQLite schema in tracker/db.py, keyed by run_uuid
-- instead of the local autoincrement run_id so multiple machines can sync
-- into the same project without collisions.

create extension if not exists pgcrypto;

create table if not exists runs (
  run_uuid uuid primary key,
  started_at double precision not null,
  ended_at double precision,
  hero text,
  game_mode text,
  result text,
  rank_delta integer not null default 0,
  created_at timestamptz not null default now(),
  player_username text,
  player_account_id text
);
create index if not exists idx_runs_player on runs(player_account_id);

create table if not exists run_items (
  id bigint generated always as identity primary key,
  run_uuid uuid not null references runs(run_uuid) on delete cascade,
  instance_id text not null,
  template_id text not null,
  socket_target text,
  purchased_at double precision not null,
  sold_at double precision,
  sell_price integer
);
create index if not exists idx_run_items_run on run_items(run_uuid);
create index if not exists idx_run_items_template on run_items(template_id);

create table if not exists run_combats (
  id bigint generated always as identity primary key,
  run_uuid uuid not null references runs(run_uuid) on delete cascade,
  combat_type text not null,
  started_at double precision not null,
  ended_at double precision,
  duration_ms integer,
  frames integer
);
create index if not exists idx_run_combats_run on run_combats(run_uuid);

create table if not exists run_rerolls (
  id bigint generated always as identity primary key,
  run_uuid uuid not null references runs(run_uuid) on delete cascade,
  occurred_at double precision not null
);

create table if not exists run_skills (
  id bigint generated always as identity primary key,
  run_uuid uuid not null references runs(run_uuid) on delete cascade,
  skill_id text not null,
  socket text,
  selected_at double precision not null
);

create table if not exists run_metrics (
  run_uuid uuid primary key references runs(run_uuid) on delete cascade,
  wins integer,
  gold integer,
  prestige integer,
  level integer,
  income integer,
  max_health integer,
  won boolean
);

-- Item performance: purchase/sale counts + win-rate at the 4/7/10-win thresholds.
--
-- IMPORTANT: "times_purchased" / "runs_with_item" only reflect items that were
-- actually bought. The game's shop offers aren't visible in Player.log, so this
-- is NOT a true drop-rate -- it under-counts items that were offered and skipped.
-- Treat it as a biased proxy, as agreed in the design doc.
create or replace view item_stats as
select
  ri.template_id,
  count(*) as times_purchased,
  count(*) filter (where ri.sold_at is not null) as times_sold,
  count(distinct ri.run_uuid) as runs_with_item,
  count(distinct ri.run_uuid) filter (where rm.wins >= 4) as runs_reaching_4_wins,
  count(distinct ri.run_uuid) filter (where rm.wins >= 7) as runs_reaching_7_wins,
  count(distinct ri.run_uuid) filter (where rm.wins >= 10) as runs_reaching_10_wins
from run_items ri
left join run_metrics rm on rm.run_uuid = ri.run_uuid
group by ri.template_id;

-- Row Level Security: the anon key (handed out to friends so their own
-- tracker can sync into this same project) may only read everything and
-- insert new rows. Update/delete stay owner-only (the service_role key
-- bypasses RLS entirely and is never shared).
alter table runs enable row level security;
alter table run_items enable row level security;
alter table run_combats enable row level security;
alter table run_rerolls enable row level security;
alter table run_skills enable row level security;
alter table run_metrics enable row level security;

do $$
declare
  t text;
begin
  foreach t in array array['runs','run_items','run_combats','run_rerolls','run_skills','run_metrics']
  loop
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select using (true)', t);
    execute format('drop policy if exists "public insert" on %I', t);
    execute format('create policy "public insert" on %I for insert with check (true)', t);
  end loop;
end $$;
