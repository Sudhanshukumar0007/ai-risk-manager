#!/usr/bin/env bash
# scripts/test_idempotency.sh
#
# Integration idempotency tests for POST /v1/orders/score.
#
# Usage (inside the running stack):
#   docker compose exec api bash scripts/test_idempotency.sh
#
# What is tested:
#   Test A — Sequential duplicate: sends same event_id twice; asserts DB row count == 1.
#   Test B — Concurrent duplicate: sends same event_id twice via background curl jobs;
#            asserts DB row count == 1.
#   Test C — Verifies idempotency is working end-to-end with a fresh event_id.
#
# The Redis-unavailable code path is tested in:
#   pytest tests/test_idempotency.py::test_redis_unavailable_postgres_catches_duplicate
# which mocks RedisError and asserts insert-and-catch behaviour (cannot be replicated
# in a shell script without stopping the shared Redis container).
#
# Exit code: 0 = all tests passed, 1 = at least one failed.

set -uo pipefail   # no -e; arithmetic increments exit 1 when result == 0

API_BASE="${API_BASE:-http://localhost:8000}"

PASS=0
FAIL=0

# ── Helpers ───────────────────────────────────────────────────────────────────

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
pass() { log "  ✓ PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  ✗ FAIL: $*"; FAIL=$((FAIL + 1)); }

db_row_count() {
    local event_id="$1"
    python3 - "$event_id" <<'PYEOF'
import sys, psycopg2, os
eid = sys.argv[1]
dsn = os.environ.get('DATABASE_URL_SYNC', 'postgresql://risk_user:risk_pass@postgres:5432/risk_db')
try:
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM audit_log WHERE event_id = %s", (eid,))
    print(cur.fetchone()[0])
    conn.close()
except Exception as e:
    print(0, file=sys.stderr)
    print(0)
PYEOF
}

wait_for_db_row() {
    # Poll until audit_log row appears (Celery task writes async)
    local event_id="$1"
    local max_wait="${2:-20}"
    local elapsed=0
    while [ "$elapsed" -lt "$max_wait" ]; do
        count=$(db_row_count "$event_id")
        if [ "$count" -ge 1 ] 2>/dev/null; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

random_event_id() {
    python3 -c "import uuid; print(uuid.uuid4())"
}

make_payload() {
    local event_id="$1"
    local order_id="order-${event_id:0:8}"
    cat <<EOF
{
  "event_id": "$event_id",
  "order_id": "$order_id",
  "pincode": "110001",
  "customer_id": "cust-shell-test",
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

# ── Test A: Sequential duplicate ─────────────────────────────────────────────
log "=== Test A: Sequential duplicate ==="
EID_A=$(random_event_id)
PAYLOAD_A=$(make_payload "$EID_A")

R1=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE/v1/orders/score" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD_A")

R2=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE/v1/orders/score" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD_A")

log "  First response: $R1 | Second response: $R2"

if [ "$R1" = "202" ]; then
    pass "First request → 202 Accepted"
else
    fail "First request → expected 202, got $R1"
fi

if [ "$R2" = "200" ] || [ "$R2" = "202" ]; then
    pass "Duplicate request → $R2 (idempotent response)"
else
    fail "Duplicate request → expected 200 or 202, got $R2"
fi

# Wait for Celery worker to write the audit_log row
log "  Waiting for Celery task to write DB row (max 20s) ..."
if wait_for_db_row "$EID_A" 20; then
    COUNT_A=$(db_row_count "$EID_A")
    if [ "$COUNT_A" = "1" ]; then
        pass "DB row count after sequential duplicate = 1"
    else
        fail "DB row count after sequential duplicate = $COUNT_A (expected 1)"
    fi
else
    fail "Celery task did not write DB row within 20s for event_id=$EID_A"
fi

# ── Test B: Concurrent duplicate ─────────────────────────────────────────────
log "=== Test B: Concurrent duplicate (background curl jobs) ==="
EID_B=$(random_event_id)
PAYLOAD_B=$(make_payload "$EID_B")

TMPSTATUS1=$(mktemp)
TMPSTATUS2=$(mktemp)

curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE/v1/orders/score" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD_B" > "$TMPSTATUS1" &
PID1=$!

curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE/v1/orders/score" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD_B" > "$TMPSTATUS2" &
PID2=$!

wait "$PID1" "$PID2"

S1=$(cat "$TMPSTATUS1")
S2=$(cat "$TMPSTATUS2")
rm -f "$TMPSTATUS1" "$TMPSTATUS2"

log "  Concurrent responses: $S1 | $S2"

if [[ "$S1" =~ ^(200|202)$ ]] && [[ "$S2" =~ ^(200|202)$ ]]; then
    pass "Both concurrent responses are 200 or 202"
else
    fail "Unexpected concurrent response codes: $S1, $S2"
fi

log "  Waiting for Celery task to write DB row (max 20s) ..."
if wait_for_db_row "$EID_B" 20; then
    COUNT_B=$(db_row_count "$EID_B")
    if [ "$COUNT_B" = "1" ]; then
        pass "DB row count after concurrent duplicate = 1"
    else
        fail "DB row count after concurrent duplicate = $COUNT_B (expected 1)"
    fi
else
    fail "Celery task did not write DB row within 20s for event_id=$EID_B"
fi

# ── Test C: Fresh event → DB row appears ─────────────────────────────────────
log "=== Test C: Fresh event creates exactly one DB row ==="
EID_C=$(random_event_id)
PAYLOAD_C=$(make_payload "$EID_C")

RC=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE/v1/orders/score" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD_C")

if [ "$RC" = "202" ]; then
    pass "Fresh event → 202 Accepted"
else
    fail "Fresh event → expected 202, got $RC"
fi

log "  Waiting for Celery task to write DB row (max 20s) ..."
if wait_for_db_row "$EID_C" 20; then
    COUNT_C=$(db_row_count "$EID_C")
    if [ "$COUNT_C" = "1" ]; then
        pass "DB row count for fresh event = 1"
    else
        fail "DB row count for fresh event = $COUNT_C (expected 1)"
    fi
else
    fail "Celery task did not write DB row within 20s for event_id=$EID_C"
fi

log ""
log "NOTE: Redis-unavailable → Postgres UNIQUE fallback is tested by:"
log "      pytest tests/test_idempotency.py::test_redis_unavailable_postgres_catches_duplicate"

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    log "ACCEPTANCE TEST: FAIL"
    exit 1
else
    log "ACCEPTANCE TEST: PASS"
    exit 0
fi
