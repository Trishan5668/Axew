-- 0003_payments.sql
-- Razorpay payment ledger + idempotent credit-application RPC.
--
-- Idempotency contract:
--   apply_payment_credits() will not double-credit if the payment row is
--   already 'paid'. Webhook handlers MUST call this RPC instead of updating
--   profiles.credit_balance directly.

create table if not exists public.payments (
    id                   uuid primary key default gen_random_uuid(),
    user_id              uuid not null references public.profiles(id) on delete cascade,
    razorpay_order_id    text not null unique,
    razorpay_payment_id  text unique,
    razorpay_signature   text,
    plan_id              text not null check (plan_id in ('starter', 'creator', 'pro')),
    amount_inr           integer not null,   -- in paise
    credits_purchased    integer not null,
    status               text not null default 'created'
                              check (status in ('created', 'paid', 'failed', 'refunded')),
    created_at           timestamptz not null default now(),
    paid_at              timestamptz,
    failure_reason       text
);

create index if not exists payments_user_idx    on public.payments (user_id, created_at desc);
create index if not exists payments_status_idx  on public.payments (status);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

alter table public.payments enable row level security;

drop policy if exists "Payments: users read own"   on public.payments;
drop policy if exists "Payments: users insert own" on public.payments;

create policy "Payments: users read own"
    on public.payments
    for select
    using (auth.uid() = user_id);

-- Inserts/updates happen ONLY from the server-side service-role key (in
-- apps/ai-service/routers/payments.py). Clients have no insert/update policy.

-- ---------------------------------------------------------------------------
-- apply_payment_credits — atomic, idempotent credit application.
--
-- Guarantees:
--   1. If payment row does not exist, raises 'payment_not_found'.
--   2. If payment row already 'paid', returns false (no double credit).
--   3. Otherwise: increments profile balance and marks payment 'paid' in
--      a single transaction. Concurrent replays serialize on the row lock.
-- ---------------------------------------------------------------------------

create or replace function public.apply_payment_credits(
    p_payment_id uuid,
    p_razorpay_payment_id text,
    p_razorpay_signature text
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid;
    v_credits integer;
    v_status  text;
begin
    -- Lock the payment row for the duration of the transaction
    select user_id, credits_purchased, status
      into v_user_id, v_credits, v_status
      from public.payments
     where id = p_payment_id
     for update;

    if not found then
        raise exception 'payment_not_found' using errcode = 'P0001';
    end if;

    if v_status = 'paid' then
        return false;  -- already applied, do not double-credit
    end if;

    update public.profiles
       set credit_balance = credit_balance + v_credits
     where id = v_user_id;

    update public.payments
       set status              = 'paid',
           paid_at             = now(),
           razorpay_payment_id = p_razorpay_payment_id,
           razorpay_signature  = p_razorpay_signature
     where id = p_payment_id;

    return true;
end;
$$;

create or replace function public.mark_payment_failed(
    p_payment_id uuid,
    p_reason text
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    update public.payments
       set status         = 'failed',
           failure_reason = p_reason
     where id = p_payment_id
       and status in ('created');
end;
$$;

-- ---------------------------------------------------------------------------
-- refund_payment_credits — atomic refund. Subtracts the previously-credited
-- amount from the user's balance and marks the payment row 'refunded'.
--
-- Guarantees:
--   1. Payment must exist and currently be 'paid' — otherwise no-op.
--   2. Balance is clamped at 0; a refund never produces a negative balance
--      (which would block all future processing for the user).
--   3. Returns true if the refund was applied, false if no-op (already
--      refunded or not paid).
-- ---------------------------------------------------------------------------

create or replace function public.refund_payment_credits(
    p_payment_id uuid
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    v_user_id uuid;
    v_credits integer;
    v_status  text;
    v_balance numeric;
begin
    select user_id, credits_purchased, status
      into v_user_id, v_credits, v_status
      from public.payments
     where id = p_payment_id
     for update;

    if not found then
        raise exception 'payment_not_found' using errcode = 'P0001';
    end if;

    if v_status <> 'paid' then
        return false;
    end if;

    select credit_balance into v_balance
      from public.profiles
     where id = v_user_id
     for update;

    update public.profiles
       set credit_balance = greatest(0, v_balance - v_credits)
     where id = v_user_id;

    update public.payments
       set status = 'refunded'
     where id = p_payment_id;

    return true;
end;
$$;
