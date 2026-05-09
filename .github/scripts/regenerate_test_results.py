#!/usr/bin/env python3
"""Bulk-ingest PageIndex results from PDFs into Postgres."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pageindex.page_index import page_index_main
from pageindex.postgres_store import upsert_pageindex_document
from pageindex.utils import ConfigLoader


def regenerate_pdf(pdf_path, model=None):
    opt = ConfigLoader().load(
        {
            "model": model,
            "if_add_node_id": "yes",
            "if_add_node_summary": "yes",
            "if_add_doc_description": "yes",
            "if_add_node_text": "yes",
        }
    )
    result = page_index_main(str(pdf_path), opt)

    doc_description = ""
    if isinstance(result, dict):
        doc_description = str(result.get("doc_description", "")).strip()
    if not doc_description:
        raise ValueError(f"Generated result is missing doc_description: {pdf_path.name}")

    return upsert_pageindex_document(
        source_path=pdf_path,
        source_type="pdf",
        result=result,
    )


def main():
    parser = argparse.ArgumentParser(description="Bulk-ingest PDFs into the Postgres-backed PageIndex catalog")
    parser.add_argument("--pdf_dir", type=str, default="tests/pdfs", help="Directory containing input PDFs")
    parser.add_argument("--pattern", type=str, default="*.pdf", help="Glob pattern for matching PDFs")
    parser.add_argument("--model", type=str, default=None, help="Override the default model")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.exists():
        raise FileNotFoundError(f"PDF directory not found: {pdf_dir}")
    if not pdf_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {pdf_dir}")

    pdf_paths = sorted(pdf_dir.glob(args.pattern))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDFs matching {args.pattern} were found in: {pdf_dir}")

    print(f"PDF count: {len(pdf_paths)}")
    print(f"Input directory: {pdf_dir}")

    for index, pdf_path in enumerate(pdf_paths, 1):
        print(f"\n[{index}/{len(pdf_paths)}] Processing {pdf_path.name}")
        document = regenerate_pdf(pdf_path, model=args.model)
        print(f"Stored document_id={document.document_id} source_path={document.source_path}")

    print("\n" + "=" * 60)
    print(f"Completed: success={len(pdf_paths)} failed=0")
    print("=" * 60)


if __name__ == "__main__":
    main()
