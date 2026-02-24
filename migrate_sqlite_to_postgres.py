"""
One-time migration script: SQLite → PostgreSQL
Reads all data from the existing SQLite database and bulk-inserts into PostgreSQL.

Usage (from inside the Docker container or locally):
    python migrate_sqlite_to_postgres.py

Requires both aiosqlite and asyncpg installed.
Expects DATABASE_URL and DATABASE_PATH env vars (or defaults from config).
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime

import aiosqlite
import asyncpg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
SQLITE_PATH = os.getenv('DATABASE_PATH', 'upwork_bot.db')
POSTGRES_URL = os.getenv('DATABASE_URL', 'postgresql://outbid:outbid_secret@localhost:5432/outbid')


def convert_bool(value):
    """Convert SQLite 0/1 to Python bool."""
    if value is None:
        return None
    return bool(value)


def convert_datetime(value):
    """Convert SQLite datetime string to Python datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


# Table definitions: (table_name, columns, has_serial_id)
# has_serial_id=True means we need to reset the sequence after bulk insert
TABLES = [
    {
        'name': 'seen_jobs',
        'columns': ['id', 'timestamp', 'title', 'link'],
        'has_serial_id': False,
        'bool_columns': [],
        'datetime_columns': ['timestamp'],
    },
    {
        'name': 'users',
        'columns': [
            'id', 'telegram_id', 'keywords', 'context', 'is_paid', 'state',
            'current_job_id', 'referral_code', 'referred_by', 'min_budget',
            'max_budget', 'experience_levels', 'pause_start', 'pause_end',
            'country_code', 'subscription_plan', 'subscription_expiry',
            'is_auto_renewal', 'payment_provider', 'email', 'reveal_credits',
            'pending_reveal_job_id', 'promo_code_used', 'min_hourly', 'max_hourly',
            'created_at', 'updated_at',
        ],
        'has_serial_id': True,
        'bool_columns': ['is_paid', 'is_auto_renewal'],
        'datetime_columns': ['created_at', 'updated_at'],
    },
    {
        'name': 'referrals',
        'columns': ['id', 'referrer_id', 'referred_id', 'referral_code', 'status', 'created_at', 'activated_at'],
        'has_serial_id': True,
        'bool_columns': [],
        'datetime_columns': ['created_at', 'activated_at'],
    },
    {
        'name': 'jobs',
        'columns': ['id', 'title', 'link', 'description', 'tags', 'budget', 'published', 'created_at'],
        'has_serial_id': False,
        'bool_columns': [],
        'datetime_columns': ['created_at'],
    },
    {
        'name': 'proposal_drafts',
        'columns': ['id', 'user_id', 'job_id', 'draft_count', 'strategy_count', 'last_generated_at'],
        'has_serial_id': True,
        'bool_columns': [],
        'datetime_columns': ['last_generated_at'],
    },
    {
        'name': 'revealed_jobs',
        'columns': ['id', 'user_id', 'job_id', 'proposal_text', 'revealed_at'],
        'has_serial_id': True,
        'bool_columns': [],
        'datetime_columns': ['revealed_at'],
    },
    {
        'name': 'alerts_sent',
        'columns': ['id', 'job_id', 'user_id', 'sent_at', 'alert_type'],
        'has_serial_id': True,
        'bool_columns': [],
        'datetime_columns': ['sent_at'],
    },
    {
        'name': 'promo_codes',
        'columns': ['id', 'code', 'discount_percent', 'applies_to', 'max_uses', 'times_used', 'conversions', 'is_active', 'created_at'],
        'has_serial_id': True,
        'bool_columns': ['is_active'],
        'datetime_columns': ['created_at'],
    },
    {
        'name': 'announcements',
        'columns': ['id', 'message', 'target', 'scheduled_at', 'sent_at', 'status', 'sent_count', 'failed_count', 'blocked_count', 'created_by', 'created_at'],
        'has_serial_id': True,
        'bool_columns': [],
        'datetime_columns': ['created_at'],
    },
]


async def get_sqlite_columns(db, table_name):
    """Get actual column names from SQLite table."""
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    columns = await cursor.fetchall()
    return [col[1] for col in columns]


