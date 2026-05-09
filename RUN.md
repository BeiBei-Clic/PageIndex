### 1. 环境准备

创建并激活虚拟环境，安装项目依赖。

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. 启动 PostgreSQL

用 Docker 启动 PostgreSQL 数据库，并设置连接字符串环境变量。

```bash
docker run -d -p 5432:5432 -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_DB=pageindex postgres

export PAGEINDEX_POSTGRES_DSN="postgresql://user:password@localhost:5432/pageindex"
```

### 3. 解析 PDF 并构建索引

对 PDF 文件进行目录提取和页码索引，结果写入数据库。

```bash
# 解析单个 PDF
python ./run_pageindex.py --pdf_path ./tests/pdfs/main.pdf

# 批量解析目录下所有 PDF（10 个并发）
python ./run_pageindex.py --pdf_path ./tests/pdfs --max-workers 10

# 解析多个指定 PDF
python ./run_pageindex.py --pdf_path ./tests/pdfs/main.pdf ./tests/pdfs/ocr_test.pdf --max-workers 10
```

### 4. 查看已入库的文档

列出数据库中已解析的文档及其索引信息。

```bash
# 列出所有文档
python ./list_pageindex_docs.py

# 查询指定文档
python ./list_pageindex_docs.py --doc-name main.pdf
```

### 5. 树搜索检索

基于已构建的索引进行层级化搜索，返回相关内容。

```bash
python -c "from pageindex.search import run_tree_search; result = run_tree_search(query='这份文档主要讲了什么？', model='deepseek/deepseek-chat', doc_top_k=3, max_concurrency=3, max_context=8000); print(result.answer); print(result.selected_entries); print(result.relevant_nodes[:3])"
```

### 6. Agent 问答

使用 Agent 对文档进行自然语言问答。

```bash
python ./agent_pageindex.py --query "端到端符号回归是指哪一篇参考文献，作者是谁" --doc-top-k 3 --max-concurrency 3 --verbose
```
