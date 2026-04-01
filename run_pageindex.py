import argparse
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pageindex.page_index import page_index_main
from pageindex.page_index_md import md_to_tree
from pageindex.postgres_store import upsert_pageindex_document
from pageindex.utils import ConfigLoader


def ingest_pdf(pdf_path: str, user_opt: dict) -> object:
    opt = ConfigLoader().load(user_opt)
    toc_with_page_number = page_index_main(pdf_path, opt)
    return upsert_pageindex_document(
        source_path=pdf_path,
        source_type='pdf',
        result=toc_with_page_number,
    )


def main() -> None:
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Process PDF or Markdown document and generate structure')
    parser.add_argument('--pdf_path', nargs='+', type=str, help='Path to PDF file(s) or directories containing PDFs')
    parser.add_argument('--md_path', type=str, help='Path to the Markdown file')

    parser.add_argument('--model', type=str, default=None, help='Model to use (overrides config.yaml)')

    parser.add_argument('--toc-check-pages', type=int, default=None,
                      help='Number of pages to check for table of contents (PDF only)')
    parser.add_argument('--max-pages-per-node', type=int, default=None,
                      help='Maximum number of pages per node (PDF only)')
    parser.add_argument('--max-tokens-per-node', type=int, default=None,
                      help='Maximum number of tokens per node (PDF only)')

    parser.add_argument('--if-add-node-id', type=str, default=None,
                      help='Whether to add node id to the node')
    parser.add_argument('--if-add-node-summary', type=str, default=None,
                      help='Whether to add summary to the node')
    parser.add_argument('--if-add-doc-description', type=str, default=None,
                      help='Whether to add doc description to the doc')
    parser.add_argument('--if-add-node-text', type=str, default=None,
                      help='Whether to add text to the node')
                      
    # Markdown specific arguments
    parser.add_argument('--if-thinning', type=str, default='no',
                      help='Whether to apply tree thinning for markdown (markdown only)')
    parser.add_argument('--thinning-threshold', type=int, default=5000,
                      help='Minimum token threshold for thinning (markdown only)')
    parser.add_argument('--summary-token-threshold', type=int, default=200,
                      help='Token threshold for generating summaries (markdown only)')
    parser.add_argument('--max-workers', type=int, default=None,
                      help='Maximum number of PDFs processed in parallel when using directory or multiple PDF inputs')
    args = parser.parse_args()
    
    # Validate that exactly one file type is specified
    if not args.pdf_path and not args.md_path:
        raise ValueError("Either --pdf_path or --md_path must be specified")
    if args.pdf_path and args.md_path:
        raise ValueError("Only one of --pdf_path or --md_path can be specified")
    if args.max_workers is not None and args.max_workers <= 0:
        raise ValueError("--max-workers must be greater than 0")
    
    if args.pdf_path:
        pdf_paths = []
        for raw_pdf_path in args.pdf_path:
            input_path = Path(raw_pdf_path).expanduser()
            if not input_path.exists():
                raise ValueError(f"PDF path not found: {raw_pdf_path}")
            if input_path.is_file():
                if input_path.suffix.lower() != '.pdf':
                    raise ValueError(f"PDF file must have .pdf extension: {raw_pdf_path}")
                pdf_paths.append(str(input_path.resolve()))
                continue
            if input_path.is_dir():
                directory_pdf_paths = sorted(
                    str(pdf_file.resolve())
                    for pdf_file in input_path.iterdir()
                    if pdf_file.is_file() and pdf_file.suffix.lower() == '.pdf'
                )
                if not directory_pdf_paths:
                    raise ValueError(f"No PDF files found in directory: {raw_pdf_path}")
                pdf_paths.extend(directory_pdf_paths)
                continue
            raise ValueError(f"Unsupported PDF path: {raw_pdf_path}")

        deduplicated_pdf_paths = []
        seen_pdf_paths = set()
        for pdf_path in pdf_paths:
            if pdf_path in seen_pdf_paths:
                continue
            seen_pdf_paths.add(pdf_path)
            deduplicated_pdf_paths.append(pdf_path)

        user_opt = {
            'model': args.model,
            'toc_check_page_num': args.toc_check_pages,
            'max_page_num_each_node': args.max_pages_per_node,
            'max_token_num_each_node': args.max_tokens_per_node,
            'if_add_node_id': args.if_add_node_id,
            'if_add_node_summary': args.if_add_node_summary,
            'if_add_doc_description': args.if_add_doc_description,
            'if_add_node_text': args.if_add_node_text,
        }
        resolved_user_opt = {k: v for k, v in user_opt.items() if v is not None}

        if len(deduplicated_pdf_paths) == 1:
            document = ingest_pdf(deduplicated_pdf_paths[0], resolved_user_opt)
            print("Parsing done, saving to Postgres...")
            print(f"document_id: {document.document_id}")
            print(f"doc_name: {document.doc_name}")
            print(f"source_path: {document.source_path}")
        else:
            max_workers = args.max_workers
            if max_workers is None:
                max_workers = min(len(deduplicated_pdf_paths), max(1, min(4, os.cpu_count() or 1)))

            print(f"PDF count: {len(deduplicated_pdf_paths)}")
            print(f"Parallel workers: {max_workers}")

            completed_count = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_pdf_path = {
                    executor.submit(ingest_pdf, pdf_path, resolved_user_opt): pdf_path
                    for pdf_path in deduplicated_pdf_paths
                }
                for future in as_completed(future_to_pdf_path):
                    document = future.result()
                    completed_count += 1
                    print(f"[{completed_count}/{len(deduplicated_pdf_paths)}] Stored document_id={document.document_id}")
                    print(f"doc_name: {document.doc_name}")
                    print(f"source_path: {document.source_path}")

            print("Parsing done, saving to Postgres...")
            print(f"Completed: success={completed_count} failed=0")
            
    elif args.md_path:
        # Validate Markdown file
        if not args.md_path.lower().endswith(('.md', '.markdown')):
            raise ValueError("Markdown file must have .md or .markdown extension")
        if not os.path.isfile(args.md_path):
            raise ValueError(f"Markdown file not found: {args.md_path}")
            
        # Process markdown file
        print('Processing markdown file...')
        
        # Process the markdown
        # Use ConfigLoader to get consistent defaults (matching PDF behavior)
        config_loader = ConfigLoader()
        
        # Create options dict with user args
        user_opt = {
            'model': args.model,
            'if_add_node_summary': args.if_add_node_summary,
            'if_add_doc_description': args.if_add_doc_description,
            'if_add_node_text': args.if_add_node_text,
            'if_add_node_id': args.if_add_node_id
        }
        
        # Load config with defaults from config.yaml
        opt = config_loader.load(user_opt)
        
        toc_with_page_number = asyncio.run(md_to_tree(
            md_path=args.md_path,
            if_thinning=args.if_thinning.lower() == 'yes',
            min_token_threshold=args.thinning_threshold,
            if_add_node_summary=opt.if_add_node_summary,
            summary_token_threshold=args.summary_token_threshold,
            model=opt.model,
            if_add_doc_description=opt.if_add_doc_description,
            if_add_node_text=opt.if_add_node_text,
            if_add_node_id=opt.if_add_node_id
        ))
        
        document = upsert_pageindex_document(
            source_path=args.md_path,
            source_type='md',
            result=toc_with_page_number,
        )
        print("Parsing done, saving to Postgres...")
        print(f"document_id: {document.document_id}")
        print(f"doc_name: {document.doc_name}")
        print(f"source_path: {document.source_path}")


if __name__ == "__main__":
    main()
