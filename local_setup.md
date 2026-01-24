# 🏠 Local Development Setup Guide

## Prerequisites

### 1. Python 3.11+
```bash
python --version  # Should show 3.11 or higher
```

### 2. Chrome/Chromium Browser
**Required** for browser automation (DrissionPage needs it).

#### Windows:
- Download from: https://www.google.com/chrome/
- Or use Microsoft Edge (Chromium-based)

#### macOS:
```bash
# Using Homebrew
brew install --cask google-chrome

# Or install Chromium
brew install chromium
```

#### Linux (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install chromium-browser
```

#### Verify Installation:
```bash
# Windows
where chrome

# macOS/Linux
which google-chrome || which chromium-browser
```

## 🚀 Quick Start (5 minutes)

### Step 1: Clone & Install
```bash
# Install dependencies
pip install -r requirements.txt
```

### Step 2: Setup Environment
```bash
# Copy the test config
cp test_env.example .env

# Edit with your real keys (open .env in editor)
# Choose your AI provider:

## Option 1: OpenAI (Default)
# TELEGRAM_TOKEN=your_telegram_bot_token_here
# AI_PROVIDER=openai
# OPENAI_API_KEY=your_openai_api_key_here

## Option 2: Google Gemini
# TELEGRAM_TOKEN=your_telegram_bot_token_here
# AI_PROVIDER=gemini
# GEMINI_API_KEY=your_gemini_api_key_here
```

### Step 3: Get Required API Keys

#### Telegram Bot Token:
1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot`
3. Follow instructions to create bot
4. Copy the token (looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

#### OpenAI API Key:
1. Go to [OpenAI Platform](https://platform.openai.com/api-keys)
2. Create new API key
3. Copy the key (looks like: `sk-...`)

#### Gemini API Key (Alternative):
1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create new API key
3. Copy the key (looks like: `AIza...`)
4. **Bonus**: Gemini has a generous free tier!

### Step 4: Run the Bot
```bash
python main.py
```

## 🔧 Detailed Setup

### Environment Variables
Edit your `.env` file:

```bash
# Required
TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
OPENAI_API_KEY=sk-your-openai-key-here

# Optional (defaults provided)
UPWORK_SEARCH_URL=https://www.upwork.com/nx/search/jobs/?sort=recency&per_page=50
ADMIN_IDS=your_telegram_user_id
DATABASE_PATH=upwork_bot.db
SCAN_INTERVAL_SECONDS=60
PAYSTACK_PAYMENT_URL=https://paystack.com/pay/upwork-first-responder
SUPPORT_CONTACT=@your_support_username
REFERRAL_DISCOUNT_PERCENT=10
PAYMENTS_ENABLED=false  # Keep false for testing
LOG_LEVEL=INFO
```

### Get Your Telegram User ID
1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send `/start`
3. Copy your numeric user ID
4. Add to `ADMIN_IDS` in `.env`

## 🧪 Testing the Bot

### 1. Start the Bot
```bash
python main.py
```

### 2. Test Commands
In Telegram, message your bot:

```
/start              # Begin onboarding
/status            # Check bot status
/settings          # View your profile
/help              # Show help
```

### 3. Verify Browser Works
The bot will show logs like:
```
INFO - Starting Upwork browser-based scanner
INFO - Initializing DrissionPage browser...
INFO - Browser initialized successfully
INFO - Pre-filling seen jobs cache from current job listings
INFO - Found X new jobs
```

## 🐛 Troubleshooting

### Chrome/Chromium Not Found
```
Error: Failed to initialize browser: [Errno 2] No such file or directory: 'chromium'
```

**Solution:**
- Install Chrome/Chromium (see prerequisites above)
- Make sure it's in your PATH
- Try full path in code if needed

### Missing Dependencies
```
ModuleNotFoundError: No module named 'DrissionPage'
```

**Solution:**
```bash
pip install DrissionPage==4.0.4b18
```

### Telegram Token Invalid
```
telegram.error.Unauthorized: Unauthorized
```

**Solution:**
- Double-check your bot token from @BotFather
- Make sure token is correct in `.env`

### OpenAI API Key Invalid
```
openai.AuthenticationError: Incorrect API key provided
```

**Solution:**
- Check your OpenAI API key
- Make sure billing is enabled on OpenAI account
- Verify key has credits

### Browser Won't Start
```
Error: Failed to initialize browser
```

**Solutions:**
- Try running as administrator/sudo
- Check if Chrome is already running (close it)
- Try different Chrome path
- Check system resources (RAM, disk space)

## 🔍 Debugging

### Enable Debug Logging
In `.env`:
```bash
LOG_LEVEL=DEBUG
```

### Test Browser Manually
```python
from DrissionPage import ChromiumPage, ChromiumOptions

options = ChromiumOptions()
options.headless()
page = ChromiumPage(options)
page.get('https://www.google.com')
print("Browser works!")
page.quit()
```

### Check Chrome Version
```bash
# Windows
chrome --version

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version

# Linux
chromium-browser --version
```

## 📁 Project Structure
```
.
├── main.py           # Entry point
├── config.py         # Configuration
├── database.py       # SQLite database
├── scanner.py        # Browser automation
├── brain.py          # AI proposal generation
├── bot.py           # Telegram bot
├── requirements.txt  # Dependencies
├── .env             # Your config (create this)
└── upwork_bot.db    # Database (created automatically)
```

## 🚦 Next Steps

1. **Bot Working?** → Test onboarding flow
2. **Jobs Appearing?** → Check scanner logs
3. **Payments?** → Set `PAYMENTS_ENABLED=true` when ready
4. **Production?** → Deploy to VPS (needs Chrome installed)

## 💡 Tips

- **Keep `PAYMENTS_ENABLED=false`** for testing
- **Use `/status`** to monitor bot activity
- **Check logs** for any errors
- **Admin access** lets you test all features
- **Browser stays running** between scans (performance optimized)

**Ready to test?** Run `python main.py` and message your bot! 🎉