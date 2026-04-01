### 3. Run PageIndex on your PDF

```bash
$env:PAGEINDEX_POSTGRES_DSN="postgresql://user:password@localhost:5432/pageindex"
```

```bash
python .\run_pageindex.py --pdf_path .\tests\pdfs\main.pdf

python .\run_pageindex.py --pdf_path .\tests\pdfs --max-workers 10

python .\run_pageindex.py --pdf_path .\tests\pdfs\main.pdf .\tests\pdfs\ocr_test.pdf --max-workers 10
```

```bash
python .\list_pageindex_docs.py

python .\list_pageindex_docs.py --doc-name main.pdf
```

```bash
python -c "from pageindex.search import run_tree_search; result = run_tree_search(query='这份文档主要讲了什么？', model='deepseek/deepseek-chat', doc_top_k=3, max_concurrency=3, max_context=8000); print(result.answer); print(result.selected_entries); print(result.relevant_nodes[:3])"
```

```bash
python .\agent_pageindex.py --query "端到端符号回归是指哪一篇参考文献，作者是谁" --doc-top-k 3 --max-concurrency 3 --verbose
```
