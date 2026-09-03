-- Run this once in the SQL editor of your existing project. Adds the
-- in-game Day/Hour columns (derived from AppState transitions, not
-- wall-clock time -- see tracker/state.py) to every event table.

alter table runs add column if not exists final_day integer;
alter table runs add column if not exists final_hour integer;

alter table run_items add column if not exists purchased_day integer;
alter table run_items add column if not exists purchased_hour integer;
alter table run_items add column if not exists sold_day integer;
alter table run_items add column if not exists sold_hour integer;

alter table run_combats add column if not exists day integer;
alter table run_combats add column if not exists hour integer;

alter table run_rerolls add column if not exists day integer;
alter table run_rerolls add column if not exists hour integer;

alter table run_skills add column if not exists day integer;
alter table run_skills add column if not exists hour integer;