async def migrate_table(sqlite_db, pg_conn, table_def):
    """Migrate a single table from SQLite to PostgreSQL."""
    table_name = table_def['name']
    expected_columns = table_def['columns']
    bool_columns = set(table_def['bool_columns'])

    # Get actual SQLite columns
    actual_columns = await get_sqlite_columns(sqlite_db, table_name)
    if not actual_columns:
        logger.warning(f"Table '{table_name}' not found in SQLite, skipping")
        return 0

    # Use intersection: only columns that exist in both SQLite and our target schema
    columns = [c for c in expected_columns if c in actual_columns]
    if not columns:
        logger.warning(f"No matching columns for '{table_name}', skipping")
        return 0

    missing = set(expected_columns) - set(actual_columns)
    if missing:
        logger.info(f"  Table '{table_name}' missing columns in SQLite (will use defaults): {missing}")

    # Read all rows from SQLite
    col_list = ', '.join(columns)
    cursor = await sqlite_db.execute(f"SELECT {col_list} FROM {table_name}")
    rows = await cursor.fetchall()

    if not rows:
        logger.info(f"  Table '{table_name}': 0 rows (empty)")
        return 0

    # Convert booleans and datetimes
    datetime_columns = set(table_def.get('datetime_columns', []))
    bool_indices = [i for i, c in enumerate(columns) if c in bool_columns]
    datetime_indices = [i for i, c in enumerate(columns) if c in datetime_columns]
    if bool_indices or datetime_indices:
        converted = []
        for row in rows:
            row_list = list(row)
            for idx in bool_indices:
                row_list[idx] = convert_bool(row_list[idx])
            for idx in datetime_indices:
                row_list[idx] = convert_datetime(row_list[idx])
            converted.append(tuple(row_list))
        rows = converted

    # Truncate target table first (makes re-runs safe after partial migration)
    await pg_conn.execute(f"TRUNCATE {table_name} CASCADE")

    # Bulk insert into Postgres using copy_records_to_table for speed
    start = time.time()
    try:
        await pg_conn.copy_records_to_table(
            table_name,
            records=rows,
            columns=columns,
        )
    except Exception as e:
        # Fallback to individual inserts if COPY fails (e.g. type mismatches)
        logger.warning(f"  COPY failed for '{table_name}': {e}. Falling back to INSERT...")
        placeholders = ', '.join(f'${i+1}' for i in range(len(columns)))
        col_names = ', '.join(columns)
        query = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        inserted = 0
        for row in rows:
            try:
                await pg_conn.execute(query, *row)
                inserted += 1
            except Exception as row_err:
                logger.error(f"  Failed to insert row in '{table_name}': {row_err}")
        elapsed = time.time() - start
        logger.info(f"  Table '{table_name}': {inserted}/{len(rows)} rows (fallback INSERT, {elapsed:.1f}s)")
        return inserted

    elapsed = time.time() - start
    logger.info(f"  Table '{table_name}': {len(rows)} rows ({elapsed:.1f}s)")
    return len(rows)


async def reset_sequences(pg_conn):
    """Reset SERIAL sequences to max(id) + 1 after bulk insert."""
    serial_tables = [t for t in TABLES if t['has_serial_id']]
    for table_def in serial_tables:
        table_name = table_def['name']
        seq_name = f"{table_name}_id_seq"
        try:
            max_id = await pg_conn.fetchval(f"SELECT COALESCE(MAX(id), 0) FROM {table_name}")
            await pg_conn.execute(f"SELECT setval('{seq_name}', $1, true)", max(max_id, 1))
            logger.info(f"  Sequence '{seq_name}' reset to {max_id}")
        except Exception as e:
            logger.warning(f"  Could not reset sequence for '{table_name}': {e}")


async def main():
    # Verify SQLite file exists
    if not os.path.exists(SQLITE_PATH):
        logger.error(f"SQLite database not found at: {SQLITE_PATH}")
        logger.error("Set DATABASE_PATH env var to the correct path")
        sys.exit(1)

    sqlite_size = os.path.getsize(SQLITE_PATH) / (1024 * 1024)
    logger.info(f"SQLite database: {SQLITE_PATH} ({sqlite_size:.1f} MB)")
    logger.info(f"PostgreSQL target: {POSTGRES_URL.split('@')[1] if '@' in POSTGRES_URL else POSTGRES_URL}")

    # Connect to both databases
    logger.info("Connecting to SQLite...")
    sqlite_db = await aiosqlite.connect(SQLITE_PATH)
    sqlite_db.row_factory = aiosqlite.Row

    logger.info("Connecting to PostgreSQL...")
    pg_conn = await asyncpg.connect(POSTGRES_URL)

    total_start = time.time()
    total_rows = 0

    try:
        # Migrate each table (order matters for foreign keys)
        logger.info("\n--- Starting migration ---")
        for table_def in TABLES:
            count = await migrate_table(sqlite_db, pg_conn, table_def)
            total_rows += count

        # Reset sequences
        logger.info("\n--- Resetting sequences ---")
        await reset_sequences(pg_conn)

    finally:
        await sqlite_db.close()
        await pg_conn.close()

    total_elapsed = time.time() - total_start
    logger.info(f"\n=== Migration complete: {total_rows} total rows in {total_elapsed:.1f}s ===")


if __name__ == '__main__':
    asyncio.run(main())
