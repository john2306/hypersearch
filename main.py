import logging
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
from typing import List
import asyncio

from core import init_db_pool, close_db_pool, AsyncPGORM, AsyncOpenAIClient
from settings import DB_DSN
from models import Source
from core.tasks import process_knowledge

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("hypersearch.log")
    ]
)
logger = logging.getLogger("HyperSearch")

# Global variables for dependency injection
custom_orm: AsyncPGORM | None = None
openai_client: AsyncOpenAIClient | None = None
startup_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global custom_orm, openai_client, startup_time

    startup_start = time.time()
    logger.info("Starting HyperSearch service...")

    try:
        # 1. Initialize database pool with optimized settings
        await init_db_pool(DB_DSN, min_size=5, max_size=20)
        logger.info("✅ Database pool initialized")

        # 2. Initialize OpenAI client
        openai_client = AsyncOpenAIClient()
        # Test OpenAI connection
        health_result = await openai_client.health_check()
        logger.info(f"✅ OpenAI client initialized: {health_result}")

        # 3. Initialize ORM
        custom_orm = AsyncPGORM(timeout=30.0)
        logger.info("✅ ORM initialized")

        startup_time = time.time() - startup_start
        logger.info(f"🚀 HyperSearch service ready in {startup_time:.2f}s")

        yield  # Application is ready to serve requests

    except Exception as e:
        logger.error(f"❌ Failed to initialize service: {e}")
        raise
    finally:
        # Cleanup resources
        logger.info("Shutting down HyperSearch service...")
        await close_db_pool()
        logger.info("✅ Resources cleaned up")


# Create FastAPI app with optimized settings
app = FastAPI(
    title="HyperSearch Service",
    description="High-performance semantic search and knowledge processing service",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Security middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Configure according to your needs
)

