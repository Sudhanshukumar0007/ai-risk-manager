#!/bin/bash
# ── init-test-db.sh ──────────────────────────────────────────────────────────
# Postgres initdb.d script — runs ONCE when the data directory is first
# initialised (i.e. on a fresh `docker compose up` after `docker compose down -v`).
#
# Creates a separate test database so that pytest never touches risk_db.
# The trigger that makes audit_log append-only is NOT installed in risk_db_test
# (conftest.py handles table creation for the test DB and deliberately skips it).
# ─────────────────────────────────────────────────────────────────────────────
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create the test database
    CREATE DATABASE risk_db_test;
    -- Grant all privileges to the existing app user
    GRANT ALL PRIVILEGES ON DATABASE risk_db_test TO $POSTGRES_USER;
EOSQL

echo "risk_db_test database created."
