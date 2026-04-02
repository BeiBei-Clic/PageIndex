import importlib.util
import sys

from .page_index import *
from .page_index_md import md_to_tree

langchain_spec = None
if "langchain" in sys.modules:
    langchain_spec = sys.modules["langchain"]
else:
    try:
        langchain_spec = importlib.util.find_spec("langchain")
    except ValueError:
        langchain_spec = None

if langchain_spec is not None:
    from .search import DEFAULT_DOC_TOP_K, DEFAULT_MAX_CONCURRENCY, run_tree_search, search_pageindex
