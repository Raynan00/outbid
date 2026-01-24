# OutBid - Upwork First Responder Bot

A high-performance Telegram Bot that monitors Upwork in real-time, filters jobs by your criteria, and generates instant AI-powered proposals. Get notified of new jobs within 60 seconds and be the first to apply with personalized cover letters ready to copy-paste.

## 🚀 Complete Feature Summary

### 📡 Core Functionality

| Feature | Description |
|---------|-------------|
| **Real-Time Job Scanning** | Scans Upwork every 60 seconds for new jobs |
| **Cloudflare Bypass** | Uses Docker bypass servers with residential proxies to bypass Upwork's protection |
| **AI-Powered Proposals** | Generates personalized cover letters using Gemini or OpenAI |
| **Instant Telegram Alerts** | Sends job alerts with one-tap copyable proposals |

### 🎯 Smart Filtering System

| Filter | Options |
|--------|---------|
| **Keywords** | User-defined keywords (e.g., "Python, Django, API") - only matching jobs trigger alerts |
| **Budget** | Minimum budget filter ($50+, $100+, $250+, $500+, $1000+, or custom ranges) |
| **Experience Level** | Entry, Intermediate, Expert (single or combined) |
| **Quiet Hours** | Pause alerts during sleep (e.g., 10 PM - 7 AM) |

### 🤖 AI Capabilities

| Feature | Description |
|---------|-------------|
| **Personalized Proposals** | AI uses user's bio/skills to craft tailored cover letters |
| **Multi-Provider Support** | Supports both Google Gemini and OpenAI GPT-4o-mini |
| **"War Room" Strategy Mode** | Click a button on any job to give custom instructions and regenerate the proposal |
| **Cost Protection** | AI only activates for job alerts and defined flows - no wasted API calls on casual chat |

### 👤 User Management

| Feature | Description |
|---------|-------------|
| **Smart Onboarding** | Multi-step setup: collect keywords → collect bio |
| **Settings Management** | `/settings` to view and update all preferences |
| **Update Keywords/Bio** | Modify profile anytime |
| **Referral System** | Unique referral codes, track referred users |
| **Payment Integration** | Paystack ready (can be disabled for testing) |
| **Access Control** | Only authorized/paid users receive alerts |

### 🛡️ Cloudflare Bypass Infrastructure

| Method | Status |
|--------|--------|
| **Docker Bypass Servers** | 3 containers with round-robin rotation |
| **Residential Proxies** | Webshare proxy rotation (215K+ proxies) |
| **Auto-Restart** | Failed containers automatically restart with fresh proxy |
| **BrightData Fallback** | Paid API fallback if Docker fails |
| **Solverify Option** | Cloudflare Interstitial solver (optional) |

### 📊 Data Extracted Per Job

- **Title** - Job title
- **Link** - Direct Upwork job URL
- **Description** - Full job description (500 chars preview)
- **Budget** - Exact amount or range (e.g., "$500" or "$50-$80/hr")
- **Job Type** - Fixed price or Hourly
- **Experience Level** - Entry, Intermediate, or Expert
- **Skills/Tags** - Up to 6 relevant skills
- **Posted Time** - "Posted 2 minutes ago"

---

## 📱 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Begin onboarding or restart |
| `/settings` | View and update all preferences |
| `/status` | Check bot status and scan health |
| `/help` | List all commands |
| `/cancel` | Cancel current operation |

## ⚙️ Settings Menu (via buttons)

```
├── Update Keywords
├── Update Bio  
├── Set Budget Filter
│   ├── Any Budget
│   ├── $50+ / $100+ / $250+ / $500+ / $1000+
│   └── Custom ranges ($100-$500, $500-$2000)
├── Set Experience Filter
│   ├── All Levels
│   ├── Entry / Intermediate / Expert Only
│   └── Intermediate + Expert
└── Set Quiet Hours
    ├── Off
    ├── 10 PM - 7 AM
    ├── 11 PM - 8 AM
    └── Custom times
```

## 📱 Job Alert Format

