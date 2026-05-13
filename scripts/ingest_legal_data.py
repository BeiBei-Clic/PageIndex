#!/usr/bin/env python3
"""Ingest Swiss legal data (federal laws + court decisions) into PageIndex PostgreSQL.

Each row in the CSV becomes one document with a single-node tree.

Usage:
    python scripts/ingest_legal_data.py [--laws data/laws_de.csv] [--courts data/court_considerations.csv]
"""
import argparse
import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

from pageindex.postgres_store import list_catalog_documents, upsert_pageindex_document

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ── Summary generation ──────────────────────────────────────────────────────

MAX_CONCURRENT = 20

PROMPT_TEMPLATE = """You are given a part of a document, your task is to generate a summary of the partial document about what are main points covered in the partial document.

    Partial Document Text: {text}

    Directly return the summary, do not include any other text.
    """


async def _generate_summary(idx, text, llm, semaphore):
    async with semaphore:
        print(f"  [{idx}] generating...", flush=True)
        resp = await llm.ainvoke([HumanMessage(content=PROMPT_TEMPLATE.format(text=text))])
        return resp.content


# ── Ingestion ───────────────────────────────────────────────────────────────

async def _ingest_csv(csv_path: str, llm, uri_prefix: str, limit=None) -> int:
    """Read CSV, each row becomes one document with summary, upsert to DB."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]

    # Query existing source_paths to skip already-ingested docs
    existing_doc_names = {d.doc_name for d in list_catalog_documents()}

    todo = []
    for r in rows:
        if r["citation"] in existing_doc_names:
            print(f"  Skip (already exists): {r['citation']}", flush=True)
        else:
            todo.append(r)

    if not todo:
        print(f"  All {len(rows)} entries already ingested, nothing to do.")
        return 0

    print(f"  {len(rows)} total, {len(todo)} new, {len(rows) - len(todo)} skipped")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [_generate_summary(i, r.get("text", ""), llm, semaphore) for i, r in enumerate(todo, 1)]
    print(f"  Generating summaries for {len(todo)} entries (concurrency={MAX_CONCURRENT})...")
    summaries = await asyncio.gather(*tasks)

    for row, summary in zip(todo, summaries):
        citation = row["citation"]
        text = row.get("text", "")
        tree = {
            "doc_name": citation,
            "doc_description": summary,
            "structure": [{"node_id": "0001", "title": citation, "text": text, "summary": summary}],
        }
        upsert_pageindex_document(f"legal://{uri_prefix}/{citation}", "md", tree)

    return len(todo)


# ── Main ────────────────────────────────────────────────────────────────────

async def async_main(args) -> None:
    llm = init_chat_model(f"deepseek:{args.model}", temperature=0)
    total = 0

    if Path(args.laws).exists():
        print(f"\n=== Ingesting laws from {args.laws} ===")
        total += await _ingest_csv(args.laws, llm, "laws", args.limit)
    else:
        print(f"Warning: {args.laws} not found, skipping laws.")

    if Path(args.courts).exists():
        print(f"\n=== Ingesting court decisions from {args.courts} ===")
        total += await _ingest_csv(args.courts, llm, "courts", args.limit)
    else:
        print(f"Warning: {args.courts} not found, skipping courts.")

    print(f"\nDone. {total} documents ingested.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest legal data into PageIndex")
    parser.add_argument("--laws", default="data/laws_de.csv", help="Path to laws CSV")
    parser.add_argument("--courts", default="data/court_considerations.csv", help="Path to court considerations CSV")
    parser.add_argument("--model", default="deepseek-v4-flash", help="LLM model for summaries")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows to ingest")
    asyncio.run(async_main(parser.parse_args()))


if __name__ == "__main__":
    main()