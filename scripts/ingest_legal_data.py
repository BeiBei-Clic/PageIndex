#!/usr/bin/env python3
"""Ingest Swiss legal data (federal laws + court decisions) into PageIndex PostgreSQL.

Each row in the CSV becomes one document with a single-node tree.

Usage:
    python scripts/ingest_legal_data.py [--laws data/laws_de.csv] [--courts data/court_considerations.csv]
"""
import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

from pageindex.postgres_store import upsert_pageindex_document

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ── Summary generation ──────────────────────────────────────────────────────

async def _generate_node_summary(node, llm):
    prompt = f"""You are given a part of a document, your task is to generate a summary of the partial document about what are main points covered in the partial document.

    Partial Document Text: {node['text']}

    Directly return the summary, do not include any other text.
    """
    resp = await llm.ainvoke([HumanMessage(content=prompt)])
    return resp.content


# ── Ingestion ───────────────────────────────────────────────────────────────

async def _ingest_csv(csv_path: str, llm, uri_prefix: str) -> int:
    """Read CSV, each row becomes one document with summary, upsert to DB."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for i, row in enumerate(rows, 1):
        citation = row["citation"]
        text = row.get("text", "")
        print(f"  [{i}/{len(rows)}] {citation}, generating summary...")

        summary = await _generate_node_summary({"text": text}, llm)

        tree = {
            "doc_name": citation,
            "doc_description": summary,
            "structure": [{"node_id": "0001", "title": citation, "text": text, "summary": summary}],
        }
        upsert_pageindex_document(f"legal://{uri_prefix}/{citation}", "md", tree)

    return len(rows)


# ── Main ────────────────────────────────────────────────────────────────────

async def async_main(args) -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY not set")
    llm = init_chat_model(
        model=args.model,
        model_provider="openai",
        base_url="https://api.deepseek.com",
        api_key=api_key,
        temperature=0,
    )
    total = 0

    if Path(args.laws).exists():
        print(f"\n=== Ingesting laws from {args.laws} ===")
        total += await _ingest_csv(args.laws, llm, "laws")
    else:
        print(f"Warning: {args.laws} not found, skipping laws.")

    if Path(args.courts).exists():
        print(f"\n=== Ingesting court decisions from {args.courts} ===")
        total += await _ingest_csv(args.courts, llm, "courts")
    else:
        print(f"Warning: {args.courts} not found, skipping courts.")

    print(f"\nDone. {total} documents ingested.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest legal data into PageIndex")
    parser.add_argument("--laws", default="data/laws_de.csv", help="Path to laws CSV")
    parser.add_argument("--courts", default="data/court_considerations.csv", help="Path to court considerations CSV")
    parser.add_argument("--model", default="deepseek-v4-flash", help="LLM model for summaries")
    asyncio.run(async_main(parser.parse_args()))


if __name__ == "__main__":
    main()