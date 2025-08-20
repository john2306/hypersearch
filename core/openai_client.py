import asyncio
from openai import AsyncOpenAI
from settings import OPENAI_API_KEY

_MAX_TRIES = 3
_BASE_DELAY = 2  # seconds

aopenai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

class AsyncOpenAIClient:
    """OpenAI Async Client for handling asynchronous requests to the OpenAI API."""

    def __init__(self):
        self.client = aopenai_client
        self.trying_text_generation = 0
        self.trying_embeddings = 0

    async def create_embeddings(self, sentences: list, dimensions: int = 1536, model: str = "text-embedding-3-small", username="hyperdb"):
        try:
            resp = await self.client.embeddings.create(
                input=sentences,
                model=model,
                encoding_format="float",
                dimensions=dimensions,
                user=username,
            )
            return [d.embedding for d in resp.data]
        except Exception as e:
            self.trying_embeddings += 1
            if self.trying_embeddings <= _MAX_TRIES:
                await asyncio.sleep(_BASE_DELAY ** self.trying_embeddings)
                return await self.create_embeddings(sentences, dimensions, model, username)
            self.trying_embeddings = 0
            return []

    async def text_generation(self, messages, model="gpt-4o-mini", username="cashea", response_format=None, temperature=0.7):
        import asyncio
        tries = 0
        while tries < _MAX_TRIES:
            try:
                resp = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    user=username,
                    response_format=response_format,
                    temperature=temperature,
                )
                return resp.choices[0].message.content
            except Exception as e:
                print(e)
                tries += 1
                await asyncio.sleep(_BASE_DELAY ** tries)
        return None
    
    async def health_check(self):
        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": "ping"}
                ],
                max_tokens=1,
                temperature=0.0,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(e)
            return str(e)