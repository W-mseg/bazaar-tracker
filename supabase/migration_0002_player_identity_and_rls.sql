-- Run this once in the SQL editor of your EXISTING project (the one where
-- you already ran schema.sql). Adds player identity to `runs`, and locks
-- the anon key down to read + insert only, so friends' trackers can sync
-- into this project without being able to touch anyone else's rows.

alter table runs add column if not exists player_username text;
alter table runs add column if not exists player_account_id text;
create index if not exists idx_runs_player on runs(player_account_id);

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
