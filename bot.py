"""
Telegram bot implementation for Upwork First Responder.
Handles user commands, onboarding, strategy mode, and job alerts with AI-generated proposals.
"""

import asyncio
import logging
from typing import List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

from config import config
from database import db_manager
from brain import ProposalGenerator
from scanner import JobData
from access_service import access_service
from billing_service import billing_service

logger = logging.getLogger(__name__)

# Conversation states for onboarding, strategy, and settings
ONBOARDING_KEYWORDS, ONBOARDING_BIO, STRATEGIZING, UPDATE_KEYWORDS, UPDATE_BIO, AWAITING_EMAIL = range(6)

class UpworkBot:
    """Telegram bot for Upwork job monitoring and alerts."""

    def __init__(self):
        self.proposal_generator = ProposalGenerator()
        self.application = None

    async def safe_reply_text(self, update: Update, text: str, parse_mode: str = None, max_retries: int = 3):
        """Safely send a reply with retry logic for timeouts."""
        for attempt in range(max_retries):
            try:
                # Use reply_text which is simpler and uses the configured timeouts
                await update.message.reply_text(text, parse_mode=parse_mode)
                return True
            except Exception as e:
                error_type = type(e).__name__
                # Check if it's a timeout or connection error
                is_timeout = 'Timeout' in error_type or 'timeout' in str(e).lower() or 'Connect' in error_type
                
                if attempt < max_retries - 1 and is_timeout:
                    wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                    logger.warning(f"Telegram API timeout on attempt {attempt + 1}/{max_retries}, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    # For non-timeout errors or final attempt, log and return
                    if is_timeout:
                        logger.error(f"Failed to send message after {max_retries} attempts due to timeout: {e}")
                    else:
                        logger.error(f"Failed to send message ({error_type}): {e}")
                    return False
        return False

    async def setup_application(self) -> Application:
        """Setup the Telegram bot application."""
        # Configure with longer timeouts for reliability
        # concurrent_updates=True allows multiple users to be handled simultaneously
        self.application = (
            Application.builder()
            .token(config.TELEGRAM_TOKEN)
            .concurrent_updates(True)  # Enable concurrent update processing
            .read_timeout(30)
            .write_timeout(30)
            .connect_timeout(30)
            .build()
        )

        # Add logging for all updates
        async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
            logger.info(f"Received update: {update}")

        self.application.add_handler(MessageHandler(filters.ALL, log_update), group=-1)

        # Create conversation handler for onboarding and strategy
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                ONBOARDING_KEYWORDS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_keywords_input)
                ],
                ONBOARDING_BIO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_bio_input)
                ],
                STRATEGIZING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_strategy_input)
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_command)],
        )

        # Create conversation handler for settings updates
        # Note: Button callbacks set the state directly, then next message is handled by the handler
        settings_conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("settings", self.settings_command),
                # Also allow entering state from button callbacks via state check
            ],
            states={
                UPDATE_KEYWORDS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_update_keywords)
                ],
                UPDATE_BIO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_update_bio)
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_command)],
            # Allow re-entry if state is already set
            allow_reentry=True,
        )

        # Create conversation handler for email input (upgrade flow)
        email_conv_handler = ConversationHandler(
            entry_points=[],  # Entry is via button callback setting state
            states={
                AWAITING_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_email_input)
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_command)],
            allow_reentry=True,
        )

        # Add handlers
        self.application.add_handler(conv_handler)
        self.application.add_handler(settings_conv_handler)
        self.application.add_handler(email_conv_handler)
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("upgrade", self.upgrade_command))
        self.application.add_handler(CommandHandler("country", self.country_command))
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(CommandHandler("admin_users", self.admin_users_command))
        self.application.add_handler(CommandHandler("admin_drafts", self.admin_drafts_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))

        # Add general message handler for cost protection
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_general_message
        ))

        # Add error handlers
        async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            """Handle errors gracefully."""
            error = context.error
            if isinstance(error, Exception):
                logger.error(f"Telegram bot error: {error}", exc_info=error)
                # Try to send error message to user if update is available
                if update and isinstance(update, Update) and update.effective_message:
                    try:
                        await update.effective_message.reply_text(
                            "⚠️ Sorry, I encountered an error. Please try again or use /start to restart.",
                            read_timeout=10,
                            write_timeout=10,
                            connect_timeout=10
                        )
                    except:
                        pass  # If we can't send error message, just log it

        self.application.add_error_handler(error_handler)

        logger.info("Telegram bot application setup complete")
        return self.application

    # Onboarding Handlers
    async def handle_keywords_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle keywords input during onboarding."""
        user_id = update.effective_user.id
        keywords = update.message.text.strip()

        # Validate keywords
        if len(keywords.split(',')) < 1 or len(keywords) > 200:
            await update.message.reply_text(
                "❌ Please enter 1-10 keywords separated by commas (max 200 characters).\n\n"
                "Example: `Python, Django, API, Backend`",
                parse_mode='Markdown'
            )
            return ONBOARDING_KEYWORDS

        # Save keywords
        await db_manager.update_user_onboarding(user_id, keywords=keywords)

        # Move to bio collection
        await update.message.reply_text(
            "📚 **Got it!** Now tell me about your experience.\n\n"
            "Paste a short bio ('brag sheet') about your skills and achievements.\n\n"
            "💡 **Keep it under 500 characters and focus on results.**",
            parse_mode='Markdown'
        )
        await db_manager.set_user_state(user_id, "ONBOARDING_BIO")
        return ONBOARDING_BIO

    async def handle_bio_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle bio input during onboarding."""
        user_id = update.effective_user.id
        bio = update.message.text.strip()

        # Validate bio
        if len(bio) > 500:
            await update.message.reply_text(
                f"❌ Bio is too long ({len(bio)}/500 characters). Please shorten it.",
                parse_mode='Markdown'
            )
            return ONBOARDING_BIO

        # Save bio
        await db_manager.update_user_onboarding(user_id, context=bio)
        await db_manager.clear_user_state(user_id)

        # Show "Finish Setup" button for country detection
        setup_url = f"{config.WEBHOOK_BASE_URL}/setup/{user_id}"
        
        keyboard = [
            [InlineKeyboardButton("✅ Finish Setup", url=setup_url)]
        ]
        
        await update.message.reply_text(
            "✨ *Almost done!*\n\n"
            "Tap below to complete your setup and start receiving job alerts.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    # Strategy Mode Handler
    async def handle_strategy_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle strategy input in War Room mode."""
        user_id = update.effective_user.id
        strategy_input = update.message.text.strip()

        # Get user context and current job
        user_context = await db_manager.get_user_context(user_id)
        if not user_context or not user_context.get('current_job_id'):
            await update.message.reply_text("❌ Strategy session expired. Try again from a job alert.")
            await db_manager.clear_user_state(user_id)
            return ConversationHandler.END

        job_id = user_context['current_job_id']
        job_data = await db_manager.get_job_for_strategy(job_id)

        if not job_data:
            await update.message.reply_text("❌ Job data not found. Try again from a recent job alert.")
            await db_manager.clear_user_state(user_id)
            return ConversationHandler.END

        # Generate strategy proposal
        await update.message.reply_text(
            "🧠 **Processing your strategy...**\n\n"
            f"Strategy: {strategy_input}\n\n"
            "Generating customized proposal...",
            parse_mode='Markdown'
        )

        try:
            # Check strategy draft limit before generating
            MAX_STRATEGY_DRAFTS = config.MAX_STRATEGY_DRAFTS
            try:
                draft_counts = await db_manager.get_proposal_draft_count(user_id, job_data.id)
                strategy_count = draft_counts['strategy_count']
            except Exception as e:
                logger.error(f"Failed to get strategy draft count for user {user_id}, job {job_data.id}: {e}")
                strategy_count = 0  # Allow generation if database fails
            
            if strategy_count >= MAX_STRATEGY_DRAFTS:
                await update.message.reply_text(
                    f"⚠️ **Limit Reached**\n\n"
                    f"You've generated {strategy_count} strategy proposals for this job.\n\n"
                    f"💡 **Tip:** Try editing your existing proposal instead. "
                    f"Clients can tell when proposals are personalized - add 1-2 specific details about this job to make it stand out.",
                    parse_mode='Markdown'
                )
                await db_manager.clear_user_state(user_id)
                return ConversationHandler.END

            # Generate strategic proposal
            strategic_proposal = await self.proposal_generator.generate_strategy(
                job_data,
                user_context,
                strategy_input
            )

            if strategic_proposal:
                # Increment strategy draft count (only if generation succeeded)
                try:
                    new_strategy_count = await db_manager.increment_proposal_draft(user_id, job_data.id, is_strategy=True)
                except Exception as e:
                    logger.error(f"Failed to increment strategy draft count for user {user_id}, job {job_data.id}: {e}")
                    new_strategy_count = 1  # Default for display purposes
                
                # Format and send the strategic proposal
                message_text = self.proposal_generator.format_proposal_for_telegram(
                    strategic_proposal, job_data, draft_count=new_strategy_count, max_drafts=MAX_STRATEGY_DRAFTS, is_strategy=True
                )

                # Add strategy note
                strategy_note = f"\n\n🎯 **Strategy Applied:** {strategy_input}"

                await update.message.reply_text(
                    message_text + strategy_note,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ Failed to generate strategic proposal. Please try again.",
                    parse_mode='Markdown'
                )

        except Exception as e:
            logger.error(f"Strategy generation failed: {e}")
            await update.message.reply_text(
                "❌ Strategy generation failed. Please try again later.",
                parse_mode='Markdown'
            )

        # Clear strategy state
        await db_manager.clear_user_state(user_id)

        return ConversationHandler.END

    # Settings Update Handlers
    async def handle_update_keywords(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle keywords update from settings."""
        user_id = update.effective_user.id
        keywords = update.message.text.strip()

        # Validate keywords
        if len(keywords.split(',')) < 1 or len(keywords) > 200:
            await self.safe_reply_text(
                update,
                "❌ Please enter 1-10 keywords separated by commas (max 200 characters).\n\n"
                "Example: `Python, Django, API, Backend`\n\n"
                "Try again:",
                parse_mode='Markdown'
            )
            return UPDATE_KEYWORDS

        # Update keywords
        await db_manager.update_user_onboarding(user_id, keywords=keywords)
        await db_manager.clear_user_state(user_id)

        await self.safe_reply_text(
            update,
            "✅ **Keywords Updated!**\n\n"
            f"Your new keywords: `{keywords}`\n\n"
            "Use /settings to update more or check your profile.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    async def handle_update_bio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle bio update from settings."""
        user_id = update.effective_user.id
        bio = update.message.text.strip()

        # Validate bio
        if len(bio) > 500:
            await self.safe_reply_text(
                update,
                f"❌ Bio is too long ({len(bio)}/500 characters). Please shorten it.\n\n"
                "Try again:",
                parse_mode='Markdown'
            )
            return UPDATE_BIO

        # Update bio
        await db_manager.update_user_onboarding(user_id, context=bio)
        await db_manager.clear_user_state(user_id)

        await self.safe_reply_text(
            update,
            "✅ **Bio Updated!**\n\n"
            f"Your new bio ({len(bio)}/500 characters):\n\n"
            f"_{bio[:200]}{'...' if len(bio) > 200 else ''}_\n\n"
            "Use /settings to update more or check your profile.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # Cost Protection - General Message Handler
    async def handle_general_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle general messages with cost protection guardrails."""
        user_id = update.effective_user.id

        # Check if user is in a valid state
        user_context = await db_manager.get_user_context(user_id)
        if user_context and user_context.get('state'):
            state = user_context.get('state')
            # Route to appropriate handler based on state
            if state == "UPDATE_KEYWORDS":
                await self.handle_update_keywords(update, context)
                return
            elif state == "UPDATE_BIO":
                await self.handle_update_bio(update, context)
                return
            elif state == "AWAITING_EMAIL":
                # Handle email input for payment flow
                await self.handle_email_input(update, context)
                return
            elif state == "STRATEGIZING":
                # Handle War Room strategy input
                await self.handle_strategy_input(update, context)
                return
            # For onboarding states (ONBOARDING_KEYWORDS, ONBOARDING_BIO), 
            # the conversation handler should catch them via /start entry
            return

        # User is chatting randomly - cost protection
        if await db_manager.is_user_authorized(user_id):
            await update.message.reply_text(
                "🤖 **Alert Mode Active**\n\n"
                "I'm monitoring for jobs. Wait for alerts or use:\n\n"
                "/status - Check bot status\n"
                "/settings - Update your profile\n"
                "/help - Get help",
                parse_mode='Markdown'
            )
        else:
            if config.PAYMENTS_ENABLED:
                # Not paid - redirect to payment
                payment_msg = self._get_payment_message()
                await update.message.reply_text(payment_msg, parse_mode='Markdown')
            else:
                # Payments disabled - add user for testing
                await db_manager.add_user(user_id, is_paid=True)
                await update.message.reply_text(
                    "🤖 **Alert Mode Active**\n\n"
                    "Payments are disabled for testing. You're now authorized!\n\n"
                    "/start - Begin setup\n"
                    "/status - Check bot status",
                    parse_mode='Markdown'
                )

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel current operation."""
        user_id = update.effective_user.id
        await db_manager.clear_user_state(user_id)

        await self.safe_reply_text(
            update,
            "❌ **Cancelled**\n\n"
            "Use /start to begin again or /settings to update your profile.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /start command with onboarding flow."""
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        args = context.args  # For referral codes like /start NIGERIA50 or /start setup_done

        logger.info(f"User {user_id} ({username}) started the bot with args: {args}")

        # Check if user exists
        user_info = await db_manager.get_user_info(user_id)
        
        # Check if this is a return from setup page
        is_setup_done = args and args[0] == 'setup_done'

        if not user_info:
            # New user - add to database
            await db_manager.add_user(user_id, is_paid=False)
            
            # Process referral if provided (not setup_done)
            if args and len(args[0]) >= 4 and args[0] != 'setup_done':
                referral_success = await db_manager.process_referral(args[0], user_id)
                if referral_success:
                    logger.info(f"Processed referral {args[0]} for new user {user_id}")
            
            # Refresh user info after creation
            user_info = await db_manager.get_user_info(user_id)
            
            # Go straight to keywords onboarding (country detection happens at the end)
            await self.safe_reply_text(
                update,
                "🎯 *Welcome to Upwork First Responder!*\n\n"
                "I help you apply before everyone else — with AI-written proposals.\n\n"
                "📝 *Enter your skills/technologies (comma separated):*\n\n"
                "*Examples:*\n"
                "• `Python, Django, API, Backend`\n"
                "• `Copywriting, Content Marketing, SEO`\n"
                "• `Video Editing, Premiere Pro, YouTube`",
                parse_mode='Markdown'
            )
            await db_manager.set_user_state(user_id, "ONBOARDING_KEYWORDS")
            return ONBOARDING_KEYWORDS
        
        # If returning from setup (after clicking "Finish Setup" button)
        if is_setup_done:
            # Show final welcome message - onboarding complete!
            await self.safe_reply_text(
                update,
                "🎉 *Setup Complete!*\n\n"
                "I'll start monitoring for jobs matching your keywords.\n\n"
                "📋 *Commands:*\n"
                "/status - Check bot status\n"
                "/settings - Update your profile\n"
                "/upgrade - View subscription plans\n\n"
                "🔔 *Job alerts will appear here automatically!*",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Check and handle subscription expiry (auto-downgrade if needed)
        was_downgraded = await access_service.check_and_handle_expiry(user_id)
        if was_downgraded:
            await self.safe_reply_text(
                update,
                access_service.get_downgrade_message(),
                parse_mode='Markdown'
            )

        # Get permissions and subscription status
        permissions = await access_service.get_user_permissions(user_id)
        subscription = await db_manager.get_subscription_status(user_id)
        
        # If payments disabled for testing, grant full access
        if not config.PAYMENTS_ENABLED and permissions.get('plan') == 'scout':
            logger.info(f"Payments disabled - granting full access to user {user_id}")
            await db_manager.add_user(user_id, is_paid=True)
            permissions = await access_service.get_user_permissions(user_id)

        # Check onboarding status - ALL users (scout or paid) need to complete onboarding
        if not user_info or not user_info.get('keywords'):
            # Need keywords - go straight to keywords input
            await self.safe_reply_text(
                update,
                "🎯 *Let's set up your job alerts!*\n\n"
                "📝 *Enter your skills/technologies (comma separated):*\n\n"
                "*Examples:*\n"
                "• `Python, Django, API, Backend`\n"
                "• `Copywriting, Content Marketing, SEO`\n"
                "• `Video Editing, Premiere Pro, YouTube`",
                parse_mode='Markdown'
            )
            await db_manager.set_user_state(user_id, "ONBOARDING_KEYWORDS")
            return ONBOARDING_KEYWORDS

        if not user_info.get('context'):
            # Keywords done, now bio
            await self.safe_reply_text(
                update,
                "📚 *Quick profile setup*\n\n"
                "Paste a short bio about your experience.\n\n"
                "💡 *Focus on results. Keep it under 500 characters.*",
                parse_mode='Markdown'
            )
            await db_manager.set_user_state(user_id, "ONBOARDING_BIO")
            return ONBOARDING_BIO

        # Fully onboarded user - show welcome with subscription status
        plan_name = billing_service.get_plan_name(subscription.get('plan', 'scout'))
        
        if subscription.get('is_active'):
            # Paid user
            days_remaining = subscription.get('days_remaining', 0)
            status_line = f"📊 *Plan:* {plan_name} ({days_remaining} days remaining)"
        else:
            # Free user - show credits instead of "Scout"
            credits = await db_manager.get_reveal_credits(user_id)
            status_line = f"📊 *Free Access*\n👁 *You have {credits} Reveal Credits*\n💡 Use /upgrade to unlock full proposals and job links!"
        
        welcome_msg = (
            "🤖 *Upwork First Responder Bot*\n\n"
            "Welcome back! Your profile is ready.\n\n"
            f"🎯 *Your Keywords:* {user_info['keywords']}\n"
            f"{status_line}\n\n"
            "📋 *Commands:*\n"
            "/status - Check bot status\n"
            "/settings - Update keywords/bio\n"
            "/upgrade - View subscription plans\n"
            "/help - Show help\n\n"
            "🔔 *You'll receive alerts automatically when new jobs are found!*"
        )

        await self.safe_reply_text(update, welcome_msg, parse_mode='Markdown')
        return ConversationHandler.END

    def _get_payment_message(self, referral_code: str = None) -> str:
        """Generate payment message with Paystack link."""
        base_msg = (
            "🚀 **Upwork First Responder Bot**\n\n"
            "Get instant job alerts with AI-generated proposals!\n\n"
            "💰 **Pricing:**\n"
            "• 1 Month: $9.99\n"
            "• 3 Months: $24.99 (17% off)\n"
            "• 6 Months: $44.99 (25% off)\n\n"
        )

        if referral_code:
            discount = config.REFERRAL_DISCOUNT_PERCENT
            base_msg += f"🎁 **Referral Code:** `{referral_code}` ({discount}% discount applied!)\n\n"

        payment_url = config.get_payment_url(referral_code)
        base_msg += (
            f"💳 **Pay Now:** [Click here to pay with Paystack]({payment_url})\n\n"
            "After payment, reply with your transaction ID to activate your account.\n\n"
            f"❓ Questions? Contact {config.SUPPORT_CONTACT}"
        )

        return base_msg

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        user_id = update.effective_user.id

        # Check authorization
        if not await db_manager.is_user_authorized(user_id):
            await update.message.reply_text("🚫 Access denied. Please contact an administrator.")
            return

        try:
            # Get scanner status (will be passed from main.py)
            scanner_status = context.bot_data.get('scanner_status', {})

            status_msg = "📊 **Bot Status**\n\n"

            # Scanner status
            if scanner_status:
                status_msg += f"🔍 **Scanner:** {'🟢 Running' if scanner_status.get('is_running') else '🔴 Stopped'}\n"
                if scanner_status.get('last_scan_time'):
                    status_msg += f"⏰ Last scan: {scanner_status['last_scan_time']}\n"
                status_msg += f"⚡ Scan interval: {scanner_status.get('scan_interval', 'N/A')} seconds\n"
            else:
                status_msg += "🔍 **Scanner:** Status unavailable\n"

            # Keywords
            keywords = config.KEYWORDS
            status_msg += f"\n🎯 **Monitored Keywords:** {', '.join(keywords)}\n"

            # User stats
            user_info = await db_manager.get_user_info(user_id)
            if user_info:
                status_msg += f"\n👤 **Your Account:** {'✅ Paid' if user_info['is_paid'] else '❌ Free Trial'}\n"
                status_msg += f"🎯 **Your Keywords:** {user_info['keywords'] or 'Not set'}\n"
                status_msg += f"📝 **Bio Status:** {'✅ Set' if user_info['context'] else '❌ Not set'}\n"

            # Recent jobs count
            recent_jobs = await db_manager.get_recent_jobs(hours=24)
            status_msg += f"\n📈 Jobs found (24h): {len(recent_jobs)}\n"

            await update.message.reply_text(status_msg, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error getting status: {e}")
            await update.message.reply_text("❌ Error retrieving status. Please try again later.")

    # ==================== UPGRADE / PAYMENT HANDLERS ====================
    
    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle /upgrade command - show pricing options."""
        user_id = update.effective_user.id
        
        # Detect country if not already set
        await access_service.detect_user_country(user_id, update)
        
        # Get subscription status
        status = await db_manager.get_subscription_status(user_id)
        
        if status['is_active']:
            # Already subscribed
            plan_name = billing_service.get_plan_name(status['plan'])
            days_remaining = status['days_remaining']
            
            await self.safe_reply_text(
                update,
                f"✅ *You're already subscribed!*\n\n"
                f"Plan: *{plan_name}*\n"
                f"Days remaining: *{days_remaining}*\n\n"
                f"Use /settings to view your profile.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Show upgrade options
        user_info = await db_manager.get_user_info(user_id)
        country = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
        pricing = billing_service.get_pricing_for_country(country)
        
        if country == 'NG':
            # Nigeria - show daily, weekly, monthly options
            keyboard = [
                [InlineKeyboardButton(f"⚡ Daily Hustle – {pricing['plans']['daily']['display']} / 24h", callback_data="upgrade_plan_daily")],
                [InlineKeyboardButton(f"🔥 Weekly Sprint – {pricing['plans']['weekly']['display']} / 7d", callback_data="upgrade_plan_weekly")],
                [InlineKeyboardButton(f"💎 Monthly Pro – {pricing['plans']['monthly']['display']} / 30d – Most Popular ✅", callback_data="upgrade_plan_monthly")]
            ]
            
            message = (
                "💎 *Upgrade to Pro*\n\n"
                "Unlock full access:\n"
                "• AI-written proposals tailored to your skills\n"
                "• Direct job links to apply instantly\n"
                "• War Room strategy mode\n"
                "• Unlimited real-time alerts\n\n"
                "*Choose your plan:*"
            )
        else:
            # Global - monthly only via Stripe
            keyboard = [
                [InlineKeyboardButton(f"💎 Monthly Pro – {pricing['plans']['monthly']['display']}/mo – Most Popular ✅", callback_data="upgrade_plan_monthly")]
            ]
            
            message = (
                "💎 *Upgrade to Pro*\n\n"
                "Unlock full access:\n"
                "• AI-written proposals tailored to your skills\n"
                "• Direct job links to apply instantly\n"
                "• War Room strategy mode\n"
                "• Unlimited real-time alerts\n\n"
                "*Monthly subscription (cancel anytime):*"
            )
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self.safe_reply_text(update, message, parse_mode='Markdown')
        await update.message.reply_text("Select a plan:", reply_markup=reply_markup)
        
        return ConversationHandler.END
    
    async def _show_upgrade_options(self, query, user_id: int) -> None:
        """Show upgrade options based on user's country."""
        # Detect country if not already set
        user_info = await db_manager.get_user_info(user_id)
        country = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
        pricing = billing_service.get_pricing_for_country(country)
        
        if country == 'NG':
            # Nigeria - show daily, weekly, monthly options
            keyboard = [
                [InlineKeyboardButton(f"⚡ Daily Hustle – {pricing['plans']['daily']['display']} / 24h", callback_data="upgrade_plan_daily")],
                [InlineKeyboardButton(f"🔥 Weekly Sprint – {pricing['plans']['weekly']['display']} / 7d", callback_data="upgrade_plan_weekly")],
                [InlineKeyboardButton(f"💎 Monthly Pro – {pricing['plans']['monthly']['display']} / 30d – Most Popular ✅", callback_data="upgrade_plan_monthly")]
            ]
            
            message = (
                "💎 *Upgrade to Pro*\n\n"
                "Unlock full access:\n"
                "• AI-written proposals tailored to your skills\n"
                "• Direct job links to apply instantly\n"
                "• War Room strategy mode\n"
                "• Unlimited real-time alerts\n\n"
                "*Choose your plan:*"
            )
        else:
            # Global - monthly only via Stripe
            keyboard = [
                [InlineKeyboardButton(f"💎 Monthly Pro – {pricing['plans']['monthly']['display']}/mo – Most Popular ✅", callback_data="upgrade_plan_monthly")]
            ]
            
            message = (
                "💎 *Upgrade to Pro*\n\n"
                "Unlock full access:\n"
                "• AI-written proposals tailored to your skills\n"
                "• Direct job links to apply instantly\n"
                "• War Room strategy mode\n"
                "• Unlimited real-time alerts\n\n"
                "*Monthly subscription (cancel anytime):*"
            )
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=message, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def _show_plan_confirmation(self, query, user_id: int, plan: str) -> None:
        """Show plan confirmation with benefits before payment."""
        user_info = await db_manager.get_user_info(user_id)
        country = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
        pricing = billing_service.get_pricing_for_country(country)
        
        plan_name = billing_service.get_plan_name(plan)
        price_display = pricing['plans'][plan]['display']
        benefits = billing_service.get_plan_benefits(plan)
        
        # Add duration clarity
        duration_map = {
            'daily': '24h',
            'weekly': '7d',
            'monthly': '30d'
        }
        duration = duration_map.get(plan, '')
        
        benefits_text = "\n".join([f"• {benefit}" for benefit in benefits])
        
        keyboard = [
            [InlineKeyboardButton("💳 Pay Now", callback_data=f"confirm_pay_{plan}")],
            [InlineKeyboardButton("← Back", callback_data=f"upgrade_show")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=f"✅ *{plan_name} – {price_display} / {duration}*\n\n"
            f"You get:\n{benefits_text}\n\n"
            f"Click *Pay Now* to start:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def _handle_plan_selection(self, query, user_id: int, plan: str) -> None:
        """Handle plan selection - generate payment link."""
        user_info = await db_manager.get_user_info(user_id)
        country = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
        email = user_info.get('email') if user_info else None
        
        if country == 'NG':
            # Nigeria - Paystack requires email
            if not email:
                # Ask for email
                await db_manager.set_user_state(user_id, "AWAITING_EMAIL", plan)
                await query.edit_message_text(
                    text=f"📧 *Email Required*\n\n"
                    f"Please send your email address to complete payment.\n\n"
                    f"_(We'll send your payment receipt to this email)_",
                    parse_mode='Markdown'
                )
                return
            
            # Generate Paystack link
            payment_url, error = await billing_service.initialize_paystack_transaction(
                telegram_id=user_id,
                email=email,
                plan=plan
            )
            
            if payment_url:
                keyboard = [[InlineKeyboardButton("💳 Pay Now", url=payment_url)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                pricing = billing_service.get_pricing_for_country(country)
                price_display = pricing['plans'][plan]['display']
                plan_name = billing_service.get_plan_name(plan)
                
                await query.edit_message_text(
                    text=f"✅ *Payment Ready*\n\n"
                    f"Plan: *{plan_name}*\n"
                    f"Price: *{price_display}*\n\n"
                    f"Click below to complete payment:",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text(
                    text=f"❌ *Payment Error*\n\n{error or 'Unknown error'}\n\nPlease try again with /upgrade",
                    parse_mode='Markdown'
                )
        else:
            # Global - Stripe (monthly only)
            if plan != 'monthly':
                await query.edit_message_text(
                    text="❌ Only monthly subscription available for international users.\n\nPlease try again with /upgrade",
                    parse_mode='Markdown'
                )
                return
            
            payment_url, error = await billing_service.create_stripe_checkout_session(user_id)
            
            if payment_url:
                keyboard = [[InlineKeyboardButton("💳 Pay Now", url=payment_url)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                pricing = billing_service.get_pricing_for_country(country)
                price_display = pricing['plans']['monthly']['display']
                
                await query.edit_message_text(
                    text=f"✅ *Payment Ready*\n\n"
                    f"Plan: *Monthly Pro*\n"
                    f"Price: *{price_display}/month*\n\n"
                    f"Click below to complete payment:",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text(
                    text=f"❌ *Payment Error*\n\n{error or 'Unknown error'}\n\nPlease try again with /upgrade",
                    parse_mode='Markdown'
                )
    
    async def handle_email_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle email input for payment."""
        user_id = update.effective_user.id
        email = update.message.text.strip().lower()
        
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            await update.message.reply_text(
                "❌ Invalid email format. Please enter a valid email address:",
                parse_mode='Markdown'
            )
            return AWAITING_EMAIL
        
        # Get user context to get the selected plan
        user_context = await db_manager.get_user_context(user_id)
        plan = user_context.get('current_job_id', 'daily')  # We stored plan in current_job_id
        
        # Save email
        await db_manager.update_user_email(user_id, email)
        await db_manager.clear_user_state(user_id)
        
        # Generate payment link
        payment_url, error = await billing_service.initialize_paystack_transaction(
            telegram_id=user_id,
            email=email,
            plan=plan
        )
        
        if payment_url:
            keyboard = [[InlineKeyboardButton("💳 Pay Now", url=payment_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            pricing = billing_service.get_pricing_for_country('NG')
            price_display = pricing['plans'][plan]['display']
            plan_name = billing_service.get_plan_name(plan)
            
            await update.message.reply_text(
                f"✅ *Payment Ready*\n\n"
                f"Plan: *{plan_name}*\n"
                f"Price: *{price_display}*\n"
                f"Email: {email}\n\n"
                f"Click below to complete payment:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"❌ *Payment Error*\n\n{error or 'Unknown error'}\n\nPlease try again with /upgrade",
                parse_mode='Markdown'
            )
        
        return ConversationHandler.END

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /admin command - database statistics and user management (admin only)."""
        user_id = update.effective_user.id
        
        # Check if user is admin
        if not config.is_admin(user_id):
            await self.safe_reply_text(update, "Access denied. Admin only.")
            return
        
        try:
            # Get database statistics
            stats = await db_manager.get_database_stats()
            
            stats_msg = (
                "📊 **Database Statistics**\n\n"
                f"👥 **Users:**\n"
                f"   • Total: {stats['total_users']}\n"
                f"   • Paid: {stats['paid_users']}\n"
                f"   • Unpaid: {stats['unpaid_users']}\n"
                f"   • With Keywords: {stats['users_with_keywords']}\n"
                f"   • New (7 days): {stats['new_users_7d']}\n\n"
                f"💼 **Jobs:**\n"
                f"   • Total Seen: {stats['total_jobs_seen']}\n"
                f"   • Stored: {stats['jobs_stored']}\n"
                f"   • Last 24h: {stats['jobs_last_24h']}\n\n"
                f"📝 **Proposals:**\n"
                f"   • Total Draft Records: {stats['total_proposal_drafts']}\n"
                f"   • Regular Drafts: {stats['total_regular_drafts']}\n"
                f"   • Strategy Drafts: {stats['total_strategy_drafts']}\n\n"
                f"🎁 **Referrals:**\n"
                f"   • Total: {stats['total_referrals']}\n"
                f"   • Activated: {stats['activated_referrals']}\n\n"
                f"💡 Use /admin_users to see user list\n"
                f"💡 Use /admin_drafts to see draft activity"
            )
            
            await self.safe_reply_text(update, stats_msg, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Admin command failed: {e}")
            await self.safe_reply_text(update, f"Error retrieving stats: {e}")

    async def admin_users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /admin_users command - list all users (admin only)."""
        user_id = update.effective_user.id
        
        if not config.is_admin(user_id):
            await self.safe_reply_text(update, "Access denied. Admin only.")
            return
        
        try:
            users = await db_manager.get_all_users_summary()
            
            if not users:
                await self.safe_reply_text(update, "No users found.")
                return
            
            # Format first 10 users (Telegram message limit)
            user_list = "👥 **Users List** (showing first 10)\n\n"
            for user in users[:10]:
                paid_status = "✅ Paid" if user['is_paid'] else "❌ Unpaid"
                user_list += (
                    f"**User {user['telegram_id']}**\n"
                    f"   {paid_status} | Keywords: {user['keywords'][:30]}\n"
                    f"   Budget: ${user['min_budget']}-${user['max_budget'] if user['max_budget'] < 999999 else '∞'}\n"
                    f"   Joined: {user['created_at']}\n\n"
                )
            
            if len(users) > 10:
                user_list += f"... and {len(users) - 10} more users"
            
            await self.safe_reply_text(update, user_list, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Admin users command failed: {e}")
            await self.safe_reply_text(update, f"Error: {e}")

    async def admin_drafts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /admin_drafts command - show proposal draft activity (admin only)."""
        user_id = update.effective_user.id
        
        if not config.is_admin(user_id):
            await self.safe_reply_text(update, "Access denied. Admin only.")
            return
        
        try:
            drafts = await db_manager.get_user_draft_summary()
            
            if not drafts:
                await self.safe_reply_text(update, "No proposal drafts found.")
                return
            
            # Format first 10 drafts
            drafts_list = "📝 **Recent Proposal Activity** (last 10)\n\n"
            for draft in drafts[:10]:
                drafts_list += (
                    f"**Job:** {draft['job_title'][:40]}\n"
                    f"   User: {draft['user_telegram_id']}\n"
                    f"   Regular: {draft['draft_count']} | Strategy: {draft['strategy_count']}\n"
                    f"   Last: {draft['last_generated']}\n\n"
                )
            
            if len(drafts) > 10:
                drafts_list += f"... and {len(drafts) - 10} more records"
            
            await self.safe_reply_text(update, drafts_list, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Admin drafts command failed: {e}")
            await self.safe_reply_text(update, f"Error: {e}")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        user_id = update.effective_user.id

        if not await db_manager.is_user_authorized(user_id):
            await update.message.reply_text("🚫 Access denied.")
            return

        help_text = (
            "🆘 **Help - Upwork First Responder Bot**\n\n"
            "**What I Do:**\n"
            "• Monitor Upwork 24/7\n"
            "• Filter jobs by your keywords\n"
            "• Generate custom cover letters with AI\n"
            "• Send instant alerts via Telegram\n\n"
            "**Commands:**\n"
            "/start - Initialize and check authorization\n"
            "/settings - Update keywords, bio, and filters\n"
            "/status - View bot status and statistics\n"
            "/upgrade - View subscription plans\n"
            "/country - Change your pricing region\n"
            "/help - Show this help message\n"
            "/cancel - Cancel current operation\n\n"
        )
        
        # Add admin commands if user is admin
        if config.is_admin(user_id):
            help_text += (
                "**Admin Commands:**\n"
                "/admin - Database statistics\n"
                "/admin_users - List all users\n"
                "/admin_drafts - Proposal draft activity\n\n"
            )
        
        help_text += (
            "**How Alerts Work:**\n"
            "• Job title and budget info\n"
            "• AI-generated proposal in code block (tap to copy)\n"
            "• Direct link to apply on Upwork\n\n"
            "**Features:**\n"
            "• ✅ Smart filtering (budget, experience, keywords)\n"
            "• ✅ Pause alerts (1h, 4h, 8h, etc.)\n"
            "• ✅ War Room strategy mode\n"
            "• ✅ Mobile-friendly copy-paste\n\n"
            "**Need Help?**\n"
            "Contact your administrator if you have issues."
        )

        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def country_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /country command - allow users to change their country/pricing region."""
        user_id = update.effective_user.id
        
        user_info = await db_manager.get_user_info(user_id)
        if not user_info:
            await self.safe_reply_text(update, "Please /start first.", parse_mode='Markdown')
            return
        
        current_country = user_info.get('country_code', 'GLOBAL')
        
        if current_country == 'NG':
            current_display = "🇳🇬 Nigeria (Naira pricing via Paystack)"
        else:
            current_display = "🌍 International (USD pricing via Stripe)"
        
        # Auto-detect option
        setup_url = f"{config.WEBHOOK_BASE_URL}/setup/{user_id}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Auto-Detect My Location", url=setup_url)],
            [InlineKeyboardButton("🇳🇬 Nigeria (₦ Naira)", callback_data="set_country_NG")],
            [InlineKeyboardButton("🌍 International ($ USD)", callback_data="set_country_GLOBAL")]
        ]
        
        await self.safe_reply_text(
            update,
            f"🌍 *Country Settings*\n\n"
            f"*Current:* {current_display}\n\n"
            f"This affects your payment options:\n"
            f"• 🇳🇬 *Nigeria:* Paystack (Daily/Weekly/Monthly)\n"
            f"• 🌍 *International:* Stripe (Monthly only)\n\n"
            f"👇 *Select your region:*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button callbacks."""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        if query.data == "set_country_NG":
            # User manually selected Nigeria
            await db_manager.update_user_country(user_id, 'NG')
            await query.edit_message_text(
                "🇳🇬 *Nigeria selected!*\n\n"
                "You'll now see Naira pricing via Paystack:\n"
                "• Daily: ₦999\n"
                "• Weekly: ₦2,999\n"
                "• Monthly: ₦4,999\n\n"
                "Use /upgrade to see your payment options.",
                parse_mode='Markdown'
            )
            return
        
        elif query.data == "set_country_GLOBAL":
            # User manually selected International
            await db_manager.update_user_country(user_id, 'GLOBAL')
            await query.edit_message_text(
                "🌍 *International selected!*\n\n"
                "You'll see USD pricing via Stripe:\n"
                "• Monthly: $9.99/month\n\n"
                "Use /upgrade to see your payment options.",
                parse_mode='Markdown'
            )
            return
        
        elif query.data.startswith("open_job_"):
            job_id = query.data.replace("open_job_", "")
            # The URL is already embedded in the button, so this is just for acknowledgment
            await query.edit_message_reply_markup(reply_markup=None)

        elif query.data == "upgrade_show":
            # Show upgrade options based on user's country
            await self._show_upgrade_options(query, user_id)
            return
        
        elif query.data.startswith("upgrade_plan_"):
            # User selected a plan - show confirmation with benefits
            # Format: upgrade_plan_{plan}_{job_id} or upgrade_plan_{plan}
            data_after_prefix = query.data.replace("upgrade_plan_", "")
            
            # Handle plans: daily, weekly, monthly
            if data_after_prefix.startswith("daily_"):
                plan = "daily"
                job_id = data_after_prefix.replace("daily_", "", 1) if len(data_after_prefix) > 6 else None
            elif data_after_prefix.startswith("weekly_"):
                plan = "weekly"
                job_id = data_after_prefix.replace("weekly_", "", 1) if len(data_after_prefix) > 7 else None
            elif data_after_prefix.startswith("monthly_"):
                plan = "monthly"
                job_id = data_after_prefix.replace("monthly_", "", 1) if len(data_after_prefix) > 8 else None
            else:
                # No job_id, just plan name
                plan = data_after_prefix
                job_id = None
            
            # If job_id exists, ensure it's stored as pending
            if job_id:
                await db_manager.set_pending_reveal_job(user_id, job_id)
            
            await self._show_plan_confirmation(query, user_id, plan)
            return
        
        elif query.data.startswith("confirm_pay_"):
            # User confirmed plan selection - proceed to payment
            plan = query.data.replace("confirm_pay_", "")
            await self._handle_plan_selection(query, user_id, plan)
            return

        elif query.data.startswith("reveal_"):
            # Scout user wants to reveal a job using a credit
            job_id = query.data.replace("reveal_", "")
            
            # Check if user has credits
            credits = await db_manager.get_reveal_credits(user_id)
            if credits <= 0:
                # Store pending job for auto-reveal after payment
                await db_manager.set_pending_reveal_job(user_id, job_id)
                
                # Get job data to show in paywall message
                job_data_dict = await db_manager.get_job_for_strategy(job_id)
                if not job_data_dict:
                    await query.edit_message_text(
                        text="❌ Job data not found. This job may have expired.",
                        parse_mode='Markdown'
                    )
                    return
                
                # Format job metadata (same as in send_job_alert)
                job_budget = ""
                if job_data_dict.get('budget_max') and job_data_dict['budget_max'] > 0:
                    job_budget = f"${job_data_dict['budget_max']}"
                elif job_data_dict.get('budget_min') and job_data_dict['budget_min'] > 0:
                    job_budget = f"${job_data_dict['budget_min']}+"
                job_type = job_data_dict.get('job_type', '') or ''
                job_exp = job_data_dict.get('experience_level', '') or ''
                posted_time = job_data_dict.get('posted_time', '') or ''
                
                metadata_line = " | ".join(filter(None, [job_budget, job_type, job_exp]))
                if posted_time:
                    metadata_line += f"\nPosted {posted_time}"
                else:
                    metadata_line += "\nPosted just now"
                
                # Get user's region for pricing
                user_info = await db_manager.get_user_info(user_id)
                country = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
                pricing = billing_service.get_pricing_for_country(country)
                
                # Show paywall with region-based pricing and messaging
                if country == 'NG':
                    keyboard = [
                        [InlineKeyboardButton(f"⚡ Daily Hustle – {pricing['plans']['daily']['display']} / 24h", callback_data=f"upgrade_plan_daily_{job_id}")],
                        [InlineKeyboardButton(f"🔥 Weekly Sprint – {pricing['plans']['weekly']['display']} / 7d", callback_data=f"upgrade_plan_weekly_{job_id}")],
                        [InlineKeyboardButton(f"💎 Monthly Pro – {pricing['plans']['monthly']['display']} / 30d – Most Popular ✅", callback_data=f"upgrade_plan_monthly_{job_id}")]
                    ]
                    unlock_text = "Unlock unlimited job reveals and AI proposals for the next 24 hours, 7 days, or 30 days."
                else:
                    keyboard = [
                        [InlineKeyboardButton(f"💎 Monthly Pro – {pricing['plans']['monthly']['display']}/mo – Most Popular ✅", callback_data=f"upgrade_plan_monthly_{job_id}")]
                    ]
                    unlock_text = "Unlock unlimited job reveals and AI proposals for the next 30 days."
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Combine job alert + paywall in one message
                paywall_message = (
                    f"🚨 *NEW JOB ALERT*\n\n"
                    f"*{job_data_dict.get('title', 'Job')}*\n"
                    f"{metadata_line}\n\n"
                    f"⛔ *No Reveal Credits left!*\n\n"
                    f"This job was posted just now — unlock it before others apply.\n\n"
                    f"{unlock_text}\n\n"
                    f"💡 *You won't be charged until you click Pay Now.*\n"
                    f"⏱ *Apply before others see this job — your advantage disappears fast.*"
                )
                
                await query.edit_message_text(
                    text=paywall_message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                return
            
            # Get job data
            job_data_dict = await db_manager.get_job_for_strategy(job_id)
            if not job_data_dict:
                await query.edit_message_text(
                    text="❌ Job data not found. This job may have expired.",
                    parse_mode='Markdown'
                )
                return
            
            # Show processing message
            await query.edit_message_text(
                text="🧠 *Generating your proposal...*\n\n"
                "This may take a few seconds.",
                parse_mode='Markdown'
            )
            
            # Get user context for proposal generation
            user_context = await db_manager.get_user_context(user_id)
            if not user_context:
                await query.edit_message_text(
                    text="❌ User profile not found. Use /start to set up.",
                    parse_mode='Markdown'
                )
                return
            
            # NOW generate proposal (this is where AI call happens)
            try:
                proposal_text = await self.proposal_generator.generate_proposal(
                    job_data_dict,
                    user_context
                )
                
                if not proposal_text:
                    await query.edit_message_text(
                        text="❌ Failed to generate proposal. Please try again later.",
                        parse_mode='Markdown'
                    )
                    return
                
                # Use credit and store proposal
                success = await db_manager.use_reveal_credit(user_id, job_id, proposal_text)
                
                if not success:
                    await query.edit_message_text(
                        text="❌ Failed to use reveal credit. Please try again.",
                        parse_mode='Markdown'
                    )
                    return
                
                # Get updated credits count
                remaining_credits = await db_manager.get_reveal_credits(user_id)
                
                # Format full proposal message
                message_text = self.proposal_generator.format_proposal_for_telegram(
                    proposal_text, job_data_dict, draft_count=0, max_drafts=0
                )
                
                # Add credits remaining info
                message_text += f"\n\n👁 *Reveal Credits remaining: {remaining_credits}*"
                
                # Create keyboard with job link
                keyboard = [
                    [InlineKeyboardButton("🚀 Open Job on Upwork", url=job_data_dict['link'])]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Update message with full proposal
                await query.edit_message_text(
                    text=message_text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                
                logger.info(f"Revealed job {job_id} for scout user {user_id}. Credits remaining: {remaining_credits}")
                
            except Exception as e:
                logger.error(f"Error revealing job {job_id} for user {user_id}: {e}")
                await query.edit_message_text(
                    text="❌ An error occurred. Please try again later.",
                    parse_mode='Markdown'
                )
            return

        elif query.data.startswith("strategy_"):
            job_id = query.data.replace("strategy_", "")

            # Check War Room permissions
            can_use_war_room = await access_service.can_use_war_room(user_id)
            
            if not can_use_war_room:
                # Show upgrade prompt instead
                user_info = await db_manager.get_user_info(user_id)
                country = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
                pricing = billing_service.get_pricing_for_country(country)
                
                if country == 'NG':
                    price_display = pricing['plans']['daily']['display']
                else:
                    price_display = pricing['plans']['monthly']['display'] + "/mo"
                
                keyboard = [[InlineKeyboardButton(f"🔓 Upgrade Now - {price_display}", callback_data="upgrade_show")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text="🚫 *War Room is Pro Only*\n\n"
                    "Upgrade to unlock:\n"
                    "• Full AI-generated proposals\n"
                    "• Job links to apply directly\n"
                    "• War Room strategy mode\n"
                    "• Real-time job alerts",
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                return

            # Check strategy draft limit
            MAX_STRATEGY_DRAFTS = config.MAX_STRATEGY_DRAFTS
            try:
                draft_counts = await db_manager.get_proposal_draft_count(user_id, job_id)
                strategy_count = draft_counts['strategy_count']
            except Exception as e:
                logger.error(f"Failed to get strategy draft count for user {user_id}, job {job_id}: {e}")
                strategy_count = 0  # Allow if database fails
            
            if strategy_count >= MAX_STRATEGY_DRAFTS:
                await query.edit_message_text(
                    text=f"⚠️ *Limit Reached*\n\n"
                    f"You've generated {strategy_count} strategy proposals for this job.\n\n"
                    f"💡 *Tip:* Try editing your existing proposal instead. "
                    f"Clients appreciate personalized touches - add 1-2 specific details about this job to make it stand out.\n\n"
                    f"Copy your previous proposal and edit it directly in Upwork.",
                    parse_mode='Markdown'
                )
                return

            # Enter strategy mode
            await db_manager.set_user_state(user_id, "STRATEGIZING", job_id)

            await query.edit_message_text(
                text="🧠 **War Room Activated!**\n\n"
                f"**Job ID:** {job_id}\n\n"
                "How do you want to play this? Give me specific instructions:\n\n"
                "💡 **Examples:**\n"
                "• \"Be aggressive on price, I'm the fastest\"\n"
                "• \"Focus on my Django expertise and scalability\"\n"
                "• \"Ask consultative questions about their tech stack\"\n\n"
                "Type your strategy:",
                parse_mode='Markdown'
            )

        elif query.data == "update_keywords":
            # Enter keywords update state - set both DB and conversation handler state
            await db_manager.set_user_state(user_id, "UPDATE_KEYWORDS")
            context.user_data['state'] = UPDATE_KEYWORDS  # Set conversation handler state
            await query.edit_message_text(
                text="✏️ **Update Keywords**\n\n"
                "Enter your new keywords (comma separated):\n\n"
                "📝 **Example:** `Python, Django, API, Backend, React`\n\n"
                "Type your keywords (or /cancel to cancel):",
                parse_mode='Markdown'
            )

        elif query.data == "update_bio":
            # Enter bio update state - set both DB and conversation handler state
            await db_manager.set_user_state(user_id, "UPDATE_BIO")
            context.user_data['state'] = UPDATE_BIO  # Set conversation handler state
            await query.edit_message_text(
                text="✏️ **Update Bio**\n\n"
                "Enter your new bio/experience:\n\n"
                "💡 **Example:**\n"
                "`Senior Python developer with 5+ years building scalable web apps. "
                "Led 20+ Django projects, reduced deployment time by 60%. "
                "Expert in REST APIs, PostgreSQL, and cloud deployment.`\n\n"
                "Your bio (keep it under 500 characters, or /cancel to cancel):",
                parse_mode='Markdown'
            )

        elif query.data == "update_budget":
            # Show budget filter options
            keyboard = [
                [InlineKeyboardButton("Any Budget", callback_data="budget_0_999999")],
                [InlineKeyboardButton("$50+", callback_data="budget_50_999999")],
                [InlineKeyboardButton("$100+", callback_data="budget_100_999999")],
                [InlineKeyboardButton("$250+", callback_data="budget_250_999999")],
                [InlineKeyboardButton("$500+", callback_data="budget_500_999999")],
                [InlineKeyboardButton("$1000+", callback_data="budget_1000_999999")],
                [InlineKeyboardButton("$100 - $500", callback_data="budget_100_500")],
                [InlineKeyboardButton("$500 - $2000", callback_data="budget_500_2000")],
                [InlineKeyboardButton("Cancel", callback_data="cancel_settings")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="Set Budget Filter\n\n"
                "Select minimum budget for job alerts:\n\n"
                "(Jobs below this budget will be filtered out)",
                reply_markup=reply_markup
            )
        
        elif query.data.startswith("budget_"):
            # Parse budget range: budget_MIN_MAX
            parts = query.data.split("_")
            if len(parts) == 3:
                min_budget = int(parts[1])
                max_budget = int(parts[2])
                await db_manager.update_user_filters(user_id, min_budget=min_budget, max_budget=max_budget)
                
                if max_budget >= 999999:
                    budget_text = f"${min_budget}+" if min_budget > 0 else "Any"
                else:
                    budget_text = f"${min_budget} - ${max_budget}"
                
                await query.edit_message_text(
                    text=f"Budget filter updated to: {budget_text}\n\n"
                    "Use /settings to view all settings."
                )
        
        elif query.data == "update_experience":
            # Show experience level options (multi-select would require more complex state)
            keyboard = [
                [InlineKeyboardButton("All Levels", callback_data="exp_all")],
                [InlineKeyboardButton("Entry Level Only", callback_data="exp_Entry")],
                [InlineKeyboardButton("Intermediate Only", callback_data="exp_Intermediate")],
                [InlineKeyboardButton("Expert Only", callback_data="exp_Expert")],
                [InlineKeyboardButton("Intermediate + Expert", callback_data="exp_Intermediate,Expert")],
                [InlineKeyboardButton("Cancel", callback_data="cancel_settings")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="Set Experience Filter\n\n"
                "Select which experience levels to receive alerts for:",
                reply_markup=reply_markup
            )
        
        elif query.data.startswith("exp_"):
            exp_value = query.data.replace("exp_", "")
            if exp_value == "all":
                exp_levels = ["Entry", "Intermediate", "Expert"]
            else:
                exp_levels = exp_value.split(",")
            
            await db_manager.update_user_filters(user_id, experience_levels=exp_levels)
            
            await query.edit_message_text(
                text=f"Experience filter updated to: {', '.join(exp_levels)}\n\n"
                "Use /settings to view all settings."
            )
        
        elif query.data == "update_pause":
            # Show pause duration options
            keyboard = [
                [InlineKeyboardButton("⏸️ Pause 1 hour", callback_data="pause_1")],
                [InlineKeyboardButton("⏸️ Pause 4 hours", callback_data="pause_4")],
                [InlineKeyboardButton("⏸️ Pause 8 hours", callback_data="pause_8")],
                [InlineKeyboardButton("😴 Pause 12 hours", callback_data="pause_12")],
                [InlineKeyboardButton("🌙 Pause 24 hours", callback_data="pause_24")],
                [InlineKeyboardButton("▶️ Resume Alerts", callback_data="pause_off")],
                [InlineKeyboardButton("Cancel", callback_data="cancel_settings")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="⏸️ *Pause Alerts*\n\n"
                "Take a break from job notifications.\n"
                "Alerts will automatically resume when the timer ends.",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        
        elif query.data.startswith("pause_"):
            pause_value = query.data.replace("pause_", "")
            if pause_value == "off":
                await db_manager.clear_user_pause(user_id)
                await query.edit_message_text(
                    text="▶️ *Alerts Resumed*\n\n"
                    "You'll receive job alerts again.\n"
                    "Use /settings to view all settings.",
                    parse_mode='Markdown'
                )
            else:
                try:
                    hours = int(pause_value)
                    pause_until = await db_manager.set_user_pause(user_id, hours)
                    
                    # Format display time
                    time_display = pause_until.strftime("%I:%M %p")
                    
                    keyboard = [[InlineKeyboardButton("▶️ Unpause Now", callback_data="pause_off")]]
                    await query.edit_message_text(
                        text=f"⏸️ *Alerts Paused*\n\n"
                        f"You won't receive alerts for *{hours} hour{'s' if hours > 1 else ''}*.\n"
                        f"Resuming at: {time_display}",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except ValueError:
                    await query.edit_message_text("Invalid pause duration.")

        elif query.data == "cancel_settings":
            await query.edit_message_text(
                text="Cancelled\n\nUse /settings to try again."
            )

    async def send_job_alert(self, user_id: int, job_data: JobData) -> bool:
        """
        Send a job alert to a specific user.
        Handles both paid users (full proposal) and scout users (blurred).

        Args:
            user_id: Telegram user ID to send alert to
            job_data: Job data object

        Returns:
            True if alert was sent successfully, False otherwise
        """
        try:
            # Get user permissions (also handles auto-downgrade)
            permissions = await access_service.get_user_permissions(user_id)
            
            # Check if user was just downgraded - send notification
            was_downgraded = await access_service.check_and_handle_expiry(user_id)
            if was_downgraded:
                try:
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text=access_service.get_downgrade_message(),
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to send downgrade notification to {user_id}: {e}")
                # Refresh permissions after downgrade
                permissions = await access_service.get_user_permissions(user_id)

            # Get user context for personalized proposals
            user_context = await db_manager.get_user_context(user_id)
            if not user_context:
                logger.warning(f"No user context found for user: {user_id}")
                return False

            # Store job data for potential strategy mode
            await db_manager.store_job_for_strategy(job_data.to_dict())

            # Format job metadata
            job_budget = ""
            if hasattr(job_data, 'budget_min') and hasattr(job_data, 'budget_max'):
                if job_data.budget_max and job_data.budget_max > 0:
                    job_budget = f"${job_data.budget_max}"
                elif job_data.budget_min and job_data.budget_min > 0:
                    job_budget = f"${job_data.budget_min}+"
            job_type = getattr(job_data, 'job_type', '') or ''
            job_exp = getattr(job_data, 'experience_level', '') or ''
            posted_time = getattr(job_data, 'posted_time', '') or ''
            
            metadata_line = " | ".join(filter(None, [job_budget, job_type, job_exp]))
            if posted_time:
                metadata_line += f"\nPosted {posted_time}"

            # ==================== SCOUT USER (BLURRED) ====================
            if not permissions.get('can_view_proposal', False):
                # Check if job already revealed (NO AI call if already revealed)
                revealed_data = await db_manager.get_revealed_proposal(user_id, job_data.id)
                
                if revealed_data:
                    # Already revealed - show stored proposal (NO AI call)
                    proposal_text = revealed_data['proposal_text']
                    
                    # Format message for Telegram
                    message_text = self.proposal_generator.format_proposal_for_telegram(
                        proposal_text, job_data.to_dict(), draft_count=0, max_drafts=0
                    )
                    
                    # Create inline keyboard with job link
                    keyboard = [
                        [InlineKeyboardButton("🚀 Open Job on Upwork", url=job_data.link)]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode='Markdown',
                        reply_markup=reply_markup,
                        disable_web_page_preview=True
                    )
                    
                    logger.info(f"Sent revealed job alert to scout user {user_id} for job: {job_data.id} (stored proposal)")
                    return True
                
                # Not revealed - show blurred (NO AI call)
                credits = await db_manager.get_reveal_credits(user_id)
                
                # Truncate description for preview (first 200 chars)
                description_preview = ""
                if job_data.description:
                    desc = job_data.description.strip()
                    if len(desc) > 200:
                        description_preview = desc[:200].rsplit(' ', 1)[0] + "..."
                    else:
                        description_preview = desc
                
                blurred_message = (
                    f"🚨 *NEW JOB ALERT*\n\n"
                    f"*{job_data.title}*\n"
                    f"{metadata_line}\n\n"
                )
                
                if description_preview:
                    blurred_message += f"_{description_preview}_\n\n"
                
                blurred_message += (
                    f"*Your Custom Proposal:*\n"
                    f"░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░\n"
                    f"░░░░░░░░░░ BLURRED ░░░░░░░░░░░░░░░░░░░░░\n"
                    f"░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░\n\n"
                    f"💎 *Unlock full proposal and job link*\n"
                    f"Use a reveal credit or upgrade to see AI-generated proposals!"
                )
                
                # Get user's country for pricing display
                user_info = await db_manager.get_user_info(user_id)
                country = user_info.get('country_code', 'GLOBAL') if user_info else 'GLOBAL'
                pricing = billing_service.get_pricing_for_country(country)
                
                # Create keyboard with reveal button (if credits available) and upgrade button
                keyboard = []
                
                if credits > 0:
                    reveal_btn = InlineKeyboardButton(
                        f"👁 Reveal Proposal ({credits} left)",
                        callback_data=f"reveal_{job_data.id}"
                    )
                    keyboard.append([reveal_btn])
                else:
                    # Even with 0 credits, use reveal_ callback to store job_id for auto-reveal
                    reveal_btn = InlineKeyboardButton(
                        "👁 No credits left",
                        callback_data=f"reveal_{job_data.id}"
                    )
                    keyboard.append([reveal_btn])
                
                # Add upgrade button
                if country == 'NG':
                    daily_price = pricing['plans']['daily']['display']
                    upgrade_btn = InlineKeyboardButton(
                        f"🔓 Upgrade Now - {daily_price}",
                        callback_data="upgrade_show"
                    )
                else:
                    monthly_price = pricing['plans']['monthly']['display']
                    upgrade_btn = InlineKeyboardButton(
                        f"🔓 Upgrade Now - {monthly_price}/mo",
                        callback_data="upgrade_show"
                    )
                keyboard.append([upgrade_btn])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=blurred_message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                
                logger.info(f"Sent blurred job alert to scout user {user_id} for job: {job_data.id} (NO AI call)")
                return True

            # ==================== PAID USER (FULL ACCESS) ====================
            
            # Check proposal draft limit
            MAX_DRAFTS = config.MAX_PROPOSAL_DRAFTS
            try:
                draft_counts = await db_manager.get_proposal_draft_count(user_id, job_data.id)
                draft_count = draft_counts['draft_count']
            except Exception as e:
                logger.error(f"Failed to get draft count for user {user_id}, job {job_data.id}: {e}")
                draft_count = 0  # Allow generation if database fails
            
            if draft_count >= MAX_DRAFTS:
                # Limit reached - send message encouraging editing
                limit_message = (
                    f"🚨 *NEW JOB ALERT*\n\n*{job_data.title}*\n{metadata_line}\n\n"
                    f"You've generated {draft_count} proposals for this job.\n\n"
                    f"💡 *Tip:* Clients can tell when proposals are personalized. "
                    f"Try editing your previous proposal (add 1-2 specific details about this job) instead of generating a new one.\n\n"
                    f"Use the War Room button below to refine your existing proposal with specific instructions."
                )
                
                keyboard = [
                    [InlineKeyboardButton("🚀 Open Job on Upwork", url=job_data.link)],
                    [InlineKeyboardButton("🧠 War Room (Refine Existing)", callback_data=f"strategy_{job_data.id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=limit_message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                logger.info(f"Proposal limit reached for user {user_id}, job {job_data.id}")
                return True

            # Generate personalized proposal
            proposal_text = await self.proposal_generator.generate_proposal(
                job_data.to_dict(),
                user_context
            )

            if not proposal_text:
                logger.error(f"Failed to generate proposal for user {user_id}, job {job_data.id}")
                return False

            # Increment draft count (only if generation succeeded)
            try:
                await db_manager.increment_proposal_draft(user_id, job_data.id, is_strategy=False)
            except Exception as e:
                logger.error(f"Failed to increment draft count for user {user_id}, job {job_data.id}: {e}")

            # Format message for Telegram
            message_text = self.proposal_generator.format_proposal_for_telegram(
                proposal_text, job_data.to_dict(), draft_count=draft_count + 1, max_drafts=MAX_DRAFTS
            )

            # Create inline keyboard with job link and strategy button
            keyboard = [
                [InlineKeyboardButton("🚀 Open Job on Upwork", url=job_data.link)],
                [InlineKeyboardButton("🧠 Brainstorm Strategy", callback_data=f"strategy_{job_data.id}")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send message
            await self.application.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )

            logger.info(f"Sent job alert to user {user_id} for job: {job_data.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send job alert to user {user_id}: {e}")
            return False

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command."""
        user_id = update.effective_user.id

        user_info = await db_manager.get_user_info(user_id)
        if not user_info:
            await self.safe_reply_text(update, "Profile not found. Use /start to set up.")
            return ConversationHandler.END

        # Get subscription status
        subscription = await db_manager.get_subscription_status(user_id)
        plan_name = billing_service.get_plan_name(subscription.get('plan', 'scout'))
        
        # Get referral stats
        referral_stats = await db_manager.get_referral_stats(user_id)
        referral_code = await db_manager.create_referral_code(user_id)

        # Show current settings with update buttons
        keywords_display = user_info['keywords'] or 'Not set'
        if len(keywords_display) > 50:
            keywords_display = keywords_display[:50] + "..."
        
        bio_length = len(user_info['context'] or '')
        bio_preview = (user_info['context'] or 'Not set')[:100]
        if len(user_info.get('context', '') or '') > 100:
            bio_preview += "..."

        # Format budget display
        min_budget = user_info.get('min_budget', 0)
        max_budget = user_info.get('max_budget', 999999)
        if max_budget >= 999999:
            budget_display = f"${min_budget}+" if min_budget > 0 else "Any"
        else:
            budget_display = f"${min_budget} - ${max_budget}"
        
        # Format experience levels
        exp_levels = user_info.get('experience_levels', ['Entry', 'Intermediate', 'Expert'])
        exp_display = ', '.join(exp_levels) if exp_levels else 'All levels'
        
        # Format pause status
        pause_until_str = user_info.get('pause_start')  # We store pause_until in pause_start field
        if pause_until_str and db_manager.is_user_paused(pause_until_str):
            remaining = db_manager.get_pause_remaining(pause_until_str)
            pause_display = f"⏸️ Paused ({remaining})"
        else:
            pause_display = "▶️ Active"

        # Format subscription display (hide "Scout" label)
        if subscription.get('is_active'):
            days_remaining = subscription.get('days_remaining', 0)
            sub_display = f"*{plan_name}* ({days_remaining} days left)"
        else:
            # Free user - show credits instead of "Scout"
            credits = await db_manager.get_reveal_credits(user_id)
            sub_display = f"*Free Access* (👁 {credits} Reveal Credits)\n💡 /upgrade to unlock full features"

        settings_msg = (
            "⚙️ *Settings*\n\n"
            f"📊 *Plan:* {sub_display}\n\n"
            f"🎯 *Keywords:* {keywords_display}\n\n"
            f"📝 *Bio:* {bio_preview}\n"
            f"   ({bio_length}/500 characters)\n\n"
            f"💰 *Budget Filter:* {budget_display}\n"
            f"📈 *Experience:* {exp_display}\n"
            f"🔔 *Alerts:* {pause_display}\n\n"
            f"🔗 *Referral Code:* `{referral_code}`\n"
            f"👥 *Referrals:* {referral_stats['activated_referrals']} activated, {referral_stats['total_referrals']} total\n\n"
            "Click buttons below to update:"
        )

        # Create inline keyboard with update buttons
        keyboard = [
            [InlineKeyboardButton("Update Keywords", callback_data="update_keywords")],
            [InlineKeyboardButton("Update Bio", callback_data="update_bio")],
            [InlineKeyboardButton("Set Budget Filter", callback_data="update_budget")],
            [InlineKeyboardButton("Set Experience Filter", callback_data="update_experience")],
            [InlineKeyboardButton("⏸️ Pause Alerts", callback_data="update_pause")],
            [InlineKeyboardButton("Cancel", callback_data="cancel_settings")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.safe_reply_text(update, settings_msg)
        await update.message.reply_text("Choose an option:", reply_markup=reply_markup)
        
        return ConversationHandler.END  # Don't enter a state yet, wait for button click

    # Payment Activation Handler (would be called when user provides transaction ID)
    async def activate_payment(self, user_id: int, transaction_id: str) -> bool:
        """Activate user payment and process referrals."""
        try:
            # Mark user as paid
            await db_manager.activate_user_payment(user_id)

            # Generate referral code for new paid user
            await db_manager.create_referral_code(user_id)

            logger.info(f"Activated payment for user {user_id} with transaction {transaction_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to activate payment for user {user_id}: {e}")
            return False

    async def broadcast_job_alert(self, job_data: JobData) -> int:
        """
        Send job alert to authorized users whose keywords match the job.

        Args:
            job_data: Job data object

        Returns:
            Number of users who received the alert
        """
        try:
            # Get all active users
            active_users = await db_manager.get_active_users()
            admin_users = config.ADMIN_IDS

            # Combine and deduplicate user IDs
            all_user_ids = set()
            for user in active_users:
                all_user_ids.add(user['telegram_id'])
            for admin_id in admin_users:
                all_user_ids.add(admin_id)

            # Collect all users who should receive the alert
            users_to_alert = []
            for user_id in all_user_ids:
                user_info = await db_manager.get_user_info(user_id)
                
                if not user_info:
                    continue
                
                # Check if user is currently paused
                pause_until_str = user_info.get('pause_start')  # pause_until stored in pause_start
                if db_manager.is_user_paused(pause_until_str):
                    logger.debug(f"Skipping user {user_id} - alerts paused")
                    continue
                
                # Check budget filter
                min_budget = user_info.get('min_budget', 0)
                max_budget = user_info.get('max_budget', 999999)
                job_budget = getattr(job_data, 'budget_max', 0) or getattr(job_data, 'budget_min', 0)
                
                if job_budget > 0:  # Only filter if job has a budget
                    if job_budget < min_budget:
                        logger.debug(f"Skipping user {user_id} - job budget ${job_budget} below min ${min_budget}")
                        continue
                    if job_budget > max_budget and max_budget < 999999:
                        logger.debug(f"Skipping user {user_id} - job budget ${job_budget} above max ${max_budget}")
                        continue
                
                # Check experience level filter
                exp_levels = user_info.get('experience_levels', ['Entry', 'Intermediate', 'Expert'])
                job_exp = getattr(job_data, 'experience_level', 'Unknown')
                if job_exp != 'Unknown' and exp_levels:
                    if job_exp not in exp_levels:
                        logger.debug(f"Skipping user {user_id} - job exp {job_exp} not in {exp_levels}")
                        continue
                
                # Check keyword match
                should_alert = False
                if user_info.get('keywords'):
                    user_keywords = [kw.strip() for kw in user_info['keywords'].split(',') if kw.strip()]
                    if job_data.matches_keywords(user_keywords):
                        should_alert = True
                elif user_id in admin_users:
                    # Admins get all jobs regardless of keywords
                    should_alert = True
                
                if should_alert:
                    users_to_alert.append(user_id)

            # Optimized two-phase approach for speed:
            # Phase 1: Generate all proposals in parallel (AI is the bottleneck)
            # Phase 2: Send all messages in parallel (Telegram handles rate limiting)
            # This ensures all users get alerts within 1 minute
            
            if not users_to_alert:
                return 0
            
            import time
            start_time = time.time()
            logger.info(f"Broadcasting to {len(users_to_alert)} users - generating proposals in parallel...")
            
            # Phase 1: Generate proposals for PAID users only (scouts get blurred via send_job_alert)
            async def prepare_alert(user_id: int):
                """Prepare alert for a user (generate proposal for paid, mark scouts for blurred)"""
                try:
                    # Check authorization
                    if not await db_manager.is_user_authorized(user_id):
                        return None
                    
                    # Check if user can view proposals (paid vs scout)
                    permissions = await access_service.get_user_permissions(user_id)
                    
                    # Scout users - return marker to trigger send_job_alert (blurred flow, NO AI cost)
                    if not permissions.get('can_view_proposal', False):
                        return {
                            'user_id': user_id,
                            'type': 'scout',  # Will be handled by send_job_alert
                            'message': None
                        }
                    
                    # PAID USER - Generate full proposal with AI
                    # Get user context
                    user_context = await db_manager.get_user_context(user_id)
                    if not user_context:
                        return None
                    
                    # Check draft limit
                    MAX_DRAFTS = config.MAX_PROPOSAL_DRAFTS
                    try:
                        draft_counts = await db_manager.get_proposal_draft_count(user_id, job_data.id)
                        draft_count = draft_counts['draft_count']
                    except Exception as e:
                        logger.error(f"Failed to get draft count for user {user_id}: {e}")
                        draft_count = 0
                    
                    if draft_count >= MAX_DRAFTS:
                        # Return limit message instead of proposal
                        return {
                            'user_id': user_id,
                            'type': 'limit',
                            'draft_count': draft_count,
                            'message': None
                        }
                    
                    # Generate proposal (this is the slow part - happens in parallel for all users)
                    proposal_text = await self.proposal_generator.generate_proposal(
                        job_data.to_dict(),
                        user_context
                    )
                    
                    if not proposal_text:
                        return None
                    
                    # Increment draft count
                    try:
                        await db_manager.increment_proposal_draft(user_id, job_data.id, is_strategy=False)
                    except Exception as e:
                        logger.error(f"Failed to increment draft count for user {user_id}: {e}")
                    
                    # Format message
                    message_text = self.proposal_generator.format_proposal_for_telegram(
                        proposal_text, job_data.to_dict(), draft_count=draft_count + 1, max_drafts=MAX_DRAFTS
                    )
                    
                    return {
                        'user_id': user_id,
                        'type': 'proposal',
                        'message': message_text,
                        'draft_count': draft_count + 1
                    }
                except Exception as e:
                    logger.error(f"Error preparing alert for user {user_id}: {e}")
                    return None
            
            # Generate all proposals concurrently (semaphore in ProposalGenerator limits to 5 at a time)
            prepared_alerts = await asyncio.gather(
                *[prepare_alert(user_id) for user_id in users_to_alert],
                return_exceptions=True
            )
            
            # Filter out None/errors and separate by type
            valid_alerts = [a for a in prepared_alerts if a and not isinstance(a, Exception)]
            scout_alerts = [a for a in valid_alerts if a.get('type') == 'scout']
            limit_alerts = [a for a in valid_alerts if a.get('type') == 'limit']
            proposal_alerts = [a for a in valid_alerts if a.get('type') == 'proposal']
            
            generation_time = time.time() - start_time
            logger.info(f"Generated {len(proposal_alerts)} proposals, {len(limit_alerts)} limit msgs, {len(scout_alerts)} scout (blurred) in {generation_time:.1f}s")
            
            # Phase 2: Send all messages concurrently (Telegram API handles 30 msg/sec rate limiting)
            send_start = time.time()
            
            async def send_prepared_alert(alert_data: dict):
                """Send a prepared alert message"""
                try:
                    user_id = alert_data['user_id']
                    
                    if alert_data['type'] == 'scout':
                        # Scout user - use send_job_alert which has blurring logic (NO AI call)
                        return await self.send_job_alert(user_id, job_data)
                    
                    elif alert_data['type'] == 'limit':
                        # Send limit message
                        limit_message = (
                            f"NEW JOB ALERT\n\n{job_data.title}\n\n"
                            f"You've generated {alert_data['draft_count']} proposals for this job.\n\n"
                            f"💡 **Tip:** Clients can tell when proposals are personalized. "
                            f"Try editing your previous proposal (add 1-2 specific details about this job) instead of generating a new one.\n\n"
                            f"Use the War Room button below to refine your existing proposal with specific instructions."
                        )
                        keyboard = [
                            [InlineKeyboardButton("🚀 Open Job on Upwork", url=job_data.link)],
                            [InlineKeyboardButton("🧠 War Room (Refine Existing)", callback_data=f"strategy_{job_data.id}")]
                        ]
                        await self.application.bot.send_message(
                            chat_id=user_id,
                            text=limit_message,
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            disable_web_page_preview=True
                        )
                    else:
                        # Send proposal message (paid user)
                        keyboard = [
                            [InlineKeyboardButton("🚀 Open Job on Upwork", url=job_data.link)],
                            [InlineKeyboardButton("🧠 Brainstorm Strategy", callback_data=f"strategy_{job_data.id}")]
                        ]
                        await self.application.bot.send_message(
                            chat_id=user_id,
                            text=alert_data['message'],
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            disable_web_page_preview=True
                        )
                    
                    return True
                except Exception as e:
                    logger.error(f"Failed to send alert to user {alert_data.get('user_id')}: {e}")
                    return False
            
            # Send all messages concurrently (Telegram API queues automatically at 30 msg/sec)
            all_alerts = proposal_alerts + limit_alerts + scout_alerts
            if all_alerts:
                send_results = await asyncio.gather(
                    *[send_prepared_alert(alert) for alert in all_alerts],
                    return_exceptions=True
                )
                sent_count = sum(1 for r in send_results if r is True)
            else:
                sent_count = 0
            
            # Store job data once (not per user)
            await db_manager.store_job_for_strategy(job_data.to_dict())
            
            total_time = time.time() - start_time
            send_time = time.time() - send_start
            logger.info(
                f"Broadcast complete: {sent_count} users alerted in {total_time:.1f}s total "
                f"(AI: {generation_time:.1f}s, Send: {send_time:.1f}s) for job: {job_data.id}"
            )
            return sent_count

        except Exception as e:
            logger.error(f"Failed to broadcast job alert: {e}")
            return 0

    async def send_error_notification(self, user_id: int, error_message: str) -> None:
        """Send an error notification to a user."""
        try:
            await self.application.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ **Bot Error**\n\n{error_message}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send error notification: {e}")

# Global bot instance
bot = UpworkBot()