# CORS middleware with optimized settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "uptime": time.time() - startup_time if startup_time > 0 else 0,
        "services": {}
    }

    # Check database connection
    try:
        if custom_orm:
            await custom_orm.execute("SELECT 1")
            health_status["services"]["database"] = "healthy"
        else:
            health_status["services"]["database"] = "not_initialized"
    except Exception as e:
        health_status["services"]["database"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"

    # Check OpenAI connection
    try:
        if openai_client:
            await openai_client.health_check()
            health_status["services"]["openai"] = "healthy"
        else:
            health_status["services"]["openai"] = "not_initialized"
    except Exception as e:
        health_status["services"]["openai"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    status_code = 200 if health_status["status"] in ["healthy", "degraded"] else 503
    return JSONResponse(content=health_status, status_code=status_code)


@app.get("/metrics")
async def get_metrics():
    """Basic metrics endpoint"""
    try:
        import psutil

        metrics = {
            "timestamp": time.time(),
            "uptime": time.time() - startup_time if startup_time > 0 else 0,
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_usage": psutil.disk_usage('/').percent
            }
        }

        if custom_orm:
            try:
                # Get database stats
                db_stats = await custom_orm.fetch("SELECT COUNT(*) as total_knowledge FROM knowledge")
                chunk_stats = await custom_orm.fetch("SELECT COUNT(*) as total_chunks FROM chunks")
                metrics["database"] = {
                    "total_knowledge": db_stats[0]["total_knowledge"] if db_stats else 0,
                    "total_chunks": chunk_stats[0]["total_chunks"] if chunk_stats else 0
                }
            except Exception as e:
                metrics["database"] = {"error": str(e)}

        return JSONResponse(content=metrics)
    except ImportError:
        return JSONResponse(
            content={"error": "psutil not installed, limited metrics available"},
            status_code=503
        )

@app.get("/init_db")
async def init_db():
    if custom_orm is None:
        return JSONResponse(content={"error": "Database not initialized"}, status_code=500)

    SQL_CMDS = [
        # Extensiones PostgreSQL
        "CREATE EXTENSION IF NOT EXISTS vector;", # Soporte de embeddings (pgvector)
        "CREATE EXTENSION IF NOT EXISTS pg_search;", # Búsqueda full-text con BM25
        "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";", # Generación de UUIDs

        # 0) Tabla Source
        """
        -- Primero definimos el ENUM para status
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'source_status') THEN
                CREATE TYPE source_status AS ENUM ('QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED');
            END IF;
        END$$;

        -- Tabla
        CREATE TABLE IF NOT EXISTS knowledge (
            id         bigserial PRIMARY KEY,
            uuid       UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
            source_id  varchar(255) NOT NULL UNIQUE,
            title      text NOT NULL,
            body       text NOT NULL,
            content_type   text NOT NULL,
            metadata   jsonb,
            status     source_status NOT NULL DEFAULT 'QUEUED',
            created_at timestamp NOT NULL DEFAULT NOW(),
            updated_at timestamp NOT NULL DEFAULT NOW()
        );

        -- Función que actualiza la columna updated_at
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        -- Trigger para la tabla knowledge
        DROP TRIGGER IF EXISTS trg_knowledge_updated_at ON knowledge;
        CREATE TRIGGER trg_knowledge_updated_at
        BEFORE UPDATE ON knowledge
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
        """,

        # 1) Tabla Chunk
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id         bigserial PRIMARY KEY,
            uuid       UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
            knowledge_id  bigint NOT NULL REFERENCES knowledge(id) ON DELETE CASCADE,
            position   integer NOT NULL DEFAULT 0,
            raw_text   text NOT NULL,
            processed_text    text NOT NULL,
            lang       text NOT NULL DEFAULT 'es',
            embedding  vector(1536) NOT NULL,
            metadata   jsonb
        );
        -- Índices sugeridos
        CREATE INDEX IF NOT EXISTS idx_chunks_knowledge_id ON chunks(knowledge_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_raw_text ON chunks(raw_text);
        CREATE INDEX IF NOT EXISTS idx_chunks_processed_text ON chunks(processed_text);
        CREATE INDEX IF NOT EXISTS idx_chunks_metadata ON chunks USING gin (metadata);
        """,

        # 2) Índice único por (knowledge_id, position)
        """
        CREATE UNIQUE INDEX IF NOT EXISTS chunks_source_pos_ux
        ON chunks (knowledge_id, position)
        """,

        # 3) Índices de búsqueda (opcional si aún no creas embeddings)
        # BM25
        """
        CREATE INDEX IF NOT EXISTS chunks_bm25
        ON chunks USING bm25 (id, processed_text)
        WITH (key_field = 'id')
        """,

        # HNSW (si usarás coseno; cambia a vector_ip_ops o vector_l2_ops si corresponde)
        """
        CREATE INDEX IF NOT EXISTS chunks_emb_hnsw
        ON chunks USING hnsw (embedding vector_cosine_ops)
        """
    ]
    for cmd in SQL_CMDS:
        await custom_orm.execute(cmd)
    print("✅ Database initialized")
    return JSONResponse(content={"status": "database initialized"})

@app.get("/clear_db")
async def clear_db():
    if custom_orm is None:
        return JSONResponse(content={"error": "Database not initialized"}, status_code=500)

    sql = """
        -- 1) Eliminar triggers y funciones
        DROP TRIGGER IF EXISTS trg_knowledge_updated_at ON knowledge;
        DROP FUNCTION IF EXISTS update_updated_at_column();

        -- 2) Eliminar tablas dependientes primero (chunks depende de knowledge)
        DROP TABLE IF EXISTS chunks CASCADE;
        DROP TABLE IF EXISTS knowledge CASCADE;

        -- 3) Eliminar tipos ENUM
        DROP TYPE IF EXISTS source_status;

        -- 4) Eliminar extensiones (opcional, solo si quieres limpiar TODO el entorno)
        DROP EXTENSION IF EXISTS "uuid-ossp";
        DROP EXTENSION IF EXISTS pg_search;
        DROP EXTENSION IF EXISTS vector;
    """
    await custom_orm.execute(sql)
    print("✅ Database cleared")
    return JSONResponse(content={"status": "database cleared"})

@app.post("/add_knowledge")
async def add_knowledge(knowledge: List[Source], background_tasks: BackgroundTasks):
    """Add knowledge with improved validation and batch processing"""

    if custom_orm is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if not knowledge:
        raise HTTPException(status_code=400, detail="No knowledge items provided")

    if len(knowledge) > 1000:  # Limit batch size
        raise HTTPException(status_code=400, detail="Batch size too large (max 1000 items)")

    try:
        # Convert to dict and validate
        data = jsonable_encoder(knowledge)
        source_ids = [item["source_id"] for item in data]

        # Check for duplicates in request
        if len(source_ids) != len(set(source_ids)):
            duplicates = [sid for sid in set(source_ids) if source_ids.count(sid) > 1]
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate source_ids in request: {duplicates}"
            )

        # Check for existing records in database
        existing_records = []
        for source_id in source_ids[:10]:  # Check first 10 to avoid overwhelming DB
            if await custom_orm.exists("knowledge", "source_id", source_id):
                existing_records.append(source_id)

        if existing_records:
            logger.warning(f"Found existing records: {existing_records}")

        # Insert/update knowledge records
        knowledge_ids = await custom_orm.bulk_upsert("knowledge", data)

        if not knowledge_ids:
            raise HTTPException(status_code=500, detail="Failed to insert knowledge records")

        # Process in smaller batches to avoid overwhelming Celery
        batch_size = 50
        for i in range(0, len(knowledge_ids), batch_size):
            batch = knowledge_ids[i:i + batch_size]
            process_knowledge.delay(batch)

        logger.info(f"✅ Added {len(knowledge_ids)} knowledge items in {len(range(0, len(knowledge_ids), batch_size))} batches")

        return JSONResponse(content={
            "status": "success",
            "message": f"Added {len(knowledge_ids)} knowledge items",
            "knowledge_ids": knowledge_ids,
            "existing_records": existing_records,
            "batches_queued": len(range(0, len(knowledge_ids), batch_size))
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error adding knowledge: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/knowledge/status/{knowledge_id}")
async def get_knowledge_status(knowledge_id: int):
    """Get processing status of specific knowledge item"""

    if custom_orm is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        knowledge = await custom_orm.get("knowledge", "id", knowledge_id)
        if not knowledge:
            raise HTTPException(status_code=404, detail="Knowledge not found")

        # Get chunk count
        chunks = await custom_orm.fetch(
            "SELECT COUNT(*) as chunk_count FROM chunks WHERE knowledge_id = $1",
            knowledge_id
        )
        chunk_count = chunks[0]["chunk_count"] if chunks else 0

        return JSONResponse(content={
            "id": knowledge["id"],
            "source_id": knowledge["source_id"],
            "status": knowledge["status"],
            "title": knowledge["title"],
            "chunk_count": chunk_count,
            "created_at": knowledge["created_at"].isoformat() if knowledge["created_at"] else None,
            "updated_at": knowledge["updated_at"].isoformat() if knowledge["updated_at"] else None
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting knowledge status: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/knowledge/stats")
async def get_knowledge_stats():
    """Get overall knowledge processing statistics"""

    if custom_orm is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        # Get status counts
        status_stats = await custom_orm.fetch("""
            SELECT status, COUNT(*) as count
            FROM knowledge
            GROUP BY status
        """)

        # Get total chunks
        chunk_stats = await custom_orm.fetch("SELECT COUNT(*) as total_chunks FROM chunks")

        # Get recent activity (last 24 hours)
        recent_activity = await custom_orm.fetch("""
            SELECT COUNT(*) as recent_count
            FROM knowledge
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """)

        return JSONResponse(content={
            "status_breakdown": {row["status"]: row["count"] for row in status_stats},
            "total_chunks": chunk_stats[0]["total_chunks"] if chunk_stats else 0,
            "recent_activity_24h": recent_activity[0]["recent_count"] if recent_activity else 0,
            "timestamp": time.time()
        })

    except Exception as e:
        logger.error(f"❌ Error getting knowledge stats: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")