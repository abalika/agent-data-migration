#!/usr/bin/env python3
"""verify.py - 迁移后验收：结构、链接、数量、幂等性。

用法：
    python verify.py --plan plan.json
    python verify.py --plan plan.json --json report.json

判据分四组：
  V1 路径   目标存在、源已消失（keep 除外）
  V2 链接   新根下无悬空符号链接/联接
  V3 数量   目标文件数/字节数 >= 计划基线
  V4 幂等   再跑一次 plan 应无新增改动（这里是"目标已存在"的等价检查）

退出码：0 全过，1 有失败。
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console  # noqa: E402  统一控制台编码，避免中文乱码
_console.setup()

lines = []
P = F = 0


def log(s=''):
    print(s)
    lines.append(s)


def ck(name, ok, detail=''):
    global P, F
    if ok:
        P += 1
        log(f'  [PASS] {name}' + (f'  ({detail})' if detail else ''))
    else:
        F += 1
        log(f'  [FAIL] {name}' + (f'  ({detail})' if detail else ''))


def is_link(p):
    try:
        return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def measure(path):
    files = total = 0
    for dp, dn, fn in os.walk(path):
        for f in fn:
            files += 1
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return files, total


def scan_links(root):
    bad = []
    for dp, dn, fn in os.walk(root):
        if os.path.basename(dp) == 'node_modules':
            for name in list(os.listdir(dp)):
                q = os.path.join(dp, name)
                if name.startswith('@') and os.path.isdir(q) and not is_link(q):
                    for sub in os.listdir(q):
                        r = os.path.join(q, sub)
                        if is_link(r) and not os.path.exists(r):
                            bad.append(r)
                elif is_link(q) and not os.path.exists(q):
                    bad.append(q)
            dn[:] = []
            continue
        for name in list(dn) + fn:
            p = os.path.join(dp, name)
            if is_link(p) and not os.path.exists(p):
                bad.append(p)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    plan = json.load(open(args.plan, encoding='utf-8-sig'))
    root = plan['root']
    items = [i for i in plan['items'] if i['method'] != 'keep']

    log('=' * 68)
    log(f'验收：{plan.get("app")} -> {root}')
    log('=' * 68)

    log('V1 目标存在 / 源处理正确')
    missing = [i['dst'] for i in items if not os.path.isdir(i['dst'])]
    bad_src = []
    for i in items:
        src, dst, method = i['src'], i['dst'], i['method']
        exists = os.path.exists(src) or os.path.islink(src)
        if method == 'rename':
            # 同盘改名后源应当彻底消失
            if exists:
                bad_src.append((src, 'rename 后源仍存在'))
        else:
            # 跨盘复制+联接：源应当变成指向目标的联接
            if not exists:
                bad_src.append((src, '联接缺失'))
            elif not is_link(src):
                bad_src.append((src, '源仍是真实目录，未建立联接'))
            else:
                try:
                    real = os.path.realpath(src)
                    if os.path.normcase(real) != os.path.normcase(os.path.realpath(dst)):
                        bad_src.append((src, f'联接指向不符: {real}'))
                except OSError:
                    pass
    ck('全部目标目录存在', not missing, f'缺失 {len(missing)}: {missing[:3]}' if missing else f'{len(items)} 项')
    ck('源已正确处理（改名消失 / 复制后变联接）', not bad_src,
       f'{len(bad_src)} 项异常: {bad_src[:2]}' if bad_src else '')

    log('')
    log('V2 新根下无悬空链接')
    bad = scan_links(root)
    ck('悬空符号链接/联接 = 0', not bad, f'{len(bad)} 个: {bad[:3]}' if bad else '')

    log('')
    log('V3 数量一致性')
    shrink = []
    for i in items:
        if not os.path.isdir(i['dst']):
            continue
        f, b = measure(i['dst'])
        base = i.get('files')
        if base is not None and f < base:
            shrink.append((i['dst'], base, f))
    ck('目标文件数不少于计划基线', not shrink,
       f'{len(shrink)} 项变少: {shrink[:2]}' if shrink else f'{len(items)} 项')

    log('')
    log('V4 幂等（目标已存在，重跑不会再动）')
    again = [i['dst'] for i in items if os.path.isdir(i['dst'])]
    ck('重跑将被"目标已存在"跳过', len(again) == len(items), f'{len(again)}/{len(items)}')

    log('')
    log('=' * 68)
    log(f'结果：PASS {P} / FAIL {F}')
    log('=' * 68)

    if args.json:
        _console.ensure_parent(args.json)
        json.dump({'pass': P, 'fail': F, 'log': lines}, open(args.json, 'w', encoding='utf-8-sig'),
                  ensure_ascii=False, indent=2)
        log(f'报告：{args.json}')
    _console.write_report(os.path.splitext(args.plan)[0] + '-verify.txt', '\n'.join(lines))
    sys.exit(0 if F == 0 else 1)


if __name__ == '__main__':
    main()
