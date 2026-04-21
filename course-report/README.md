# 课程报告资料

这个目录只保留当前软件测试课程报告实际需要的内容。

## 主要文件

- `main.tex`：课程报告主入口
- `main.pdf`：已生成的课程报告 PDF
- `slides/main.tex`：汇报 slides 源文件
- `slides/main.pdf`：已生成的 slides PDF
- `docs/`：正文与附录章节
- `fonts/`、`image/`、`figures/`：编译所需资源
- `homework.md`：作业要求

## 编译

在仓库根目录执行：

```bash
make -C course-report pdf
```

如果只在本目录内编译：

```bash
latexmk main -shell-escape -xelatex
```
