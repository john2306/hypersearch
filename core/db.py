# RUN HyperRAG DB
# PG_USER=<postgres>
# PG_PASSWORD=<password>
# PG_DB=<hyperdb>
# PG_PORT=<5400>
# docker run --name paradedb -e POSTGRES_USER=<postgres> -e POSTGRES_PASSWORD=<password> -e POSTGRES_DB=<hyperdb> -v paradedb_data:/var/lib/postgresql/data/ -p <5400>:5432 -d paradedb/paradedb:latest

# docker run --name paradedb -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=qazwsx,.-UNI2020pe -e POSTGRES_DB=hyperdb -v paradedb_data:/var/lib/postgresql/data/ -p 5400:5432 -d paradedb/paradedb:latest

# docker exec -it paradedb psql -U postgres -d hyperdb -W

import re
from typing import Any, Dict, List, Optional
import asyncpg

IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$")  # opcional: permite schema.table

def _ident(name: str) -> str:
    """Valida nombres de tabla/campo para prevenir inyección en identificadores."""
    if not isinstance(name, str) or not IDENT_RE.match(name):
        raise ValueError(f"Identificador inválido: {name!r}")
    # Si quieres preservar mayúsculas/minúsculas exactas, podrías comillar aquí.
    return name

def _order(order: str) -> str:
    order = (order or "ASC").upper()
    if order not in ("ASC", "DESC"):
        raise ValueError("ORDER inválido")
    return order

# ===== Pool global opcional (inícialo en startup de tu app) =====
_pool: Optional[asyncpg.Pool] = None

async def init_db_pool(dsn: str, min_size: int = 1, max_size: int = 21):
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)

async def close_db_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

def get_pool() -> asyncpg.Pool:
    assert _pool is not None, "Pool no inicializado: llama init_db_pool() primero"
    return _pool

class AsyncPGORM:
    """
    ORM ligero sobre asyncpg.Pool.
    NOTA: table_name y field se validan con regex para evitar inyección.
    """

    async def exists(self, table_name: str, field: str, value) -> bool:
        tbl, fld = _ident(table_name), _ident(field)
        sql = f'SELECT 1 FROM {tbl} WHERE {fld} = $1 LIMIT 1'
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(sql, value)
            return row is not None

    async def get(self, table_name: str, field: str, value) -> Optional[Dict[str, Any]]:
        tbl, fld = _ident(table_name), _ident(field)
        sql = f'SELECT * FROM {tbl} WHERE {fld} = $1 LIMIT 1'
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(sql, value)
            return dict(row) if row else None

    async def get_one_specific_values(self, table_name: str, field: str, value, specific_fields: List[str]) -> Optional[Dict[str, Any]]:
        tbl, fld = _ident(table_name), _ident(field)
        cols = ", ".join(_ident(c) for c in specific_fields)
        sql = f'SELECT {cols} FROM {tbl} WHERE {fld} = $1 LIMIT 1'
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(sql, value)
            return dict(row) if row else None

    async def create(self, table_name: str, data: Dict[str, Any]) -> Optional[int]:
        tbl = _ident(table_name)
        keys = list(data.keys())
        for k in keys: _ident(k)
        cols = ", ".join(keys)
        placeholders = ", ".join(f"${i+1}" for i in range(len(keys)))
        sql = f'INSERT INTO {tbl} ({cols}) VALUES ({placeholders}) RETURNING id'
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(sql, *[data[k] for k in keys])
            return row["id"] if row else None

    async def update(self, table_name: str, field: str, value, data: Dict[str, Any]) -> bool:
        tbl, fld = _ident(table_name), _ident(field)
        keys = list(data.keys())
        for k in keys: _ident(k)
        set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(keys))
        sql = f'UPDATE {tbl} SET {set_clause} WHERE {fld} = ${len(keys)+1}'
        params = [data[k] for k in keys] + [value]
        async with get_pool().acquire() as conn:
            await conn.execute(sql, *params)
        return True

    async def delete(self, table_name: str, field: str, value) -> bool:
        tbl, fld = _ident(table_name), _ident(field)
        sql = f'UPDATE {tbl} SET is_deleted = TRUE WHERE {fld} = $1'
        async with get_pool().acquire() as conn:
            await conn.execute(sql, value)
        return True

    async def execute(self, sql: str, *args) -> str:
        async with get_pool().acquire() as conn:
            result = await conn.execute(sql, *args)
            return result

    async def bulk_create(self, table_name: str, data: List[Dict[str, Any]]) -> List[int]:
        tbl = _ident(table_name)
        if not data:
            return []

        keys = list(data[0].keys())
        for k in keys: 
            _ident(k)  # validar columnas
        cols = ", ".join(keys)

        # Generar placeholders para cada fila
        values = []
        placeholders_list = []
        for row_idx, item in enumerate(data):
            start = row_idx * len(keys)
            placeholders = [f"${start + i + 1}" for i in range(len(keys))]
            placeholders_list.append(f"({', '.join(placeholders)})")
            values.extend(item[k] for k in keys)

        placeholders_sql = ", ".join(placeholders_list)
        sql = f"INSERT INTO {tbl} ({cols}) VALUES {placeholders_sql} RETURNING id"

        async with get_pool().acquire() as conn:
            rows = await conn.fetch(sql, *values)
            return [row["id"] for row in rows] if rows else []
        
    async def fetch(self, sql: str, *args) -> List[Dict[str, Any]]:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(row) for row in rows]
    
    async def bulk_upsert(self, table_name: str, data: List[Dict[str, Any]]) -> List[int]:
        """
        Inserta o actualiza múltiples filas en la tabla especificada.
        Si existe conflicto en `source_id`, actualiza los valores.
        Retorna los IDs afectados.
        """
        if not data:
            return []

        tbl = _ident(table_name)
        keys = list(data[0].keys())
        for k in keys:
            _ident(k)  # valida columnas
        cols = ", ".join(keys)

        values = []
        placeholders_list = []
        for row_idx, item in enumerate(data):
            start = row_idx * len(keys)
            placeholders = [f"${start + i + 1}" for i in range(len(keys))]
            placeholders_list.append(f"({', '.join(placeholders)})")
            values.extend(item[k] for k in keys)

        placeholders_sql = ", ".join(placeholders_list)

        # Construir la parte del UPDATE, excluyendo el source_id
        update_set = ", ".join(
            [f"{col} = EXCLUDED.{col}" for col in keys if col != "source_id"]
        )
        update_set += ", updated_at = NOW()"

        sql = f"""
        INSERT INTO {tbl} ({cols})
        VALUES {placeholders_sql}
        ON CONFLICT (source_id)
        DO UPDATE SET {update_set}
        RETURNING id;
        """

        async with get_pool().acquire() as conn:
            rows = await conn.fetch(sql, *values)
            return [row["id"] for row in rows] if rows else []
