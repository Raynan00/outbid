"""
Access Control Service for Upwork First Responder Bot.
Handles country detection, subscription validation, and permission checks.
"""

import logging
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any
from telegram import Update

from config import config
from database import db_manager

logger = logging.getLogger(__name__)


# ==================== PERMISSIONS ====================

SCOUT_PERMISSIONS = {
    "can_view_proposal": False,      # Blurred
    "can_view_job_link": False,      # No Upwork URL
    "can_use_war_room": False,       # No strategy mode
    "show_upgrade_cta": True         # Always show upgrade button
}

PAID_PERMISSIONS = {
    "can_view_proposal": True,
    "can_view_job_link": True,
    "can_use_war_room": True,
    "show_upgrade_cta": False
}


class AccessService:
    """Manages user access levels, country detection, and subscription validation."""
    
    def __init__(self):
        self.ip_api_url = "http://ip-api.com/json"  # Free, no key needed, 45 req/min
    
    # ==================== COUNTRY DETECTION ====================
    
    async def detect_user_country(self, telegram_id: int, update: Update = None) -> str:
        """
        Auto-detect user country using multiple methods.
        
        Detection order:
        1. Check DB (if already set)
        2. Check Telegram phone number prefix (+234 = Nigeria) - most reliable
        3. Check language_code fallback (e.g., "en-NG", "yo", "ig", "ha" = Nigeria)
        4. Default to 'GLOBAL'
        
        Returns: 'NG' or 'GLOBAL'
        """
        # 1. Check existing DB value
        user_info = await db_manager.get_user_info(telegram_id)
        if user_info and user_info.get('country_code'):
            return user_info['country_code']
        
        # 2. Check phone number first (most reliable)
        if update and update.effective_user:
            phone = getattr(update.effective_user, 'phone_number', None)
            if phone:
                if phone.startswith('+234') or phone.startswith('234'):
                    await db_manager.update_user_country(telegram_id, 'NG')
                    logger.info(f"Detected Nigeria (NG) for user {telegram_id} via phone number")
                    return 'NG'
        
        # 3. Fallback: Check language_code
        if update and update.effective_user:
            lang_code = (getattr(update.effective_user, 'language_code', None) or '').lower()
            if lang_code:
                # Nigerian language codes
                if 'ng' in lang_code or lang_code in ['yo', 'ig', 'ha']:
                    await db_manager.update_user_country(telegram_id, 'NG')
                    logger.info(f"Detected Nigeria (NG) for user {telegram_id} via language_code: {lang_code}")
                    return 'NG'
        
        # 4. Default to GLOBAL
        await db_manager.update_user_country(telegram_id, 'GLOBAL')
        logger.info(f"Defaulted to GLOBAL for user {telegram_id}")
        return 'GLOBAL'
    
    async def detect_country_from_ip(self, ip_address: str) -> str:
        """
        Detect country from IP address using geolocation API.
        Called when user visits payment page.
        
        Returns: 'NG' or 'GLOBAL'
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f'{self.ip_api_url}/{ip_address}', timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        country_code = data.get('countryCode', '')
                        
                        if country_code == 'NG':
                            logger.info(f"IP {ip_address} detected as Nigeria (NG)")
                            return 'NG'
                        
                        logger.info(f"IP {ip_address} detected as {country_code} -> GLOBAL")
                        return 'GLOBAL'
        except Exception as e:
            logger.error(f"IP geolocation failed for {ip_address}: {e}")
        
        return 'GLOBAL'  # Default to GLOBAL on error
    
    async def update_country_from_ip(self, telegram_id: int, ip_address: str) -> str:
        """
        Update user's country based on IP address.
        Called when user visits payment page.
        
        Returns: 'NG' or 'GLOBAL'
        """
        country = await self.detect_country_from_ip(ip_address)
        await db_manager.update_user_country(telegram_id, country)
        return country
    
    # ==================== SUBSCRIPTION VALIDATION ====================
    
    async def check_and_handle_expiry(self, telegram_id: int) -> bool:
        """
        Check if user subscription expired and downgrade immediately.
        Returns True if user was downgraded, False if still active.
        """
        # Check if expired
        is_expired = await db_manager.check_subscription_expired(telegram_id)
        
        if is_expired:
            # Get current status to see if they were previously paid
            status = await db_manager.get_subscription_status(telegram_id)
            
            # Only downgrade if they had a paid plan (not already scout)
            if status['plan'] != 'scout':
                await db_manager.downgrade_to_scout(telegram_id)
                logger.info(f"Auto-downgraded expired user {telegram_id} to scout")
                return True
        
        return False
    
    async def get_user_permissions(self, telegram_id: int) -> Dict[str, Any]:
        """
        Get user's current permissions based on subscription status.
        Also handles auto-downgrade if subscription expired.
        
        Returns: Permission dictionary
        """
        # First, check if admin (always has full access)
        if config.is_admin(telegram_id):
            return {
                **PAID_PERMISSIONS,
                "is_admin": True,
                "plan": "admin"
            }
        
        # If payments disabled globally, everyone gets full access
        if not config.PAYMENTS_ENABLED:
            return {
                **PAID_PERMISSIONS,
                "is_admin": False,
                "plan": "free_mode"
            }
        
        # Check and handle expiry (auto-downgrade if needed)
        was_downgraded = await self.check_and_handle_expiry(telegram_id)
        
        # Get subscription status
        status = await db_manager.get_subscription_status(telegram_id)
        
        if status['is_active'] or status['plan'] in ['daily', 'weekly', 'monthly']:
            # Re-check after potential downgrade
            if not was_downgraded and status['is_active']:
                return {
                    **PAID_PERMISSIONS,
                    "is_admin": False,
                    "plan": status['plan'],
                    "days_remaining": status['days_remaining'],
                    "expiry": status['expiry']
                }
        
        # Scout plan (free) - blurred proposals, no job link
        return {
            **SCOUT_PERMISSIONS,
            "is_admin": False,
            "plan": "scout",
            "days_remaining": 0,
            "expiry": None
        }
    
    async def can_view_proposal(self, telegram_id: int) -> bool:
        """Check if user can view full proposals."""
        permissions = await self.get_user_permissions(telegram_id)
        return permissions.get('can_view_proposal', False)
    
    async def can_view_job_link(self, telegram_id: int) -> bool:
        """Check if user can view job links."""
        permissions = await self.get_user_permissions(telegram_id)
        return permissions.get('can_view_job_link', False)
    
    async def can_use_war_room(self, telegram_id: int) -> bool:
        """Check if user can use War Room (strategy mode)."""
        permissions = await self.get_user_permissions(telegram_id)
        return permissions.get('can_use_war_room', False)
    
    async def should_show_upgrade_cta(self, telegram_id: int) -> bool:
        """Check if we should show upgrade CTA to user."""
        permissions = await self.get_user_permissions(telegram_id)
        return permissions.get('show_upgrade_cta', True)
    
    # ==================== DOWNGRADE NOTIFICATION ====================
    
    def get_downgrade_message(self) -> str:
        """Get the message to send when user is auto-downgraded."""
        return (
            "⏰ *Your subscription has expired*\n\n"
            "You've been moved to free access.\n\n"
            "You'll still get:\n"
            "✅ Unlimited job alerts\n"
            "✅ 3 Reveal Credits to unlock jobs\n"
            "⚠️ Blurred proposals (use credits or upgrade to view)\n"
            "⚠️ No job links (upgrade to view)\n"
            "⚠️ No War Room access\n\n"
            "💎 *Upgrade to continue getting full proposals:*\n"
            "Use /upgrade to choose a plan."
        )


# Global access service instance
access_service = AccessService()
