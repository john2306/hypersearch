import asyncio
import logging
from typing import List, Optional, Dict, Any
from openai import AsyncOpenAI, RateLimitError, APITimeoutError, APIConnectionError
from settings import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# Configuration constants
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds
_MAX_DELAY = 60.0  # seconds
_TIMEOUT = 120.0  # 2 minutes timeout

# Global client with optimized settings
aopenai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    timeout=_TIMEOUT,
    max_retries=0  # We handle retries manually
)


class AsyncOpenAIClient:
    """Optimized OpenAI Async Client with proper error handling and rate limiting."""

    def __init__(self):
        self.client = aopenai_client

    async def _exponential_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter"""
        delay = min(_BASE_DELAY * (2 ** attempt), _MAX_DELAY)
        # Add jitter to prevent thundering herd
        jitter = delay * 0.1 * (0.5 - asyncio.get_event_loop().time() % 1)
        return delay + jitter

    async def _retry_with_backoff(self, operation, *args, **kwargs):
        """Generic retry wrapper with exponential backoff"""
        last_exception = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await operation(*args, **kwargs)
            except RateLimitError as e:
                last_exception = e
                if attempt < _MAX_RETRIES - 1:
                    delay = await self._exponential_backoff(attempt + 1)
                    logger.warning(f"Rate limit hit, retrying in {delay:.2f}s (attempt {attempt + 1})")
                    await asyncio.sleep(delay)
                continue
            except (APITimeoutError, APIConnectionError) as e:
                last_exception = e
                if attempt < _MAX_RETRIES - 1:
                    delay = await self._exponential_backoff(attempt)
                    logger.warning(f"API error: {e}, retrying in {delay:.2f}s (attempt {attempt + 1})")
                    await asyncio.sleep(delay)
                continue
            except Exception as e:
                # Non-retryable error
                logger.error(f"Non-retryable error in OpenAI operation: {e}")
                raise e

        logger.error(f"All retry attempts failed. Last error: {last_exception}")
        raise last_exception

    async def create_embeddings(
        self,
        sentences: List[str],
        dimensions: int = 1536,
        model: str = "text-embedding-3-small",
        username: str = "hypersearch"
    ) -> List[List[float]]:
        """Create embeddings with optimized batching and error handling"""

        if not sentences:
            return []

        # Filter empty sentences
        filtered_sentences = [s.strip() for s in sentences if s.strip()]
        if not filtered_sentences:
            return []

        async def _create_embeddings():
            try:
                response = await self.client.embeddings.create(
                    input=filtered_sentences,
                    model=model,
                    encoding_format="float",
                    dimensions=dimensions,
                    user=username,
                )
                return [data.embedding for data in response.data]
            except Exception as e:
                logger.error(f"Error creating embeddings: {e}")
                raise

        try:
            embeddings = await self._retry_with_backoff(_create_embeddings)
            logger.info(f"Successfully created {len(embeddings)} embeddings")
            return embeddings
        except Exception as e:
            logger.error(f"Failed to create embeddings after all retries: {e}")
            # Return empty embeddings instead of failing completely
            return [[] for _ in filtered_sentences]

    async def text_generation(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        username: str = "hypersearch",
        response_format: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Optional[str]:
        """Generate text with proper error handling"""

        async def _generate_text():
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    user=username,
                    response_format=response_format,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"Error in text generation: {e}")
                raise

        try:
            result = await self._retry_with_backoff(_generate_text)
            logger.info(f"Successfully generated text with model {model}")
            return result
        except Exception as e:
            logger.error(f"Failed to generate text after all retries: {e}")
            return None

    async def health_check(self) -> str:
        """Perform health check on OpenAI API"""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0.0,
                user="hypersearch_health_check"
            )
            result = response.choices[0].message.content or "OK"
            logger.info("OpenAI health check successful")
            return result
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return f"ERROR: {str(e)}"

    async def batch_embeddings(
        self,
        sentences_batches: List[List[str]],
        **kwargs
    ) -> List[List[List[float]]]:
        """Process multiple batches of embeddings concurrently"""
        if not sentences_batches:
            return []

        # Limit concurrent requests to avoid rate limits
        semaphore = asyncio.Semaphore(3)

        async def _process_batch(batch):
            async with semaphore:
                return await self.create_embeddings(batch, **kwargs)

        try:
            results = await asyncio.gather(
                *[_process_batch(batch) for batch in sentences_batches],
                return_exceptions=True
            )

            # Handle exceptions in results
            final_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Batch {i} failed: {result}")
                    final_results.append([[] for _ in sentences_batches[i]])
                else:
                    final_results.append(result)

            return final_results
        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            return [[] for _ in sentences_batches]