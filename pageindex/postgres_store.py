from __future__ import annotations

import importlib
import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

POSTGRES_DSN_ENV = "PAGEINDEX_POSTGRES_DSN"
TABLE_NAME = "pageindex_documents"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    document_id UUID PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN ('pdf', 'md')),
    doc_name TEXT NOT NULL,
    doc_description TEXT NOT NULL,
    tree_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

UPSERT_DOCUMENT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    document_id,
    source_path,
    source_type,
    doc_name,
    doc_description,
    tree_json,
    created_at,
    updated_at
)
VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
ON CONFLICT (source_path) DO UPDATE SET
    source_type = EXCLUDED.source_type,
    doc_name = EXCLUDED.doc_name,
    doc_description = EXCLUDED.doc_description,
    tree_json = EXCLUDED.tree_json,
    updated_at = NOW()
RETURNING
    document_id::text,
    source_path,
    source_type,
    doc_name,
    doc_description,
    tree_json,
    created_at,
    updated_at
"""

LIST_CATALOG_SQL = f"""
SELECT
    document_id::text,
    source_path,
    source_type,
    doc_name,
    doc_description,
    updated_at
FROM {TABLE_NAME}
ORDER BY source_path
"""

GET_DOCUMENTS_SQL = f"""
SELECT
    document_id::text,
    source_path,
    source_type,
    doc_name,
    doc_description,
    tree_json,
    created_at,
    updated_at
FROM {TABLE_NAME}
WHERE document_id::text = ANY(%s)
ORDER BY source_path
"""
if importlib.util.find_spec("psycopg") is None:
    psycopg = None
else:
    psycopg = importlib.import_module("psycopg")


@dataclass(slots=True)
class CatalogDocument:
    document_id: str
    source_path: str
    source_type: str
    doc_name: str
    doc_description: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StoredDocument:
    document_id: str
    source_path: str
    source_type: str
    doc_name: str
    doc_description: str
    tree_json: dict[str, Any] | list[Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
def get_postgres_dsn() -> str:
    dsn = os.getenv(POSTGRES_DSN_ENV, "").strip()
    if not dsn:
        raise ValueError(
            f"{POSTGRES_DSN_ENV} is not set. Configure a Postgres DSN before ingesting or searching documents."
        )
    return dsn


def _connect() -> Any:
    if psycopg is None:
        raise ModuleNotFoundError(
            "psycopg is required for Postgres-backed PageIndex search. Install dependencies from requirements.txt."
        )
    return psycopg.connect(get_postgres_dsn())


def _normalize_timestamp(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value).split()) if value else ""
def ensure_table_exists(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(CREATE_TABLE_SQL)


def _stored_document_from_row(row: tuple[Any, ...]) -> StoredDocument:
    return StoredDocument(
        document_id=str(row[0]),
        source_path=str(row[1]),
        source_type=str(row[2]),
        doc_name=str(row[3]),
        doc_description=str(row[4]),
        tree_json=row[5],
        created_at=_normalize_timestamp(row[6]),
        updated_at=_normalize_timestamp(row[7]),
    )


def upsert_pageindex_document(
    source_path: str | os.PathLike[str],
    source_type: str,
    result: dict[str, Any] | list[Any],
) -> StoredDocument:
    normalized_source_path = str(Path(source_path).expanduser().resolve())
    normalized_source_type = source_type.strip().lower()
    if normalized_source_type not in {"pdf", "md"}:
        raise ValueError(f"Unsupported source_type: {source_type}. Expected 'pdf' or 'md'.")

    if not isinstance(result, (dict, list)):
        raise TypeError("PageIndex result must be a JSON-serializable dict or list.")

    if isinstance(result, dict):
        doc_name = _normalize_text(result.get("doc_name")) or Path(normalized_source_path).name
        doc_description = _normalize_text(result.get("doc_description"))
    else:
        doc_name = Path(normalized_source_path).name
        doc_description = ""

    if not doc_description:
        raise ValueError(
            "PageIndex result is missing doc_description. Ingest requires doc_description for document selection."
        )

    tree_json = json.dumps(result, ensure_ascii=False)

    with _connect() as connection:
        ensure_table_exists(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                UPSERT_DOCUMENT_SQL,
                (
                    str(uuid4()),
                    normalized_source_path,
                    normalized_source_type,
                    doc_name,
                    doc_description,
                    tree_json,
                ),
            )
            row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Postgres upsert did not return a stored document row.")
    return _stored_document_from_row(row)


def list_catalog_documents() -> list[CatalogDocument]:
    with _connect() as connection:
        ensure_table_exists(connection)
        with connection.cursor() as cursor:
            cursor.execute(LIST_CATALOG_SQL)
            rows = cursor.fetchall() or []
    return [
        CatalogDocument(
            document_id=str(row[0]),
            source_path=str(row[1]),
            source_type=str(row[2]),
            doc_name=str(row[3]),
            doc_description=str(row[4]),
            updated_at=_normalize_timestamp(row[5]),
        )
        for row in rows
    ]


def get_documents_by_ids(document_ids: list[str]) -> list[StoredDocument]:
    if not document_ids:
        return []

    normalized_ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
    if not normalized_ids:
        return []

    with _connect() as connection:
        ensure_table_exists(connection)
        with connection.cursor() as cursor:
            cursor.execute(GET_DOCUMENTS_SQL, (normalized_ids,))
            rows = cursor.fetchall() or []
    return [_stored_document_from_row(row) for row in rows]


__all__ = [
    "POSTGRES_DSN_ENV",
    "TABLE_NAME",
    "CatalogDocument",
    "StoredDocument",
    "ensure_table_exists",
    "get_documents_by_ids",
    "get_postgres_dsn",
    "list_catalog_documents",
    "upsert_pageindex_document",
]
