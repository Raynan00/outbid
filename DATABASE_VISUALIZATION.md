# Database Visualization Guide

Your bot uses SQLite for data storage. Here are several ways to visualize and inspect your database.

## 📊 Admin Commands (Built-in)

The bot includes admin commands you can use directly in Telegram:

### `/admin`
Shows comprehensive database statistics:
- User counts (total, paid, unpaid, new users)
- Job statistics (total seen, stored, last 24h)
- Proposal draft activity
- Referral statistics

### `/admin_users`
Lists all users with their:
- Telegram ID
- Payment status (paid/unpaid)
- Keywords
- Budget filters
- Join date

### `/admin_drafts`
Shows recent proposal draft activity:
- Which users generated proposals
- For which jobs
- Draft counts (regular + strategy)

**Note:** These commands are admin-only. Set your Telegram ID in `ADMIN_IDS` in `.env`.

---

## 🖥️ Desktop Visualization Tools

### Option 1: DB Browser for SQLite (Recommended)

**Download:** https://sqlitebrowser.org/

**Steps:**
1. Download and install DB Browser for SQLite
2. Open the app
3. Click "Open Database"
4. Navigate to your bot directory
5. Select `upwork_bot.db`
6. Browse tables, run queries, export data

**Features:**
- Visual table browser
- SQL query editor
- Data export (CSV, JSON, etc.)
- Database structure viewer
- Data visualization

### Option 2: SQLiteStudio

**Download:** https://sqlitestudio.pl/

Similar to DB Browser, with additional features like:
- Multiple database connections
- Advanced query builder
- Data comparison tools

### Option 3: VS Code Extension

If you use VS Code:
1. Install "SQLite Viewer" extension
2. Right-click `upwork_bot.db` → "Open Database"
3. Browse tables in sidebar

---

## 📋 Database Schema Overview

### `users` Table
Stores all user information:
- `telegram_id` - User's Telegram ID
- `keywords` - User's target keywords
- `context` - User's bio/experience
- `is_paid` - Payment status (0/1)
- `min_budget`, `max_budget` - Budget filters
- `experience_levels` - Experience level filters
- `pause_start`, `pause_end` - Quiet hours
- `created_at`, `updated_at` - Timestamps

### `seen_jobs` Table
Tracks jobs to prevent duplicates:
- `id` - Job hash (primary key)
- `title` - Job title
- `link` - Job URL
- `timestamp` - When job was first seen

### `jobs` Table
Stores job details for strategy mode:
- `id` - Job hash
- `title`, `link`, `description`
- `tags`, `budget`, `published`

### `proposal_drafts` Table
Tracks proposal generation per user per job:
- `user_id` - Internal user ID
- `job_id` - Job hash
- `draft_count` - Regular proposals generated
- `strategy_count` - Strategy proposals generated
- `last_generated_at` - Last generation timestamp

### `referrals` Table
Tracks referral relationships:
- `referrer_id` - Who referred
- `referred_id` - Who was referred
- `referral_code` - Code used
- `status` - pending/activated
- `activated_at` - When activated

---

## 🔍 Useful SQL Queries

### View All Paid Users
```sql
SELECT telegram_id, keywords, created_at 
FROM users 
WHERE is_paid = 1 
ORDER BY created_at DESC;
```

### Find Users Who Hit Draft Limits
```sql
SELECT u.telegram_id, pd.job_id, pd.draft_count, pd.strategy_count
FROM proposal_drafts pd
JOIN users u ON pd.user_id = u.id
WHERE pd.draft_count >= 3 OR pd.strategy_count >= 2;
```

### Recent Job Activity
```sql
SELECT title, timestamp 
FROM seen_jobs 
WHERE timestamp > datetime('now', '-24 hours')
ORDER BY timestamp DESC;
```

### User Growth Over Time
```sql
SELECT 
    DATE(created_at) as date,
    COUNT(*) as new_users
FROM users
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

### Most Active Users (by proposals)
```sql
SELECT 
    u.telegram_id,
    SUM(pd.draft_count + pd.strategy_count) as total_proposals
FROM proposal_drafts pd
JOIN users u ON pd.user_id = u.id
GROUP BY u.telegram_id
ORDER BY total_proposals DESC
LIMIT 10;
```

---

## 📤 Exporting Data

### Export Users to CSV
```bash
sqlite3 upwork_bot.db <<EOF
.headers on
.mode csv
.output users_export.csv
SELECT * FROM users;
.quit
EOF
```

### Export Proposal Activity
```bash
sqlite3 upwork_bot.db <<EOF
.headers on
.mode csv
.output drafts_export.csv
SELECT u.telegram_id, pd.job_id, pd.draft_count, pd.strategy_count, pd.last_generated_at
FROM proposal_drafts pd
JOIN users u ON pd.user_id = u.id;
.quit
EOF
```

---

## 🛠️ Database Maintenance

### Backup Database
```bash
cp upwork_bot.db upwork_bot_backup_$(date +%Y%m%d).db
```

### Clean Old Jobs (older than 30 days)
```sql
DELETE FROM seen_jobs 
WHERE timestamp < datetime('now', '-30 days');
```

### Reset Draft Counts (for testing)
```sql
DELETE FROM proposal_drafts;
```

---

## 💡 Tips

1. **Regular Backups**: Backup your database before major changes
2. **Monitor Size**: SQLite databases can grow - clean old data periodically
3. **Indexes**: The database has indexes on frequently queried columns
4. **Read-Only Mode**: Use read-only mode in DB Browser to avoid accidental changes

---

## 🔐 Security Note

The database contains user data. Keep it secure:
- Don't commit `upwork_bot.db` to git (add to `.gitignore`)
- Restrict file permissions: `chmod 600 upwork_bot.db`
- Backup regularly
- Encrypt backups if storing off-server