```
NEW JOB ALERT

Build React Dashboard for SaaS Platform
Budget: $1,500 | Fixed | Intermediate
Posted 1 minute ago
Skills: React, TypeScript, Tailwind CSS

Your Custom Proposal:
```
[AI-generated cover letter in code block for easy copying]
```

Tap the proposal above to copy it instantly!

[🚀 Open Job on Upwork]  [🧠 War Room]
```

---

## 🏗️ Technical Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Telegram Bot                      │
│         (Handles commands, sends alerts)             │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│                   Main Orchestrator                  │
│            (Coordinates all components)              │
└──────┬──────────────┬───────────────────┬───────────┘
       │              │                   │
┌──────▼─────┐ ┌──────▼──────┐ ┌─────────▼─────────┐
│  Scanner   │ │  Database   │ │  AI Brain         │
│ (Scraping) │ │  (SQLite)   │ │ (Gemini/OpenAI)   │
└──────┬─────┘ └─────────────┘ └───────────────────┘
       │
┌──────▼─────────────────────────────────────────────┐
│           Cloudflare Bypass Layer                   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐               │
│  │Docker 1 │ │Docker 2 │ │Docker 3 │ + BrightData  │
│  │ :8001   │ │ :8002   │ │ :8003   │   (fallback)  │
│  └────┬────┘ └────┬────┘ └────┬────┘               │
│       └───────────┼───────────┘                    │
│            Residential Proxies                      │
└────────────────────────────────────────────────────┘
```

---

## 💰 Cost Breakdown (Monthly)

| Item | Cost |
|------|------|
| AWS EC2 (t3.large) | FREE (free tier) |
| Residential Proxies | ~$6 |
| Gemini API | FREE (within free tier) |
| **Total** | **~$6/month** |

---

## 🎯 Ideal For

- ✅ Freelancers who want to be first to apply on Upwork
- ✅ Users who want AI-written proposals ready instantly
- ✅ People who want to filter out low-budget or wrong-level jobs
- ✅ Anyone who needs quiet hours during sleep

---

## Tech Stack

- **Language**: Python 3.11+
- **Telegram**: `python-telegram-bot` (async)
- **Web Scraping**: `BeautifulSoup`, `curl_cffi`, `DrissionPage`
- **AI**: `openai` or `google-generativeai` (async)
- **Database**: `aiosqlite` (async SQLite)
- **Config**: `python-dotenv`
- **Cloudflare Bypass**: Docker containers + residential proxies

---

## Setup Instructions

### 1. Clone and Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your actual values
nano .env
```

