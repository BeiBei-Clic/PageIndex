#!/usr/bin/env python3
"""Batch legal citation retrieval using PageIndex vectorless RAG + LangChain.

Reads queries from a CSV (val / test), retrieves relevant citations via
two-step LLM reasoning (doc selection → citation refinement),
and writes output in competition format.

Usage:
    python scripts/run_legal_retrieval.py --input data/val.csv --output predictions.csv
    python scripts/run_legal_retrieval.py --input data/test.csv
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

from pageindex.postgres_store import (
    get_documents_by_ids,
    list_catalog_documents,
)
from pageindex.utils import extract_json

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Config ───────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "deepseek-v4-flash"
MAX_DOC_SELECTION = 20
MAX_CONCURRENT = 5

# ── Prompts ──────────────────────────────────────────────────────────────────

DOC_SELECTION_PROMPT = """You are a Swiss legal citation retrieval expert.

Given a legal question, select the most relevant law codes and BGE court decision collections from the catalog below.

Question: {query}

Document catalog (doc_id | name | description):
{catalog_text}

Return a JSON object with:
- "thinking": brief reasoning
- "doc_list": list of doc_id strings, ordered by relevance, max {top_k}

Return ONLY the JSON, nothing else."""

CITATION_REFINEMENT_PROMPT = """You are a Swiss legal citation retrieval expert.

Given a legal question and a set of candidate legal texts, select ONLY the citations that are truly relevant to the question.

Question: {query}

Candidate texts:
{candidate_texts}

Return a JSON object with:
- "thinking": brief reasoning
- "citations": list of citation strings that are truly relevant to the question

Return ONLY the JSON, nothing else."""


# ── Main ────────────────────────────────────────────────────────────────────

async def _process_query(idx, row, llm, catalog_text, semaphore):
    """Process a single query: doc selection → citation refinement."""
    qid = row["query_id"]
    query = row["query"]
    print(f"\n[{idx}] {qid}: {query[:80]}...", flush=True)

    async with semaphore:
        # Step 1: Select relevant documents
        resp = await llm.ainvoke([HumanMessage(content=DOC_SELECTION_PROMPT.format(
            query=query, catalog_text=catalog_text, top_k=MAX_DOC_SELECTION,
        ))])
        doc_ids = extract_json(resp.content).get("doc_list", [])
        if not doc_ids:
            print(f"  [{idx}] → (no docs selected)", flush=True)
            return {"query_id": qid, "predicted_citations": ""}

        # Step 2: Load full documents and refine citations
        loaded = get_documents_by_ids(doc_ids)
        loaded_map = {d.document_id: d for d in loaded}

        candidate_texts = ""
        for did in doc_ids:
            doc = loaded_map.get(did)
            if not doc:
                continue
            tree = doc.tree_json
            structure = tree.get("structure", tree) if isinstance(tree, dict) else tree
            nodes = structure if isinstance(structure, list) else [structure]
            text = nodes[0].get("text", "") if nodes else ""
            candidate_texts += f"\n---\n[{doc.doc_name}]\n{text}"

        resp = await llm.ainvoke([HumanMessage(content=CITATION_REFINEMENT_PROMPT.format(
            query=query, candidate_texts=candidate_texts,
        ))])
        citations = extract_json(resp.content).get("citations", [])
        predicted = ";".join(citations)

        print(f"  [{idx}] → {predicted[:120]}{'...' if len(predicted) > 120 else ''}", flush=True)
        return {"query_id": qid, "predicted_citations": predicted}


async def async_main(args) -> None:
    # Output path
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.parent / f"predictions_{input_path.stem}.csv"

    # Load catalog
    print("Loading document catalog...")
    catalog = list_catalog_documents()
    print(f"  {len(catalog)} documents in catalog")

    # Load queries
    with open(args.input, newline="", encoding="utf-8") as f:
        queries = list(csv.DictReader(f))
    if args.limit:
        queries = queries[:args.limit]
    print(f"  {len(queries)} queries to process")

    # Init LLM
    llm = init_chat_model(f"deepseek:{args.model}", temperature=0)

    # Pre-build catalog text for doc selection
    catalog_text = "\n".join(
        f"{d.document_id} | {d.doc_name} | {d.doc_description[:120]}"
        for d in catalog
    )

    # Process queries concurrently
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [
        _process_query(i, row, llm, catalog_text, semaphore)
        for i, row in enumerate(queries, 1)
    ]
    print(f"\nProcessing {len(queries)} queries (concurrency={MAX_CONCURRENT})...")
    results = await asyncio.gather(*tasks)

    # Write output
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["query_id", "predicted_citations"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults written to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Legal citation retrieval")
    parser.add_argument("--input", required=True, help="Input CSV (val.csv or test.csv)")
    parser.add_argument("--output", default=None, help="Output CSV path (default: predictions_<input_name>.csv)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model name")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries")
    asyncio.run(async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
