import logging
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from typing import List 

from core import init_db_pool, close_db_pool, AsyncPGORM, AsyncOpenAIClient
from settings import DB_DSN
from models import Source
from core.tasks import process_knowledge

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("HyperSearch-service")

custom_orm: AsyncPGORM | None = None
openai_client: AsyncOpenAIClient | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global custom_orm, openai_client

    # 1. Inicializar DB primero
    await init_db_pool(DB_DSN)

    # 2. Inicializar clientes
    openai_client = AsyncOpenAIClient()

    # 3. Inicializar ORM
    custom_orm = AsyncPGORM()

    logger.info("HyperSearch serverless initialized.")

    try:
        yield  # <-- la app está lista para recibir requests
    finally:
        # Cerrar recursos en orden inverso
        await close_db_pool()

app = FastAPI(title="HyperSearch As Service", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "healthy"})

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
            content    text NOT NULL,
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
async def add_knowledge(knowledge: List[Source]):
    if custom_orm is None:
        return JSONResponse(content={"error": "Database not initialized"}, status_code=500)
    data = jsonable_encoder(knowledge)
    source_ids = [item["source_id"] for item in data]
    if len(source_ids) != len(set(source_ids)):
        source_ids_duplicates = [item for item in data if item["source_id"] in source_ids]
        return JSONResponse(
            content={"error": "Duplicate source_ids found", "duplicates": source_ids_duplicates},
            status_code=400
        )
    knowledge_ids = await custom_orm.bulk_upsert("knowledge", data)
    process_knowledge.delay(knowledge_ids)
    print("✅ knowledge added")
    return JSONResponse(content={"status": "knowledge added"})