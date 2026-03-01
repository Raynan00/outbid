"""
Database operations for Upwork First Responder Bot.
Handles seen jobs tracking and user management using async PostgreSQL.
"""

import asyncpg
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from config import config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Async database manager for the Upwork bot using PostgreSQL."""

    def __init__(self, database_url: str = None):
        self.database_url = database_url or config.DATABASE_URL
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create a connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=config.DATABASE_POOL_MIN,
                max_size=config.DATABASE_POOL_MAX,
            )
            logger.info("Database connection pool created")
        return self._pool

    @asynccontextmanager
    async def _connect(self):
        """Acquire a connection from the pool."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            yield conn

    async def close(self):
        """Close the database connection pool."""
        if self._pool is not None:
            try:
                await self._pool.close()
                logger.info("Database connection pool closed")
            except Exception as e:
                logger.error(f"Error closing database pool: {e}")
            finally:
                self._pool = None

    @staticmethod
    def _get_rowcount(result: str) -> int:
        """Extract row count from asyncpg execute result string (e.g. 'DELETE 5')."""
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def init_db(self) -> None:
        """Initialize database tables."""
        async with self._connect() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    id TEXT PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    title TEXT,
                    link TEXT
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE,
                    keywords TEXT,
                    context TEXT,
                    is_paid BOOLEAN DEFAULT FALSE,
                    state TEXT DEFAULT '',
                    current_job_id TEXT DEFAULT '',
                    referral_code TEXT,
                    referred_by INTEGER,
                    min_budget INTEGER DEFAULT 0,
                    max_budget INTEGER DEFAULT 999999,
                    experience_levels TEXT DEFAULT 'Entry,Intermediate,Expert',
                    pause_start TEXT DEFAULT NULL,
                    pause_end TEXT DEFAULT NULL,
                    country_code TEXT DEFAULT NULL,
                    subscription_plan TEXT DEFAULT 'scout',
                    subscription_expiry TEXT DEFAULT NULL,
                    is_auto_renewal BOOLEAN DEFAULT FALSE,
                    payment_provider TEXT DEFAULT NULL,
                    email TEXT DEFAULT NULL,
                    reveal_credits INTEGER DEFAULT 3,
                    pending_reveal_job_id TEXT DEFAULT NULL,
                    promo_code_used TEXT DEFAULT NULL,
                    min_hourly INTEGER DEFAULT 0,
                    max_hourly INTEGER DEFAULT 999,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id INTEGER,
                    referred_id INTEGER,
                    referral_code TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    activated_at TIMESTAMP,
                    FOREIGN KEY (referrer_id) REFERENCES users (id),
                    FOREIGN KEY (referred_id) REFERENCES users (id)
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    link TEXT,
                    description TEXT,
                    tags TEXT,
                    budget TEXT,
                    published TEXT,
                    budget_min REAL DEFAULT 0,
                    budget_max REAL DEFAULT 0,
                    job_type TEXT DEFAULT 'Unknown',
                    experience_level TEXT DEFAULT 'Unknown',
                    posted TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS proposal_drafts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    job_id TEXT,
                    draft_count INTEGER DEFAULT 1,
                    strategy_count INTEGER DEFAULT 0,
                    last_generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    UNIQUE(user_id, job_id)
                )
            ''')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS revealed_jobs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    job_id TEXT,
                    proposal_text TEXT,
                    revealed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    UNIQUE(user_id, job_id)
                )
            ''')

            await conn.execute('CREATE INDEX IF NOT EXISTS idx_proposal_drafts_user_job ON proposal_drafts(user_id, job_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_revealed_jobs_user_job ON revealed_jobs(user_id, job_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_seen_jobs_timestamp ON seen_jobs(timestamp)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_users_paid ON users(is_paid)')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS alerts_sent (
                    id SERIAL PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    user_id BIGINT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    alert_type TEXT DEFAULT 'proposal'
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_alerts_sent_job ON alerts_sent(job_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_alerts_sent_user ON alerts_sent(user_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_alerts_sent_time ON alerts_sent(sent_at)')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id SERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    discount_percent INTEGER DEFAULT 20,
                    applies_to TEXT DEFAULT 'monthly',
                    max_uses INTEGER DEFAULT NULL,
                    times_used INTEGER DEFAULT 0,
                    conversions INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes(code)')

            await conn.execute('''
                CREATE TABLE IF NOT EXISTS announcements (
                    id SERIAL PRIMARY KEY,
                    message TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT 'all',
                    scheduled_at TEXT DEFAULT NULL,
                    sent_at TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'pending',
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    blocked_count INTEGER DEFAULT 0,
                    created_by BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Schema migrations for existing deployments
            for col, col_def in [
                ('budget_min', 'REAL DEFAULT 0'),
                ('budget_max', 'REAL DEFAULT 0'),
                ('job_type', "TEXT DEFAULT 'Unknown'"),
                ('experience_level', "TEXT DEFAULT 'Unknown'"),
                ('posted', "TEXT DEFAULT ''"),
            ]:
                try:
                    await conn.execute(f'ALTER TABLE jobs ADD COLUMN {col} {col_def}')
                except Exception:
                    pass  # Column already exists

            logger.info("Database initialized successfully")

    # Seen Jobs Operations
    async def is_job_seen(self, job_id: str) -> bool:
        """Check if a job has been seen before."""
        async with self._connect() as conn:
            result = await conn.fetchrow('SELECT id FROM seen_jobs WHERE id = $1', job_id)
            return result is not None

    async def mark_job_seen(self, job_id: str, title: str, link: str) -> None:
        """Mark a job as seen."""
        async with self._connect() as conn:
            await conn.execute(
                '''INSERT INTO seen_jobs (id, timestamp, title, link) VALUES ($1, $2, $3, $4)
                   ON CONFLICT (id) DO UPDATE SET timestamp = $2, title = $3, link = $4''',
                job_id, datetime.now(), title, link
            )
            logger.debug(f"Marked job as seen: {job_id}")

    async def get_recent_jobs(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get jobs seen in the last N hours."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        async with self._connect() as conn:
            rows = await conn.fetch(
                'SELECT id, title, link, timestamp FROM seen_jobs WHERE timestamp > $1 ORDER BY timestamp DESC',
                cutoff_time
            )

        return [{'id': row[0], 'title': row[1], 'link': row[2], 'timestamp': row[3]} for row in rows]

    async def cleanup_old_jobs(self, days: int = 30) -> int:
        """Remove jobs older than N days. Returns number of deleted records."""
        cutoff_time = datetime.now() - timedelta(days=days)
        async with self._connect() as conn:
            result = await conn.execute('DELETE FROM seen_jobs WHERE timestamp < $1', cutoff_time)
            deleted_count = self._get_rowcount(result)
            logger.info(f"Cleaned up {deleted_count} old job records")
            return deleted_count

    # Alert Tracking Operations
    async def record_alert_sent(self, job_id: str, user_id: int, alert_type: str = 'proposal') -> None:
        """Record that an alert was sent to a user."""
        async with self._connect() as conn:
            await conn.execute(
                'INSERT INTO alerts_sent (job_id, user_id, alert_type) VALUES ($1, $2, $3)',
                job_id, user_id, alert_type
            )

    async def get_alerts_stats(self) -> Dict[str, Any]:
        """Get alert statistics."""
        async with self._connect() as conn:
            stats = {}

            result = await conn.fetchrow('SELECT COUNT(*) FROM alerts_sent')
            stats['total_alerts'] = result[0]

            result = await conn.fetchrow('SELECT COUNT(DISTINCT job_id) FROM alerts_sent')
            stats['unique_jobs_sent'] = result[0]

            result = await conn.fetchrow(
                "SELECT COUNT(*) FROM alerts_sent WHERE sent_at > NOW() - INTERVAL '24 hours'"
            )
            stats['alerts_24h'] = result[0]

            rows = await conn.fetch('SELECT alert_type, COUNT(*) FROM alerts_sent GROUP BY alert_type')
            stats['by_type'] = {row[0]: row[1] for row in rows}

            return stats

    # User Management Operations
    async def add_user(self, telegram_id: int, is_paid: bool = False) -> None:
        """Add or update a user."""
        async with self._connect() as conn:
            await conn.execute('''
                INSERT INTO users (telegram_id, is_paid, reveal_credits, updated_at)
                VALUES ($1, $2, 3, $3)
                ON CONFLICT (telegram_id) DO UPDATE SET is_paid = $2, updated_at = $3
            ''', telegram_id, is_paid, datetime.now())

            logger.info(f"Added/updated user: {telegram_id}, paid: {is_paid}")

    async def update_user_onboarding(self, telegram_id: int, keywords: str = None, context: str = None) -> None:
        """Update user onboarding information."""
        async with self._connect() as conn:
            updates = []
            params = []
            idx = 1

            if keywords is not None:
                updates.append(f"keywords = ${idx}")
                params.append(keywords)
                idx += 1

            if context is not None:
                updates.append(f"context = ${idx}")
                params.append(context)
                idx += 1

            if updates:
                updates.append(f"updated_at = ${idx}")
                params.append(datetime.now())
                idx += 1
                params.append(telegram_id)

                query = f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ${idx}"
                await conn.execute(query, *params)
                logger.info(f"Updated onboarding for user: {telegram_id}")

    async def is_user_authorized(self, telegram_id: int) -> bool:
        """Check if user is authorized to receive job alerts."""
        if config.is_admin(telegram_id):
            return True

        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT keywords FROM users WHERE telegram_id = $1', telegram_id
            )

        return result is not None and bool(result[0])

    # State Management Operations
    async def set_user_state(self, telegram_id: int, state: str, current_job_id: str = "") -> None:
        """Set user state for onboarding or strategy mode."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET state = $1, current_job_id = $2, updated_at = $3 WHERE telegram_id = $4',
                state, current_job_id, datetime.now(), telegram_id
            )
            logger.debug(f"Set state for user {telegram_id}: {state}")

    async def clear_user_state(self, telegram_id: int) -> None:
        """Clear user state (end onboarding or strategy session)."""
        async with self._connect() as conn:
            await conn.execute(
                "UPDATE users SET state = '', current_job_id = '', updated_at = $1 WHERE telegram_id = $2",
                datetime.now(), telegram_id
            )
            logger.debug(f"Cleared state for user {telegram_id}")

    async def get_user_context(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user context including keywords, bio, and state for proposal generation."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT keywords, context, state, current_job_id, referral_code FROM users WHERE telegram_id = $1',
                telegram_id
            )

        if not result:
            return None

        return {
            'keywords': result[0] or '',
            'context': result[1] or '',
            'state': result[2] or '',
            'current_job_id': result[3] or '',
            'referral_code': result[4] or ''
        }

    # Referral System Methods
    async def create_referral_code(self, telegram_id: int) -> str:
        """Generate and assign a unique referral code for a user."""
        import secrets
        referral_code = secrets.token_hex(4).upper()

        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET referral_code = $1, updated_at = $2 WHERE telegram_id = $3',
                referral_code, datetime.now(), telegram_id
            )

        return referral_code

    async def process_referral(self, referrer_code: str, new_user_id: int) -> bool:
        """Process a referral when a new user signs up with a referral code."""
        async with self._connect() as conn:
            referrer_result = await conn.fetchrow(
                'SELECT id FROM users WHERE referral_code = $1', referrer_code
            )

            if not referrer_result:
                return False

            referrer_id = referrer_result[0]

            async with conn.transaction():
                await conn.execute(
                    'INSERT INTO referrals (referrer_id, referred_id, referral_code, status) VALUES ($1, $2, $3, $4)',
                    referrer_id, new_user_id, referrer_code, 'pending'
                )
                await conn.execute(
                    'UPDATE users SET referred_by = $1, updated_at = $2 WHERE id = $3',
                    referrer_id, datetime.now(), new_user_id
                )

        return True

    async def activate_referral(self, user_id: int) -> None:
        """Mark a referral as activated when user completes payment."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE referrals SET status = $1, activated_at = $2 WHERE referred_id = $3',
                'activated', datetime.now(), user_id
            )

    async def get_referral_stats(self, telegram_id: int) -> Dict[str, int]:
        """Get referral statistics for a user."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT COUNT(*) FROM referrals WHERE referrer_id = (SELECT id FROM users WHERE telegram_id = $1) AND status = $2',
                telegram_id, 'activated'
            )
            activated_count = result[0]

            result = await conn.fetchrow(
                'SELECT COUNT(*) FROM referrals WHERE referrer_id = (SELECT id FROM users WHERE telegram_id = $1)',
                telegram_id
            )
            total_count = result[0]

        return {
            'total_referrals': total_count,
            'activated_referrals': activated_count,
            'pending_referrals': total_count - activated_count
        }

    # Promo Code System
    async def get_promo_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Get promo code details if valid and active."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                '''SELECT code, discount_percent, applies_to, max_uses, times_used, is_active
                   FROM promo_codes WHERE UPPER(code) = UPPER($1) AND is_active = TRUE''',
                code
            )

        if not result:
            return None

        if result[3] is not None and result[4] >= result[3]:
            return None

        return {
            'code': result[0],
            'discount_percent': result[1],
            'applies_to': result[2],
            'max_uses': result[3],
            'times_used': result[4]
        }

    async def apply_promo_code(self, telegram_id: int, code: str) -> Optional[Dict[str, Any]]:
        """Apply a promo code to a user. Returns promo details if successful."""
        promo = await self.get_promo_code(code)
        if not promo:
            return None

        async with self._connect() as conn:
            async with conn.transaction():
                # Check user hasn't already used a promo (inside transaction to prevent race)
                result = await conn.fetchrow(
                    'SELECT promo_code_used FROM users WHERE telegram_id = $1 FOR UPDATE',
                    telegram_id
                )

                if result and result[0]:
                    return None

                await conn.execute(
                    'UPDATE users SET promo_code_used = $1, updated_at = $2 WHERE telegram_id = $3',
                    promo['code'], datetime.now(), telegram_id
                )
                await conn.execute(
                    'UPDATE promo_codes SET times_used = times_used + 1 WHERE UPPER(code) = UPPER($1)',
                    code
                )

        logger.info(f"Applied promo code {promo['code']} to user {telegram_id}")
        return promo

    async def get_user_promo(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get the promo code a user has applied (if any)."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT promo_code_used FROM users WHERE telegram_id = $1', telegram_id
            )

        if not result or not result[0]:
            return None

        return await self.get_promo_code(result[0])

    async def increment_promo_conversion(self, code: str) -> None:
        """Increment the conversion count for a promo code."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE promo_codes SET conversions = conversions + 1 WHERE UPPER(code) = UPPER($1)',
                code
            )
            logger.info(f"Recorded conversion for promo code {code}")

    async def get_promo_stats(self, code: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a promo code."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                '''SELECT code, discount_percent, applies_to, max_uses, times_used, conversions, is_active, created_at
                   FROM promo_codes WHERE UPPER(code) = UPPER($1)''',
                code
            )

        if not result:
            return None

        return {
            'code': result[0],
            'discount_percent': result[1],
            'applies_to': result[2],
            'max_uses': result[3],
            'times_used': result[4],
            'conversions': result[5],
            'is_active': bool(result[6]),
            'created_at': result[7]
        }

    async def create_promo_code(self, code: str, discount_percent: int = 20, applies_to: str = 'monthly', max_uses: int = None) -> bool:
        """Create a new promo code."""
        try:
            async with self._connect() as conn:
                await conn.execute(
                    'INSERT INTO promo_codes (code, discount_percent, applies_to, max_uses) VALUES ($1, $2, $3, $4)',
                    code.upper(), discount_percent, applies_to, max_uses
                )
            logger.info(f"Created promo code {code.upper()} with {discount_percent}% discount")
            return True
        except Exception as e:
            logger.error(f"Failed to create promo code {code}: {e}")
            return False

    async def delete_promo_code(self, code: str) -> bool:
        """Delete a promo code."""
        try:
            async with self._connect() as conn:
                result = await conn.execute(
                    'DELETE FROM promo_codes WHERE UPPER(code) = UPPER($1)', code
                )
                if self._get_rowcount(result) > 0:
                    logger.info(f"Deleted promo code {code.upper()}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to delete promo code {code}: {e}")
            return False

    async def get_all_promo_codes(self) -> list:
        """Get all promo codes for admin listing."""
        async with self._connect() as conn:
            rows = await conn.fetch(
                'SELECT code, discount_percent, times_used, conversions, is_active, created_at FROM promo_codes ORDER BY created_at DESC'
            )
            return [tuple(row.values()) for row in rows]

    # Job Storage for Strategy Mode
    async def store_job_for_strategy(self, job_data: Dict[str, Any]) -> None:
        """Store job data for potential strategy mode usage."""
        async with self._connect() as conn:
            await conn.execute('''
                INSERT INTO jobs (id, title, link, description, tags, budget, published,
                                  budget_min, budget_max, job_type, experience_level, posted)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (id) DO UPDATE SET
                    title = $2, link = $3, description = $4, tags = $5, budget = $6, published = $7,
                    budget_min = $8, budget_max = $9, job_type = $10, experience_level = $11, posted = $12
            ''',
                job_data['id'],
                job_data.get('title', ''),
                job_data.get('link', ''),
                job_data.get('description', ''),
                ','.join(job_data.get('tags', [])),
                job_data.get('budget', ''),
                str(job_data.get('published', '')),
                float(job_data.get('budget_min', 0) or 0),
                float(job_data.get('budget_max', 0) or 0),
                job_data.get('job_type', 'Unknown') or 'Unknown',
                job_data.get('experience_level', 'Unknown') or 'Unknown',
                job_data.get('posted', '') or ''
            )

    async def get_job_for_strategy(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job data for strategy mode."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT id, title, link, description, tags, budget, published, '
                'budget_min, budget_max, job_type, experience_level, posted '
                'FROM jobs WHERE id = $1',
                job_id
            )

        if not result:
            return None

        return {
            'id': result[0],
            'title': result[1],
            'link': result[2],
            'description': result[3],
            'tags': result[4].split(',') if result[4] else [],
            'budget': result[5],
            'published': result[6],
            'budget_min': result[7] or 0,
            'budget_max': result[8] or 0,
            'job_type': result[9] or 'Unknown',
            'experience_level': result[10] or 'Unknown',
            'posted': result[11] or ''
        }

    # Payment Activation
    async def activate_user_payment(self, telegram_id: int) -> None:
        """Activate user payment status."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET is_paid = TRUE, updated_at = $1 WHERE telegram_id = $2',
                datetime.now(), telegram_id
            )

            result = await conn.fetchrow('SELECT id FROM users WHERE telegram_id = $1', telegram_id)
            if result:
                user_id = result[0]
                await self.activate_referral(user_id)

    async def get_active_users(self) -> List[Dict[str, Any]]:
        """Get all users who have completed onboarding (have keywords)."""
        async with self._connect() as conn:
            rows = await conn.fetch(
                "SELECT telegram_id, keywords, created_at FROM users WHERE keywords IS NOT NULL AND keywords != ''"
            )

        return [{'telegram_id': row[0], 'keywords': row[1] or '', 'created_at': row[2]} for row in rows]

    async def get_all_users_for_broadcast(self) -> List[Dict[str, Any]]:
        """Fetch all user data needed for broadcast filtering and alert prep in ONE query."""
        async with self._connect() as conn:
            rows = await conn.fetch('''
                SELECT telegram_id, keywords, context, is_paid,
                       min_budget, max_budget, experience_levels,
                       pause_start, country_code,
                       subscription_plan, subscription_expiry,
                       is_auto_renewal, payment_provider, reveal_credits,
                       min_hourly, max_hourly
                FROM users
                WHERE keywords IS NOT NULL AND keywords != ''
            ''')

        users = []
        for row in rows:
            users.append({
                'telegram_id': row[0],
                'keywords': row[1] or '',
                'context': row[2] or '',
                'is_paid': bool(row[3]),
                'min_budget': row[4] or 0,
                'max_budget': row[5] or 999999,
                'experience_levels': row[6] or 'Entry,Intermediate,Expert',
                'pause_start': row[7],
                'country_code': row[8] or 'GLOBAL',
                'subscription_plan': row[9] or 'scout',
                'subscription_expiry': row[10],
                'is_auto_renewal': bool(row[11]),
                'payment_provider': row[12],
                'reveal_credits': row[13] if row[13] is not None else 3,
                'min_hourly': row[14] or 0,
                'max_hourly': row[15] or 999,
            })
        return users

    # Proposal Draft Tracking
    async def get_proposal_draft_count(self, telegram_id: int, job_id: str) -> Dict[str, int]:
        """Get proposal draft counts for a user and job."""
        async with self._connect() as conn:
            user_result = await conn.fetchrow('SELECT id FROM users WHERE telegram_id = $1', telegram_id)
            if not user_result:
                return {'draft_count': 0, 'strategy_count': 0}

            user_id = user_result[0]

            result = await conn.fetchrow(
                'SELECT draft_count, strategy_count FROM proposal_drafts WHERE user_id = $1 AND job_id = $2',
                user_id, job_id
            )

            if result:
                return {'draft_count': result[0], 'strategy_count': result[1]}
            return {'draft_count': 0, 'strategy_count': 0}

    async def increment_proposal_draft(self, telegram_id: int, job_id: str, is_strategy: bool = False) -> int:
        """Increment proposal draft count for a user and job. Returns the new count."""
        async with self._connect() as conn:
            user_result = await conn.fetchrow('SELECT id FROM users WHERE telegram_id = $1', telegram_id)
            if not user_result:
                return 0

            user_id = user_result[0]

            if is_strategy:
                row = await conn.fetchrow('''
                    INSERT INTO proposal_drafts (user_id, job_id, draft_count, strategy_count)
                    VALUES ($1, $2, 0, 1)
                    ON CONFLICT (user_id, job_id) DO UPDATE SET
                        strategy_count = proposal_drafts.strategy_count + 1,
                        last_generated_at = CURRENT_TIMESTAMP
                    RETURNING strategy_count
                ''', user_id, job_id)
            else:
                row = await conn.fetchrow('''
                    INSERT INTO proposal_drafts (user_id, job_id, draft_count, strategy_count)
                    VALUES ($1, $2, 1, 0)
                    ON CONFLICT (user_id, job_id) DO UPDATE SET
                        draft_count = proposal_drafts.draft_count + 1,
                        last_generated_at = CURRENT_TIMESTAMP
                    RETURNING draft_count
                ''', user_id, job_id)

            return row[0] if row else 1

    # Database Statistics (for admin dashboard)
    async def get_database_stats(self) -> Dict[str, Any]:
        """Get comprehensive database statistics for admin dashboard."""
        async with self._connect() as conn:
            stats = {}

            result = await conn.fetchrow('SELECT COUNT(*) FROM users')
            stats['total_users'] = result[0]

            result = await conn.fetchrow('SELECT COUNT(*) FROM users WHERE is_paid = TRUE')
            stats['paid_users'] = result[0]

            result = await conn.fetchrow("SELECT COUNT(*) FROM users WHERE keywords IS NOT NULL AND keywords != ''")
            stats['users_with_keywords'] = result[0]

            result = await conn.fetchrow('SELECT COUNT(*) FROM users WHERE is_paid = FALSE')
            stats['unpaid_users'] = result[0]

            result = await conn.fetchrow('SELECT COUNT(*) FROM seen_jobs')
            stats['total_jobs_seen'] = result[0]

            result = await conn.fetchrow('SELECT COUNT(*) FROM jobs')
            stats['jobs_stored'] = result[0]

            result = await conn.fetchrow('SELECT COUNT(*) FROM referrals')
            stats['total_referrals'] = result[0]

            result = await conn.fetchrow("SELECT COUNT(*) FROM referrals WHERE status = 'activated'")
            stats['activated_referrals'] = result[0]

            result = await conn.fetchrow('SELECT COUNT(*) FROM proposal_drafts')
            stats['total_proposal_drafts'] = result[0]

            result = await conn.fetchrow('SELECT SUM(draft_count) FROM proposal_drafts')
            stats['total_regular_drafts'] = result[0] or 0

            result = await conn.fetchrow('SELECT SUM(strategy_count) FROM proposal_drafts')
            stats['total_strategy_drafts'] = result[0] or 0

            result = await conn.fetchrow(
                "SELECT COUNT(*) FROM seen_jobs WHERE timestamp > NOW() - INTERVAL '24 hours'"
            )
            stats['jobs_last_24h'] = result[0]

            result = await conn.fetchrow(
                "SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days'"
            )
            stats['new_users_7d'] = result[0]

            return stats

    async def get_all_users_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all users for admin view."""
        async with self._connect() as conn:
            rows = await conn.fetch('''
                SELECT telegram_id, keywords, is_paid, created_at, updated_at,
                       min_budget, max_budget, experience_levels
                FROM users
                ORDER BY created_at DESC
            ''')

            users = []
            for row in rows:
                users.append({
                    'telegram_id': row[0],
                    'keywords': row[1] or 'Not set',
                    'is_paid': bool(row[2]),
                    'created_at': row[3],
                    'updated_at': row[4],
                    'min_budget': row[5] or 0,
                    'max_budget': row[6] or 999999,
                    'experience_levels': row[7] or 'All'
                })
            return users

    async def get_user_draft_summary(self, telegram_id: int = None) -> List[Dict[str, Any]]:
        """Get proposal draft summary, optionally filtered by user."""
        async with self._connect() as conn:
            if telegram_id:
                user_result = await conn.fetchrow('SELECT id FROM users WHERE telegram_id = $1', telegram_id)
                if not user_result:
                    return []
                user_id = user_result[0]

                rows = await conn.fetch('''
                    SELECT pd.job_id, pd.draft_count, pd.strategy_count, pd.last_generated_at,
                           j.title, u.telegram_id
                    FROM proposal_drafts pd
                    LEFT JOIN jobs j ON pd.job_id = j.id
                    LEFT JOIN users u ON pd.user_id = u.id
                    WHERE pd.user_id = $1
                    ORDER BY pd.last_generated_at DESC
                    LIMIT 50
                ''', user_id)
            else:
                rows = await conn.fetch('''
                    SELECT pd.job_id, pd.draft_count, pd.strategy_count, pd.last_generated_at,
                           j.title, u.telegram_id
                    FROM proposal_drafts pd
                    LEFT JOIN jobs j ON pd.job_id = j.id
                    LEFT JOIN users u ON pd.user_id = u.id
                    ORDER BY pd.last_generated_at DESC
                    LIMIT 100
                ''')

            drafts = []
            for row in rows:
                drafts.append({
                    'job_id': row[0],
                    'job_title': row[4] or 'Unknown',
                    'user_telegram_id': row[5],
                    'draft_count': row[1],
                    'strategy_count': row[2],
                    'last_generated': row[3]
                })
            return drafts

    async def get_user_info(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed user information."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                '''SELECT telegram_id, keywords, context, is_paid, state, current_job_id,
                   created_at, updated_at, min_budget, max_budget, experience_levels,
                   pause_start, pause_end, country_code, subscription_plan, subscription_expiry,
                   is_auto_renewal, payment_provider, email, min_hourly, max_hourly
                   FROM users WHERE telegram_id = $1''',
                telegram_id
            )

        if not result:
            return None

        return {
            'telegram_id': result[0],
            'keywords': result[1] or '',
            'context': result[2] or '',
            'is_paid': bool(result[3]),
            'state': result[4] or '',
            'current_job_id': result[5] or '',
            'created_at': result[6],
            'updated_at': result[7],
            'min_budget': result[8] or 0,
            'max_budget': result[9] or 999999,
            'experience_levels': (result[10] or 'Entry,Intermediate,Expert').split(','),
            'pause_start': result[11],
            'pause_end': result[12],
            'country_code': result[13],
            'subscription_plan': result[14] or 'scout',
            'subscription_expiry': result[15],
            'is_auto_renewal': bool(result[16]),
            'payment_provider': result[17],
            'email': result[18],
            'min_hourly': result[19] or 0,
            'max_hourly': result[20] or 999,
        }

    async def get_user_jobs_matched_count(self, telegram_id: int) -> int:
        """Count alerts sent to a specific user."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT COUNT(*) FROM alerts_sent WHERE user_id = $1', telegram_id
            )
            return result[0] if result else 0

    # Budget and Filter Settings
    async def update_user_filters(self, telegram_id: int, min_budget: int = None,
                                   max_budget: int = None, experience_levels: List[str] = None,
                                   min_hourly: int = None, max_hourly: int = None) -> None:
        """Update user budget, hourly rate, and experience level filters."""
        async with self._connect() as conn:
            updates = []
            params = []
            idx = 1

            if min_budget is not None:
                updates.append(f"min_budget = ${idx}")
                params.append(min_budget)
                idx += 1

            if max_budget is not None:
                updates.append(f"max_budget = ${idx}")
                params.append(max_budget)
                idx += 1

            if min_hourly is not None:
                updates.append(f"min_hourly = ${idx}")
                params.append(min_hourly)
                idx += 1

            if max_hourly is not None:
                updates.append(f"max_hourly = ${idx}")
                params.append(max_hourly)
                idx += 1

            if experience_levels is not None:
                updates.append(f"experience_levels = ${idx}")
                params.append(','.join(experience_levels))
                idx += 1

            if updates:
                updates.append(f"updated_at = ${idx}")
                params.append(datetime.now())
                idx += 1
                params.append(telegram_id)

                query = f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ${idx}"
                await conn.execute(query, *params)
                logger.info(f"Updated filters for user {telegram_id}")

    # Pause/Schedule Settings
    async def set_user_pause(self, telegram_id: int, hours: int) -> datetime:
        """Pause alerts for X hours. Returns the pause_until datetime."""
        pause_until = datetime.now() + timedelta(hours=hours)
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET pause_start = $1, pause_end = NULL, updated_at = $2 WHERE telegram_id = $3',
                pause_until.isoformat(), datetime.now(), telegram_id
            )
            logger.info(f"Paused alerts for user {telegram_id} until {pause_until}")
        return pause_until

    async def set_user_pause_indefinite(self, telegram_id: int) -> None:
        """Pause alerts indefinitely until manually resumed."""
        pause_until = datetime(9999, 12, 31, 23, 59, 59)
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET pause_start = $1, pause_end = NULL, updated_at = $2 WHERE telegram_id = $3',
                pause_until.isoformat(), datetime.now(), telegram_id
            )
            logger.info(f"Paused alerts indefinitely for user {telegram_id}")

    async def clear_user_pause(self, telegram_id: int) -> None:
        """Clear user pause (resume alerts)."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET pause_start = NULL, pause_end = NULL, updated_at = $1 WHERE telegram_id = $2',
                datetime.now(), telegram_id
            )
            logger.info(f"Resumed alerts for user {telegram_id}")

    def is_user_paused(self, pause_until_str: str) -> bool:
        """Check if user is currently paused. pause_until_str is ISO format datetime."""
        if not pause_until_str:
            return False

        try:
            pause_until = datetime.fromisoformat(str(pause_until_str))
            return datetime.now() < pause_until
        except (ValueError, TypeError):
            return False

    def get_pause_remaining(self, pause_until_str: str) -> str:
        """Get human-readable time remaining on pause."""
        if not pause_until_str:
            return None

        try:
            pause_until = datetime.fromisoformat(str(pause_until_str))

            if pause_until.year >= 9999:
                return "Paused indefinitely"

            remaining = pause_until - datetime.now()

            if remaining.total_seconds() <= 0:
                return None

            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)

            if hours > 0:
                return f"{hours}h {minutes}m remaining"
            else:
                return f"{minutes}m remaining"
        except (ValueError, TypeError):
            return None

    # ==================== SUBSCRIPTION MANAGEMENT ====================

    async def update_user_country(self, telegram_id: int, country_code: str) -> None:
        """Update user's country code (NG or GLOBAL)."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET country_code = $1, updated_at = $2 WHERE telegram_id = $3',
                country_code, datetime.now(), telegram_id
            )
            logger.info(f"Updated country for user {telegram_id}: {country_code}")

    async def update_user_email(self, telegram_id: int, email: str) -> None:
        """Update user's email address (needed for Paystack)."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET email = $1, updated_at = $2 WHERE telegram_id = $3',
                email, datetime.now(), telegram_id
            )
            logger.info(f"Updated email for user {telegram_id}")

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user info by email address (for Paystack subscription lookups)."""
        async with self._connect() as conn:
            row = await conn.fetchrow(
                'SELECT telegram_id, email, subscription_plan FROM users WHERE email = $1',
                email
            )
            if row:
                return dict(row)
            return None

    async def grant_subscription(self, telegram_id: int, plan: str, expiry: datetime,
                                  payment_provider: str, is_auto_renewal: bool = False) -> None:
        """Grant subscription to user after payment confirmation."""
        async with self._connect() as conn:
            await conn.execute('''
                UPDATE users SET
                    subscription_plan = $1,
                    subscription_expiry = $2,
                    payment_provider = $3,
                    is_auto_renewal = $4,
                    is_paid = TRUE,
                    updated_at = $5
                WHERE telegram_id = $6
            ''', plan, expiry.isoformat(), payment_provider, is_auto_renewal, datetime.now(), telegram_id)
            logger.info(f"Granted {plan} subscription to user {telegram_id}, expires: {expiry}")

    async def downgrade_to_scout(self, telegram_id: int) -> None:
        """Downgrade user to scout plan (expired subscription)."""
        async with self._connect() as conn:
            await conn.execute('''
                UPDATE users SET
                    subscription_plan = 'scout',
                    subscription_expiry = NULL,
                    is_auto_renewal = FALSE,
                    is_paid = FALSE,
                    updated_at = $1
                WHERE telegram_id = $2
            ''', datetime.now(), telegram_id)
            logger.info(f"Downgraded user {telegram_id} to scout plan")

    async def set_auto_renewal(self, telegram_id: int, enabled: bool) -> None:
        """Set user's auto-renewal status."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET is_auto_renewal = $1, updated_at = $2 WHERE telegram_id = $3',
                enabled, datetime.now(), telegram_id
            )
            logger.info(f"Set auto_renewal={enabled} for user {telegram_id}")

    async def check_subscription_expired(self, telegram_id: int) -> bool:
        """Check if user's subscription has expired. Returns True if expired."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT subscription_plan, subscription_expiry FROM users WHERE telegram_id = $1',
                telegram_id
            )

        if not result:
            return True

        plan, expiry_str = result

        if plan == 'scout' or not expiry_str:
            return False

        try:
            expiry = datetime.fromisoformat(str(expiry_str))
            return datetime.now() > expiry
        except:
            return True

    async def get_subscription_status(self, telegram_id: int) -> Dict[str, Any]:
        """Get user's current subscription status."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                '''SELECT subscription_plan, subscription_expiry, is_auto_renewal,
                   payment_provider, country_code FROM users WHERE telegram_id = $1''',
                telegram_id
            )

        if not result:
            return {
                'plan': 'scout',
                'expiry': None,
                'is_auto_renewal': False,
                'payment_provider': None,
                'country_code': None,
                'is_active': False,
                'days_remaining': 0
            }

        plan, expiry_str, is_auto_renewal, payment_provider, country_code = result

        is_active = False
        days_remaining = 0

        if plan != 'scout' and expiry_str:
            try:
                expiry = datetime.fromisoformat(str(expiry_str))
                is_active = datetime.now() < expiry
                if is_active:
                    delta = expiry - datetime.now()
                    days_remaining = delta.days + (1 if delta.seconds > 0 else 0)
            except:
                pass

        return {
            'plan': plan or 'scout',
            'expiry': expiry_str,
            'is_auto_renewal': bool(is_auto_renewal),
            'payment_provider': payment_provider,
            'country_code': country_code,
            'is_active': is_active,
            'days_remaining': days_remaining
        }

    async def get_users_with_expiring_subscriptions(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get users whose subscriptions expire within the next N hours."""
        cutoff = datetime.now() + timedelta(hours=hours)
        now = datetime.now()

        async with self._connect() as conn:
            rows = await conn.fetch('''
                SELECT telegram_id, subscription_plan, subscription_expiry
                FROM users
                WHERE subscription_plan != 'scout'
                AND subscription_expiry IS NOT NULL
            ''')

        expiring_users = []
        for row in rows:
            telegram_id, plan, expiry_str = row
            try:
                expiry = datetime.fromisoformat(str(expiry_str))
                if now < expiry <= cutoff:
                    expiring_users.append({
                        'telegram_id': telegram_id,
                        'plan': plan,
                        'expiry': expiry_str,
                        'hours_remaining': int((expiry - now).total_seconds() / 3600)
                    })
            except:
                pass

        return expiring_users

    # ==================== REVEAL CREDITS MANAGEMENT ====================

    async def get_reveal_credits(self, telegram_id: int) -> int:
        """Get remaining reveal credits for a user."""
        async with self._connect() as conn:
            result = await conn.fetchrow(
                'SELECT reveal_credits FROM users WHERE telegram_id = $1', telegram_id
            )

            if result:
                return result[0] if result[0] is not None else 3
            return 3

    async def use_reveal_credit(self, telegram_id: int, job_id: str, proposal_text: str) -> bool:
        """Use a reveal credit for a user and store the revealed proposal."""
        async with self._connect() as conn:
            async with conn.transaction():
                # Lock the user row to prevent concurrent credit usage
                user_result = await conn.fetchrow(
                    'SELECT id, reveal_credits FROM users WHERE telegram_id = $1 FOR UPDATE',
                    telegram_id
                )

                if not user_result:
                    logger.error(f"User {telegram_id} not found")
                    return False

                user_id, current_credits = user_result

                if current_credits is None:
                    current_credits = 3
                if current_credits <= 0:
                    logger.warning(f"User {telegram_id} has no reveal credits left")
                    return False

                existing = await conn.fetchrow(
                    'SELECT id FROM revealed_jobs WHERE user_id = $1 AND job_id = $2',
                    user_id, job_id
                )

                if existing:
                    logger.info(f"Job {job_id} already revealed for user {telegram_id}")
                    return True

                new_credits = current_credits - 1
                await conn.execute(
                    'UPDATE users SET reveal_credits = $1, updated_at = $2 WHERE telegram_id = $3',
                    new_credits, datetime.now(), telegram_id
                )
                await conn.execute(
                    'INSERT INTO revealed_jobs (user_id, job_id, proposal_text) VALUES ($1, $2, $3)',
                    user_id, job_id, proposal_text
                )

            logger.info(f"Used reveal credit for user {telegram_id}, job {job_id}. Credits remaining: {new_credits}")
            return True

    async def is_job_revealed(self, telegram_id: int, job_id: str) -> bool:
        """Check if a job has already been revealed for a user."""
        async with self._connect() as conn:
            user_result = await conn.fetchrow(
                'SELECT id FROM users WHERE telegram_id = $1', telegram_id
            )

            if not user_result:
                return False

            user_id = user_result[0]

            result = await conn.fetchrow(
                'SELECT id FROM revealed_jobs WHERE user_id = $1 AND job_id = $2',
                user_id, job_id
            )
            return result is not None

    async def get_revealed_proposal(self, telegram_id: int, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the stored proposal for a revealed job."""
        async with self._connect() as conn:
            user_result = await conn.fetchrow(
                'SELECT id FROM users WHERE telegram_id = $1', telegram_id
            )

            if not user_result:
                return None

            user_id = user_result[0]

            result = await conn.fetchrow(
                'SELECT proposal_text, revealed_at FROM revealed_jobs WHERE user_id = $1 AND job_id = $2',
                user_id, job_id
            )

            if result:
                return {
                    'proposal_text': result[0],
                    'revealed_at': result[1]
                }
            return None

    # ==================== PENDING REVEAL JOB (POST-PAYMENT AUTO-REVEAL) ====================

    async def set_pending_reveal_job(self, telegram_id: int, job_id: str) -> None:
        """Store the job ID that triggered the paywall for auto-reveal after payment."""
        async with self._connect() as conn:
            await conn.execute(
                'UPDATE users SET pending_reveal_job_id = $1, updated_at = $2 WHERE telegram_id = $3',
                job_id, datetime.now(), telegram_id
            )
            logger.info(f"Set pending reveal job {job_id} for user {telegram_id}")

    async def get_and_clear_pending_reveal_job(self, telegram_id: int) -> Optional[str]:
        """Get and clear the pending reveal job ID."""
        async with self._connect() as conn:
            # Atomic read-and-clear: only one concurrent caller gets the job_id
            result = await conn.fetchrow(
                '''UPDATE users SET pending_reveal_job_id = NULL, updated_at = $1
                   WHERE telegram_id = $2 AND pending_reveal_job_id IS NOT NULL
                   RETURNING pending_reveal_job_id''',
                datetime.now(), telegram_id
            )

            if result and result[0]:
                logger.info(f"Retrieved and cleared pending reveal job {result[0]} for user {telegram_id}")
                return result[0]
            return None

    # Announcement Operations
    async def create_announcement(self, message: str, target: str, created_by: int,
                                   scheduled_at: str = None) -> int:
        """Create a new announcement. Returns the announcement ID."""
        async with self._connect() as conn:
            status = 'pending' if scheduled_at else 'sending'
            row = await conn.fetchrow(
                '''INSERT INTO announcements (message, target, scheduled_at, status, created_by)
                   VALUES ($1, $2, $3, $4, $5) RETURNING id''',
                message, target, scheduled_at, status, created_by
            )
            return row[0]

    async def get_pending_announcements(self) -> List[Dict[str, Any]]:
        """Get scheduled announcements that are due to be sent."""
        async with self._connect() as conn:
            now = datetime.now().isoformat()
            rows = await conn.fetch(
                '''SELECT id, message, target, scheduled_at, created_by
                   FROM announcements
                   WHERE status = 'pending' AND scheduled_at IS NOT NULL AND scheduled_at <= $1''',
                now
            )
            return [{'id': r[0], 'message': r[1], 'target': r[2],
                     'scheduled_at': r[3], 'created_by': r[4]} for r in rows]

    async def update_announcement_status(self, announcement_id: int, status: str,
                                          sent_count: int = 0, failed_count: int = 0,
                                          blocked_count: int = 0) -> None:
        """Update announcement status and delivery stats."""
        async with self._connect() as conn:
            sent_at = datetime.now().isoformat() if status == 'sent' else None
            await conn.execute(
                '''UPDATE announcements SET status = $1, sent_at = COALESCE($2, sent_at),
                   sent_count = $3, failed_count = $4, blocked_count = $5
                   WHERE id = $6''',
                status, sent_at, sent_count, failed_count, blocked_count, announcement_id
            )

    async def get_announcement_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent announcement history for admin review."""
        async with self._connect() as conn:
            rows = await conn.fetch(
                '''SELECT id, message, target, status, sent_count, failed_count,
                          blocked_count, scheduled_at, sent_at, created_at
                   FROM announcements ORDER BY created_at DESC LIMIT $1''',
                limit
            )
            return [{'id': r[0], 'message': r[1], 'target': r[2], 'status': r[3],
                     'sent_count': r[4], 'failed_count': r[5], 'blocked_count': r[6],
                     'scheduled_at': r[7], 'sent_at': r[8], 'created_at': r[9]} for r in rows]

    async def get_users_for_announcement(self, target: str) -> List[int]:
        """Get telegram_ids matching the announcement target filter."""
        async with self._connect() as conn:
            if target.isdigit():
                return [int(target)]

            base_where = "keywords IS NOT NULL AND keywords != ''"

            if target == 'all':
                rows = await conn.fetch(f'SELECT telegram_id FROM users WHERE {base_where}')
            elif target == 'paid':
                rows = await conn.fetch(
                    f'''SELECT telegram_id FROM users
                       WHERE {base_where} AND (is_paid = TRUE OR
                       (subscription_plan != 'scout' AND subscription_expiry > $1))''',
                    datetime.now().isoformat()
                )
            elif target in ('free', 'scout'):
                rows = await conn.fetch(
                    f'''SELECT telegram_id FROM users
                       WHERE {base_where} AND (subscription_plan = 'scout' OR
                       subscription_plan IS NULL OR subscription_expiry <= $1 OR subscription_expiry IS NULL)
                       AND is_paid = FALSE''',
                    datetime.now().isoformat()
                )
            else:
                rows = await conn.fetch(
                    f'SELECT telegram_id FROM users WHERE {base_where} AND country_code = $1',
                    target.upper()
                )

            return [r[0] for r in rows]


# Global database instance
db_manager = DatabaseManager()
