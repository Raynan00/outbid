"""
AI-powered proposal generator supporting multiple providers (OpenAI, Gemini, Claude).
Generates custom cover letters for Upwork job applications.
"""

import asyncio
import logging
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from openai import AsyncOpenAI
from config import config

logger = logging.getLogger(__name__)

class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    async def generate_text(self, prompt: str, system_prompt: str = "", max_tokens: int = 1000) -> Optional[str]:
        """Generate text using the AI provider."""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the name of this AI provider."""
        pass


class OpenAIProvider(AIProvider):
    """OpenAI GPT provider implementation."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate_text(self, prompt: str, system_prompt: str = "", max_tokens: int = 1000) -> Optional[str]:
        """Generate text using OpenAI."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
                presence_penalty=0.1,
                frequency_penalty=0.1
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI generation failed: {e}")
            return None

    def get_provider_name(self) -> str:
        return f"OpenAI ({self.model})"


class GeminiProvider(AIProvider):
    """Google Gemini provider implementation."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        try:
            # Use the modern google.genai package
            import google.genai as genai
            self.client = genai.Client(api_key=api_key)
            self.model_name = model
        except ImportError:
            raise ImportError("Google Generative AI package not installed. Run: pip install google.genai")

    async def generate_text(self, prompt: str, system_prompt: str = "", max_tokens: int = 1000) -> Optional[str]:
        """Generate text using Gemini."""
        try:
            # Configure generation parameters
            config = {
                'max_output_tokens': max_tokens,
                'temperature': 0.7,
                'top_p': 0.9,
                'top_k': 40,
            }

            # Combine system prompt and user prompt
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"

            # Generate content using the new API
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=full_prompt,
                config=config
            )

            if response and response.text:
                return response.text.strip()
            else:
                logger.error("Gemini returned empty response")
                return None

        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            return None

    def get_provider_name(self) -> str:
        return "Google Gemini"


