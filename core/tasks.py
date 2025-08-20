import logging
import asyncio
import threading
from typing import List
from celery import shared_task
from celery.signals import worker_process_init, worker_shutdown

from settings import DB_DSN
from .db import AsyncPGORM, init_db_pool, close_db_pool
from .openai_client import AsyncOpenAIClient
from .tokenizer import preprocess_content

logger = logging.getLogger(__name__)

# Thread-local storage para event loops y recursos
_thread_local = threading.local()


def get_or_create_event_loop():
    """Get or create event loop for current thread"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def get_orm():
    """Get thread-local ORM instance"""
    if not hasattr(_thread_local, 'orm'):
        _thread_local.orm = AsyncPGORM()
    return _thread_local.orm


# ============================================================
# Inicializar / cerrar pool al inicio y fin del worker
# ============================================================
@worker_process_init.connect
def init_worker(**kwargs):
    """Initialize worker with proper async setup"""
    try:
        loop = get_or_create_event_loop()
        loop.run_until_complete(init_db_pool(DB_DSN, min_size=2, max_size=10))
        logger.info("✅ DB pool initialized in worker")
    except Exception as e:
        logger.error("❌ Failed to initialize worker: %s", e)
        raise


@worker_shutdown.connect
def shutdown_worker(**kwargs):
    """Cleanup worker resources"""
    try:
        loop = get_or_create_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(close_db_pool())
        logger.info("✅ DB pool closed in worker")
    except Exception as e:
        logger.error("❌ Error during worker shutdown: %s", e)


# ============================================================
# Tarea principal optimizada
# ============================================================
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff_max=300
)
def process_knowledge(self, knowledge_ids: List[int]) -> str:
    """Process knowledge batch with proper async handling"""
    logger.info("Processing knowledge batch with %d items", len(knowledge_ids))

    try:
        loop = get_or_create_event_loop()
        # Use run_until_complete instead of asyncio.run to avoid loop conflicts
        loop.run_until_complete(_process_batch(knowledge_ids))
        logger.info("✅ Successfully processed %d knowledge items", len(knowledge_ids))
        return f"Knowledge batch of {len(knowledge_ids)} items processed successfully"
    except Exception as e:
        logger.error("❌ Failed to process knowledge batch: %s", e)
        raise


async def _process_batch(knowledge_ids: List[int]):
    """Process batch with controlled concurrency"""
    # Process in smaller chunks to avoid overwhelming the system
    chunk_size = 5  # Process 5 items concurrently

    for i in range(0, len(knowledge_ids), chunk_size):
        chunk = knowledge_ids[i:i + chunk_size]
        try:
            await asyncio.gather(
                *[process_chunk_knowledge(k) for k in chunk],
                return_exceptions=True
            )
        except Exception as e:
            logger.error("❌ Error processing chunk %s: %s", chunk, e)
            raise


# ============================================================
# Procesamiento individual optimizado
# ============================================================
async def process_chunk_knowledge(knowledge_id: int):
    """Process individual knowledge item with error handling"""
    orm = get_orm()
    openai_client = None

    try:
        # Get knowledge record
        knowledge = await orm.get("knowledge", "id", knowledge_id)
        if knowledge is None:
            logger.warning("Knowledge not found for ID: %d", knowledge_id)
            return

        title = knowledge.get("title", "").strip()
        body = knowledge.get("body", "").strip()

        # Filter empty chunks
        chunks = [chunk for chunk in [title, body] if chunk]

        if not chunks:
            logger.warning("No valid content found for knowledge ID: %d", knowledge_id)
            return

        # Initialize OpenAI client
        openai_client = AsyncOpenAIClient()

        # Create embeddings
        embeddings = await openai_client.create_embeddings(chunks)

        # Prepare chunk data for bulk insert
        new_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            processed_text = await preprocess_content(chunk, lang="es")
            new_chunks.append({
                "knowledge_id": knowledge_id,
                "raw_text": chunk,
                "processed_text": processed_text,
                "embedding": embedding
            })

        # Bulk insert chunks
        if new_chunks:
            await orm.bulk_create("chunks", new_chunks)
            logger.info("✅ Knowledge %d processed successfully (%d chunks)",
                       knowledge_id, len(new_chunks))
        else:
            logger.warning("No chunks created for knowledge ID: %d", knowledge_id)

    except Exception as e:
        logger.exception("❌ Error processing knowledge %d: %s", knowledge_id, e)
        raise  # Let Celery handle retries
    finally:
        # Cleanup if needed
        if openai_client:
            del openai_client
