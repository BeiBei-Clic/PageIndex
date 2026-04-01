import argparse
import json
from pathlib import Path

from pageindex.postgres_store import get_documents_by_ids, list_catalog_documents


def main() -> None:
    parser = argparse.ArgumentParser(description="List ingested PageIndex documents and inspect stored nodes")
    parser.add_argument("--doc-name", type=str, default=None, help="Document name to inspect")
    parser.add_argument("--document-id", type=str, default=None, help="Document ID to inspect")
    args = parser.parse_args()

    if args.doc_name and args.document_id:
        raise ValueError("Only one of --doc-name or --document-id can be specified")

    catalog_entries = list_catalog_documents()
    if not catalog_entries:
        print("No documents found in pageindex_documents.")
        return

    if not args.doc_name and not args.document_id:
        print(f"Document count: {len(catalog_entries)}")
        for index, entry in enumerate(catalog_entries, 1):
            print(f"\n[{index}] {entry.doc_name}")
            print(f"document_id: {entry.document_id}")
            print(f"source_path: {entry.source_path}")
            print(f"updated_at: {entry.updated_at}")
        return

    if args.document_id:
        documents = get_documents_by_ids([args.document_id])
        if not documents:
            raise ValueError(f"Document not found: {args.document_id}")
        document = documents[0]
    else:
        matched_entries = [
            entry
            for entry in catalog_entries
            if entry.doc_name.lower() == args.doc_name.lower()
            or Path(entry.source_path).name.lower() == args.doc_name.lower()
        ]
        if not matched_entries:
            raise ValueError(f"Document not found by name: {args.doc_name}")
        if len(matched_entries) > 1:
            print("Matched multiple documents:")
            for index, entry in enumerate(matched_entries, 1):
                print(f"\n[{index}] {entry.doc_name}")
                print(f"document_id: {entry.document_id}")
                print(f"source_path: {entry.source_path}")
            raise ValueError("Multiple documents matched. Use --document-id to select one document.")
        documents = get_documents_by_ids([matched_entries[0].document_id])
        if not documents:
            raise ValueError(f"Document metadata exists but stored tree is missing: {matched_entries[0].document_id}")
        document = documents[0]

    print(f"document_id: {document.document_id}")
    print(f"doc_name: {document.doc_name}")
    print(f"source_path: {document.source_path}")
    print(f"source_type: {document.source_type}")
    print(f"created_at: {document.created_at}")
    print(f"updated_at: {document.updated_at}")
    print(f"doc_description: {document.doc_description}")

    tree = document.tree_json
    structure = tree.get("structure", tree) if isinstance(tree, dict) else tree
    stack = []
    if isinstance(structure, list):
        for item in reversed(structure):
            stack.append((item, 0))
    elif isinstance(structure, dict):
        stack.append((structure, 0))
    else:
        raise TypeError("tree_json must be a dict or list")

    if not stack:
        print("\nNo nodes found in stored tree.")
        return

    node_count = 0
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, dict):
            continue

        node_count += 1
        children = node.get("nodes")
        node_payload = {
            "depth": depth,
            "children_count": len(children) if isinstance(children, list) else 0,
        }
        for key, value in node.items():
            if key == "nodes":
                continue
            node_payload[key] = value

        print("\n" + "=" * 80)
        print(json.dumps(node_payload, ensure_ascii=False, indent=2))

        if isinstance(children, list):
            for child in reversed(children):
                stack.append((child, depth + 1))

    print("\n" + "=" * 80)
    print(f"Total nodes: {node_count}")


if __name__ == "__main__":
    main()
