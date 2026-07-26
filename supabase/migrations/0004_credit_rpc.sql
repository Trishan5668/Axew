-- 0004_credit_rpc.sql
-- Atomic credit deduction used by the OpusClip processing pipeline.
--
-- Concurrency contract:
--   The SELECT ... FOR UPDATE locks the profile row, so two simultaneous
--   processing requests cannot both pass the balance check and over-deduct.
--   This is required for the QA bar: "deduct_credits RPC is atomic — concurrent
--   calls cannot double-deduct".

create or replace function public.deduct_credits(
    p_user_id uuid,
    p_minutes numeric
) returns numeric
language plpgsql
security definer
set search_path = public
as $$
declare
    v_balance numeric;
    v_new_balance numeric;
begin
    if p_minutes is null or p_minutes <= 0 then
        raise exception 'invalid_minutes'
            using hint = 'Minutes must be a positive number';
    end if;

    select credit_balance
      into v_balance
      from public.profiles
     where id = p_user_id
     for update;

    if not found then
        raise exception 'profile_not_found'
            using hint = 'No profile exists for the given user id';
    end if;

    if v_balance < p_minutes then
        raise exception 'insufficient_credits'
            using hint = 'Purchase more credits in Billing';
    end if;

    v_new_balance := v_balance - p_minutes;

    update public.profiles
       set credit_balance           = v_new_balance,
           total_minutes_processed  = total_minutes_processed + p_minutes
     where id = p_user_id;

    return v_new_balance;
end;
$$;

-- Convenience read used by the frontend useCredits hook when realtime
-- isn't available (e.g. offline mode). Returns a stable snapshot.
create or replace function public.get_credit_summary(p_user_id uuid)
returns table (
    credit_balance numeric,
    total_minutes_processed numeric,
    free_tier_minutes numeric
)
language sql
security definer
set search_path = public
as $$
    select credit_balance, total_minutes_processed, 10::numeric as free_tier_minutes
      from public.profiles
     where id = p_user_id;
$$;
