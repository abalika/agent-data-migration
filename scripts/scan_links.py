#!/usr/bin/env python3
"""scan_links.py — 扫出根目录下所有悬空的符号链接/目录联接。

为什么要单独扫：搬目录后 `node_modules` 里的 `file:` 依赖会变成死链，
插件就加载不了；而 Python 的 os.path.islink() 对 Windows junction 返回 False，
用错判据会得到"0 个链接"的假结论。

用法：
    python scan_links.py --root D:\\agents\\myapp
    python scan_links.py --root D:\\agents\\myapp --fix --map old=new
"""
from __future__ import annotations

import argparse
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console  # noqa: E402
_console.setup()

PRUNE = {'.git', '__pycache__', 'cache', 'Cache', 'GPUCache', 'Code Cache',
         'logs', 'traces', 'sessions'}


def is_link(p: str) -> bool:
    try:
        return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def readlink(p: str) -> str:
    try:
        return os.readlink(p)
    except OSError:
        return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--json', default=None, help='把结果写成 JSON')
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    bad = []

    for dp, dn, fn in os.walk(root):
        # node_modules 只查两层：直接子项 + @scope/子项
        if os.path.basename(dp) == 'node_modules':
            for name in list(os.listdir(dp)):
                q = os.path.join(dp, name)
                if name.startswith('@') and os.path.isdir(q) and not is_link(q):
                    for sub in os.listdir(q):
                        r = os.path.join(q, sub)
                        if is_link(r) and not os.path.exists(r):
                            bad.append((r, readlink(r)))
                elif is_link(q) and not os.path.exists(q):
                    bad.append((q, readlink(q)))
            dn[:] = []
            continue

        dn[:] = [d for d in dn if d not in PRUNE]
        for name in list(dn) + fn:
            p = os.path.join(dp, name)
            if is_link(p) and not os.path.exists(p):
                bad.append((p, readlink(p)))

    print(f'扫描根目录: {root}')
    print(f'悬空链接 {len(bad)} 个')
    for p, t in bad:
        print(f'  {p}')
        print(f'      原指向: {t}')

    if args.json:
        import json
        _console.ensure_parent(args.json)
        with open(args.json, 'w', encoding='utf-8-sig') as f:
            json.dump([{'link': p, 'target': t} for p, t in bad], f, ensure_ascii=False, indent=2)
        print(f'已写出 {args.json}')

    print()
    print('修复思路：')
    print("  New-Item -ItemType Junction -Path '<link>' -Target '<新位置>'")
    print('  链接已悬空导致删除失败时：')
    print("  [System.IO.Directory]::Delete('<link>', $false)")
    sys.exit(0 if not bad else 1)


if __name__ == '__main__':
    main()
