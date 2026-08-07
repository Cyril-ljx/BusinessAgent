"""Safely import certificate images from a DOCX bundle.

This script reuses the same importer as the API. It appends new certificate rows
and never deletes existing data.

Example:
    python scripts/import_certificates.py "D:/path/商务文件-汇总.docx" --company-id demo-company
    python scripts/import_certificates.py "D:/path/共享证书.docx" --scope shared
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import certificate images from a heading-structured DOCX bundle.")
    parser.add_argument("docx", type=Path, help="证书合集 DOCX 路径")
    parser.add_argument("--company-id", default="demo-company", help="公司 ID；scope=company 时写入该公司素材库")
    parser.add_argument("--scope", choices=("company", "shared"), default="company", help="写入公司素材库或共享素材库")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出导入结果")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    docx_path = args.docx.expanduser().resolve()
    if not docx_path.exists():
        print(f"文件不存在: {docx_path}", file=sys.stderr)
        return 2
    if docx_path.suffix.lower() != ".docx":
        print("只支持 .docx 证书合集", file=sys.stderr)
        return 2

    try:
        from tender_agent.knowledge.certificate_importer import import_certificate_images_from_docx
    except ModuleNotFoundError as exc:
        if exc.name == 'docx':
            print('当前 Python 环境缺少 python-docx，请先安装：python -m pip install python-docx', file=sys.stderr)
            return 3
        raise

    result = import_certificate_images_from_docx(docx_path, company_id=args.company_id, scope=args.scope)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("证书合集导入完成")
        print(f"  文件: {docx_path}")
        print(f"  范围: {args.scope}")
        print(f"  公司: {args.company_id if args.scope == 'company' else 'shared/all'}")
        print(f"  识别标题: {result.get('heading_count', 0)}")
        print(f"  文档图片: {result.get('image_count', 0)}")
        print(f"  入库证书: {result.get('imported_count', 0)}")
        categories = result.get("categories") or []
        if categories:
            summary = "，".join(f"{item.get('name')} {item.get('count')}" for item in categories[:8])
            print(f"  类别统计: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
