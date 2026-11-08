#!/usr/bin/env python3
"""plan.py - 把测绘结果分成四类，生成「施工图」plan.json（只出计划，不动文件）。

四分类：
    projects     用户长期工程
    chats        一次性对话工作区 / 交付物
    _runtime     应用自己会去找的：数据根、插件、缓存、运行时
    maintenance  备份、归档、诊断脚本、旧版本安装
    exception    不能动（安装目录、系统集成、被外部引用的固定路径）

用法：
    python plan.py --inventory inventory.json --root D:\\agents\\myapp
    python plan.py --inventory inventory.json --root D:\\agents\\myapp --out plan.json
    # 生成后先人工/模型审一遍，再交给 apply.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console  # noqa: E402  统一控制台编码，避免中文乱码
_console.setup()

BUCKET_HINTS = [
    ('maintenance', {'backup', 'backups', 'archive', 'archives', 'trash', 'logs', 'log',
                     'tmp', 'temp', 'old', 'legacy', 'staging', 'dump', 'snapshot',
                     '备份', '归档', '历史', '旧', '日志'}),
    ('_runtime', {'_runtime', 'runtime', 'binaries', 'bin', 'node', 'node_modules', 'python',
                  'plugins', 'plugin', 'extensions', 'cache', 'caches', 'profiles', 'profile',
                  'home', 'data', 'db', 'store', 'storage', 'models', 'tools', 'env', 'envs',
                  'venv', '.venv', 'toolchain', 'sdk', 'vendor', 'deps'}),
    ('chats', {'chats', 'chat', 'sessions', 'session', 'workspace', 'workspaces', 'conversations',
               'threads', 'deliverables', 'scratch', 'temp-chat', '对话', '交付'}),
    ('projects', {'projects', 'project', 'repos', 'repos', 'src', 'work', 'apps', '项目'}),
]

RED_HINTS = {'home', 'data', 'profiles', 'binaries', 'node_modules', 'db', 'store',
             'storage', '.venv', 'venv', 'toolchain', 'sessions', 'credentials', 'secrets'}

ARCHIVE_HINTS = BUCKET_HINTS[0][1]


def classify_name(name: str) -> str | None:
    n = name.lower()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}[-_.\d]*', n):
        return 'chats'          # 时间戳目录 = 对话工作区
    for bucket, words in BUCKET_HINTS:
        if n in words:
            return bucket
    for bucket, words in BUCKET_HINTS:
        if any(w in n for w in words if len(w) > 2):
            return bucket
    return None


def drive_of(p: str) -> str:
    return os.path.splitdrive(os.path.abspath(p))[0].upper()


def count_hint(cands, app, root):
    return sum(c['files'] for c in cands)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inventory', required=True)
    ap.add_argument('--root', required=True, help='统一骨架根目录，如 D:\\agents\\myapp')
    ap.add_argument('--expand', nargs='*', default=[],
                    help='把这些目录的子项逐个分类（应用把东西堆在一个根下时用这个）')
    ap.add_argument('--out', default='plan.json')
    args = ap.parse_args()

    inv = json.load(open(args.inventory, encoding='utf-8-sig'))
    root = os.path.abspath(args.root)
    root_drive = drive_of(root)
    expand = {os.path.normcase(os.path.abspath(p)) for p in args.expand}

    install_locs = {os.path.normcase(os.path.abspath(r['loc']))
                    for r in inv.get('registry', []) if r.get('loc')}
    # 只有"可执行文件落在该目录下"才算真的在用；命令行只是提到名字的不算
    proc_paths = [p['exe'] for p in inv.get('processes', [])
                  if p.get('exe') and p.get('match', 'exe') == 'exe']

    items, notes, skipped = [], [], []

    # 把候选展开成"待归类的单元"
    units = []
    for c in inv.get('candidates', []):
        p = os.path.abspath(c['path'])
        if os.path.normcase(p) in expand and os.path.isdir(p):
            for child in sorted(os.listdir(p)):
                cp = os.path.join(p, child)
                if os.path.isdir(cp):
                    units.append({'path': cp, 'files': None, 'bytes': None, 'capped': False,
                                  'top': [], 'configs': [], 'databases': [],
                                  'parent': p})
        else:
            units.append(dict(c, parent=None))

    for c in units:
        src = os.path.abspath(c['path'])
        name = os.path.basename(src.rstrip('\\/'))

        # 已在新根下 -> 跳过
        if os.path.normcase(src).startswith(os.path.normcase(root) + os.sep):
            skipped.append((src, '已在目标根内'))
            continue

        # 安装目录 -> 例外
        if os.path.normcase(src) in install_locs:
            items.append({'src': src, 'dst': None, 'bucket': 'exception',
                          'reason': '注册表卸载项指向此目录，移动会破坏卸载/更新',
                          'risk': 'red', 'method': 'keep', 'requires_stop': False})
            continue

        in_use = any(os.path.normcase(p).startswith(os.path.normcase(src) + os.sep) for p in proc_paths)

        bucket = classify_name(name)
        reason = '按目录名归类'
        if bucket is None:
            if c.get('top') and any(os.path.exists(os.path.join(src, m))
                                    for m in ('README.md', '.git', 'package.json', 'pyproject.toml', 'Cargo.toml')):
                bucket, reason = 'projects', '含 README/.git/工程清单，判为项目'
            elif c.get('databases'):
                bucket, reason = '_runtime', '含 SQLite，判为应用数据'
            else:
                bucket, reason = '_runtime', '未识别，保守放入运行时（需人工确认）'
                notes.append(f'{src}: 未能明确归类，建议人工确认')

        n = name.lower()
        if bucket == '_runtime' and (n in RED_HINTS or in_use):
            risk = 'red'
        elif bucket in ('maintenance',) and not in_use:
            risk = 'green'
        else:
            risk = 'yellow'
        if in_use:
            risk = 'red'

        # 目录名与分类同名（如 projects/）-> 不能整体搬进同名目录，改为并入其子项
        same_as_bucket = (n.rstrip('s') == bucket.rstrip('s')) or (n == bucket)
        if same_as_bucket:
            try:
                children = sorted(os.listdir(src))
            except OSError:
                children = []
            if not children:
                skipped.append((src, '与骨架同名且为空'))
                continue
            for child in children:
                cs = os.path.join(src, child)
                if not os.path.isdir(cs):
                    continue
                items.append({
                    'src': cs,
                    'dst': os.path.join(root, bucket, child),
                    'bucket': bucket,
                    'reason': f'并入同名骨架目录 {bucket}',
                    'risk': risk,
                    'method': 'rename' if drive_of(cs) == root_drive else 'copy+junction',
                    'requires_stop': risk == 'red',
                    'files': None, 'bytes': None, 'capped': False,
                    'in_use_by_process': in_use,
                    'has_sqlite': False, 'configs': [],
                })
            notes.append(f'{src}: 与骨架同名，已改为把 {len(children)} 个子项并入 {root}\\{bucket}')
            continue

        dst = os.path.join(root, bucket, name)
        method = 'rename' if drive_of(src) == root_drive else 'copy+junction'
        if risk == 'red':
            requires_stop = True
        else:
            requires_stop = False

        items.append({
            'src': src,
            'dst': dst,
            'bucket': bucket,
            'reason': reason,
            'risk': risk,
            'method': method,
            'requires_stop': requires_stop,
            'files': c.get('files'),
            'bytes': c.get('bytes'),
            'capped': c.get('capped'),
            'in_use_by_process': in_use,
            'has_sqlite': bool(c.get('databases')),
            'configs': (c.get('configs') or [])[:8],
        })

    # 目标重名检查
    seen = {}
    for it in items:
        if it['method'] == 'keep':
            continue
        key = os.path.normcase(it['dst'])
        if key in seen:
            it['dst'] = it['dst'] + '_2'
            notes.append(f'目标重名，已改名为 {it["dst"]}')
        seen[os.path.normcase(it['dst'])] = it['src']

    order = {'green': 0, 'yellow': 1, 'red': 2}
    items.sort(key=lambda x: (order.get(x['risk'], 9), x['src']))

    plan = {
        'version': 1,
        'app': inv.get('app'),
        'root': root,
        'generated': datetime.now().isoformat(timespec='seconds'),
        'skeleton': ['projects', 'chats', '_runtime', 'maintenance'],
        'items': items,
        'skipped': [{'src': s, 'why': w} for s, w in skipped],
        'notes': notes,
        'summary': {
            'total': len(items),
            'by_bucket': {b: sum(1 for i in items if i['bucket'] == b)
                          for b in ('projects', 'chats', '_runtime', 'maintenance', 'exception')},
            'by_risk': {r: sum(1 for i in items if i['risk'] == r)
                        for r in ('green', 'yellow', 'red')},
            'bytes': sum(i.get('bytes') or 0 for i in items),
        },
    }
    _console.ensure_parent(args.out)
    with open(args.out, 'w', encoding='utf-8-sig') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    s = plan['summary']
    out = []
    out.append(f'== 计划：{plan["app"]} -> {root} ==')
    out.append(f'共 {s["total"]} 项，合计 {s["bytes"] / 1024 / 1024:.1f} MB')
    out.append('  分类: ' + '  '.join(f'{k}={v}' for k, v in s['by_bucket'].items()))
    out.append('  风险: ' + '  '.join(f'{k}={v}' for k, v in s['by_risk'].items()))
    out.append('')
    for it in items:
        dst = it['dst'] or '(原位保留)'
        out.append(f'  [{it["risk"]:<6}] {it["bucket"]:<11} {it["method"]:<14} {it["src"]}')
        out.append(f'           -> {dst}')
        if it['in_use_by_process']:
            out.append('           [!] 有进程正在使用，必须停机')
    if notes:
        out.append('')
        out.append('需要人工确认：')
        for n in notes:
            out.append('  - ' + n)
    out.append('')
    out.append(f'已写出 {args.out}。审完再执行：python apply.py --plan {args.out} --dry-run')

    for line in out:
        print(line)
    _console.write_report(os.path.splitext(args.out)[0] + '.txt', '\n'.join(out))


if __name__ == '__main__':
    main()