**Required environment variables:**
- `TELEGRAM_TOKEN`: Get from [@BotFather](https://t.me/botfather) on Telegram
- `AI_PROVIDER`: Choose 'openai' or 'gemini' (default: gemini)
- `OPENAI_API_KEY`: Required if AI_PROVIDER=openai - Get from [OpenAI Platform](https://platform.openai.com/api-keys)
- `GEMINI_API_KEY`: Required if AI_PROVIDER=gemini - Get from [Google AI Studio](https://makersuite.google.com/app/apikey)
- `GEMINI_MODEL`: Gemini model to use (default: gemini-2.0-flash)
- `UPWORK_SEARCH_URL`: Upwork search URL (default: recent jobs sorted by recency)
- `ADMIN_IDS`: Your Telegram user ID (message [@userinfobot](https://t.me/userinfobot))
- `PAYSTACK_PAYMENT_URL`: Your Paystack payment page URL
- `SUPPORT_CONTACT`: Support Telegram username
- `REFERRAL_DISCOUNT_PERCENT`: Referral discount percentage (default: 10)
- `PAYMENTS_ENABLED`: Set to 'false' to disable payments for testing (default: true)

**Cloudflare Bypass Configuration:**
- `CLOUDFLARE_BYPASS_URLS`: Comma-separated bypass server URLs (default: http://localhost:8001,http://localhost:8002,http://localhost:8003)
- `CLOUDFLARE_BYPASS_ENABLED`: Enable/disable Cloudflare bypass server (default: true)
- `PROXY_URL`: Residential proxy URL (optional, for bypass servers)
- `PROXY_ENABLED`: Enable proxy usage (default: true)

**Optional APIs:**
- `BRIGHTDATA_UNLOCKER_API_KEY`: BrightData Unlocker API key (fallback)
- `BRIGHTDATA_UNLOCKER_ENABLED`: Enable BrightData (default: false)
- `BRIGHTDATA_UNLOCKER_ZONE`: BrightData zone name
- `SOLVERIFY_API_KEY`: Solverify API key (optional)
- `SOLVERIFY_ENABLED`: Enable Solverify (default: false)

**Note:** Keywords are set per-user during onboarding, not globally via environment variables.

### 3. Cloudflare Bypass Setup

The bot uses [CloudflareBypassForScraping](https://github.com/sarperavci/CloudflareBypassForScraping) for reliable Cloudflare bypass:

**Option 1: Docker Compose (Recommended)**
```bash
# Start 3 bypass servers with round-robin rotation
docker-compose up -d

# Or use the helper script
./start_bypass_servers.sh  # Linux/WSL
./start_bypass_servers.ps1  # Windows PowerShell
```

**Option 2: Manual Docker**
```bash
# Start individual containers
docker run -d -p 8001:8000 --name cloudflare_bypass_1 \
  -e PROXY_URL=http://user:pass@proxy:port \
  ghcr.io/sarperavci/cloudflarebypassforscraping:latest

docker run -d -p 8002:8000 --name cloudflare_bypass_2 \
  -e PROXY_URL=http://user:pass@proxy:port \
  ghcr.io/sarperavci/cloudflarebypassforscraping:latest

docker run -d -p 8003:8000 --name cloudflare_bypass_3 \
  -e PROXY_URL=http://user:pass@proxy:port \
  ghcr.io/sarperavci/cloudflarebypassforscraping:latest
```

The bot will automatically:
- Rotate requests across all 3 bypass servers
- Auto-restart failed containers
- Fall back to BrightData if all servers fail

### 4. Run the Bot

```bash
python main.py
```

The bot will:
1. Initialize the database
2. Start monitoring Upwork (scans every 60 seconds)
3. Begin polling for Telegram messages
4. Send alerts when matching jobs are found

---

## AI Provider Options

Choose between **OpenAI GPT** or **Google Gemini** for proposal generation:

### Google Gemini (Recommended)
- **Models**: Gemini-2.0-flash, Gemini-1.5-pro
- **Pricing**: Generous free tier (15 req/min, 1,500/day) + pay-per-token
- **Setup**: `AI_PROVIDER=gemini` and `GEMINI_API_KEY=your_key`

### OpenAI GPT
- **Models**: GPT-4o-mini, GPT-4, GPT-3.5-turbo
- **Pricing**: Pay-per-token (~$0.002/1k tokens)
- **Setup**: `AI_PROVIDER=openai` and `OPENAI_API_KEY=your_key`

**Switch anytime**: Just change `AI_PROVIDER` in your `.env` and restart the bot!

---

## User Journey

### Phase 1: Entry & Onboarding
1. **Start**: Send `/start` (or `/start REFERRALCODE` for referral discounts)
2. **Payment**: Complete Paystack payment if not authorized (disabled for testing)
3. **Setup Keywords**: Enter your target skills (e.g., "Python, Django, API")
4. **Setup Bio**: Paste your professional experience/background

### Phase 2: Active Monitoring
- Bot uses **browser automation** to scrape Upwork search pages
- **Filters jobs per-user** based on your individual keywords, budget, and experience level
- Receives instant alerts for **your specific criteria only**
- Each alert includes AI-generated proposal + strategy option

### Phase 3: War Room Strategy
- Click "🧠 War Room" on any job alert
- Enter specific tactics (e.g., "Focus on my speed and timezone advantage")
- Receive customized strategic proposal

---

## Referral System

Earn discounts by referring friends:
1. Get your referral code from `/settings`
2. Share links like: `https://t.me/your_bot?start=YOURCODE`
3. Friends get discount, you earn rewards when they subscribe!

---

## Project Structure

```
.
├── config.py          # Environment configuration
├── database.py        # Async SQLite operations
├── scanner.py         # Upwork scraping & Cloudflare bypass
├── brain.py           # AI proposal generation
├── bot.py            # Telegram bot logic
├── main.py           # Application orchestration
├── requirements.txt   # Python dependencies
├── .env.example      # Environment template
├── docker-compose.yml # Docker setup for bypass servers
├── start_bypass_servers.sh  # Linux helper script
├── start_bypass_servers.ps1 # Windows helper script
└── README.md         # This file
```

---

## Key Features Explained

### One-Tap Copy
Proposals are wrapped in ```markdown code blocks``` so mobile users can tap to copy instantly.

### Access Control
- Users must be in the database or admin list
- Subscriptions have expiration dates
- Automatic cleanup of expired users

### Error Handling
- Scraping failures retry with different bypass servers
- OpenAI/Gemini failures send job link without proposal
- Comprehensive logging for debugging

### Deduplication
- Jobs are tracked by unique ID
- Prevents spam on bot restart
- Database cleanup removes old entries

### Smart Filtering
- **Budget Filter**: Only show jobs above your minimum budget
- **Experience Filter**: Only show jobs matching your skill level
- **Quiet Hours**: Automatically pause alerts during sleep hours

---

## Deployment

### VPS Requirements
This bot requires a VPS (not free hosting) because it uses browser automation and Docker:

**Recommended Providers:**
- **AWS EC2**: t3.medium or t3.large (free tier eligible)
- **DigitalOcean Droplet**: Ubuntu 22.04, 2GB RAM (~$12/month)
- **Hetzner Cloud**: Ubuntu 22.04, 2GB RAM (~$8/month)

**Server Setup:**
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install docker-compose

# Install Python dependencies
pip install -r requirements.txt

# Start bypass servers
docker-compose up -d

# Run the bot
python main.py
```

### Why VPS Required
- Browser automation needs Chrome/Chromium installed
- Docker containers for bypass servers need system resources
- Free tiers (Railway, Vercel, Render) don't allow browsers/Docker

---

## Development

### Customizing Search URL
Edit `UPWORK_SEARCH_URL` to change which jobs are scraped:
```bash
# Recent jobs (default)
UPWORK_SEARCH_URL=https://www.upwork.com/nx/search/jobs/?sort=recency&per_page=50

# High-paying jobs
UPWORK_SEARCH_URL=https://www.upwork.com/nx/search/jobs/?sort=budget&per_page=50
```

### Customizing AI Prompts
Modify the system prompt in `brain.py` for different proposal styles.

### Database Schema
The SQLite database includes:
- `users`: User profiles, keywords, bio, payment status, filters (budget, experience, quiet hours), state management
- `seen_jobs`: Job deduplication tracking
- `referrals`: Referral system tracking and rewards
- `jobs`: Job data storage for strategy mode

---

## Troubleshooting

### Bot Not Responding
1. Check Telegram token is correct
2. Verify bot is running (`ps aux | grep main.py`)
3. Check logs for errors

### No Job Alerts
1. Verify bypass servers are running (`docker ps`)
2. Check keywords match job postings
3. Ensure users are authorized
4. Review scanner logs
5. Check if filters are too restrictive (budget/experience)

### Cloudflare Bypass Failing
1. Verify Docker containers are running: `docker ps | grep cloudflare`
2. Check bypass server logs: `docker logs cloudflare_bypass_1`
3. Verify residential proxies are configured correctly
4. Try restarting containers: `docker restart cloudflare_bypass_1 cloudflare_bypass_2 cloudflare_bypass_3`

### AI Errors
1. Check API key is valid
2. Verify billing status on OpenAI/Gemini
3. Monitor rate limits
4. Check if free tier limits are exceeded

---

## License

This project is provided as-is for educational and personal use.
