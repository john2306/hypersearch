import logging
import asyncio
from typing import List
from celery import shared_task
from celery.signals import worker_process_init, worker_shutdown

from settings import DB_DSN
from .db import AsyncPGORM, init_db_pool, close_db_pool
from .openai_client import AsyncOpenAIClient
from .tokenizer import preprocess_content

logger = logging.getLogger(__name__)

# ORM global para reusar dentro del worker
orm: AsyncPGORM | None = None


# ============================================================
# Inicializar / cerrar pool al inicio y fin del worker
# ============================================================
@worker_process_init.connect
def init_worker(**kwargs):
    global orm
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db_pool(DB_DSN, min_size=1, max_size=5))
    orm = AsyncPGORM()
    logger.info("✅ DB pool initialized in worker")


@worker_shutdown.connect
def shutdown_worker(**kwargs):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(close_db_pool())
    logger.info("✅ DB pool closed in worker")


# ============================================================
# Tarea principal
# ============================================================
@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_knowledge(self, knowledge_ids: List[int]) -> str:
    logger.info("Processing knowledge batch with size: %d", len(knowledge_ids))
    asyncio.run(_process_batch(knowledge_ids))
    return "Knowledge saved successfully"


async def _process_batch(knowledge_ids: List[int]):
    # procesar en paralelo todos los IDs
    await asyncio.gather(*(process_chunk_knowledge(k) for k in knowledge_ids))


# ============================================================
# Procesamiento individual
# ============================================================
async def process_chunk_knowledge(knowledge_id: int):
    global orm
    try:
        knowledge = await orm.get("knowledge", "id", knowledge_id)
        if knowledge is None:
            logger.warning("Knowledge not found for ID: %d", knowledge_id)
            return

        title = knowledge["title"]
        body = knowledge["body"]
        chunks = [title, body]

        openai_client = AsyncOpenAIClient()
        embeddings = await openai_client.create_embeddings(chunks)

        new_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            new_chunks.append({
                "knowledge_id": knowledge_id,
                "raw_text": chunk,
                "processed_text": await preprocess_content(chunk, lang="es"),
                "embedding": embedding
            })

        await orm.bulk_create("chunks", new_chunks)
        logger.info("✅ Knowledge %d processed successfully", knowledge_id)

    except Exception as e:
        logger.exception("❌ Error processing knowledge %d: %s", knowledge_id, e)
        raise  # deja que Celery reintente si corresponde
