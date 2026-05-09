#!/usr/bin/env python3
"""Batch legal citation retrieval using PageIndex vectorless RAG + LangChain.

Reads queries from a CSV (val / test), retrieves relevant citations via
three-step LLM reasoning (doc selection → tree search → citation extraction),
and writes output in competition format.

Usage:
    python scripts/run_legal_retrieval.py --input data/val.csv --output predictions.csv
    python scripts/run_legal_retrieval.py --input data/test.csv
"""
import argparse
import csv
import os
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
MAX_NODE_DISPLAY = 4000
MAX_CONTEXT_LENGTH = 80000

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

TREE_SEARCH_PROMPT = """You are searching within a legal document for relevant articles/considerations.

Question: {query}
Document: {doc_name} – {doc_description}

Node titles (node_id: title | summary):
{node_list_text}

Return a JSON object with:
- "thinking": brief reasoning
- "node_list": list of node_id strings for relevant nodes

Return ONLY the JSON, nothing else."""

CITATION_EXTRACTION_PROMPT = """Based on the following retrieved legal articles and court considerations, extract ALL legal citations that are relevant to the question.

Question: {query}

Retrieved content:
{context}

Return a JSON object with:
- "thinking": brief reasoning
- "citations": list of citation strings in standard Swiss format

Standard format examples:
- Law articles: "Art. 221 Abs. 1 StPO", "Art. 308 Abs. 1 ZGB", "Art. 8 Abs. 1 ATSG"
- Court decisions: "BGE 137 IV 122 E. 6.2", "1B_210/2023 E. 4.1"

Include citations explicitly mentioned in the question AND any additional relevant ones found in the retrieved content.

Return ONLY the JSON, nothing else."""


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Legal citation retrieval")
    parser.add_argument("--input", required=True, help="Input CSV (val.csv or test.csv)")
    parser.add_argument("--output", default=None, help="Output CSV path (default: predictions_<input_name>.csv)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model name")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries")
    args = parser.parse_args()

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
    llm = make_llm(args.model)

    def ask(prompt: str) -> dict:
        """Call LLM and parse JSON response."""
        resp = llm.invoke([HumanMessage(content=prompt)]).content
        return extract_json(resp)

    # Pre-build catalog text for doc selection
    catalog_text = "\n".join(
        f"{d.document_id} | {d.doc_name} | {d.doc_description[:120]}"
        for d in catalog
    )

    # Process queries
    results = []
    for i, row in enumerate(queries):
        qid = row["query_id"]
        query = row["query"]
        print(f"\n[{i+1}/{len(queries)}] {qid}: {query[:80]}...")

        # Step 1: Select relevant documents
        doc_ids = ask(DOC_SELECTION_PROMPT.format(
            query=query, catalog_text=catalog_text, top_k=MAX_DOC_SELECTION,
        )).get("doc_list", [])
        if not doc_ids:
            results.append({"query_id": qid, "predicted_citations": ""})
            continue

        # Load full documents
        loaded = get_documents_by_ids(doc_ids)
        loaded_map = {d.document_id: d for d in loaded}

        # Step 2: Tree search within each selected document
        all_context_parts = []
        for doc_id in doc_ids:
            doc = loaded_map.get(doc_id)
            if not doc:
                continue

            # Build node list (title + summary)
            tree = doc.tree_json
            structure = tree.get("structure", tree) if isinstance(tree, dict) else tree
            nodes = structure if isinstance(structure, list) else [structure]
            node_lines = [
                f"{n.get('node_id', '')}: {n.get('title', '')} | {n.get('summary', '')}"
                for n in nodes
            ]
            node_list_text = "\n".join(node_lines[:MAX_NODE_DISPLAY])
            if len(node_lines) > MAX_NODE_DISPLAY:
                node_list_text += f"\n... ({len(node_lines) - MAX_NODE_DISPLAY} more nodes)"

            node_ids = ask(TREE_SEARCH_PROMPT.format(
                query=query,
                doc_name=doc.doc_name,
                doc_description=doc.doc_description,
                node_list_text=node_list_text,
            )).get("node_list", [])
            if not node_ids:
                continue

            # Collect text of selected nodes
            node_map = {n.get("node_id"): n for n in nodes}
            for nid in node_ids:
                node = node_map.get(nid)
                if node and node.get("text"):
                    all_context_parts.append(f"[{node.get('title', '')}]\n{node['text']}")

        # Step 3: Extract citations
        if not all_context_parts:
            predicted = ";".join(
                loaded_map[did].doc_name for did in doc_ids if did in loaded_map
            )
        else:
            context = "\n\n---\n\n".join(all_context_parts)
            if len(context) > MAX_CONTEXT_LENGTH:
                context = context[:MAX_CONTEXT_LENGTH] + "\n...(truncated)"
            citations = ask(CITATION_EXTRACTION_PROMPT.format(
                query=query, context=context,
            )).get("citations", [])
            predicted = ";".join(citations)

        results.append({"query_id": qid, "predicted_citations": predicted})
        print(f"  → {predicted[:120]}{'...' if len(predicted) > 120 else ''}")

    # Write output
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["query_id", "predicted_citations"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
