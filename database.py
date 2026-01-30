"""
Database operations for Upwork First Responder Bot.
Handles seen jobs tracking and user management using async SQLite.
"""

import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from config import config

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Async database manager for the Upwork bot."""

    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self) -> None:
        """Initialize database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # Create seen_jobs table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    title TEXT,
                    link TEXT
                )
            ''')

            # Create users table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    keywords TEXT,
                    context TEXT,
                    is_paid BOOLEAN DEFAULT 0,
                    state TEXT DEFAULT '',
                    current_job_id TEXT DEFAULT '',
                    referral_code TEXT,
                    referred_by INTEGER,
                    min_budget INTEGER DEFAULT 0,
                    max_budget INTEGER DEFAULT 999999,
                    experience_levels TEXT DEFAULT 'Entry,Intermediate,Expert',
                    pause_start INTEGER DEFAULT NULL,
                    pause_end INTEGER DEFAULT NULL,
                    country_code TEXT DEFAULT NULL,
                    subscription_plan TEXT DEFAULT 'scout',
                    subscription_expiry TEXT DEFAULT NULL,
                    is_auto_renewal BOOLEAN DEFAULT 0,
                    payment_provider TEXT DEFAULT NULL,
                    email TEXT DEFAULT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Add new columns if they don't exist (for existing databases)
            try:
                await db.execute('ALTER TABLE users ADD COLUMN min_budget INTEGER DEFAULT 0')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN max_budget INTEGER DEFAULT 999999')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN experience_levels TEXT DEFAULT "Entry,Intermediate,Expert"')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN pause_start INTEGER DEFAULT NULL')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN pause_end INTEGER DEFAULT NULL')
            except: pass
            # Subscription columns (monetization)
            try:
                await db.execute('ALTER TABLE users ADD COLUMN country_code TEXT DEFAULT NULL')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN subscription_plan TEXT DEFAULT "scout"')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN subscription_expiry TEXT DEFAULT NULL')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN is_auto_renewal BOOLEAN DEFAULT 0')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN payment_provider TEXT DEFAULT NULL')
            except: pass
            try:
                await db.execute('ALTER TABLE users ADD COLUMN email TEXT DEFAULT NULL')
            except: pass
            # Reveal credits column
            try:
                await db.execute('ALTER TABLE users ADD COLUMN reveal_credits INTEGER DEFAULT 3')
            except: pass
            # Pending reveal job (for post-payment auto-reveal)
            try:
                await db.execute('ALTER TABLE users ADD COLUMN pending_reveal_job_id TEXT DEFAULT NULL')
            except: pass

            # Create referrals table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER,
                    referred_id INTEGER,
                    referral_code TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    activated_at DATETIME,
                    FOREIGN KEY (referrer_id) REFERENCES users (id),
                    FOREIGN KEY (referred_id) REFERENCES users (id)
                )
            ''')

            # Create jobs table for strategy mode
            await db.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    link TEXT,
                    description TEXT,
                    tags TEXT,
                    budget TEXT,
                    published TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create proposal_drafts table to track proposal generation per user per job
            await db.execute('''
                CREATE TABLE IF NOT EXISTS proposal_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    job_id TEXT,
                    draft_count INTEGER DEFAULT 1,
                    strategy_count INTEGER DEFAULT 0,
                    last_generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    UNIQUE(user_id, job_id)
                )
            ''')
            
            # Create revealed_jobs table to store revealed proposals for scout users
            await db.execute('''
                CREATE TABLE IF NOT EXISTS revealed_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    job_id TEXT,
                    proposal_text TEXT,
                    revealed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    UNIQUE(user_id, job_id)
                )
            ''')
            
            # Create indexes for faster lookups
            await db.execute('CREATE INDEX IF NOT EXISTS idx_proposal_drafts_user_job ON proposal_drafts(user_id, job_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_revealed_jobs_user_job ON revealed_jobs(user_id, job_id)')

            # Create indexes for better performance
            await db.execute('CREATE INDEX IF NOT EXISTS idx_seen_jobs_timestamp ON seen_jobs(timestamp)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_users_paid ON users(is_paid)')
            
            # Track alerts sent to users
            await db.execute('''
                CREATE TABLE IF NOT EXISTS alerts_sent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    alert_type TEXT DEFAULT 'proposal'
                )
            ''')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_sent_job ON alerts_sent(job_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_sent_user ON alerts_sent(user_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_sent_time ON alerts_sent(sent_at)')

            # Create promo_codes table for promotional discounts
            await db.execute('''
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    discount_percent INTEGER DEFAULT 20,
                    applies_to TEXT DEFAULT 'monthly',
                    max_uses INTEGER DEFAULT NULL,
                    times_used INTEGER DEFAULT 0,
                    conversions INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes(code)')

            # Add promo_code_used column to users table
            try:
                await db.execute('ALTER TABLE users ADD COLUMN promo_code_used TEXT DEFAULT NULL')
            except: pass

            await db.commit()
            logger.info("Database initialized successfully")

    # Seen Jobs Operations
    async def is_job_seen(self, job_id: str) -> bool:
        """Check if a job has been seen before."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT id FROM seen_jobs WHERE id = ?', (job_id,))
            result = await cursor.fetchone()
            return result is not None

    async def mark_job_seen(self, job_id: str, title: str, link: str) -> None:
        """Mark a job as seen."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT OR REPLACE INTO seen_jobs (id, timestamp, title, link) VALUES (?, ?, ?, ?)',
                (job_id, datetime.now(), title, link)
            )
            await db.commit()
            logger.debug(f"Marked job as seen: {job_id}")

    async def get_recent_jobs(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get jobs seen in the last N hours."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT id, title, link, timestamp FROM seen_jobs WHERE timestamp > ? ORDER BY timestamp DESC',
                (cutoff_time,)
            )
            rows = await cursor.fetchall()

        jobs = []
        for row in rows:
            jobs.append({
                'id': row[0],
                'title': row[1],
                'link': row[2],
                'timestamp': row[3]
            })
        return jobs

    async def cleanup_old_jobs(self, days: int = 30) -> int:
        """Remove jobs older than N days. Returns number of deleted records."""
        cutoff_time = datetime.now() - timedelta(days=days)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('DELETE FROM seen_jobs WHERE timestamp < ?', (cutoff_time,))
            deleted_count = cursor.rowcount
            await db.commit()
            logger.info(f"Cleaned up {deleted_count} old job records")
            return deleted_count

    # Alert Tracking Operations
    async def record_alert_sent(self, job_id: str, user_id: int, alert_type: str = 'proposal') -> None:
        """Record that an alert was sent to a user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO alerts_sent (job_id, user_id, alert_type) VALUES (?, ?, ?)',
                (job_id, user_id, alert_type)
            )
            await db.commit()

    async def get_alerts_stats(self) -> Dict[str, Any]:
        """Get alert statistics."""
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            
            # Total alerts ever sent
            cursor = await db.execute('SELECT COUNT(*) FROM alerts_sent')
            stats['total_alerts'] = (await cursor.fetchone())[0]
            
            # Unique jobs sent (at least one user got it)
            cursor = await db.execute('SELECT COUNT(DISTINCT job_id) FROM alerts_sent')
            stats['unique_jobs_sent'] = (await cursor.fetchone())[0]
            
            # Alerts in last 24h
            cursor = await db.execute('''
                SELECT COUNT(*) FROM alerts_sent 
                WHERE sent_at > datetime('now', '-24 hours')
            ''')
            stats['alerts_24h'] = (await cursor.fetchone())[0]
            
            # By type
            cursor = await db.execute('''
                SELECT alert_type, COUNT(*) FROM alerts_sent GROUP BY alert_type
            ''')
            stats['by_type'] = {row[0]: row[1] for row in await cursor.fetchall()}
            
            return stats

    # User Management Operations
    async def add_user(self, telegram_id: int, is_paid: bool = False) -> None:
        """Add or update a user."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user exists
            cursor = await db.execute('SELECT reveal_credits FROM users WHERE telegram_id = ?', (telegram_id,))
            existing = await cursor.fetchone()
            
            if existing:
                # User exists - update is_paid only, preserve reveal_credits
                await db.execute('''
                    UPDATE users SET is_paid = ?, updated_at = ? WHERE telegram_id = ?
                ''', (is_paid, datetime.now(), telegram_id))
            else:
                # New user - set reveal_credits to 3
                await db.execute('''
                    INSERT INTO users (telegram_id, is_paid, reveal_credits, updated_at)
                    VALUES (?, ?, 3, ?)
                ''', (telegram_id, is_paid, datetime.now()))
            
            await db.commit()
            logger.info(f"Added/updated user: {telegram_id}, paid: {is_paid}")

    async def update_user_onboarding(self, telegram_id: int, keywords: str = None, context: str = None) -> None:
        """Update user onboarding information."""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []

            if keywords is not None:
                updates.append("keywords = ?")
                params.append(keywords)

            if context is not None:
                updates.append("context = ?")
                params.append(context)

            if updates:
                updates.append("updated_at = ?")
                params.extend([datetime.now(), telegram_id])

                query = f'''
                    UPDATE users
                    SET {', '.join(updates)}
                    WHERE telegram_id = ?
                '''
                await db.execute(query, params)
                await db.commit()
                logger.info(f"Updated onboarding for user: {telegram_id}")

    async def is_user_authorized(self, telegram_id: int) -> bool:
        """Check if user is authorized to receive job alerts.
        
        All users who have completed onboarding (have keywords) are authorized.
        Payment status only affects whether proposals are blurred or full,
        not whether they can receive alerts.
        """
        # Admins are always authorized
        if config.is_admin(telegram_id):
            return True

        # Check if user exists and has completed onboarding (has keywords)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT keywords FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = await cursor.fetchone()

        # User is authorized if they have keywords set
        return result is not None and bool(result[0])

    # State Management Operations
    async def set_user_state(self, telegram_id: int, state: str, current_job_id: str = "") -> None:
        """Set user state for onboarding or strategy mode."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET state = ?, current_job_id = ?, updated_at = ? WHERE telegram_id = ?',
                (state, current_job_id, datetime.now(), telegram_id)
            )
            await db.commit()
            logger.debug(f"Set state for user {telegram_id}: {state}")

    async def clear_user_state(self, telegram_id: int) -> None:
        """Clear user state (end onboarding or strategy session)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET state = "", current_job_id = "", updated_at = ? WHERE telegram_id = ?',
                (datetime.now(), telegram_id)
            )
            await db.commit()
            logger.debug(f"Cleared state for user {telegram_id}")

    async def get_user_context(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user context including keywords, bio, and state for proposal generation."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT keywords, context, state, current_job_id, referral_code FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = await cursor.fetchone()

        if not result:
            return None

        keywords, context, state, current_job_id, referral_code = result
        return {
            'keywords': keywords or '',
            'context': context or '',
            'state': state or '',
            'current_job_id': current_job_id or '',
            'referral_code': referral_code or ''
        }

    # Referral System Methods
    async def create_referral_code(self, telegram_id: int) -> str:
        """Generate and assign a unique referral code for a user."""
        import secrets
        referral_code = secrets.token_hex(4).upper()  # 8-character code

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET referral_code = ?, updated_at = ? WHERE telegram_id = ?',
                (referral_code, datetime.now(), telegram_id)
            )
            await db.commit()

        return referral_code

    async def process_referral(self, referrer_code: str, new_user_id: int) -> bool:
        """Process a referral when a new user signs up with a referral code."""
        async with aiosqlite.connect(self.db_path) as db:
            # Find the referrer
            cursor = await db.execute(
                'SELECT id FROM users WHERE referral_code = ?',
                (referrer_code,)
            )
            referrer_result = await cursor.fetchone()

            if not referrer_result:
                return False  # Invalid referral code

            referrer_id = referrer_result[0]

            # Create referral record
            await db.execute(
                'INSERT INTO referrals (referrer_id, referred_id, referral_code, status) VALUES (?, ?, ?, ?)',
                (referrer_id, new_user_id, referrer_code, 'pending')
            )
            await db.commit()

            # Update new user's referred_by field
            await db.execute(
                'UPDATE users SET referred_by = ?, updated_at = ? WHERE id = ?',
                (referrer_id, datetime.now(), new_user_id)
            )
            await db.commit()

        return True

    async def activate_referral(self, user_id: int) -> None:
        """Mark a referral as activated when user completes payment."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE referrals SET status = ?, activated_at = ? WHERE referred_id = ?',
                ('activated', datetime.now(), user_id)
            )
            await db.commit()

    async def get_referral_stats(self, telegram_id: int) -> Dict[str, int]:
        """Get referral statistics for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT COUNT(*) FROM referrals WHERE referrer_id = (SELECT id FROM users WHERE telegram_id = ?) AND status = ?',
                (telegram_id, 'activated')
            )
            activated_count = (await cursor.fetchone())[0]

            cursor = await db.execute(
                'SELECT COUNT(*) FROM referrals WHERE referrer_id = (SELECT id FROM users WHERE telegram_id = ?)',
                (telegram_id,)
            )
            total_count = (await cursor.fetchone())[0]

        return {
            'total_referrals': total_count,
            'activated_referrals': activated_count,
            'pending_referrals': total_count - activated_count
        }

    # Promo Code System
    async def get_promo_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Get promo code details if valid and active."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                '''SELECT code, discount_percent, applies_to, max_uses, times_used, is_active
                   FROM promo_codes WHERE UPPER(code) = UPPER(?) AND is_active = 1''',
                (code,)
            )
            result = await cursor.fetchone()

        if not result:
            return None

        code, discount_percent, applies_to, max_uses, times_used, is_active = result

        # Check if max uses exceeded
        if max_uses is not None and times_used >= max_uses:
            return None

        return {
            'code': code,
            'discount_percent': discount_percent,
            'applies_to': applies_to,
            'max_uses': max_uses,
            'times_used': times_used
        }

    async def apply_promo_code(self, telegram_id: int, code: str) -> Optional[Dict[str, Any]]:
        """
        Apply a promo code to a user. Returns promo details if successful, None otherwise.
        Only applies if user hasn't used a promo code before.
        """
        # Check if user already has a promo code
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT promo_code_used FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = await cursor.fetchone()

            if result and result[0]:
                return None  # User already used a promo code

        # Check if promo code is valid
        promo = await self.get_promo_code(code)
        if not promo:
            return None

        # Apply promo code to user
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET promo_code_used = ?, updated_at = ? WHERE telegram_id = ?',
                (promo['code'], datetime.now(), telegram_id)
            )
            # Increment times_used
            await db.execute(
                'UPDATE promo_codes SET times_used = times_used + 1 WHERE UPPER(code) = UPPER(?)',
                (code,)
            )
            await db.commit()

        logger.info(f"Applied promo code {promo['code']} to user {telegram_id}")
        return promo

    async def get_user_promo(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get the promo code a user has applied (if any)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT promo_code_used FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = await cursor.fetchone()

        if not result or not result[0]:
            return None

        return await self.get_promo_code(result[0])

    async def increment_promo_conversion(self, code: str) -> None:
        """Increment the conversion count for a promo code (when user becomes premium)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE promo_codes SET conversions = conversions + 1 WHERE UPPER(code) = UPPER(?)',
                (code,)
            )
            await db.commit()
            logger.info(f"Recorded conversion for promo code {code}")

    async def get_promo_stats(self, code: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a promo code."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                '''SELECT code, discount_percent, applies_to, max_uses, times_used, conversions, is_active, created_at
                   FROM promo_codes WHERE UPPER(code) = UPPER(?)''',
                (code,)
            )
            result = await cursor.fetchone()

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
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO promo_codes (code, discount_percent, applies_to, max_uses)
                       VALUES (?, ?, ?, ?)''',
                    (code.upper(), discount_percent, applies_to, max_uses)
                )
                await db.commit()
            logger.info(f"Created promo code {code.upper()} with {discount_percent}% discount")
            return True
        except Exception as e:
            logger.error(f"Failed to create promo code {code}: {e}")
            return False

    async def delete_promo_code(self, code: str) -> bool:
        """Delete a promo code."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    'DELETE FROM promo_codes WHERE UPPER(code) = UPPER(?)',
                    (code,)
                )
                await db.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Deleted promo code {code.upper()}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to delete promo code {code}: {e}")
            return False

    # Job Storage for Strategy Mode
    async def store_job_for_strategy(self, job_data: Dict[str, Any]) -> None:
        """Store job data for potential strategy mode usage."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO jobs (id, title, link, description, tags, budget, published)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_data['id'],
                job_data.get('title', ''),
                job_data.get('link', ''),
                job_data.get('description', ''),
                ','.join(job_data.get('tags', [])),
                job_data.get('budget', ''),
                str(job_data.get('published', ''))
            ))
            await db.commit()

    async def get_job_for_strategy(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job data for strategy mode."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT id, title, link, description, tags, budget, published FROM jobs WHERE id = ?',
                (job_id,)
            )
            result = await cursor.fetchone()

        if not result:
            return None

        return {
            'id': result[0],
            'title': result[1],
            'link': result[2],
            'description': result[3],
            'tags': result[4].split(',') if result[4] else [],
            'budget': result[5],
            'published': result[6]
        }

    # Payment Activation
    async def activate_user_payment(self, telegram_id: int) -> None:
        """Activate user payment status."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET is_paid = 1, updated_at = ? WHERE telegram_id = ?',
                (datetime.now(), telegram_id)
            )
            await db.commit()

            # Get user ID for referral processing
            cursor = await db.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_result = await cursor.fetchone()
            if user_result:
                user_id = user_result[0]
                await self.activate_referral(user_id)

    async def get_active_users(self) -> List[Dict[str, Any]]:
        """Get all users who have completed onboarding (have keywords).
        
        Note: This returns ALL users with keywords, regardless of payment status.
        Payment status only affects whether proposals are blurred or full - 
        scouts still receive alerts with blurred content.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Return all users who have completed onboarding (have keywords)
            # Payment status is checked separately in send_job_alert for blurring
            cursor = await db.execute(
                'SELECT telegram_id, keywords, created_at FROM users WHERE keywords IS NOT NULL AND keywords != ""'
            )
            rows = await cursor.fetchall()

        users = []
        for row in rows:
            users.append({
                'telegram_id': row[0],
                'keywords': row[1] or '',
                'created_at': row[2]
            })
        return users

    # Proposal Draft Tracking
    async def get_proposal_draft_count(self, telegram_id: int, job_id: str) -> Dict[str, int]:
        """Get proposal draft counts for a user and job."""
        async with aiosqlite.connect(self.db_path) as db:
            # Get user ID
            cursor = await db.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_result = await cursor.fetchone()
            if not user_result:
                return {'draft_count': 0, 'strategy_count': 0}
            
            user_id = user_result[0]
            
            # Get draft counts
            cursor = await db.execute(
                'SELECT draft_count, strategy_count FROM proposal_drafts WHERE user_id = ? AND job_id = ?',
                (user_id, job_id)
            )
            result = await cursor.fetchone()
            
            if result:
                return {'draft_count': result[0], 'strategy_count': result[1]}
            return {'draft_count': 0, 'strategy_count': 0}

    async def increment_proposal_draft(self, telegram_id: int, job_id: str, is_strategy: bool = False) -> int:
        """Increment proposal draft count for a user and job. Returns the new count."""
        async with aiosqlite.connect(self.db_path) as db:
            # Get user ID
            cursor = await db.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_result = await cursor.fetchone()
            if not user_result:
                return 0
            
            user_id = user_result[0]
            
            # Check if record exists
            cursor = await db.execute(
                'SELECT draft_count, strategy_count FROM proposal_drafts WHERE user_id = ? AND job_id = ?',
                (user_id, job_id)
            )
            result = await cursor.fetchone()
            
            if result:
                # Update existing record
                if is_strategy:
                    new_strategy_count = result[1] + 1
                    await db.execute(
                        'UPDATE proposal_drafts SET strategy_count = ?, last_generated_at = ? WHERE user_id = ? AND job_id = ?',
                        (new_strategy_count, datetime.now(), user_id, job_id)
                    )
                    await db.commit()
                    return new_strategy_count
                else:
                    new_draft_count = result[0] + 1
                    await db.execute(
                        'UPDATE proposal_drafts SET draft_count = ?, last_generated_at = ? WHERE user_id = ? AND job_id = ?',
                        (new_draft_count, datetime.now(), user_id, job_id)
                    )
                    await db.commit()
                    return new_draft_count
            else:
                # Create new record
                if is_strategy:
                    await db.execute(
                        'INSERT INTO proposal_drafts (user_id, job_id, draft_count, strategy_count) VALUES (?, ?, 0, 1)',
                        (user_id, job_id)
                    )
                    await db.commit()
                    return 1
                else:
                    await db.execute(
                        'INSERT INTO proposal_drafts (user_id, job_id, draft_count, strategy_count) VALUES (?, ?, 1, 0)',
                        (user_id, job_id)
                    )
                    await db.commit()
                    return 1

    # Database Statistics (for admin dashboard)
    async def get_database_stats(self) -> Dict[str, Any]:
        """Get comprehensive database statistics for admin dashboard."""
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            
            # User statistics
            cursor = await db.execute('SELECT COUNT(*) FROM users')
            stats['total_users'] = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM users WHERE is_paid = 1')
            stats['paid_users'] = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM users WHERE keywords IS NOT NULL AND keywords != ""')
            stats['users_with_keywords'] = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM users WHERE is_paid = 0')
            stats['unpaid_users'] = (await cursor.fetchone())[0]
            
            # Job statistics
            cursor = await db.execute('SELECT COUNT(*) FROM seen_jobs')
            stats['total_jobs_seen'] = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM jobs')
            stats['jobs_stored'] = (await cursor.fetchone())[0]
            
            # Referral statistics
            cursor = await db.execute('SELECT COUNT(*) FROM referrals')
            stats['total_referrals'] = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT COUNT(*) FROM referrals WHERE status = "activated"')
            stats['activated_referrals'] = (await cursor.fetchone())[0]
            
            # Proposal draft statistics
            cursor = await db.execute('SELECT COUNT(*) FROM proposal_drafts')
            stats['total_proposal_drafts'] = (await cursor.fetchone())[0]
            
            cursor = await db.execute('SELECT SUM(draft_count) FROM proposal_drafts')
            result = await cursor.fetchone()
            stats['total_regular_drafts'] = result[0] or 0
            
            cursor = await db.execute('SELECT SUM(strategy_count) FROM proposal_drafts')
            result = await cursor.fetchone()
            stats['total_strategy_drafts'] = result[0] or 0
            
            # Recent activity
            cursor = await db.execute('''
                SELECT COUNT(*) FROM seen_jobs 
                WHERE timestamp > datetime('now', '-24 hours')
            ''')
            stats['jobs_last_24h'] = (await cursor.fetchone())[0]
            
            cursor = await db.execute('''
                SELECT COUNT(*) FROM users 
                WHERE created_at > datetime('now', '-7 days')
            ''')
            stats['new_users_7d'] = (await cursor.fetchone())[0]
            
            return stats

    async def get_all_users_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all users for admin view."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT telegram_id, keywords, is_paid, created_at, updated_at, 
                       min_budget, max_budget, experience_levels
                FROM users
                ORDER BY created_at DESC
            ''')
            rows = await cursor.fetchall()
            
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
        async with aiosqlite.connect(self.db_path) as db:
            if telegram_id:
                # Get user ID
                cursor = await db.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
                user_result = await cursor.fetchone()
                if not user_result:
                    return []
                user_id = user_result[0]
                
                cursor = await db.execute('''
                    SELECT pd.job_id, pd.draft_count, pd.strategy_count, pd.last_generated_at,
                           j.title, u.telegram_id
                    FROM proposal_drafts pd
                    LEFT JOIN jobs j ON pd.job_id = j.id
                    LEFT JOIN users u ON pd.user_id = u.id
                    WHERE pd.user_id = ?
                    ORDER BY pd.last_generated_at DESC
                    LIMIT 50
                ''', (user_id,))
            else:
                cursor = await db.execute('''
                    SELECT pd.job_id, pd.draft_count, pd.strategy_count, pd.last_generated_at,
                           j.title, u.telegram_id
                    FROM proposal_drafts pd
                    LEFT JOIN jobs j ON pd.job_id = j.id
                    LEFT JOIN users u ON pd.user_id = u.id
                    ORDER BY pd.last_generated_at DESC
                    LIMIT 100
                ''')
            
            rows = await cursor.fetchall()
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
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                '''SELECT telegram_id, keywords, context, is_paid, state, current_job_id, 
                   created_at, updated_at, min_budget, max_budget, experience_levels, 
                   pause_start, pause_end, country_code, subscription_plan, subscription_expiry,
                   is_auto_renewal, payment_provider, email FROM users WHERE telegram_id = ?''',
                (telegram_id,)
            )
            result = await cursor.fetchone()

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
            'email': result[18]
        }

    # Budget and Filter Settings
    async def update_user_filters(self, telegram_id: int, min_budget: int = None, 
                                   max_budget: int = None, experience_levels: List[str] = None) -> None:
        """Update user budget and experience level filters."""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []
            
            if min_budget is not None:
                updates.append("min_budget = ?")
                params.append(min_budget)
            
            if max_budget is not None:
                updates.append("max_budget = ?")
                params.append(max_budget)
            
            if experience_levels is not None:
                updates.append("experience_levels = ?")
                params.append(','.join(experience_levels))
            
            if updates:
                updates.append("updated_at = ?")
                params.extend([datetime.now(), telegram_id])
                
                query = f'UPDATE users SET {", ".join(updates)} WHERE telegram_id = ?'
                await db.execute(query, params)
                await db.commit()
                logger.info(f"Updated filters for user {telegram_id}")

    # Pause/Schedule Settings
    async def set_user_pause(self, telegram_id: int, hours: int) -> datetime:
        """Pause alerts for X hours. Returns the pause_until datetime."""
        pause_until = datetime.now() + timedelta(hours=hours)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET pause_start = ?, pause_end = NULL, updated_at = ? WHERE telegram_id = ?',
                (pause_until.isoformat(), datetime.now(), telegram_id)
            )
            await db.commit()
            logger.info(f"Paused alerts for user {telegram_id} until {pause_until}")
        return pause_until

    async def set_user_pause_indefinite(self, telegram_id: int) -> None:
        """Pause alerts indefinitely until manually resumed."""
        # Use year 9999 as "indefinite" marker
        pause_until = datetime(9999, 12, 31, 23, 59, 59)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET pause_start = ?, pause_end = NULL, updated_at = ? WHERE telegram_id = ?',
                (pause_until.isoformat(), datetime.now(), telegram_id)
            )
            await db.commit()
            logger.info(f"Paused alerts indefinitely for user {telegram_id}")

    async def clear_user_pause(self, telegram_id: int) -> None:
        """Clear user pause (resume alerts)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET pause_start = NULL, pause_end = NULL, updated_at = ? WHERE telegram_id = ?',
                (datetime.now(), telegram_id)
            )
            await db.commit()
            logger.info(f"Resumed alerts for user {telegram_id}")

    def is_user_paused(self, pause_until_str: str) -> bool:
        """Check if user is currently paused. pause_until_str is ISO format datetime."""
        if not pause_until_str:
            return False
        
        try:
            pause_until = datetime.fromisoformat(pause_until_str)
            return datetime.now() < pause_until
        except (ValueError, TypeError):
            return False
    
    def get_pause_remaining(self, pause_until_str: str) -> str:
        """Get human-readable time remaining on pause."""
        if not pause_until_str:
            return None
        
        try:
            pause_until = datetime.fromisoformat(pause_until_str)
            
            # Check for indefinite pause (year 9999)
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET country_code = ?, updated_at = ? WHERE telegram_id = ?',
                (country_code, datetime.now(), telegram_id)
            )
            await db.commit()
            logger.info(f"Updated country for user {telegram_id}: {country_code}")

    async def update_user_email(self, telegram_id: int, email: str) -> None:
        """Update user's email address (needed for Paystack)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET email = ?, updated_at = ? WHERE telegram_id = ?',
                (email, datetime.now(), telegram_id)
            )
            await db.commit()
            logger.info(f"Updated email for user {telegram_id}")

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user info by email address (for Paystack subscription lookups)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT telegram_id, email, subscription_plan FROM users WHERE email = ?',
                (email,)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def grant_subscription(self, telegram_id: int, plan: str, expiry: datetime, 
                                  payment_provider: str, is_auto_renewal: bool = False) -> None:
        """Grant subscription to user after payment confirmation."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                UPDATE users SET 
                    subscription_plan = ?,
                    subscription_expiry = ?,
                    payment_provider = ?,
                    is_auto_renewal = ?,
                    is_paid = 1,
                    updated_at = ?
                WHERE telegram_id = ?
            ''', (plan, expiry.isoformat(), payment_provider, is_auto_renewal, datetime.now(), telegram_id))
            await db.commit()
            logger.info(f"Granted {plan} subscription to user {telegram_id}, expires: {expiry}")

    async def downgrade_to_scout(self, telegram_id: int) -> None:
        """Downgrade user to scout plan (expired subscription)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                UPDATE users SET 
                    subscription_plan = 'scout',
                    subscription_expiry = NULL,
                    is_auto_renewal = 0,
                    is_paid = 0,
                    updated_at = ?
                WHERE telegram_id = ?
            ''', (datetime.now(), telegram_id))
            await db.commit()
            logger.info(f"Downgraded user {telegram_id} to scout plan")

    async def set_auto_renewal(self, telegram_id: int, enabled: bool) -> None:
        """Set user's auto-renewal status."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET is_auto_renewal = ?, updated_at = ? WHERE telegram_id = ?',
                (1 if enabled else 0, datetime.now(), telegram_id)
            )
            await db.commit()
            logger.info(f"Set auto_renewal={enabled} for user {telegram_id}")

    async def check_subscription_expired(self, telegram_id: int) -> bool:
        """Check if user's subscription has expired. Returns True if expired."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT subscription_plan, subscription_expiry FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = await cursor.fetchone()
        
        if not result:
            return True  # No user found, treat as expired
        
        plan, expiry_str = result
        
        # Scout plan never expires
        if plan == 'scout' or not expiry_str:
            return False
        
        try:
            expiry = datetime.fromisoformat(expiry_str)
            return datetime.now() > expiry
        except:
            return True  # Invalid expiry, treat as expired

    async def get_subscription_status(self, telegram_id: int) -> Dict[str, Any]:
        """Get user's current subscription status."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                '''SELECT subscription_plan, subscription_expiry, is_auto_renewal, 
                   payment_provider, country_code FROM users WHERE telegram_id = ?''',
                (telegram_id,)
            )
            result = await cursor.fetchone()
        
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
                expiry = datetime.fromisoformat(expiry_str)
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
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT telegram_id, subscription_plan, subscription_expiry 
                FROM users 
                WHERE subscription_plan != 'scout' 
                AND subscription_expiry IS NOT NULL
            ''')
            rows = await cursor.fetchall()
        
        expiring_users = []
        for row in rows:
            telegram_id, plan, expiry_str = row
            try:
                expiry = datetime.fromisoformat(expiry_str)
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
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT reveal_credits FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = await cursor.fetchone()
            
            if result:
                return result[0] if result[0] is not None else 3  # Default to 3 if NULL
            return 3  # Default for new users
    
    async def use_reveal_credit(self, telegram_id: int, job_id: str, proposal_text: str) -> bool:
        """
        Use a reveal credit for a user and store the revealed proposal.
        Returns True if credit was used successfully, False if no credits left.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Get user ID
            cursor = await db.execute('SELECT id, reveal_credits FROM users WHERE telegram_id = ?', (telegram_id,))
            user_result = await cursor.fetchone()
            
            if not user_result:
                logger.error(f"User {telegram_id} not found")
                return False
            
            user_id, current_credits = user_result
            
            # Check if user has credits
            if current_credits is None:
                current_credits = 3  # Default
            if current_credits <= 0:
                logger.warning(f"User {telegram_id} has no reveal credits left")
                return False
            
            # Check if job already revealed
            cursor = await db.execute(
                'SELECT id FROM revealed_jobs WHERE user_id = ? AND job_id = ?',
                (user_id, job_id)
            )
            existing = await cursor.fetchone()
            
            if existing:
                # Already revealed - just return True (don't decrement credit)
                logger.info(f"Job {job_id} already revealed for user {telegram_id}")
                return True
            
            # Decrement credit
            new_credits = current_credits - 1
            await db.execute(
                'UPDATE users SET reveal_credits = ?, updated_at = ? WHERE telegram_id = ?',
                (new_credits, datetime.now(), telegram_id)
            )
            
            # Store revealed proposal
            await db.execute(
                'INSERT INTO revealed_jobs (user_id, job_id, proposal_text) VALUES (?, ?, ?)',
                (user_id, job_id, proposal_text)
            )
            
            await db.commit()
            logger.info(f"Used reveal credit for user {telegram_id}, job {job_id}. Credits remaining: {new_credits}")
            return True
    
    async def is_job_revealed(self, telegram_id: int, job_id: str) -> bool:
        """Check if a job has already been revealed for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            # Get user ID
            cursor = await db.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_result = await cursor.fetchone()
            
            if not user_result:
                return False
            
            user_id = user_result[0]
            
            # Check if revealed
            cursor = await db.execute(
                'SELECT id FROM revealed_jobs WHERE user_id = ? AND job_id = ?',
                (user_id, job_id)
            )
            result = await cursor.fetchone()
            return result is not None
    
    async def get_revealed_proposal(self, telegram_id: int, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the stored proposal for a revealed job.
        Returns None if job not revealed, or dict with proposal_text and revealed_at.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Get user ID
            cursor = await db.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_result = await cursor.fetchone()
            
            if not user_result:
                return None
            
            user_id = user_result[0]
            
            # Get revealed proposal
            cursor = await db.execute(
                'SELECT proposal_text, revealed_at FROM revealed_jobs WHERE user_id = ? AND job_id = ?',
                (user_id, job_id)
            )
            result = await cursor.fetchone()
            
            if result:
                return {
                    'proposal_text': result[0],
                    'revealed_at': result[1]
                }
            return None
    
    # ==================== PENDING REVEAL JOB (POST-PAYMENT AUTO-REVEAL) ====================
    
    async def set_pending_reveal_job(self, telegram_id: int, job_id: str) -> None:
        """Store the job ID that triggered the paywall for auto-reveal after payment."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET pending_reveal_job_id = ?, updated_at = ? WHERE telegram_id = ?',
                (job_id, datetime.now(), telegram_id)
            )
            await db.commit()
            logger.info(f"Set pending reveal job {job_id} for user {telegram_id}")
    
    async def get_and_clear_pending_reveal_job(self, telegram_id: int) -> Optional[str]:
        """
        Get and clear the pending reveal job ID.
        Returns the job_id if exists, None otherwise.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT pending_reveal_job_id FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = await cursor.fetchone()
            
            if result and result[0]:
                job_id = result[0]
                # Clear it
                await db.execute(
                    'UPDATE users SET pending_reveal_job_id = NULL, updated_at = ? WHERE telegram_id = ?',
                    (datetime.now(), telegram_id)
                )
                await db.commit()
                logger.info(f"Retrieved and cleared pending reveal job {job_id} for user {telegram_id}")
                return job_id
            return None

# Global database instance
db_manager = DatabaseManager()