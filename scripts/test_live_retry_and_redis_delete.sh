#!/usr/bin/env bash
# scripts/test_live_retry_and_redis_delete.sh
#
# Live integration test: proves that _handle_final_failure actually deletes the
# Redis dedup key against the real Redis instance — not just a mock.
#
# What this script confirms (that the unit test does NOT):
#   1. redis.delete() is called with the correct key format ("dedup:<event_id>")
#   2. The actual sync Redis client in scoring.py reaches the real Redis server
#   3. The key is gone in redis-cli after retries exhaust
#   4. A resubmission after that is accepted as fresh (202) by the API
#
# How the failure is forced:
#   The XGBoost model file is renamed inside the container for the duration of
#   the test, causing every task attempt to raise FileNotFoundError immediately.
#   The file is restored unconditionally in the cleanup trap.
#
# Retry timeline (actual wall-clock wait):
#   attempt 1 → FileNotFoundError → wait 5s
#   attempt 2 → FileNotFoundError → wait 15s
#   attempt 3 → FileNotFoundError → wait 45s
#   attempt 4 (final) → FileNotFoundError → _handle_final_failure → delete key
#   Total: ~70s + Celery scheduling overhead (allow up to 120s)
#
# Usage (from host, stack running):
#   docker compose exec api bash scripts/test_live_retry_and_redis_delete.sh
#
# Exit 0 = PASS, Exit 1 = FAIL

set -uo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
MODEL_PATH="/workspace/models/xgboost_rto_v1.base.bin"
MODEL_BACKUP="${MODEL_PATH}.bak_live_test"
RETRY_TIMEOUT=120   # seconds to wait for all retries to exhaust
POLL_INTERVAL=3

PASS=0
FAIL=0

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
pass() { log "  ✓ PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  ✗ FAIL: $*"; FAIL=$((FAIL + 1)); }

# ── Cleanup trap: always restore model file ───────────────────────────────────
cleanup() {
    if [ -f "$MODEL_BACKUP" ]; then
        log "  [cleanup] Restoring model file ..."
        mv "$MODEL_BACKUP" "$MODEL_PATH"
        log "  [cleanup] Model restored."
    fi
}
trap cleanup EXIT

# ── Helpers ───────────────────────────────────────────────────────────────────

random_event_id() {
    python3 -c "import uuid; print(uuid.uuid4())"
}

make_payload() {
    local event_id="$1"
    local order_id="live-test-${event_id:0:8}"
    cat <<EOF
{
  "event_id": "$event_id",
  "order_id": "$order_id",
  "pincode": "110001",
  "customer_id": "cust-live-test",
  "category": "Electronics",
  "cart_value": 1500.0,
  "item_quantity": 2,
  "order_timestamp": "2026-08-25T02:30:00Z",
  "address_line_1": "12 Main St",
  "address_line_2": "",
  "payment_method": "COD",
  "customer_past_rto_count": 0,
  "phone_order_velocity_7d": 1,
  "device_account_reuse_count": 1,
  "account_age_days": 180
}
EOF
}

redis_key_exists() {
    local event_id="$1"
    local key="dedup:${event_id}"
    # Use python redis client — redis-cli may not be installed in the api container
    python3 -c "
import redis, os
r = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
exists = r.exists('$key')
print('EXISTS' if exists else 'GONE')
r.close()
"
}

