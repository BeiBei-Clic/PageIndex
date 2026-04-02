# PathTracer 使用方法

追踪 Python 程序的执行路径，并生成覆盖率报告。

## 基本用法

```bash
.\.venv\Scripts\python.exe -m pathtracer.cli agent_pageindex.py --query "端到端符号回归是指哪一篇参考文献，作者是谁" --doc-top-k 3 --max-concurrency 3 --verbose

.\.venv\Scripts\python.exe -m pathtracer.cli <program.py> --quiet

.\.venv\Scripts\python.exe -m pathtracer.cli <program.py> -o report.txt
```

## 传递目标脚本参数

```bash
.\.venv\Scripts\python.exe -m pathtracer.cli <program.py> -- --arg1 value1
.\.venv\Scripts\python.exe -m pathtracer.cli <program.py> --arg1 value1
```

`pathtracer.cli` 现在同时支持两种参数传递方式：

- 使用 `--` 显式分隔 PathTracer 自己的参数和目标脚本参数
- 直接把目标脚本参数写在 `<program.py>` 后面

如果目标脚本参数和 PathTracer 自己的参数重名，优先使用 `--` 分隔以避免歧义。

## 输出格式

```bash
.\.venv\Scripts\python.exe -m pathtracer.cli <program.py> --format html -o coverage.html
.\.venv\Scripts\python.exe -m pathtracer.cli <program.py> --format json -o coverage.json
```

## 运行演示

```bash
.\.venv\Scripts\python.exe pathtracer/demo.py
```
