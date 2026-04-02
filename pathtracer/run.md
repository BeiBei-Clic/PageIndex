# PathTracer 使用方法

## 基本用法

```bash
# 追踪程序并显示覆盖率报告
python -m pathtracer.cli <program.py>

# 静默模式（只显示报告，不显示程序输出）
python -m pathtracer.cli <program.py> --quiet

# 保存报告到文件
python -m pathtracer.cli <program.py> -o report.txt
```

## 输出格式

```bash
# 文本格式（默认）
python -m pathtracer.cli <program.py> --format text

# HTML 格式
python -m pathtracer.cli <program.py> --format html -o coverage.html

# JSON 格式
python -m pathtracer.cli <program.py> --format json -o coverage.json
```

## 运行演示

```bash
python pathtracer/demo.py
```
