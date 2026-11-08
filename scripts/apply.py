#!/usr/bin/env python3
"""apply.py - 按 plan.json 执行迁移；带 dry-run、日志、断点与回滚。

原则：
  * 同盘用 rename（瞬时、原子、保 ACL）
  * 跨盘用 robocopy 复制 -> 校验 -> 删源 -> 建 junction
  * 校验不通过绝不删源
  * 每一步写进 journal.json，可整体回滚

用法：
    python apply.py --plan plan.json --dry-run          # 只检查，不动文件
    python apply.py --plan plan.json                    # 执行（逐项确认）
    python apply.py --plan plan.json --yes              # 不逐项确认
    python apply.py --plan plan.json --only maintenance # 只做某一类
    python apply.py --journal journal.json --rollback   # 回滚
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console  # noqa: E402  统一控制台编码，避免中文乱码
_console.setup()
from datetime import datetime

ROBOCOPY = ['robocopy']
RC_OK = 8          # >=8 视为失败


def now():
    return datetime.now().isoformat(timespec='seconds')


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


def ps(cmd):
    r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def make_junction(link, target):
    rc, out = ps(f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' | Out-Null")
    if rc != 0 or not os.path.exists(link):
        raise RuntimeError(f'创建联接失败: {link} -> {target}\n{out}')
    return True


def remove_dir(path):
    """删除目录或联接（联接只删链接本身）。"""
    if is_link(path):
        os.rmdir(path)          # RemoveDirectoryW 对 reparse point 只删链接
    else:
        shutil.rmtree(path)


def do_rename(item, journal):
    src, dst = item['src'], item['dst']
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.rename(src, dst)
    journal.append({'op': 'rename', 'src': src, 'dst': dst, 'time': now()})
    return f'rename {src} -> {dst}'


def do_copy_junction(item, journal):
    src, dst = item['src'], item['dst']
    before_files, before_bytes = measure(src)
    os.makedirs(dst, exist_ok=True)
    args = ROBOCOPY + [src, dst, '/E', '/COPY:DAT', '/DCOPY:T', '/R:2', '/W:2',
                       '/NFL', '/NDL', '/NJH', '/NJS', '/NP']
    r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode >= RC_OK:
        raise RuntimeError(f'robocopy 失败（{r.returncode}），未删除源:\n{(r.stdout or "")[-800:]}')

    after_files, after_bytes = measure(dst)
    if after_files < before_files or after_bytes < before_bytes:
        raise RuntimeError(f'校验失败：源 {before_files}/{before_bytes} 目标 {after_files}/{after_bytes}，未删除源')

    remove_dir(src)
    make_junction(src, dst)
    journal.append({'op': 'copy+junction', 'src': src, 'dst': dst,
                    'files': before_files, 'bytes': before_bytes, 'time': now()})
    return f'copy+junction {src} -> {dst}（{before_files} 文件 / {before_bytes/1024/1024:.1f} MB）'


def rollback(journal_path):
    data = json.load(open(journal_path, encoding='utf-8-sig'))
    ops = list(reversed(data.get('ops', [])))
    print(f'回滚 {len(ops)} 步（倒序）')
    for op in ops:
        src, dst = op['src'], op['dst']
        try:
            if op['op'] == 'rename':
                if os.path.exists(dst) and not os.path.exists(src):
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    os.rename(dst, src)
                    print(f'  还原 rename: {dst} -> {src}')
                else:
                    print(f'  跳过（状态不符）: {src}')
            elif op['op'] == 'copy+junction':
                if is_link(src):
                    os.rmdir(src)
                if os.path.isdir(dst):
                    os.makedirs(src, exist_ok=True)
                    subprocess.run(ROBOCOPY + [dst, src, '/E', '/COPY:DAT', '/DCOPY:T',
                                               '/R:2', '/W:2', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'],
                                   capture_output=True)
                    f, b = measure(src)
                    print(f'  回拷 {f} 文件 -> {src}')
                    if f >= op.get('files', 0):
                        shutil.rmtree(dst, ignore_errors=True)
                        print(f'  已删除 D 盘副本 {dst}')
                    else:
                        print(f'  [!] 回拷文件数不足，保留 {dst}')
        except Exception as e:
            print(f'  回滚失败 {op.get("op")} {src}: {e}')
    print('回滚结束。请手动复核后续引用（环境变量/数据库/链接）。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan')
    ap.add_argument('--journal')
    ap.add_argument('--rollback', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--only', default=None, help='只处理某个分类')
    ap.add_argument('--force', action='store_true', help='即使有进程在用也继续（危险）')
    ap.add_argument('--journal-out', default='journal.json')
    args = ap.parse_args()

    if args.rollback:
        if not args.journal:
            sys.exit('回滚需要 --journal journal.json')
        rollback(args.journal)
        return

    if not args.plan:
        sys.exit('需要 --plan plan.json')

    plan = json.load(open(args.plan, encoding='utf-8-sig'))
    items = [i for i in plan['items'] if i['method'] != 'keep']
    if args.only:
        items = [i for i in items if i['bucket'] == args.only]
    for b in plan.get('skeleton', []):
        os.makedirs(os.path.join(plan['root'], b), exist_ok=True)

    journal = {'app': plan.get('app'), 'root': plan['root'], 'ops': []}

    print(f'== {"演练" if args.dry_run else "执行"}：{plan.get("app")} ==')
    done = 0
    for it in items:
        src, dst = it['src'], it['dst']
        tag = f'[{it["risk"]}/{it["bucket"]}]'
        if not os.path.exists(src):
            print(f'{tag} 跳过（源不存在）: {src}')
            continue
        if os.path.exists(dst):
            print(f'{tag} 跳过（目标已存在）: {dst}')
            continue
        if it['risk'] == 'red' and it.get('in_use_by_process') and not args.force:
            print(f'{tag} 拒绝：有进程正在使用，请先退出应用（或 --force）')
            print(f'        查占用：powershell -File scripts/who-locks.ps1 "{src}"')
            continue

        if args.dry_run:
            print(f'{tag} 将执行 {it["method"]}: {src} -> {dst}')
            done += 1
            continue

        if not args.yes:
            ans = input(f'{tag} {it["method"]} {src} -> {dst}\n    继续？[y/N/a=全部] ')
            if ans.lower().startswith('a'):
                args.yes = True
            elif not ans.lower().startswith('y'):
                print('    跳过')
                continue

        try:
            msg = do_rename(it, journal['ops']) if it['method'] == 'rename' else do_copy_junction(it, journal['ops'])
            print(f'{tag} {msg}')
            done += 1
            _console.ensure_parent(args.journal_out)
            with open(args.journal_out, 'w', encoding='utf-8-sig') as f:
                json.dump(journal, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f'{tag} 失败: {e}')
            print('已中止。修复后重跑同一条命令（已完成的项会因目标存在而跳过）。')
            _console.ensure_parent(args.journal_out)
            with open(args.journal_out, 'w', encoding='utf-8-sig') as f:
                json.dump(journal, f, ensure_ascii=False, indent=2)
            sys.exit(1)

    print(f'\n完成 {done} 项。日志：{args.journal_out}')
    if not args.dry_run:
        print('下一步：')
        print('  1) 重绑引用（环境变量/配置/数据库/链接/任务），见 references/rebinding.md')
        print('  2) 验收：python verify.py --plan plan.json')


if __name__ == '__main__':
    main()
