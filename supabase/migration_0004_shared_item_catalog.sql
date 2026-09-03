-- Run this once in the SQL editor of your existing project. Adds the
-- shared community item image catalog: a table (globally deduped by
-- template_id, first capture wins) plus a public storage bucket for the
-- actual screenshot files.

create table if not exists item_catalog (
  template_id text primary key,
  storage_path text not null,
  image_url text not null,
  socket_target text,
  contributed_by text,
  captured_at double precision not null,
  created_at timestamptz not null default now()
);

alter table item_catalog enable row level security;
drop policy if exists "public read" on item_catalog;
create policy "public read" on item_catalog for select using (true);
drop policy if exists "public insert" on item_catalog;
create policy "public insert" on item_catalog for insert with check (true);

insert into storage.buckets (id, name, public)
values ('item-snapshots', 'item-snapshots', true)
on conflict (id) do nothing;

drop policy if exists "item snapshots public read" on storage.objects;
create policy "item snapshots public read"
  on storage.objects for select
  using (bucket_id = 'item-snapshots');

drop policy if exists "item snapshots public insert" on storage.objects;
create policy "item snapshots public insert"
  on storage.objects for insert
  with check (bucket_id = 'item-snapshots');
