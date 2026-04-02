# PathTracer 使用方法

## 埇用法

```bash
# 追踪程序并显示覆盖率报告
python -m pathtracer.cli <program.py>

# 静默模式（只显示报告，不显示程序输出)
python -m pathtracer.cli <program.py> --quiet

# 保存报告到文件
python -m pathtracer.cli <program.py> -o report.txt
```

## 传递参数给目标程序

```bash
# 使用 -- 分隔 pathtracer 参数和目标程序参数
python -m pathtracer.cli agent_pageindex.py -- --query "test query"
```

## 输出格式
```bash
# HTML 格式
python -m pathtracer.cli <program.py> --format html -o coverage.html

# JSON 格式
python -m pathtracer.cli <program.py> --format json -o coverage.json
```

## 运行演示
```bash
python pathtracer/demo.py
```
