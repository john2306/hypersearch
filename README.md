# 📑 Data Model: Sources & Chunks

Este esquema en **PostgreSQL** está diseñado para manejar **documentos (sources)** y sus **fragmentos (chunks)**, permitiendo búsquedas híbridas: **full-text (BM25)** y **semánticas (embeddings con pgvector)**.  

---

## ⚙️ Extensiones requeridas

```sql
CREATE EXTENSION IF NOT EXISTS pg_vector;   -- Soporte de embeddings (pgvector)
CREATE EXTENSION IF NOT EXISTS pg_search;  -- Búsqueda full-text con BM25
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- Generación de UUIDs