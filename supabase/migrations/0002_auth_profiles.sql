-- 0002_auth_profiles.sql
-- User profile table backing AXEW cloud-mode auth.
--
-- RLS is enabled and locked down so users can only read/update their own row.
-- The auto-creation trigger guarantees that every account starts with the
-- free-tier credit grant (10 minutes) without any client-side code path.

create table if not exists public.profiles (
    id                       uuid primary key references auth.users(id) on delete cascade,
    email                    text not null,
    display_name             text,
    avatar_url               text,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now(),
    total_minutes_processed  numeric(10, 2) not null default 0,
    credit_balance           numeric(10, 2) not null default 10  -- free tier: 10 minutes
);

create index if not exists profiles_email_idx on public.profiles (lower(email));

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

alter table public.profiles enable row level security;

drop policy if exists "Profiles: users read own"   on public.profiles;
drop policy if exists "Profiles: users update own" on public.profiles;

create policy "Profiles: users read own"
    on public.profiles
    for select
    using (auth.uid() = id);

create policy "Profiles: users update own"
    on public.profiles
    for update
    using (auth.uid() = id)
    with check (auth.uid() = id);

-- NOTE: There is intentionally NO insert policy. Profile rows are only
-- created by the SECURITY DEFINER trigger below; client code cannot insert.

-- ---------------------------------------------------------------------------
-- Auto-create profile on signup. SECURITY DEFINER lets the trigger insert
-- into a RLS-protected table on behalf of the new auth.users row.
-- ---------------------------------------------------------------------------

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email)
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
    before update on public.profiles
    for each row execute procedure public.touch_updated_at();
