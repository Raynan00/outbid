"""
Configuration management for Upwork First Responder Bot.
Loads environment variables and provides application settings.
"""

import os
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration loaded from environment variables."""

    # Telegram Bot Configuration
    TELEGRAM_TOKEN: str = os.getenv('TELEGRAM_TOKEN', '')
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is required")

    # AI Provider Configuration
    AI_PROVIDER: str = os.getenv('AI_PROVIDER', 'openai').lower()  # 'openai', 'gemini', or 'claude'

    # OpenAI Configuration (required if AI_PROVIDER=openai)
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')

    # Gemini Configuration (required if AI_PROVIDER=gemini)
    GEMINI_API_KEY: str = os.getenv('GEMINI_API_KEY', '')

    # Claude/Anthropic Configuration (used as fallback, or primary if AI_PROVIDER=claude)
    ANTHROPIC_API_KEY: str = os.getenv('ANTHROPIC_API_KEY', '')
    CLAUDE_MODEL: str = os.getenv('CLAUDE_MODEL', 'claude-haiku-4-5-20251001')

    # Upwork Search Configuration
    UPWORK_SEARCH_URL: str = os.getenv('UPWORK_SEARCH_URL', 'https://www.upwork.com/nx/search/jobs/?sort=recency&per_page=50')

    # Admin user IDs (comma-separated)
    ADMIN_IDS: List[int] = [
        int(admin_id.strip()) for admin_id in os.getenv('ADMIN_IDS', '').split(',')
        if admin_id.strip().isdigit()
    ]

    # Database Configuration
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'postgresql://outbid:outbid_secret@localhost:5432/outbid')
    DATABASE_POOL_MIN: int = int(os.getenv('DATABASE_POOL_MIN', '2'))
    DATABASE_POOL_MAX: int = int(os.getenv('DATABASE_POOL_MAX', '10'))
    DATABASE_PATH: str = os.getenv('DATABASE_PATH', 'upwork_bot.db')  # Legacy: used by migration script only

    # Scanner Configuration - CENTRALIZED THROTTLE
    # Change this ONE value to control how often scans run globally
    # Examples: 60 = 1 min, 120 = 2 min, 180 = 3 min
    SCAN_INTERVAL_SECONDS: int = int(os.getenv('SCAN_INTERVAL_SECONDS', '120'))  # Default: 2 min
    RETRY_DELAY_SECONDS: int = int(os.getenv('RETRY_DELAY_SECONDS', '120'))  # Match scan interval

    # OpenAI Configuration
    OPENAI_MODEL: str = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

    # Gemini Configuration
    GEMINI_MODEL: str = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

    # Common AI Configuration
    AI_MAX_TOKENS: int = int(os.getenv('AI_MAX_TOKENS', '1000'))

    # Validate API keys based on provider
    if AI_PROVIDER == 'openai' and not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY environment variable is required when AI_PROVIDER=openai")
    elif AI_PROVIDER == 'gemini' and not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable is required when AI_PROVIDER=gemini")

    # Payment Configuration
    PAYSTACK_SECRET_KEY: str = os.getenv('PAYSTACK_SECRET_KEY', '')
    PAYSTACK_PUBLIC_KEY: str = os.getenv('PAYSTACK_PUBLIC_KEY', '')
    STRIPE_SECRET_KEY: str = os.getenv('STRIPE_SECRET_KEY', '')
    STRIPE_WEBHOOK_SECRET: str = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    STRIPE_PRICE_ID_MONTHLY: str = os.getenv('STRIPE_PRICE_ID_MONTHLY', '')  # Stripe Price ID for monthly subscription
    SUPPORT_CONTACT: str = os.getenv('SUPPORT_CONTACT', '@support_username')
    
    # Pricing (Naira for Nigeria, convert to Kobo for Paystack API)
    # Using charm pricing (-1) for better conversion
    NG_PRICE_DAILY: int = int(os.getenv('NG_PRICE_DAILY', '999'))        # ₦999
    NG_PRICE_WEEKLY: int = int(os.getenv('NG_PRICE_WEEKLY', '2999'))     # ₦2,999
    NG_PRICE_MONTHLY: int = int(os.getenv('NG_PRICE_MONTHLY', '4999'))   # ₦4,999
    GLOBAL_PRICE_MONTHLY_USD: float = float(os.getenv('GLOBAL_PRICE_MONTHLY_USD', '9.99'))  # $9.99/month
    
    # Paystack Plan Code for monthly subscriptions (auto-renewal)
    # Create this in Paystack Dashboard: Payments > Plans > Create Plan
    PAYSTACK_PLAN_CODE_MONTHLY: str = os.getenv('PAYSTACK_PLAN_CODE_MONTHLY', '')  # e.g., PLN_xxxxx
    
    # Webhook server (for payment confirmations)
    WEBHOOK_SERVER_PORT: int = int(os.getenv('WEBHOOK_SERVER_PORT', '5000'))
    WEBHOOK_BASE_URL: str = os.getenv('WEBHOOK_BASE_URL', 'https://your-server.com')  # Your public URL
    
    # Telegram Bot Username (for deep links)
    TELEGRAM_BOT_USERNAME: str = os.getenv('TELEGRAM_BOT_USERNAME', 'OutbidBot')  # Without @

    # Logging Configuration
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    # Referral Configuration
    REFERRAL_DISCOUNT_PERCENT: int = int(os.getenv('REFERRAL_DISCOUNT_PERCENT', '10'))

    # Payment Configuration
    PAYMENTS_ENABLED: bool = os.getenv('PAYMENTS_ENABLED', 'true').lower() == 'true'

    # Scraping Configuration
    SCRAPING_ENABLED: bool = os.getenv('SCRAPING_ENABLED', 'true').lower() == 'true'
    CLOUDFLARE_TIMEOUT: int = int(os.getenv('CLOUDFLARE_TIMEOUT', '60'))
    SCRAPING_RETRIES: int = int(os.getenv('SCRAPING_RETRIES', '3'))
    
    # 2Captcha Configuration (for Cloudflare Turnstile solving)
    CAPTCHA_API_KEY: str = os.getenv('CAPTCHA_API_KEY', '')
    CAPTCHA_ENABLED: bool = os.getenv('CAPTCHA_ENABLED', 'true').lower() == 'true' and bool(os.getenv('CAPTCHA_API_KEY', ''))
    
    # Cloudflare Bypass Server Configuration (supports multiple servers for round-robin)
    # Single URL: http://localhost:8001
    # Multiple URLs: http://localhost:8001,http://localhost:8002,http://localhost:8003
    _bypass_urls_raw: str = os.getenv('CLOUDFLARE_BYPASS_URLS', os.getenv('CLOUDFLARE_BYPASS_URL', 'http://localhost:8001'))
    CLOUDFLARE_BYPASS_URLS: List[str] = [url.strip() for url in _bypass_urls_raw.split(',') if url.strip()]
    CLOUDFLARE_BYPASS_URL: str = CLOUDFLARE_BYPASS_URLS[0] if CLOUDFLARE_BYPASS_URLS else 'http://localhost:8001'  # Backwards compatibility
    CLOUDFLARE_BYPASS_ENABLED: bool = os.getenv('CLOUDFLARE_BYPASS_ENABLED', 'false').lower() == 'true'  # Off by default, BrightData only
    
    # BrightData Unlocker API Configuration
    BRIGHTDATA_UNLOCKER_API_KEY: str = os.getenv('BRIGHTDATA_UNLOCKER_API_KEY', '')
    BRIGHTDATA_UNLOCKER_ZONE: str = os.getenv('BRIGHTDATA_UNLOCKER_ZONE', 'web_unlocker1')  # Configure your zone in BrightData dashboard
    BRIGHTDATA_UNLOCKER_ENABLED: bool = os.getenv('BRIGHTDATA_UNLOCKER_ENABLED', 'true').lower() == 'true' and bool(os.getenv('BRIGHTDATA_UNLOCKER_API_KEY', ''))

    # Proxy Configuration
    PROXY_URL: str = os.getenv('PROXY_URL', '')
    PROXY_ENABLED: bool = os.getenv('PROXY_ENABLED', 'false').lower() == 'true'

    # Solverify Configuration
    SOLVERIFY_API_KEY: str = os.getenv('SOLVERIFY_API_KEY', '')
    SOLVERIFY_ENABLED: bool = os.getenv('SOLVERIFY_ENABLED', 'false').lower() == 'true'

    # Scrapeless API Configuration
    SCRAPELESS_API_KEY: str = os.getenv('SCRAPELESS_API_KEY', '')
    SCRAPELESS_ENABLED: bool = os.getenv('SCRAPELESS_ENABLED', 'false').lower() == 'true'

    # Proposal Draft Limits (abuse control)
    MAX_PROPOSAL_DRAFTS: int = int(os.getenv('MAX_PROPOSAL_DRAFTS', '3'))  # Max regular proposals per job
    MAX_STRATEGY_DRAFTS: int = int(os.getenv('MAX_STRATEGY_DRAFTS', '2'))  # Max strategy proposals per job
    
    # AI Concurrency (for speed optimization)
    # Higher = faster but may hit rate limits. Gemini free tier: 15 req/min, so 10 concurrent is safe
    AI_CONCURRENT_REQUESTS: int = int(os.getenv('AI_CONCURRENT_REQUESTS', '10'))

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """Check if a user ID is in the admin list."""
        return user_id in cls.ADMIN_IDS

    @classmethod
    def get_payment_url(cls, referral_code: str = None) -> str:
        """Get payment URL with optional referral code (legacy - use billing_service instead)."""
        # Note: This is deprecated. Use billing_service.generate_payment_link() instead.
        return ""


# Global configuration instance
config = Config()