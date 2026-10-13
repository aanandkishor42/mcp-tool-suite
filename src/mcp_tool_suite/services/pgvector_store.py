"""Postgres + pgvector backed ``VectorStore`` (optional, feature-flagged).

Enabled with ``VECTOR_STORE=pgvector`` plus ``PGVECTOR_DSN``; requires the
``pgvector`` extra (``pip install "mcp-tool-suite[pgvector]"``). Every collection
lives in a single table keyed by ``(collection, id)`` and results are ranked with
pgvector's cosine distance (``<=>``), so scores match ``InMemoryVectorStore``.
"""

from __future__ import annotations

import re
from typing import Sequence

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.types.json import Jsonb

from mcp_tool_suite.services.vectorstore import Hit

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PgVectorStore:
    """Vector store backed by a Postgres table with a pgvector column."""

    def __init__(self, dsn: str, *, dimension: int, table: str = "mcp_vectors") -> None:
        if not _IDENT.match(table):
            raise ValueError(f"invalid table name: {table!r}")
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dsn = dsn
        self._dimension = dimension
        self._table = table
        self._index = f"{table}_embedding_idx"
        self._ensure_schema()

    # ---- schema -----------------------------------------------------------
    def _ensure_schema(self) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            installed = conn.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            if not installed:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(conn)
            conn.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {tbl} ("
                    "collection text NOT NULL, "
                    "id text NOT NULL, "
                    "text text NOT NULL, "
                    "metadata jsonb NOT NULL, "
                    "embedding vector({dim}) NOT NULL, "
                    "PRIMARY KEY (collection, id))"
                ).format(tbl=sql.Identifier(self._table), dim=sql.Literal(self._dimension))
            )
            try:
                conn.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS {idx} ON {tbl} "
                        "USING hnsw (embedding vector_cosine_ops)"
                    ).format(idx=sql.Identifier(self._index), tbl=sql.Identifier(self._table))
                )
            except psycopg.Error:
                # HNSW needs pgvector >= 0.5; without it a sequential scan still works.
                pass

    # ---- writes -----------------------------------------------------------
    def add(
        self,
        collection: str,
        *,
        ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, object]] | None = None,
    ) -> None:
        if not (len(ids) == len(vectors) == len(texts)):
            raise ValueError("ids, vectors and texts must be the same length")
        metas = metadatas or [{}] * len(ids)
        rows = [
            (collection, str(doc_id), text, Jsonb(meta or {}), Vector(list(vec)))
            for doc_id, text, vec, meta in zip(ids, texts, vectors, metas)
        ]
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.executemany(
                    sql.SQL(
                        "INSERT INTO {tbl} (collection, id, text, metadata, embedding) "
                        "VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT (collection, id) DO UPDATE SET "
                        "text = EXCLUDED.text, metadata = EXCLUDED.metadata, "
                        "embedding = EXCLUDED.embedding"
                    ).format(tbl=sql.Identifier(self._table)),
                    rows,
                )

    # ---- reads ------------------------------------------------------------
    def search(
        self, collection: str, query_vector: Sequence[float], *, top_k: int = 4
    ) -> list[Hit]:
        query = Vector(list(query_vector))
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            register_vector(conn)
            rows = conn.execute(
                sql.SQL(
                    "SELECT id, text, metadata, 1 - (embedding <=> %s) AS score "
                    "FROM {tbl} WHERE collection = %s "
                    "ORDER BY embedding <=> %s LIMIT %s"
                ).format(tbl=sql.Identifier(self._table)),
                (query, collection, query, max(1, top_k)),
            ).fetchall()
        return [
            Hit(id=row[0], text=row[1], score=float(row[3]), metadata=dict(row[2] or {}))
            for row in rows
        ]

    def has_collection(self, collection: str) -> bool:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            return bool(
                conn.execute(
                    sql.SQL("SELECT EXISTS (SELECT 1 FROM {tbl} WHERE collection = %s)").format(
                        tbl=sql.Identifier(self._table)
                    ),
                    (collection,),
                ).fetchone()[0]
            )

    def count(self, collection: str) -> int:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            return int(
                conn.execute(
                    sql.SQL("SELECT count(*) FROM {tbl} WHERE collection = %s").format(
                        tbl=sql.Identifier(self._table)
                    ),
                    (collection,),
                ).fetchone()[0]
            )

    def collections(self) -> list[str]:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            rows = conn.execute(
                sql.SQL("SELECT DISTINCT collection FROM {tbl} ORDER BY collection").format(
                    tbl=sql.Identifier(self._table)
                )
            ).fetchall()
        return [row[0] for row in rows]

    # ---- maintenance ------------------------------------------------------
    def drop_collection(self, collection: str) -> None:
        """Delete every row for *collection* (handy for tests / reindexing)."""
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DELETE FROM {tbl} WHERE collection = %s").format(
                    tbl=sql.Identifier(self._table)
                ),
                (collection,),
            )
