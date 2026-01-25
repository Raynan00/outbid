"""
AI-powered proposal generator supporting multiple providers (OpenAI, Gemini).
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


class ProposalGenerator:
    """Generates custom cover letters using configurable AI providers."""

    def __init__(self):
        self.provider = self._initialize_provider()
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
        else:
            logger.warning(f"Unknown AI provider '{provider_type}', defaulting to OpenAI")
            return OpenAIProvider(
                api_key=config.OPENAI_API_KEY,
                model=config.OPENAI_MODEL
            )

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
            else:
                logger.error("AI provider returned empty response")
                return None

        except Exception as e:
            logger.error(f"Failed to generate proposal: {e}")
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
        return """You are an expert Upwork freelancer who consistently gets replies and interviews.

Your goal is NOT to sound impressive.
Your goal is to get the client to reply.

CORE RULES (NON-NEGOTIABLE):

1. OPEN STRONG (FIRST 1-2 SENTENCES)
- Reference the client's specific problem, goal, or constraint from the job post.
- Make it obvious you actually read the description.
- Do NOT start with greetings, names, years of experience, or generic lines.

2. SOLUTION FIRST, NOT BIO
- Explain HOW you would approach or solve the problem.
- Be concrete and practical.
- Use short paragraphs or bullet points if it improves clarity.

3. PROOF OF RELEVANCE
- Mention 1-2 highly relevant experiences or results from the freelancer's background.
- Use numbers or outcomes where possible.
- Only include experience that directly applies to THIS job.

4. TONE & STYLE
- Natural, confident, and human.
- No buzzwords. No corporate language.
- Write like a real person typing on Upwork, not a sales page.
- Optimized for mobile reading.

5. LENGTH
- 150-220 words maximum.
- Short sentences. Easy to scan.

6. CLOSE WITH A CTA
- End with a clear next step (question, suggestion, or offer to start).
- Make it easy for the client to reply.

IMPORTANT:
- Do NOT mention AI.
- Do NOT use emojis.
- Do NOT restate the entire job description.
- Do NOT sound templated.

DYNAMIC ADJUSTMENTS (CRITICAL):

Adapt the proposal style based on the job type:

A) TECHNICAL / DEVELOPMENT JOBS (software, scraping, automation, backend, frontend, data, APIs)
- Emphasize tools, stack, and technical approach.
- Mention how you would structure or implement the solution.
- Avoid generic "I'm experienced in X" statements.
- Show competence through HOW, not claims.

B) CREATIVE / CONTENT / DESIGN JOBS (copywriting, video, design, branding, content, marketing)
- Emphasize outcomes, clarity, and examples.
- Mention what result the client will get (conversions, engagement, clarity).
- Keep tone conversational and results-focused.

C) LONG-TERM / ONGOING ROLES (VA, support, maintenance, retainers, monthly work)
- Emphasize reliability, communication, and process.
- Show you understand ongoing needs, not just one task.
- Mention consistency, responsiveness, and long-term value.

D) SHORT / FIXED TASKS (one-off jobs, quick fixes, audits, small tasks)
- Be direct and efficient.
- Emphasize speed, clarity, and quick turnaround.
- Avoid over-explaining.

OUTPUT REQUIREMENTS:
- Return ONLY the proposal text.
- No headings.
- No bullet point symbols unless they improve clarity.
- No extra commentary.
- Plain text only. No markdown, no bold, no formatting."""

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