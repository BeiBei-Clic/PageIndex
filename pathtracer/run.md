# PathTracer 使用方法

追踪 Python 程序执行路径，生成覆盖率报告。

## 基本用法

```bash
python -m pathtracer.cli <program.py>                    # 追踪并显示报告
python -m pathtracer.cli <program.py> --quiet          # 静默模式
python -m pathtracer.cli <program.py> -o report.txt    # 保存到文件
```

## 传递参数

```bash
python -m pathtracer.cli <program.py> -- --arg1 value1    # 用 -- 分隔参数
```

## 输出格式
```bash
python -m pathtracer.cli <program.py> --format html -o coverage.html
python -m pathtracer.cli <program.py> --format json -o coverage.json
```

## 运行演示
```bash
python pathtracer/demo.py
```