db_failure_row_exists() {
    local event_id="$1"
    python3 -c "
import psycopg2, os
dsn = os.environ.get('DATABASE_URL_SYNC', 'postgresql://risk_user:risk_pass@postgres:5432/risk_db')
try:
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(\"SELECT COUNT(*) FROM scoring_failures WHERE event_id = %s\", ('$event_id',))
    print(cur.fetchone()[0])
    conn.close()
except Exception as e:
    print(0)
" 2>/dev/null || echo "0"
}

db_audit_row_exists() {
    local event_id="$1"
    python3 -c "
import psycopg2, os
dsn = os.environ.get('DATABASE_URL_SYNC', 'postgresql://risk_user:risk_pass@postgres:5432/risk_db')
try:
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(\"SELECT COUNT(*) FROM audit_log WHERE event_id = %s\", ('$event_id',))
    print(cur.fetchone()[0])
    conn.close()
except Exception as e:
    print(0)
" 2>/dev/null || echo "0"
}

wait_for_key_deletion() {
    local event_id="$1"
    local elapsed=0
    while [ "$elapsed" -lt "$RETRY_TIMEOUT" ]; do
        status=$(redis_key_exists "$event_id")
        if [ "$status" = "GONE" ]; then
            return 0
        fi
        sleep "$POLL_INTERVAL"
        elapsed=$((elapsed + POLL_INTERVAL))
        log "  [wait] ${elapsed}s elapsed — key still EXISTS (retries in progress) ..."
    done
    return 1  # timed out
}

# ═════════════════════════════════════════════════════════════════════════════
log "======================================================================"
log "Live Redis key deletion test"
log "This test uses real Redis, real Celery worker, real Postgres."
log "It verifies that _handle_final_failure deletes the dedup key for real."
log "======================================================================"

EID=$(random_event_id)
PAYLOAD=$(make_payload "$EID")
DEDUP_KEY="dedup:${EID}"

log ""
log "event_id = $EID"
log "Redis key = $DEDUP_KEY"

# ── Step 1: Rename model file to force task failure ───────────────────────────
log ""
log "Step 1: Disabling model file to force task failure ..."
if [ ! -f "$MODEL_PATH" ]; then
    fail "Model file not found at $MODEL_PATH — cannot proceed"
    exit 1
fi
mv "$MODEL_PATH" "$MODEL_BACKUP"
log "  Model file moved to $MODEL_BACKUP"

# ── Step 2: Submit payload — should get 202 ───────────────────────────────────
log ""
log "Step 2: Submitting order (expecting 202) ..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE/v1/orders/score" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

if [ "$HTTP_CODE" = "202" ]; then
    pass "POST returned 202 Accepted"
else
    fail "POST returned $HTTP_CODE (expected 202)"
    exit 1
fi

# ── Step 3: Verify key is set in Redis immediately after submission ────────────
log ""
log "Step 3: Checking Redis key exists immediately after submission ..."
sleep 1
KEY_STATUS=$(redis_key_exists "$EID")
if [ "$KEY_STATUS" = "EXISTS" ]; then
    pass "Redis key '$DEDUP_KEY' EXISTS immediately after submission"
else
    fail "Redis key '$DEDUP_KEY' not found immediately after submission — SET NX may not have fired"
fi

# ── Step 4: Wait for all retries to exhaust and key to be deleted ─────────────
log ""
log "Step 4: Waiting up to ${RETRY_TIMEOUT}s for retries to exhaust and key to be deleted ..."
log "  (5s + 15s + 45s backoff + Celery overhead = ~70s expected)"
if wait_for_key_deletion "$EID"; then
    pass "Redis key '$DEDUP_KEY' is GONE — _handle_final_failure deleted it"
else
    fail "Redis key '$DEDUP_KEY' still EXISTS after ${RETRY_TIMEOUT}s — key was NOT deleted"
fi

# ── Step 5: Verify scoring_failures row was written ───────────────────────────
log ""
log "Step 5: Checking scoring_failures row ..."
FAILURE_COUNT=$(db_failure_row_exists "$EID")
if [ "$FAILURE_COUNT" = "1" ]; then
    pass "scoring_failures row written for event_id=$EID"
else
    fail "scoring_failures row NOT found for event_id=$EID (count=$FAILURE_COUNT)"
fi

# ── Step 6: Restore model file ────────────────────────────────────────────────
log ""
log "Step 6: Restoring model file ..."
mv "$MODEL_BACKUP" "$MODEL_PATH"
log "  Model restored at $MODEL_PATH"

# ── Step 7: Resubmit same event_id — must be treated as fresh ────────────────
log ""
log "Step 7: Resubmitting same event_id (expecting 202 fresh, NOT duplicate) ..."
sleep 2  # brief settle
RESUBMIT_CODE=$(curl -s -o /tmp/resubmit_body.json -w "%{http_code}" \
    -X POST "$API_BASE/v1/orders/score" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

if [ "$RESUBMIT_CODE" = "202" ]; then
    pass "Resubmission returned 202 (fresh submission — not duplicate)"
else
    fail "Resubmission returned $RESUBMIT_CODE (expected 202 fresh); body: $(cat /tmp/resubmit_body.json 2>/dev/null)"
fi

# Verify new Redis key is set for the fresh submission
sleep 1
NEW_KEY_STATUS=$(redis_key_exists "$EID")
if [ "$NEW_KEY_STATUS" = "EXISTS" ]; then
    pass "New Redis key set for fresh resubmission"
else
    fail "New Redis key NOT set after fresh resubmission"
fi

# ── Step 8: Wait for resubmission task to complete ────────────────────────────
log ""
log "Step 8: Waiting up to 30s for resubmission task to write audit_log row ..."
elapsed=0
audit_written=0
while [ "$elapsed" -lt 30 ]; do
    count=$(db_audit_row_exists "$EID")
    if [ "$count" -ge 1 ] 2>/dev/null; then
        audit_written=1
        break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

if [ "$audit_written" = "1" ]; then
    pass "audit_log row written for event_id=$EID after successful resubmission"
else
    fail "audit_log row NOT found after 30s — resubmission task may still be running or failed"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    log "LIVE INTEGRATION TEST: FAIL"
    exit 1
else
    log "LIVE INTEGRATION TEST: PASS"
    exit 0
fi
