#!/usr/bin/env python3
"""
批量重新生成 tests/pdfs 下的 PageIndex 结果，默认输出到 tests/results。
会强制开启 doc_description 生成，并在写入前校验结果中存在非空描述。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pageindex.page_index import page_index_main
from pageindex.utils import ConfigLoader


def build_options(model=None):
    user_opt = {
        'model': model,
        'if_add_node_id': 'yes',
        'if_add_node_summary': 'yes',
        'if_add_doc_description': 'yes',
        'if_add_node_text': 'no',
    }
    return ConfigLoader().load({k: v for k, v in user_opt.items() if v is not None})


def regenerate_pdf(pdf_path, output_dir, model=None):
    opt = build_options(model=model)
    result = page_index_main(str(pdf_path), opt)

    doc_description = ""
    if isinstance(result, dict):
        doc_description = str(result.get('doc_description', '')).strip()
    if not doc_description:
        raise ValueError(f"生成结果缺少 doc_description: {pdf_path.name}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{pdf_path.stem}_structure.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return output_path


def main():
    parser = argparse.ArgumentParser(description='批量重建测试用 PageIndex 结果，并确保包含 doc_description')
    parser.add_argument('--pdf_dir', type=str, default='tests/pdfs',
                        help='待处理 PDF 目录')
    parser.add_argument('--output_dir', type=str, default='tests/results',
                        help='结果输出目录')
    parser.add_argument('--pattern', type=str, default='*.pdf',
                        help='PDF 文件匹配模式')
    parser.add_argument('--model', type=str, default=None,
                        help='覆盖默认模型')
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    output_dir = Path(args.output_dir)
    if not pdf_dir.exists():
        raise FileNotFoundError(f"未找到 PDF 目录: {pdf_dir}")
    if not pdf_dir.is_dir():
        raise NotADirectoryError(f"不是目录: {pdf_dir}")

    pdf_paths = sorted(pdf_dir.glob(args.pattern))
    if not pdf_paths:
        raise FileNotFoundError(f"目录中未找到匹配 {args.pattern} 的 PDF: {pdf_dir}")

    print(f"📚 待处理 PDF 数量: {len(pdf_paths)}")
    print(f"📥 输入目录: {pdf_dir}")
    print(f"📤 输出目录: {output_dir}")

    failures = []
    for index, pdf_path in enumerate(pdf_paths, 1):
        print(f"\n[{index}/{len(pdf_paths)}] 处理 {pdf_path.name}")
        try:
            output_path = regenerate_pdf(pdf_path, output_dir, model=args.model)
            print(f"✓ 已生成: {output_path}")
        except Exception as exc:
            failures.append((pdf_path.name, str(exc)))
            print(f"✗ 失败: {pdf_path.name}")
            print(f"  原因: {exc}")

    print("\n" + "=" * 60)
    print(f"完成: 成功 {len(pdf_paths) - len(failures)}，失败 {len(failures)}")
    if failures:
        print("失败列表:")
        for name, error in failures:
            print(f"- {name}: {error}")
        raise SystemExit(1)
    print("=" * 60)


if __name__ == '__main__':
    main()
