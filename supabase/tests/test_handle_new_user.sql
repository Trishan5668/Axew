-- ============================================================================
-- test_handle_new_user.sql — pgTAP-style verification of the trigger that
-- runs on every new auth.users row insert.
--
-- This is the SQL equivalent of test_profile_created_on_signup from the
-- spec. It can't live alongside the Python pytests because it depends on
-- the live Supabase auth schema (auth.users). Run it after applying the
-- migrations:
--
--   supabase db reset
--   psql "$(supabase status -o env | grep DATABASE_URL | cut -d= -f2 | tr -d '"')" \
--        -f supabase/tests/test_handle_new_user.sql
--
-- All assertions use plain RAISE EXCEPTION so the script exits non-zero on
-- failure — no pgTAP extension required.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Test 1: inserting a new auth.users row creates a profile with 10 credits
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    test_user_id uuid := gen_random_uuid();
    found_email text;
    found_balance numeric;
    found_processed numeric;
BEGIN
    INSERT INTO auth.users (id, email, instance_id, aud, role,
                            email_confirmed_at, raw_app_meta_data,
                            raw_user_meta_data, created_at, updated_at)
    VALUES (test_user_id,
            'newuser@axew.test',
            '00000000-0000-0000-0000-000000000000',
            'authenticated', 'authenticated',
            now(), '{}'::jsonb, '{}'::jsonb,
            now(), now());

    SELECT email, credit_balance, total_minutes_processed
      INTO found_email, found_balance, found_processed
      FROM public.profiles
     WHERE id = test_user_id;

    IF found_email IS NULL THEN
        RAISE EXCEPTION 'FAIL: handle_new_user trigger did not create a profile row';
    END IF;

    IF found_email <> 'newuser@axew.test' THEN
        RAISE EXCEPTION 'FAIL: profile email mismatch (got %)', found_email;
    END IF;

    IF found_balance <> 10 THEN
        RAISE EXCEPTION 'FAIL: free-tier grant wrong (got %, expected 10)', found_balance;
    END IF;

    IF found_processed <> 0 THEN
        RAISE EXCEPTION 'FAIL: total_minutes_processed should start at 0 (got %)', found_processed;
    END IF;

    RAISE NOTICE 'PASS: handle_new_user creates profile with 10 credits';
END;
$$;

-- ----------------------------------------------------------------------------
-- Test 2: deduct_credits is atomic + rejects insufficient balance
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    test_user_id uuid := gen_random_uuid();
    new_balance numeric;
BEGIN
    INSERT INTO auth.users (id, email, instance_id, aud, role,
                            email_confirmed_at, raw_app_meta_data,
                            raw_user_meta_data, created_at, updated_at)
    VALUES (test_user_id, 'deducttest@axew.test',
            '00000000-0000-0000-0000-000000000000',
            'authenticated', 'authenticated',
            now(), '{}'::jsonb, '{}'::jsonb, now(), now());

    -- Profile starts at 10 credits via trigger.
    new_balance := public.deduct_credits(test_user_id, 3.5);
    IF new_balance <> 6.5 THEN
        RAISE EXCEPTION 'FAIL: deduct_credits returned wrong balance (got %, expected 6.5)', new_balance;
    END IF;

    -- Second deduction
    new_balance := public.deduct_credits(test_user_id, 6.5);
    IF new_balance <> 0 THEN
        RAISE EXCEPTION 'FAIL: deduct_credits did not reach zero (got %)', new_balance;
    END IF;

    -- Third deduction must raise insufficient_credits
    BEGIN
        new_balance := public.deduct_credits(test_user_id, 0.1);
        RAISE EXCEPTION 'FAIL: deduct_credits should have raised insufficient_credits';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM <> 'insufficient_credits' THEN
                RAISE EXCEPTION 'FAIL: wrong error from deduct_credits (got %)', SQLERRM;
            END IF;
    END;

    RAISE NOTICE 'PASS: deduct_credits is atomic + rejects overdraw';
END;
$$;

-- ----------------------------------------------------------------------------
-- Test 3: apply_payment_credits is idempotent (same payment row twice
-- only credits once)
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    test_user_id  uuid := gen_random_uuid();
    payment_id    uuid;
    first_applied boolean;
    second_applied boolean;
    final_balance numeric;
BEGIN
    INSERT INTO auth.users (id, email, instance_id, aud, role,
                            email_confirmed_at, raw_app_meta_data,
                            raw_user_meta_data, created_at, updated_at)
    VALUES (test_user_id, 'idempotest@axew.test',
            '00000000-0000-0000-0000-000000000000',
            'authenticated', 'authenticated',
            now(), '{}'::jsonb, '{}'::jsonb, now(), now());

    INSERT INTO public.payments
        (user_id, razorpay_order_id, plan_id, amount_inr, credits_purchased, status)
    VALUES (test_user_id, 'order_test_idem', 'starter', 199900, 100, 'created')
    RETURNING id INTO payment_id;

    first_applied  := public.apply_payment_credits(payment_id, 'pay_test_x', 'sig_x');
    second_applied := public.apply_payment_credits(payment_id, 'pay_test_x', 'sig_x');

    IF first_applied IS NOT TRUE THEN
        RAISE EXCEPTION 'FAIL: first apply_payment_credits should return true';
    END IF;
    IF second_applied IS NOT FALSE THEN
        RAISE EXCEPTION 'FAIL: idempotent replay should return false';
    END IF;

    SELECT credit_balance INTO final_balance FROM public.profiles WHERE id = test_user_id;
    -- 10 free + 100 from starter = 110, NOT 210
    IF final_balance <> 110 THEN
        RAISE EXCEPTION 'FAIL: replay double-credited (final balance %)', final_balance;
    END IF;

    RAISE NOTICE 'PASS: apply_payment_credits is idempotent';
END;
$$;

ROLLBACK;