class ClaudeProvider(AIProvider):
    """Anthropic Claude provider implementation."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        try:
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=api_key)
            self.model = model
        except ImportError:
            raise ImportError("Anthropic package not installed. Run: pip install anthropic")

    async def generate_text(self, prompt: str, system_prompt: str = "", max_tokens: int = 1000) -> Optional[str]:
        """Generate text using Claude."""
        try:
            kwargs = {
                'model': self.model,
                'max_tokens': max_tokens,
                'messages': [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                kwargs['system'] = system_prompt

            response = await self.client.messages.create(**kwargs)

            if response and response.content:
                return response.content[0].text.strip()
            else:
                logger.error("Claude returned empty response")
                return None

        except Exception as e:
            logger.error(f"Claude generation failed: {e}")
            return None

    def get_provider_name(self) -> str:
        return f"Claude ({self.model})"


class ProposalGenerator:
    """Generates custom cover letters using configurable AI providers."""

    def __init__(self):
        self.provider = self._initialize_provider()
        self.fallback_provider = self._initialize_fallback()
        self.max_tokens = config.AI_MAX_TOKENS
        # Limit concurrent AI requests to avoid rate limits
        # Configurable via AI_CONCURRENT_REQUESTS (default: 10)
        # Higher = faster generation, but watch for API rate limits
        self._semaphore = asyncio.Semaphore(config.AI_CONCURRENT_REQUESTS)

    def _initialize_provider(self) -> AIProvider:
        """Initialize the appropriate AI provider based on configuration."""
        provider_type = config.AI_PROVIDER.lower()

        if provider_type == "openai":
            return OpenAIProvider(
                api_key=config.OPENAI_API_KEY,
                model=config.OPENAI_MODEL
            )
        elif provider_type == "gemini":
            return GeminiProvider(
                api_key=config.GEMINI_API_KEY,
                model=config.GEMINI_MODEL
            )
        elif provider_type == "claude":
            return ClaudeProvider(
                api_key=config.ANTHROPIC_API_KEY,
                model=config.CLAUDE_MODEL
            )
        else:
            logger.warning(f"Unknown AI provider '{provider_type}', defaulting to OpenAI")
            return OpenAIProvider(
                api_key=config.OPENAI_API_KEY,
                model=config.OPENAI_MODEL
            )

    def _initialize_fallback(self) -> Optional[AIProvider]:
        """Initialize fallback provider (Claude Haiku by default)."""
        try:
            if config.ANTHROPIC_API_KEY:
                logger.info("Fallback AI provider: Claude Haiku")
                return ClaudeProvider(api_key=config.ANTHROPIC_API_KEY, model=config.CLAUDE_MODEL)
        except Exception as e:
            logger.warning(f"Failed to initialize fallback AI provider: {e}")
        return None

    async def generate_proposal(self, job_data: Dict[str, Any], user_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate a custom cover letter for a job posting using user context.

        Args:
            job_data: Dictionary containing job information
            user_context: Dictionary containing user keywords and bio/context

        Returns:
            Generated proposal text or None if generation fails
        """
        try:
            system_prompt = self._get_standard_system_prompt()
            user_prompt = self._build_job_prompt(job_data, user_context)

            # Use semaphore to limit concurrent AI requests
            async with self._semaphore:
                proposal = await self.provider.generate_text(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=self.max_tokens
                )

            if proposal:
                logger.info(f"Generated proposal for job: {job_data.get('id', 'unknown')} using {self.provider.get_provider_name()}")
                return proposal

            # Primary failed, try fallback
            if self.fallback_provider:
                logger.warning(f"Primary AI ({self.provider.get_provider_name()}) returned empty, trying fallback ({self.fallback_provider.get_provider_name()})")
                async with self._semaphore:
                    proposal = await self.fallback_provider.generate_text(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        max_tokens=self.max_tokens
                    )
                if proposal:
                    logger.info(f"Fallback generated proposal for job: {job_data.get('id', 'unknown')} using {self.fallback_provider.get_provider_name()}")
                    return proposal

            logger.error("All AI providers returned empty response")
            return None

        except Exception as e:
            logger.error(f"Primary AI failed: {e}")
            # Try fallback on exception too
            if self.fallback_provider:
                try:
                    logger.warning(f"Trying fallback AI ({self.fallback_provider.get_provider_name()}) after primary exception")
                    async with self._semaphore:
                        proposal = await self.fallback_provider.generate_text(
                            prompt=user_prompt,
                            system_prompt=system_prompt,
                            max_tokens=self.max_tokens
                        )
                    if proposal:
                        logger.info(f"Fallback generated proposal for job: {job_data.get('id', 'unknown')}")
                        return proposal
                except Exception as fallback_error:
                    logger.error(f"Fallback AI also failed: {fallback_error}")
            return None

    async def generate_strategy(self, job_data: Dict[str, Any], user_context: Dict[str, Any], strategy_input: str, original_proposal: str = "") -> Optional[str]:
        """
        Generate a strategic proposal based on user input.

        Args:
            job_data: Dictionary containing job information
            user_context: Dictionary containing user keywords and bio/context
            strategy_input: User's specific strategy instructions
            original_proposal: Previous proposal to modify (optional)

        Returns:
            Generated strategic proposal or None if generation fails
        """
        try:
            system_prompt = self._get_strategy_system_prompt()
            user_prompt = self._build_strategy_prompt(job_data, user_context, strategy_input, original_proposal)

            # Use semaphore to limit concurrent AI requests
            async with self._semaphore:
                proposal = await self.provider.generate_text(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=self.max_tokens
                )

            if proposal:
                logger.info(f"Generated strategy proposal for job: {job_data.get('id', 'unknown')} using {self.provider.get_provider_name()}")
                return proposal
            else:
                logger.error("AI provider returned empty response for strategy")
                return None

        except Exception as e:
            logger.error(f"Failed to generate strategy proposal: {e}")
            return None

    def _get_standard_system_prompt(self) -> str:
        """Get the system prompt for standard proposal generation."""
        return """You are an expert Upwork freelancer. Your one job: get the client to reply.

Every proposal MUST follow this exact 4-part structure, in this order:

--- STRUCTURE ---

1. HOOK (first 1-2 sentences)
Identify the client's core pain, goal, or frustration from the job post. Open by directly naming it.
Do NOT start with greetings, your name, years of experience, or "I saw your post."
Bad: "Hi, I'm a developer with 5 years of experience."
Good: "Your Shopify store is leaking revenue because checkout abandonment isn't being addressed."
The hook must show you understand THEIR problem, not that you exist.

2. SOLUTION (2-4 sentences)
Explain exactly how you would solve their problem. Be specific and practical.
Name the tools, methods, or steps you'd use. Don't just say "I can help" — say HOW.
Write in natural flowing sentences — do NOT use bullet points or lists. It should read like a real person typed it, not a template.
Use current, expert-level tools (e.g. Playwright over Selenium, undetected-chromedriver over basic Selenium).
Bad: "I have experience building similar solutions."
Good: "I'd build the backend in Node.js to process Shopify webhooks in real-time, with a React dashboard so you can monitor inventory levels across all three warehouses at a glance."

3. PROOF (1-2 sentences)
Show you've done this before with a specific outcome. Use numbers, results, or concrete details.
Only mention experience that directly applies to THIS job.
IMPORTANT: Frame proof around results and systems, NOT volume or busyness. If you mention managing multiple clients/projects, the client may fear you're too busy for them. Focus on the outcome you delivered, not how many things you juggle.
Bad: "I currently manage 4 stores with 200 orders daily." (signals too busy)
Good: "I built the same flow for a DTC skincare brand. Their recovery rate went from 8% to 23% in 6 weeks."

4. CTA (final 1-2 sentences)
End with a LOW-FRICTION next step. Do NOT default to "let's hop on a call" — calls are a big commitment for clients.
Instead, offer to send something valuable (a plan, questions, a sample, a quick audit) via message.
Bad: "Let me know if you're interested."
Bad: "Can we schedule a quick call?"
Good: "I have a few questions about your warehouse API. Mind if I send them over via chat?"
Good: "I'd love to share a quick outline of the email sequence structure. Should I send it over?"

--- RULES ---

- 150-220 words max. Short sentences. Easy to scan on mobile.
- Confident and natural. Write like a real person, not a sales page.
- No buzzwords, no corporate language, no fluff.
- No emojis. No AI mentions. No restating the job description. No em dashes (—).
- Do NOT sound templated. Every proposal must feel custom-written.
- Adapt technical depth to the job type: technical jobs get specific tools/stack, creative jobs get outcomes/results, ongoing roles get reliability/process, quick tasks get speed/directness.

--- OUTPUT ---

Return ONLY the proposal text. No headings, no labels, no commentary, no bullet points, no lists. Plain text only, no markdown. It must read like a human typed it in the Upwork message box."""

    def _get_strategy_system_prompt(self) -> str:
        """Get the system prompt for strategy mode (War Room) proposal generation."""
        return """You are rewriting an Upwork proposal with additional strategic guidance.

TASK:
- Rewrite the proposal to incorporate the user's strategy notes.
- Apply the same tone, clarity, and job-type awareness as the original.
- Do NOT increase length unnecessarily.
- Keep it natural and client-focused.

RULES:
- No fluff.
- No buzzwords.
- No emojis.
- End with a clear call to action.
- 150-220 words maximum.
- Follow the user's strategy EXACTLY - they know their market.

OUTPUT:
- Return ONLY the rewritten proposal.
- No explanations, no commentary, no "Here's the rewritten..." intro.
- Plain text only. No markdown, no formatting."""

    def _build_job_prompt(self, job_data: Dict[str, Any], user_context: Dict[str, Any]) -> str:
        """Build the user prompt with job details and user context."""
        title = job_data.get('title', 'Unknown Title')
        description = job_data.get('description', '')
        tags = job_data.get('tags', [])
        budget = job_data.get('budget', 'Not specified')
        experience_level = job_data.get('experience_level', 'Not specified')
        user_keywords = user_context.get('keywords', '')
        user_bio = user_context.get('context', '')

        # Clean up description (remove HTML tags if present)
        import re
        description = re.sub(r'<[^>]+>', '', description)

        # Truncate description if too long
        if len(description) > 2000:
            description = description[:2000] + "..."

        prompt = f"""CONTEXT:
- Job Title: {title}
- Job Description: {description}
- Budget: {budget}
- Client Experience Level: {experience_level}
- Skills Required: {', '.join(tags) if tags else 'Not specified'}
- Freelancer Skills: {user_keywords}
- Freelancer Bio (Brag Sheet): {user_bio}

TASK:
Write a concise, high-conversion Upwork proposal tailored specifically to this job.
Output the proposal text only, ready to copy-paste."""

        return prompt

    def _build_strategy_prompt(self, job_data: Dict[str, Any], user_context: Dict[str, Any], strategy_input: str, original_proposal: str = "") -> str:
        """Build the strategy prompt for War Room interactive customization."""
        title = job_data.get('title', 'Unknown Title')
        description = job_data.get('description', '')
        
        # Truncate description if too long
        if len(description) > 1000:
            description = description[:1000] + "..."

        prompt = f"""ORIGINAL PROPOSAL:
{original_proposal if original_proposal else '(No original proposal - create new one)'}

JOB CONTEXT:
{title}
{description}

USER STRATEGY NOTES:
{strategy_input}

Rewrite the proposal incorporating the user's strategy notes. Return ONLY the rewritten proposal."""

        return prompt

    async def analyze_job_risks(self, job_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Analyze a job posting for potential risks or concerns.

        Returns:
            Dictionary with risk analysis
        """
        try:
            prompt = f"""Analyze this Upwork job posting for potential risks or concerns:

Title: {job_data.get('title', '')}
Description: {job_data.get('description', '')}
Budget: {job_data.get('budget', 'Not specified')}

Identify any red flags such as:
- Unclear or unrealistic requirements
- Budget that seems too low/high for the scope
- Suspicious client behavior indicators
- Timeline issues
- Missing information

Provide a brief analysis (2-3 sentences) of potential risks."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.3
            )

            analysis = response.choices[0].message.content.strip()
            return {
                "risks": analysis,
                "has_risks": len(analysis) > 10  # Consider it has risks if analysis is substantial
            }

        except Exception as e:
            logger.error(f"Failed to analyze job risks: {e}")
            return {
                "risks": "Unable to analyze risks at this time.",
                "has_risks": False
            }

    def format_proposal_for_telegram(self, proposal: str, job_data: Dict[str, Any], 
                                     draft_count: int = 1, max_drafts: int = 3, 
                                     is_strategy: bool = False) -> str:
        """
        Format the proposal text for Telegram with proper markdown and structure.
        """
        if not proposal:
            return "Failed to generate proposal automatically."

        # Create the formatted message
        title = job_data.get('title', 'Unknown Job')
        budget = job_data.get('budget', 'Not specified')
        tags = job_data.get('tags', [])
        experience_level = job_data.get('experience_level', '')
        job_type = job_data.get('job_type', '')
        posted = job_data.get('posted', '')

        # Header with job info
        header = f"NEW JOB ALERT\n\n{title}\n"
        
        # Job metadata line
        meta_parts = []
        if budget and budget != 'N/A':
            meta_parts.append(f"Budget: {budget}")
        if job_type and job_type != 'Unknown':
            meta_parts.append(job_type)
        if experience_level and experience_level != 'Unknown':
            meta_parts.append(experience_level)
        
        if meta_parts:
            header += ' | '.join(meta_parts) + "\n"
        
        if posted:
            header += f"{posted}\n"

        header += "⏱ Jobs get 10+ proposals in the first hour. Apply fast.\n"

        if tags:
            header += f"Skills: {', '.join(tags[:5])}\n"  # Limit to 5 tags

        # Proposal in code block for easy copying
        formatted_proposal = f"\nYour Custom Proposal:\n```\n{proposal}\n```"

        # Footer with tips and editing encouragement
        footer = "\nTap the proposal above to copy it instantly!"
        
        # Add editing micro-copy (show after first draft)
        if draft_count > 1 or is_strategy:
            footer += "\n\n💡 Tip: Clients can tell when proposals are personalized. Edit 1-2 lines before sending to add specific details about this job."
        
        # Show draft count if approaching limit
        if draft_count >= max_drafts - 1:
            remaining = max_drafts - draft_count
            footer += f"\n\n⚠️ {remaining} draft{'s' if remaining > 1 else ''} remaining. Try editing this one instead of generating more."

        return header + formatted_proposal + footer