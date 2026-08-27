-- ── purge_test_contamination.sql ─────────────────────────────────────────────
-- ONE-TIME cleanup script to remove test-generated rows from risk_db.
--
-- Run this ONCE before Day 9 demo prep:
--   docker compose exec postgres psql -U risk_user -d risk_db -f /workspace/scripts/purge_test_contamination.sql
--
-- What this does:
--   1. Drops the append-only trigger temporarily (it blocks TRUNCATE/DELETE)
--   2. Truncates all four contaminated tables
--   3. Re-installs the append-only trigger on audit_log
--   4. Resets the sequences so IDs start from 1 again (clean slate for demo)
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- Step 1: Drop the append-only trigger so we can truncate audit_log
DROP TRIGGER IF EXISTS tg_audit_log_append_only ON audit_log;
DROP FUNCTION IF EXISTS audit_log_append_only();

-- Step 2: Truncate all contaminated tables (CASCADE handles FK ordering)
TRUNCATE TABLE
    llm_explanations,
    scoring_failures,
    payment_link_state,
    audit_log
RESTART IDENTITY CASCADE;

-- Step 3: Re-install the append-only trigger on audit_log
CREATE OR REPLACE FUNCTION audit_log_append_only()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'audit_log is append-only: UPDATE/DELETE are forbidden (event_id=%)',
        OLD.event_id;
    RETURN NULL;
END;
$$;

CREATE TRIGGER tg_audit_log_append_only
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();

COMMIT;

-- Verify the tables are empty
SELECT 'audit_log'       AS table_name, COUNT(*) AS row_count FROM audit_log
UNION ALL
SELECT 'llm_explanations',              COUNT(*)              FROM llm_explanations
UNION ALL
SELECT 'payment_link_state',            COUNT(*)              FROM payment_link_state
UNION ALL
SELECT 'scoring_failures',              COUNT(*)              FROM scoring_failures;
