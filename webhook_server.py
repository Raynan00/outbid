"""
Webhook Server for Payment Confirmations.
Handles Paystack and Stripe webhook callbacks.

Run separately from the main bot:
    python webhook_server.py
    
Or with uvicorn:
    uvicorn webhook_server:app --host 0.0.0.0 --port 5000
"""

import asyncio
import logging
import json
import hmac
import hashlib
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse

from config import config
from database import db_manager
from billing_service import billing_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Outbid Payment Webhooks")

# Telegram bot instance for sending notifications (initialized lazily)
_telegram_bot = None

async def get_telegram_bot():
    """Get or create Telegram bot instance for sending notifications."""
    global _telegram_bot
    if _telegram_bot is None:
        from telegram import Bot
        _telegram_bot = Bot(token=config.TELEGRAM_TOKEN)
    return _telegram_bot


async def send_telegram_notification(telegram_id: int, message: str) -> bool:
    """Send a Telegram notification to user."""
    try:
        bot = await get_telegram_bot()
        await bot.send_message(
            chat_id=telegram_id,
            text=message,
            parse_mode='Markdown'
        )
        logger.info(f"Sent notification to user {telegram_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send notification to {telegram_id}: {e}")
        return False


async def auto_reveal_pending_job(telegram_id: int) -> bool:
    """
    Auto-reveal the pending job after payment.
    Returns True if job was revealed, False otherwise.
    """
    try:
        from database import db_manager
        from brain import ProposalGenerator
        
        # Get pending job ID
        pending_job_id = await db_manager.get_and_clear_pending_reveal_job(telegram_id)
        
        if not pending_job_id:
            return False  # No pending job
        
        # Get job data
        job_data = await db_manager.get_job_for_strategy(pending_job_id)
        if not job_data:
            logger.warning(f"Pending job {pending_job_id} not found for user {telegram_id}")
            return False
        
        # Get user context
        user_context = await db_manager.get_user_context(telegram_id)
        if not user_context:
            logger.warning(f"No user context for user {telegram_id}")
            return False
        
        # Generate proposal
        proposal_generator = ProposalGenerator()
        proposal_text = await proposal_generator.generate_proposal(
            job_data,
            user_context
        )
        
        if not proposal_text:
            logger.error(f"Failed to generate proposal for pending job {pending_job_id}")
            return False
        
        # Format message
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        message_text = proposal_generator.format_proposal_for_telegram(
            proposal_text, job_data, draft_count=0, max_drafts=0
        )
        
        # Add header
        full_message = (
            "✅ *Payment Successful! Here's the job you wanted:*\n\n"
            f"{message_text}"
        )
        
        # Create keyboard with job link
        keyboard = [[InlineKeyboardButton("🚀 Open Job on Upwork", url=job_data['link'])]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send to user
        bot = await get_telegram_bot()
        await bot.send_message(
            chat_id=telegram_id,
            text=full_message,
            parse_mode='Markdown',
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        
        logger.info(f"Auto-revealed pending job {pending_job_id} for user {telegram_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error auto-revealing pending job for user {telegram_id}: {e}")
        return False


# ==================== PAYSTACK WEBHOOKS ====================

@app.post("/webhooks/paystack")
async def handle_paystack_webhook(
    request: Request,
    x_paystack_signature: Optional[str] = Header(None)
):
    """
    Handle Paystack webhook events.
    
    Events handled:
    - charge.success: Payment completed successfully
    """
    try:
        # Get raw payload
        payload = await request.body()
        payload_str = payload.decode('utf-8')
        
        # Verify signature
        if config.PAYSTACK_SECRET_KEY and x_paystack_signature:
            expected_sig = hmac.new(
                config.PAYSTACK_SECRET_KEY.encode('utf-8'),
                payload_str.encode('utf-8'),
                hashlib.sha512
            ).hexdigest()
            
            if not hmac.compare_digest(expected_sig, x_paystack_signature):
                logger.warning("Invalid Paystack webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Parse payload
        data = json.loads(payload_str)
        event = data.get('event')
        
        logger.info(f"Received Paystack event: {event}")
        
        if event == 'charge.success':
            tx_data = data.get('data', {})
            metadata = tx_data.get('metadata', {})
            
            telegram_id = metadata.get('telegram_id')
            plan = metadata.get('plan')
            
            if not telegram_id or not plan:
                logger.error(f"Missing metadata in Paystack webhook: {metadata}")
                return JSONResponse({"status": "error", "message": "Missing metadata"})
            
            telegram_id = int(telegram_id)
            
            # Grant access
            success = await billing_service.grant_access(
                telegram_id=telegram_id,
                plan=plan,
                payment_provider='paystack'
            )
            
            if success:
                # Check for pending job and auto-reveal (this clears the pending job)
                had_pending = await auto_reveal_pending_job(telegram_id)
                
                # Send success notification (only if no pending job was revealed)
                if not had_pending:
                    success_msg = billing_service.get_success_message(plan)
                    await send_telegram_notification(telegram_id, success_msg)
                
                logger.info(f"Granted {plan} subscription to user {telegram_id} via Paystack")
                return JSONResponse({"status": "success"})
            else:
                logger.error(f"Failed to grant access to user {telegram_id}")
                return JSONResponse({"status": "error", "message": "Failed to grant access"})
        
        # Acknowledge other events
        return JSONResponse({"status": "ok"})
        
    except Exception as e:
        logger.error(f"Paystack webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== STRIPE WEBHOOKS ====================

@app.post("/webhooks/stripe")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None)
):
    """
    Handle Stripe webhook events.
    
    Events handled:
    - checkout.session.completed: Initial payment completed
    - invoice.payment_succeeded: Renewal payment completed
    - invoice.payment_failed: Payment failed
    - customer.subscription.deleted: Subscription cancelled
    """
    try:
        import stripe
        stripe.api_key = config.STRIPE_SECRET_KEY
        
        payload = await request.body()
        
        # Verify signature if webhook secret is configured
        if config.STRIPE_WEBHOOK_SECRET and stripe_signature:
            try:
                event = stripe.Webhook.construct_event(
                    payload, stripe_signature, config.STRIPE_WEBHOOK_SECRET
                )
            except ValueError as e:
                logger.error(f"Invalid Stripe payload: {e}")
                raise HTTPException(status_code=400, detail="Invalid payload")
            except stripe.error.SignatureVerificationError as e:
                logger.error(f"Invalid Stripe signature: {e}")
                raise HTTPException(status_code=401, detail="Invalid signature")
        else:
            event = json.loads(payload)
        
        event_type = event.get('type')
        logger.info(f"Received Stripe event: {event_type}")
        
        if event_type == 'checkout.session.completed':
            session = event['data']['object']
            telegram_id = session.get('client_reference_id')
            subscription_id = session.get('subscription')
            
            if not telegram_id:
                # Try metadata
                telegram_id = session.get('metadata', {}).get('telegram_id')
            
            if telegram_id:
                telegram_id = int(telegram_id)
                
                # CRITICAL: Copy telegram_id to subscription metadata for renewals
                # Without this, invoice.payment_succeeded won't know which user to credit
                if subscription_id:
                    try:
                        stripe.Subscription.modify(
                            subscription_id,
                            metadata={'telegram_id': str(telegram_id), 'plan': 'monthly'}
                        )
                        logger.info(f"Copied metadata to subscription {subscription_id} for user {telegram_id}")
                    except Exception as e:
                        logger.error(f"Failed to copy metadata to subscription: {e}")
                
                # Grant access
                success = await billing_service.grant_access(
                    telegram_id=telegram_id,
                    plan='monthly',
                    payment_provider='stripe'
                )
                
                if success:
                    # Check for pending job and auto-reveal (this clears the pending job)
                    had_pending = await auto_reveal_pending_job(telegram_id)
                    
                    # Send success notification (only if no pending job was revealed)
                    if not had_pending:
                        success_msg = billing_service.get_success_message('monthly')
                        await send_telegram_notification(telegram_id, success_msg)
                    
                    logger.info(f"Granted monthly subscription to user {telegram_id} via Stripe")
                else:
                    logger.error(f"Failed to grant access to user {telegram_id}")
        
        elif event_type == 'invoice.payment_succeeded':
            # Renewal payment - extend subscription
            invoice = event['data']['object']
            subscription_id = invoice.get('subscription')
            
            # Get telegram_id from subscription metadata
            if subscription_id:
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    telegram_id = subscription.metadata.get('telegram_id')
                    
                    if telegram_id:
                        telegram_id = int(telegram_id)
                        
                        # Grant another month
                        await billing_service.grant_access(
                            telegram_id=telegram_id,
                            plan='monthly',
                            payment_provider='stripe'
                        )
                        
                        logger.info(f"Renewed subscription for user {telegram_id}")
                except Exception as e:
                    logger.error(f"Error processing renewal: {e}")
        
        elif event_type == 'invoice.payment_failed':
            # Payment failed - notify user
            invoice = event['data']['object']
            subscription_id = invoice.get('subscription')
            
            if subscription_id:
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    telegram_id = subscription.metadata.get('telegram_id')
                    
                    if telegram_id:
                        telegram_id = int(telegram_id)
                        
                        # Notify user
                        await send_telegram_notification(
                            telegram_id,
                            "⚠️ *Payment Failed*\n\n"
                            "Your subscription renewal payment failed.\n\n"
                            "Please update your payment method to continue your subscription.\n"
                            "Use /upgrade to renew."
                        )
                        
                        logger.info(f"Notified user {telegram_id} of payment failure")
                except Exception as e:
                    logger.error(f"Error processing payment failure: {e}")
        
        elif event_type == 'customer.subscription.deleted':
            # Subscription cancelled - downgrade user
            subscription = event['data']['object']
            telegram_id = subscription.metadata.get('telegram_id')
            
            if telegram_id:
                telegram_id = int(telegram_id)
                
                # Downgrade to scout
                await db_manager.downgrade_to_scout(telegram_id)
                
                # Notify user
                await send_telegram_notification(
                    telegram_id,
                    "⏰ *Subscription Cancelled*\n\n"
                    "Your subscription has been cancelled.\n"
                    "You've been moved to free access with 3 Reveal Credits.\n\n"
                    "Use /upgrade to resubscribe anytime."
                )
                
                logger.info(f"Cancelled subscription for user {telegram_id}")
        
        return JSONResponse({"status": "ok"})
        
    except ImportError:
        logger.error("Stripe library not installed")
        raise HTTPException(status_code=500, detail="Stripe not configured")
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== PAYMENT CALLBACKS ====================

@app.get("/payment/callback")
async def payment_callback(request: Request):
    """
    Handle Paystack payment callback (redirect after payment).
    This is where user is redirected after completing payment.
    
    IMPORTANT: This serves as a BACKUP to the webhook.
    If webhook failed for any reason, this ensures user still gets access.
    grant_access() is idempotent - calling it twice won't hurt.
    """
    # Get reference from query params
    reference = request.query_params.get('reference')
    
    if not reference:
        return JSONResponse({"status": "error", "message": "Missing reference"})
    
    # Verify payment
    success, data = await billing_service.verify_paystack_transaction(reference)
    
    if success:
        telegram_id = data.get('telegram_id')
        plan = data.get('plan')
        
        if telegram_id and plan:
            telegram_id = int(telegram_id)
            
            # BACKUP: Grant access here in case webhook failed
            # This is idempotent - if webhook already processed, this just updates to same values
            try:
                await billing_service.grant_access(
                    telegram_id=telegram_id,
                    plan=plan,
                    payment_provider='paystack'
                )
                logger.info(f"Backup grant_access for user {telegram_id}, plan: {plan}")
                
                # Try to auto-reveal pending job (also idempotent - clears pending on first call)
                await auto_reveal_pending_job(telegram_id)
                
            except Exception as e:
                logger.error(f"Backup grant_access failed for user {telegram_id}: {e}")
            
            # Return success response
            return JSONResponse({
                "status": "success",
                "message": "Payment verified! Return to Telegram to continue.",
                "redirect": f"https://t.me/{config.TELEGRAM_TOKEN.split(':')[0]}"
            })
    
    return JSONResponse({"status": "error", "message": "Payment verification failed"})


@app.get("/payment/success")
async def payment_success(request: Request):
    """Handle Stripe payment success redirect."""
    session_id = request.query_params.get('session_id')
    return JSONResponse({
        "status": "success",
        "message": "Payment successful! Return to Telegram to continue."
    })


@app.get("/payment/cancel")
async def payment_cancel():
    """Handle payment cancellation."""
    return JSONResponse({
        "status": "cancelled",
        "message": "Payment cancelled. Return to Telegram and use /upgrade to try again."
    })


# ==================== HEALTH CHECK ====================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ==================== IP DETECTION ENDPOINT ====================

@app.get("/detect-country/{telegram_id}")
async def detect_country(telegram_id: int, request: Request):
    """
    Detect user's country from IP and update database.
    Called when user visits payment page.
    """
    from access_service import access_service
    
    # Get client IP
    client_ip = request.client.host
    
    # Check for forwarded IP (if behind proxy)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        client_ip = forwarded_for.split(',')[0].strip()
    
    # Detect country from IP
    country = await access_service.update_country_from_ip(telegram_id, client_ip)
    
    return {
        "telegram_id": telegram_id,
        "ip": client_ip,
        "country": country
    }


# ==================== ONBOARDING SETUP ENDPOINT ====================

from fastapi.responses import HTMLResponse

@app.get("/setup/{telegram_id}", response_class=HTMLResponse)
async def setup_country(telegram_id: int, request: Request):
    """
    Onboarding setup endpoint - detects user's country from IP during /start flow.
    
    Flow:
    1. User clicks "Continue Setup" button in Telegram
    2. Opens this page which captures their IP
    3. Detects country and saves to database
    4. Redirects back to Telegram bot with deep link
    """
    from access_service import access_service
    
    # Get client IP
    client_ip = request.client.host
    
    # Check for forwarded IP (if behind proxy/load balancer)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        client_ip = forwarded_for.split(',')[0].strip()
    
    # Also check X-Real-IP (used by nginx)
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        client_ip = real_ip
    
    # Detect country from IP and save
    country = await access_service.update_country_from_ip(telegram_id, client_ip)
    
    logger.info(f"Setup: Detected country {country} for user {telegram_id} from IP {client_ip}")
    
    # Determine pricing message based on country
    if country == 'NG':
        country_emoji = "🇳🇬"
        country_name = "Nigeria"
        pricing_note = "You'll see Naira pricing via Paystack"
    else:
        country_emoji = "🌍"
        country_name = "International"
        pricing_note = "You'll see USD pricing via Stripe"
    
    # Build redirect URL
    bot_username = config.TELEGRAM_BOT_USERNAME
    redirect_url = f"https://t.me/{bot_username}?start=setup_done"
    
    # Return HTML page that auto-redirects
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Outbid Setup</title>
        <meta http-equiv="refresh" content="2;url={redirect_url}">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #fff;
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: rgba(255, 255, 255, 0.1);
                border-radius: 20px;
                backdrop-filter: blur(10px);
                max-width: 400px;
                margin: 20px;
            }}
            .emoji {{ font-size: 64px; margin-bottom: 20px; }}
            h1 {{ font-size: 24px; margin-bottom: 10px; color: #4ade80; }}
            p {{ color: #a0aec0; margin-bottom: 20px; line-height: 1.6; }}
            .country {{ 
                background: rgba(74, 222, 128, 0.2); 
                padding: 10px 20px; 
                border-radius: 10px;
                display: inline-block;
                margin-bottom: 20px;
            }}
            .btn {{
                display: inline-block;
                background: #4ade80;
                color: #1a1a2e;
                padding: 15px 30px;
                border-radius: 10px;
                text-decoration: none;
                font-weight: bold;
                transition: transform 0.2s;
            }}
            .btn:hover {{ transform: scale(1.05); }}
            .redirect-note {{ font-size: 12px; color: #718096; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="emoji">{country_emoji}</div>
            <h1>Setup Complete!</h1>
            <div class="country">
                <strong>{country_name}</strong><br>
                <small>{pricing_note}</small>
            </div>
            <p>Click below to return to Telegram and continue setting up your job alerts.</p>
            <a href="{redirect_url}" class="btn">🚀 Return to Bot</a>
            <p class="redirect-note">Redirecting automatically in 2 seconds...</p>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


# ==================== MAIN ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "webhook_server:app",
        host="0.0.0.0",
        port=config.WEBHOOK_SERVER_PORT,
        reload=False
    )
