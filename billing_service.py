"""
Billing Service for Upwork First Responder Bot.
Handles Paystack (Nigeria) and Stripe (Global) payment integration.
"""

import logging
import aiohttp
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List

from config import config
from database import db_manager

logger = logging.getLogger(__name__)


# ==================== PRICING ====================

NG_PRICING = {
    'daily': config.NG_PRICE_DAILY,      # ₦999
    'weekly': config.NG_PRICE_WEEKLY,    # ₦2,999
    'monthly': config.NG_PRICE_MONTHLY   # ₦4,999
}

PLAN_NAMES = {
    'daily': 'Daily Hustle',
    'weekly': 'Weekly Sprint',
    'monthly': 'Monthly Pro',
    'scout': 'Free Access'  # Don't show "Scout" to users - use friendly language
}

PLAN_DURATIONS = {
    'daily': timedelta(hours=24),
    'weekly': timedelta(days=7),
    'monthly': timedelta(days=30)
}


class BillingService:
    """Handles payment processing for Paystack (NG) and Stripe (Global)."""
    
    def __init__(self):
        self.paystack_base_url = "https://api.paystack.co"
        self.paystack_secret = config.PAYSTACK_SECRET_KEY
        
    # ==================== PRICING HELPERS ====================
    
    def get_pricing_for_country(self, country_code: str) -> Dict[str, Any]:
        """Get pricing options based on user's country."""
        if country_code == 'NG':
            return {
                'currency': 'NGN',
                'currency_symbol': '₦',
                'plans': {
                    'daily': {'price': NG_PRICING['daily'], 'display': f"₦{NG_PRICING['daily']:,}"},
                    'weekly': {'price': NG_PRICING['weekly'], 'display': f"₦{NG_PRICING['weekly']:,}"},
                    'monthly': {'price': NG_PRICING['monthly'], 'display': f"₦{NG_PRICING['monthly']:,}"}
                },
                'provider': 'paystack'
            }
        else:
            # Global pricing (Stripe, USD, monthly only)
            return {
                'currency': 'USD',
                'currency_symbol': '$',
                'plans': {
                    'monthly': {'price': config.GLOBAL_PRICE_MONTHLY_USD, 'display': f"${config.GLOBAL_PRICE_MONTHLY_USD:.2f}"}
                },
                'provider': 'stripe'
            }
    
    def get_plan_name(self, plan: str) -> str:
        """Get human-readable plan name."""
        return PLAN_NAMES.get(plan, plan.title())
    
    def get_plan_benefits(self, plan: str) -> List[str]:
        """Get list of benefits for a plan."""
        if plan == 'daily':
            return [
                "Unlimited job reveals for 24 hours",
                "AI-written proposals for every job",
                "Direct links to apply instantly",
                "War Room strategy mode"
            ]
        elif plan == 'weekly':
            return [
                "Unlimited job reveals for 7 days",
                "AI-written proposals for every job",
                "Direct links to apply instantly",
                "War Room strategy mode"
            ]
        elif plan == 'monthly':
            return [
                "Unlimited job reveals for 30 days",
                "AI-written proposals for every job",
                "Direct links to apply instantly",
                "War Room strategy mode"
            ]
        return []
    
    def calculate_expiry(self, plan: str) -> datetime:
        """Calculate subscription expiry date based on plan."""
        duration = PLAN_DURATIONS.get(plan, timedelta(days=1))
        return datetime.now() + duration
    
    # ==================== PAYSTACK (NIGERIA) ====================
    
    async def initialize_paystack_transaction(
        self, 
        telegram_id: int, 
        email: str, 
        plan: str,
        callback_url: str = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Initialize a Paystack transaction for Nigeria users.
        
        Args:
            telegram_id: User's Telegram ID
            email: User's email address
            plan: 'daily', 'weekly', or 'monthly'
            callback_url: Optional callback URL after payment
            
        Returns:
            Tuple of (authorization_url, reference) or (None, error_message)
        """
        if not self.paystack_secret:
            logger.error("Paystack secret key not configured")
            return None, "Payment system not configured"
        
        if plan not in NG_PRICING:
            return None, f"Invalid plan: {plan}"
        
        # Amount in Kobo (Paystack expects Kobo, not Naira)
        amount_kobo = NG_PRICING[plan] * 100
        
        # Generate unique reference
        reference = f"outbid_{telegram_id}_{plan}_{int(datetime.now().timestamp())}"
        
        # Base payload
        payload = {
            "email": email,
            "amount": amount_kobo,
            "reference": reference,
            "callback_url": callback_url or f"{config.WEBHOOK_BASE_URL}/payment/callback",
            "metadata": {
                "telegram_id": telegram_id,
                "plan": plan,
                "custom_fields": [
                    {"display_name": "Telegram ID", "variable_name": "telegram_id", "value": str(telegram_id)},
                    {"display_name": "Plan", "variable_name": "plan", "value": plan}
                ]
            }
        }
        
        # For monthly plan, show card first but allow all payment methods
        # Note: Paystack Plans (auto-renewal) only work with card, so we skip it
        # to allow users flexibility in payment method. Manual renewal reminders instead.
        if plan == 'monthly':
            # Card first = default selection, but other options still available
            payload["channels"] = ["card", "bank_transfer", "ussd", "bank"]
        
        headers = {
            "Authorization": f"Bearer {self.paystack_secret}",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.paystack_base_url}/transaction/initialize",
                    json=payload,
                    headers=headers,
                    timeout=30
                ) as resp:
                    data = await resp.json()
                    
                    if resp.status == 200 and data.get('status'):
                        auth_url = data['data']['authorization_url']
                        ref = data['data']['reference']
                        logger.info(f"Paystack transaction initialized for user {telegram_id}, plan: {plan}, ref: {ref}")
                        return auth_url, ref
                    else:
                        error_msg = data.get('message', 'Payment initialization failed')
                        logger.error(f"Paystack error: {error_msg}")
                        return None, error_msg
                        
        except Exception as e:
            logger.error(f"Paystack request failed: {e}")
            return None, f"Payment service error: {str(e)}"
    
    async def verify_paystack_transaction(self, reference: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Verify a Paystack transaction by reference.
        
        Returns:
            Tuple of (success, data) where data contains transaction details
        """
        if not self.paystack_secret:
            return False, {"error": "Paystack not configured"}
        
        headers = {
            "Authorization": f"Bearer {self.paystack_secret}"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.paystack_base_url}/transaction/verify/{reference}",
                    headers=headers,
                    timeout=30
                ) as resp:
                    data = await resp.json()
                    
                    if resp.status == 200 and data.get('status'):
                        tx_data = data['data']
                        
                        if tx_data.get('status') == 'success':
                            return True, {
                                'telegram_id': tx_data.get('metadata', {}).get('telegram_id'),
                                'plan': tx_data.get('metadata', {}).get('plan'),
                                'amount': tx_data.get('amount', 0) / 100,  # Convert from Kobo
                                'email': tx_data.get('customer', {}).get('email'),
                                'reference': reference
                            }
                        else:
                            return False, {"error": f"Transaction status: {tx_data.get('status')}"}
                    else:
                        return False, {"error": data.get('message', 'Verification failed')}
                        
        except Exception as e:
            logger.error(f"Paystack verification failed: {e}")
            return False, {"error": str(e)}
    
    def verify_paystack_webhook_signature(self, payload: str, signature: str) -> bool:
        """Verify Paystack webhook signature."""
        if not self.paystack_secret:
            return False
        
        expected_signature = hmac.new(
            self.paystack_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    
    # ==================== STRIPE (GLOBAL) ====================
    
    async def create_stripe_checkout_session(
        self, 
        telegram_id: int,
        success_url: str = None,
        cancel_url: str = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Create a Stripe Checkout session for global users.
        
        Returns:
            Tuple of (checkout_url, session_id) or (None, error_message)
        """
        # Note: This requires the stripe library to be installed
        # pip install stripe
        try:
            import stripe
            stripe.api_key = config.STRIPE_SECRET_KEY
            
            if not config.STRIPE_SECRET_KEY or not config.STRIPE_PRICE_ID_MONTHLY:
                return None, "Stripe not configured"
            
            session = stripe.checkout.Session.create(
                mode='subscription',
                line_items=[{
                    'price': config.STRIPE_PRICE_ID_MONTHLY,
                    'quantity': 1
                }],
                client_reference_id=str(telegram_id),
                metadata={
                    'telegram_id': telegram_id,
                    'plan': 'monthly'
                },
                success_url=success_url or f"{config.WEBHOOK_BASE_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url or f"{config.WEBHOOK_BASE_URL}/payment/cancel"
            )
            
            logger.info(f"Stripe session created for user {telegram_id}: {session.id}")
            return session.url, session.id
            
        except ImportError:
            logger.error("Stripe library not installed. Run: pip install stripe")
            return None, "Payment system not available"
        except Exception as e:
            logger.error(f"Stripe session creation failed: {e}")
            return None, f"Payment error: {str(e)}"
    
    # ==================== GRANT ACCESS ====================
    
    async def grant_access(
        self, 
        telegram_id: int, 
        plan: str, 
        payment_provider: str
    ) -> bool:
        """
        Grant subscription access to user after payment confirmation.
        
        Args:
            telegram_id: User's Telegram ID
            plan: 'daily', 'weekly', or 'monthly'
            payment_provider: 'paystack' or 'stripe'
            
        Returns:
            True if successful, False otherwise
        """
        try:
            expiry = self.calculate_expiry(plan)
            # Auto-renewal only for Stripe monthly (Paystack uses manual renewal)
            is_auto_renewal = (payment_provider == 'stripe' and plan == 'monthly')
            
            await db_manager.grant_subscription(
                telegram_id=telegram_id,
                plan=plan,
                expiry=expiry,
                payment_provider=payment_provider,
                is_auto_renewal=is_auto_renewal
            )
            
            logger.info(f"Granted {plan} subscription to user {telegram_id} via {payment_provider}, expires: {expiry}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to grant access to user {telegram_id}: {e}")
            return False
    
    def get_success_message(self, plan: str) -> str:
        """Get the success message to send after payment confirmation."""
        plan_name = self.get_plan_name(plan)
        expiry = self.calculate_expiry(plan)
        expiry_display = expiry.strftime("%B %d, %Y at %I:%M %p")
        
        return (
            f"✅ *Payment Successful!*\n\n"
            f"You're now on the *{plan_name}* plan.\n\n"
            f"⏰ Expires: {expiry_display}\n\n"
            f"🎉 You now have:\n"
            f"• Full proposal access\n"
            f"• Job links to apply directly\n"
            f"• War Room strategy mode\n"
            f"• Real-time job alerts\n\n"
            f"Happy job hunting! 🚀"
        )
    
    # ==================== GENERATE PAYMENT LINK ====================
    
    async def generate_payment_link(
        self, 
        telegram_id: int, 
        plan: str,
        email: str = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate payment link based on user country and plan.
        
        Args:
            telegram_id: User's Telegram ID
            plan: 'daily', 'weekly', or 'monthly'
            email: User's email (required for Paystack)
            
        Returns:
            Tuple of (payment_url, error_message)
        """
        # Get user's country
        user_info = await db_manager.get_user_info(telegram_id)
        country_code = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
        
        if country_code == 'NG':
            # Nigeria - Paystack
            if not email:
                # Try to get email from database
                email = user_info.get('email') if user_info else None
                
            if not email:
                return None, "Email required for payment. Please provide your email."
            
            return await self.initialize_paystack_transaction(telegram_id, email, plan)
            
        else:
            # Global - Stripe (monthly only)
            if plan != 'monthly':
                return None, "Only monthly subscription available for international users."
            
            return await self.create_stripe_checkout_session(telegram_id)


# Global billing service instance
billing_service = BillingService()
