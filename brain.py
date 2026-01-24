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
        return """You are an expert Upwork freelancer. Write a professional cover letter that will be pasted directly into Upwork.

CRITICAL OUTPUT RULES:
1. OUTPUT ONLY THE COVER LETTER TEXT - No explanations, no meta-commentary, no "Here's a cover letter..." or "I saw your need..." introductions.
2. START DIRECTLY with the cover letter content - Begin with a strong opening that addresses the client's specific needs.
3. NO APOLOGIES OR QUALIFICATIONS - Don't say "While my skills might seem unrelated" or "Although I'm primarily experienced in..." - be confident and direct.
4. BE CONCISE: 150-300 words maximum. Every sentence must add value.

STRUCTURE:
- Opening: Direct hook addressing their specific problem/need
- Body: Highlight relevant experience and skills from user's background (be specific, not generic)
- Address screening questions if the job mentions any
- Closing: Clear call-to-action (e.g., "I'm available to start immediately" or "Let's discuss how I can help")

TONE: Professional, confident, results-focused. Write as if you're already the right person for the job.

OUTPUT FORMAT: Plain text cover letter only. No markdown, no bold, no formatting. Ready to copy-paste into Upwork."""

    def _get_strategy_system_prompt(self) -> str:
        """Get the system prompt for strategy mode proposal generation."""
        return """You are an expert Upwork freelancer. Write a strategic cover letter based on the user's specific instructions.

CRITICAL OUTPUT RULES:
1. OUTPUT ONLY THE COVER LETTER TEXT - No explanations, no meta-commentary, no "Here's..." or "I'll rewrite..." introductions.
2. START DIRECTLY with the cover letter content.
3. FOLLOW THE USER'S STRATEGY EXACTLY - They know their market better than anyone.
4. If given an original proposal, rewrite it strategically (don't just add to it).
5. BE CONCISE: 150-300 words maximum.
6. BE CONFIDENT - No apologies, no qualifications, no "while my skills might seem..."

TONE: Professional, confident, results-focused. Implement the requested strategy (pricing, positioning, timeline, etc.) directly.

OUTPUT FORMAT: Plain text cover letter only. No markdown, no formatting. Ready to copy-paste into Upwork."""

    def _build_job_prompt(self, job_data: Dict[str, Any], user_context: Dict[str, Any]) -> str:
        """Build the user prompt with job details and user context."""
        title = job_data.get('title', 'Unknown Title')
        description = job_data.get('description', '')
        tags = job_data.get('tags', [])
        budget = job_data.get('budget', 'Not specified')
        user_keywords = user_context.get('keywords', '')
        user_bio = user_context.get('context', '')

        # Clean up description (remove HTML tags if present)
        import re
        description = re.sub(r'<[^>]+>', '', description)

        # Truncate description if too long
        if len(description) > 2000:
            description = description[:2000] + "..."

        prompt = f"""JOB DETAILS:
Title: {title}
Description: {description}
Skills Required: {', '.join(tags) if tags else 'Not specified'}
Budget: {budget}

USER BACKGROUND:
Keywords/Skills: {user_keywords}
Bio/Experience: {user_bio}

Write a professional cover letter for this Upwork job. The output will be pasted directly into Upwork's proposal field.

REQUIREMENTS:
- Write ONLY the cover letter text (no explanations or introductions)
- Start directly with the cover letter content
- Use the user's background to show relevant experience
- Be confident and direct - don't apologize or qualify your skills
- Keep it 150-300 words
- End with a clear call-to-action

Output the cover letter text only, ready to copy-paste."""

        return prompt

    def _build_strategy_prompt(self, job_data: Dict[str, Any], user_context: Dict[str, Any], strategy_input: str, original_proposal: str = "") -> str:
        """Build the strategy prompt for interactive customization."""
        title = job_data.get('title', 'Unknown Title')
        user_keywords = user_context.get('keywords', '')
        user_bio = user_context.get('context', '')

        prompt = f"""JOB: {title}
USER SKILLS: {user_keywords}
USER BACKGROUND: {user_bio}

STRATEGY INSTRUCTION: {strategy_input}

"""

        if original_proposal:
            prompt += f"""ORIGINAL PROPOSAL TO MODIFY:
{original_proposal}

Rewrite this proposal following the strategy instruction above. Focus on the specific tactical approach requested."""

        else:
            prompt += """Create a new strategic proposal following the strategy instruction above. Make it tactical and competitive."""

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