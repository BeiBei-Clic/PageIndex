#!/usr/bin/env python3
"""Ingest Swiss legal data (federal laws + court decisions) into PageIndex PostgreSQL.

Each law code (OR, ZGB, StPO, ...) becomes one document whose tree is a flat
list of article nodes.  Each BGE volume-section (BGE 137 IV, ...) becomes one
document whose tree is a flat list of consideration nodes.

Node summaries are generated per-node using async LLM calls, same pattern as
pageindex/utils.py:generate_node_summary.

Usage:
    python scripts/ingest_legal_data.py [--laws data/laws_de.csv] [--courts data/court_considerations.csv]
"""
import argparse
import asyncio
import csv
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

from pageindex.postgres_store import upsert_pageindex_document

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Config ───────────────────────────────────────────────────────────────────

SUMMARY_TOKEN_THRESHOLD = 200  # short texts use original text as summary
MAX_CONCURRENT_SUMMARIES = 20


# ── Helpers ──────────────────────────────────────────────────────────────────

def _law_code(citation: str) -> str:
    parts = citation.strip().split()
    return parts[-1] if parts else ""


def _bge_volume_section(citation: str) -> str:
    m = re.match(r"(BGE \d+ [IV]+)", citation)
    return m.group(1) if m else ""


# ── Summary generation (same pattern as pageindex/utils.py) ──────────────────

async def _generate_node_summary(node, llm, semaphore):
    """Generate summary for a single node. Short texts use original text directly."""
    text = node.get("text", "") or ""
    if len(text) / 4 < SUMMARY_TOKEN_THRESHOLD:
        return text

    prompt = f"""You are given a part of a document, your task is to generate a description of the partial document about what are main points covered in the partial document.

    Partial Document Text: {text}

    Directly return the description, do not include any other text.
    """
    async with semaphore:
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        return resp.content


async def _generate_node_summaries(nodes, llm):
    """Generate summaries for all nodes in parallel with bounded concurrency."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUMMARIES)
    tasks = [_generate_node_summary(n, llm, semaphore) for n in nodes]
    summaries = await asyncio.gather(*tasks)
    for node, summary in zip(nodes, summaries):
        node["summary"] = summary


# ── Ingestion (unified for laws and courts) ─────────────────────────────────

async def _ingest_grouped(csv_path: str, llm, key_extractor, uri_prefix: str) -> int:
    """Read CSV, group by key_extractor, generate summaries, upsert to DB."""
    groups: dict[str, list[dict]] = defaultdict(list)

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = key_extractor(row["citation"])
            if not key:
                continue
            groups[key].append(row)

    total_docs = 0
    for key, rows in groups.items():
        name = rows[0].get("title", key) if "title" in rows[0] else key
        nodes = [
            {"node_id": str(i).zfill(4), "title": r["citation"], "text": r.get("text", "")}
            for i, r in enumerate(rows, 1)
        ]

        print(f"  [{total_docs+1}/{len(groups)}] {key}: {len(nodes)} entries, generating summaries...")
        await _generate_node_summaries(nodes, llm)

        tree = {
            "doc_name": key,
            "doc_description": f"{key} – {name} ({len(nodes)} entries)",
            "structure": nodes,
        }
        upsert_pageindex_document(f"legal://{uri_prefix}/{key}", "md", tree)
        total_docs += 1

    return total_docs


# ── Main ─────────────────────────────────────────────────────────────────────

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
        total += await _ingest_grouped(args.laws, llm, _law_code, "laws")
    else:
        print(f"Warning: {args.laws} not found, skipping laws.")

    if Path(args.courts).exists():
        print(f"\n=== Ingesting court decisions from {args.courts} ===")
        total += await _ingest_grouped(args.courts, llm, _bge_volume_section, "courts")
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
