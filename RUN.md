### 1. 环境准备

创建并激活虚拟环境，安装项目依赖。

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

应用 langchain-deepseek 思考模式修复（详见 [docs/langchain-deepseek-thinking-fix.md](docs/langchain-deepseek-thinking-fix.md)）：

```bash
python scripts/patch_langchain_deepseek.py
```

### 2. 启动 PostgreSQL

用 Docker 启动 PostgreSQL 数据库，并设置连接字符串环境变量。

```bash
docker run -d -p 5432:5432 -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_DB=pageindex postgres
```

设置连接字符串环境变量：

```bash
# macOS / Linux
export PAGEINDEX_POSTGRES_DSN="postgresql://user:password@localhost:5432/pageindex"

# Windows PowerShell
$env:PAGEINDEX_POSTGRES_DSN = "postgresql://user:password@localhost:5432/pageindex"
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
python -c "from pageindex.search import run_tree_search; result = run_tree_search(query='这份文档主要讲了什么？', model='deepseek/deepseek-v4-flash', doc_top_k=3, max_concurrency=3, max_context=8000); print(result.answer); print(result.selected_entries); print(result.relevant_nodes[:3])"
```

### 6. Agent 问答

使用 Agent 对文档进行自然语言问答。

```bash
python ./agent_pageindex.py --query "端到端符号回归是指哪一篇参考文献，作者是谁" --doc-top-k 3 --max-concurrency 3 --verbose
```

### 7. 清空数据库

清空 `pageindex_documents` 表，用于重新入库。

```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); import psycopg; conn = psycopg.connect(os.environ['PAGEINDEX_POSTGRES_DSN']); conn.cursor().execute('TRUNCATE pageindex_documents'); conn.commit(); print('Done')"
```

### 8. 法条数据入库（Omnilex 竞赛）

将联邦法条和法院裁判数据解析入库，每个法律编（如 OR、ZGB、StPO）和每个 BGE 卷册作为一份文档。

```bash
# 法条 + 法院裁判一起入库
python scripts/ingest_legal_data.py

# 仅入库法条
python scripts/ingest_legal_data.py --courts /dev/null

#只入库前10条法条      
python scripts/ingest_legal_data.py --laws data/laws_de.csv --limit 10

# 指定自定义路径
python scripts/ingest_legal_data.py --laws data/laws_de.csv --courts data/court_considerations.csv
```

### 9. 批量法条检索（Omnilex 竞赛）

基于已入库的法条数据，对 val/test 集的查询进行三步检索（法律选择 → 法条搜索 → 引文提取），输出竞赛格式 CSV。

```bash
# 对 val 集检索
python scripts/run_legal_retrieval.py --input data/val.csv

# 对 test 集检索
python scripts/run_legal_retrieval.py --input data/test.csv --output submissions/test_submission.csv

# 限制前 2 条快速测试
python scripts/run_legal_retrieval.py --input data/val.csv --limit 2
```
