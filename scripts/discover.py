#!/usr/bin/env python3
"""discover.py - 测绘某个应用在磁盘上的全部落点（只读，不改任何东西）。

设计目标是「先问应用，再看配置，最后扫盘」：
  1. 进程：应用此刻从哪些路径执行、命令行里带了哪些目录参数
  2. 环境变量：指向该应用的 HOME / DATA 类变量
  3. 注册表：卸载项里的 InstallLocation
  4. 常见位置：%APPDATA% / %LOCALAPPDATA% / %USERPROFILE% / 各盘根
  5. 配置与数据库：找 exe 目录和数据目录下的 .toml/.json/.yml 与 SQLite 文件

用法：
    python discover.py --app dsh
    python discover.py --app workbuddy --root D:\\agents\\workbuddy
    python discover.py --app myapp --paths "C:\\Users\\me\\AppData\\Roaming\\myapp" "D:\\myapp"

输出：
    inventory.json（机器可读）+ 终端摘要
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console  # noqa: E402  统一控制台编码，避免中文乱码
_console.setup()

MAX_FILES = 300_000          # 统计上限，超过就标 >=
CONFIG_EXT = {'.toml', '.json', '.yml', '.yaml', '.ini', '.cfg', '.conf', '.xml', '.properties'}


def sh(cmd: str) -> str:
    """跑 PowerShell，失败返回空串。"""
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', cmd],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
        return r.stdout or ''
    except Exception:
        return ''


def measure(path: str):
    """返回 (文件数, 字节数, 是否触顶)。"""
    files = 0
    total = 0
    capped = False
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            files += 1
                            total += e.stat(follow_symlinks=False).st_size
                            if files >= MAX_FILES:
                                return files, total, True
                    except OSError:
                        pass
        except OSError:
            pass
    return files, total, capped


def is_sqlite(path: str) -> bool:
    try:
        with open(path, 'rb') as f:
            return f.read(16) == b'SQLite format 3\x00'
    except OSError:
        return False


def probe_dir(path: str, app: str) -> dict:
    """探测一个目录：规模、顶层条目、配置与数据库线索。"""
    info = {
        'path': path,
        'exists': os.path.isdir(path),
        'is_link': False,
        'files': 0,
        'bytes': 0,
        'capped': False,
        'top': [],
        'configs': [],
        'databases': [],
    }
    if not info['exists']:
        return info
    try:
        info['is_link'] = bool(os.lstat(path).st_file_attributes & 0x400)
    except OSError:
        pass
    n, b, capped = measure(path)
    info.update(files=n, bytes=b, capped=capped)

    try:
        entries = sorted(os.listdir(path))[:40]
    except OSError:
        entries = []
    info['top'] = entries

    # 浅层扫配置与 sqlite（深度 2）
    base_depth = path.rstrip('\\/').count(os.sep)
    for dp, dn, fn in os.walk(path):
        if dp.count(os.sep) - base_depth >= 2:
            dn[:] = []
        dn[:] = [d for d in dn if d not in ('node_modules', '.git', '__pycache__')][:30]
        for f in fn[:200]:
            p = os.path.join(dp, f)
            ext = os.path.splitext(f)[1].lower()
            rel = os.path.relpath(p, path)
            if ext in CONFIG_EXT and len(info['configs']) < 60:
                info['configs'].append(rel)
            elif ext in ('.db', '.sqlite', '.sqlite3') and len(info['databases']) < 20:
                if is_sqlite(p):
                    info['databases'].append(rel)
    return info


SHELL_PROCS = {'python', 'python3', 'pythonw', 'pwsh', 'powershell', 'cmd', 'bash', 'sh',
               'node', 'wscript', 'cscript', 'conhost', 'wt', 'windowsterminal'}

# 系统目录一律不参与候选，防止误判
SYSTEM_BLOCKLIST = [os.environ.get('WINDIR', r'C:\Windows'),
                    os.environ.get('ProgramFiles', r'C:\Program Files'),
                    os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                    os.environ.get('ProgramData', r'C:\ProgramData')]


def name_matches(text: str, app: str) -> bool:
    """按词元匹配，不用子串。

    反例：app='capp' 时 'unsecapp.exe' 含 'capp' 子串，但那是 WMI 系统进程。
    这里按非字母数字切词，要求某个词元与 app 完全相等。
    """
    if not text:
        return False
    a = app.lower()
    for tok in re.split(r'[^a-z0-9]+', text.lower()):
        if tok and tok == a:
            return True
    return False


def is_system_path(p: str) -> bool:
    lp = os.path.normcase(os.path.abspath(p))
    for s in SYSTEM_BLOCKLIST:
        if s and lp.startswith(os.path.normcase(os.path.abspath(s))):
            return True
    return False


# 已知应用的识别特征：进程可执行文件路径关键字 + 数据目录候选
APP_SIGNATURES = {
    'dsh': {'words': ('deepseek harness', 'deepseekharnees', 'deepseekharness', 'dsh'),
            'dirs': ('~/.dsh',), 'env': ('DSH_HOME',)},
    'workbuddy': {'words': ('workbuddy',),
                  'dirs': ('~/.workbuddy',), 'env': ()},
    'codex': {'words': ('codex',),
              'dirs': ('~/.codex',), 'env': ()},
    'antigravity': {'words': ('antigravity',),
                    'dirs': ('~/.gemini',), 'env': ()},
    'claude': {'words': ('claude',),
               'dirs': ('~/.claude',), 'env': ()},
    'cursor': {'words': ('cursor',),
               'dirs': ('~/.cursor',), 'env': ()},
    'windsurf': {'words': ('windsurf',),
                 'dirs': ('~/.windsurf',), 'env': ()},
    'trae': {'words': ('trae',),
             'dirs': ('~/.trae',), 'env': ()},
    'cline': {'words': ('cline',),
              'dirs': ('~/.cline',), 'env': ()},
}

# agent 数据目录的通用特征（用于发现"没收录但很像"的目录）
AGENT_SUBDIRS = {'sessions', 'session', 'conversations', 'conversation', 'threads', 'chat',
                 'chats', 'projects', 'workspaces', 'workspace', 'skills', 'agents',
                 'memory', 'profiles', 'attachments', 'transcripts', 'prompts', 'tasks'}


def quick_agent_score(path: str, name: str) -> tuple:
    """浅层判分：这个目录像不像某个 agent 的数据目录。只看两层，保证速度。"""
    score, why = 0, []
    if name.startswith('.'):
        score += 2
        why.append('点目录')
    try:
        entries = os.listdir(path)
    except OSError:
        return 0, []
    low = {e.lower() for e in entries}
    hit = low & AGENT_SUBDIRS
    if hit:
        score += min(len(hit), 3)
        why.append('含 ' + '/'.join(sorted(hit)[:3]))
    # 顶层或一层里有数据库/配置
    db = cfg = 0
    for e in entries[:400]:
        p = os.path.join(path, e)
        el = e.lower()
        if el.endswith(('.db', '.sqlite', '.sqlite3')):
            db += 1
        elif el in ('config.json', 'settings.json', 'config.toml', 'package.json', '.env'):
            cfg += 1
        elif os.path.isdir(p) and el in ('storage', 'data', 'db', 'state'):
            try:
                for sub in os.listdir(p)[:200]:
                    if sub.lower().endswith(('.db', '.sqlite', '.sqlite3')):
                        db += 1
            except OSError:
                pass
    if db:
        score += 2
        why.append(f'{db} 个数据库文件')
    if cfg:
        score += 1
        why.append('有配置')
    if len(entries) > 8:
        score += 1
    return score, why


def scan_generic_agents(known: set) -> list:
    """扫常见根目录，找"没收录但像 agent 数据"的目录。"""
    known = {k.lower().lstrip('.') for k in known}
    roots = [os.path.expanduser('~'), os.environ.get('APPDATA'), os.environ.get('LOCALAPPDATA')]
    rows = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        try:
            names = sorted(os.listdir(root))[:400]
        except OSError:
            continue
        for name in names:
            p = os.path.join(root, name)
            if not os.path.isdir(p) or is_system_path(p):
                continue
            if name.lower().lstrip('.') in known:
                continue
            score, why = quick_agent_score(p, name)
            if score >= 5:
                rows.append({'app': name, 'score': score, 'why': why, 'path': p})
    rows.sort(key=lambda r: -r['score'])
    # 同目录、同名词去重（~ 与 AppData 可能重复，或 .foo 与 foo 并存）
    seen_name, seen_path, out = set(), set(), []
    for r in rows:
        key = r['app'].lower().lstrip('.')
        real = os.path.normcase(os.path.realpath(r['path']))
        if key in seen_name or real in seen_path:
            continue
        seen_name.add(key)
        seen_path.add(real)
        out.append(r)
    return out[:15]


def _parent_chain():
    """当前进程的祖先进程（用于判断"是谁调用了我"）。"""
    out = sh("Get-CimInstance Win32_Process | "
             "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath | ConvertTo-Json -Compress")
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    by_pid = {p['ProcessId']: p for p in data}
    chain = []
    pid = os.getpid()
    for _ in range(12):
        node = by_pid.get(pid)
        if not node:
            break
        pid = node.get('ParentProcessId')
        nxt = by_pid.get(pid)
        if not nxt:
            break
        chain.append(nxt)
    return chain


def detect_candidates() -> list:
    """列出本机存在的已知 agent，按证据强度排序。只做建议，不替用户决定。"""
    chain = _parent_chain()
    rows = []
    for app, sig in APP_SIGNATURES.items():
        score, why = 0, []
        for node in chain:
            text = f"{node.get('Name','')} {node.get('ExecutablePath','')}".lower()
            if any(w in text for w in sig['words']):
                score += 5
                why.append(f'进程链命中 {node.get("Name")}')
                break
        for var in sig['env']:
            v = os.environ.get(var)
            if v:
                score += 3
                why.append(f'环境变量 {var}={v}')
        for d in sig['dirs']:
            p = os.path.expanduser(d)
            if os.path.isdir(p):
                score += 2
                why.append(f'数据目录 {p}')
        if score:
            rows.append({'app': app, 'score': score, 'why': why})
    rows.sort(key=lambda r: -r['score'])
    return rows


def scan_processes(app: str) -> list:
    """返回 [{pid,name,exe,cmd,match}]。match 表示证据强度：
       exe     -- 可执行文件就在应用目录下（强证据）
       cmdline -- 只是命令行里提到了应用名（弱证据，可能是我自己的 shell）
    """
    out = sh(
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ProcessName,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    me = os.getpid()
    rows = []
    for p in data:
        exe = p.get('ExecutablePath') or ''
        cmd = p.get('CommandLine') or ''
        name = (p.get('ProcessName') or '')
        pid = p.get('ProcessId')
        if pid == me:
            continue
        match = None
        if name_matches(exe, app) or name_matches(name, app):
            match = 'exe'
        elif name_matches(cmd, app) and name.lower().replace('.exe', '') not in SHELL_PROCS:
            match = 'cmdline'
        if match:
            rows.append({'pid': pid, 'name': name, 'exe': exe, 'cmd': cmd, 'match': match})
    # 强证据排前面
    rows.sort(key=lambda r: 0 if r['match'] == 'exe' else 1)
    return rows


def scan_env(app: str) -> list:
    out = sh(
        "$r=@(); 'User','Machine' | ForEach-Object { $s=$_; "
        "[Environment]::GetEnvironmentVariables($s).GetEnumerator() | ForEach-Object { "
        "$r += [pscustomobject]@{scope=$s;name=$_.Key;value=[string]$_.Value} } }; "
        "$r | ConvertTo-Json -Compress"
    )
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    rows = []
    for e in data:
        v = e.get('value') or ''
        n = e.get('name') or ''
        if name_matches(n, app) or name_matches(v, app):
            if ':' in v or v.startswith('\\\\'):
                rows.append({'scope': e.get('scope'), 'name': n, 'value': v})
    return rows


def scan_registry(app: str) -> list:
    out = sh(
        "$ks=@('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*');"
        "$r=@(); foreach($k in $ks){ Get-ItemProperty $k -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DisplayName -match '%s' } | ForEach-Object { "
        "$r += [pscustomobject]@{name=$_.DisplayName;ver=$_.DisplayVersion;"
        "loc=$_.InstallLocation;uninstall=$_.UninstallString} } }; $r | ConvertTo-Json -Compress" % app
    )
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [data] if isinstance(data, dict) else data


def guess_candidates(app: str, drives=None) -> list:
    """常见安装/数据位置。只做存在性探测，不做深扫。"""
    home = os.path.expanduser('~')
    names = {app.lower()}
    # 常见变体：带点前缀、带 -data 后缀
    names |= {'.' + app.lower(), app.lower() + '-data', app.lower() + 'data'}
    cands = []
    for base in (os.environ.get('APPDATA'), os.environ.get('LOCALAPPDATA'), home):
        if not base:
            continue
        try:
            for e in os.listdir(base):
                if e.lower() in names:
                    cands.append(os.path.join(base, e))
        except OSError:
            pass
    for d in (drives or []):
        try:
            for e in os.listdir(d):
                if e.lower() in names or e.lower().startswith(app.lower()):
                    cands.append(os.path.join(d, e))
        except OSError:
            pass
    return sorted(set(cands))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--app', required=False,
                    help='应用标识（如 dsh / workbuddy / codex）。用 auto 或 --list-apps 只列候选，不测绘')
    ap.add_argument('--list-apps', action='store_true', help='只列出本机存在的 agent，供人工确认')
    ap.add_argument('--paths', nargs='*', default=[], help='手动指定候选目录（优先级最高）')
    ap.add_argument('--drives', nargs='*', default=[], help='额外扫哪些盘根，如 D:\\')
    ap.add_argument('--out', default='inventory.json')
    args = ap.parse_args()
    if not args.app and not args.list_apps:
        sys.exit('请先确认要整理哪个应用：\n'
                 '  python discover.py --list-apps          # 列出本机存在的 agent\n'
                 '  python discover.py --app <名字> --out inventory.json')

    app = args.app or 'auto'
    if args.list_apps or app.lower() == 'auto':
        rows = detect_candidates()
        print('== 已知 agent（有内置签名，识别最准）==')
        if not rows:
            print('  无')
        for i, r in enumerate(rows, 1):
            print(f'  {i}. {r["app"]:<14} 证据分 {r["score"]:<3} ' + '；'.join(r['why'][:3]))

        print()
        print('== 未收录但疑似 agent 数据目录（启发式发现）==')
        generic = scan_generic_agents({r['app'].lower() for r in rows})
        if not generic:
            print('  无')
        for i, r in enumerate(generic, 1):
            print(f'  {i}. {r["app"]:<24} 特征分 {r["score"]:<3} ' + '；'.join(r['why'][:3]))
            print(f'       {r["path"]}')

        print()
        print('这一步只做建议，不替你做决定。')
        print('已收录的用名字即可：')
        print('  python discover.py --app <名字> --out inventory.json')
        print('没收录的用名字 + 路径（更可靠）：')
        print('  python discover.py --app <名字> --paths "<上面的路径>" --out inventory.json')
        print()
        print('其余应用只要知道名字或目录，也能照常走完整流程——这一层只是"名单"，不是能力边界。')
        sys.exit(0)

    print(f'== 测绘应用: {app} ==')

    procs = scan_processes(app)
    strong = [p for p in procs if p['match'] == 'exe']
    print(f'[1/5] 相关进程 {len(procs)} 个（其中可执行文件在应用目录下的强证据 {len(strong)} 个）')
    for p in procs[:8]:
        mark = '强' if p['match'] == 'exe' else '弱'
        print(f'      [{mark}] pid {p["pid"]:<7} {p["name"]:<22} {p["exe"] or "(无路径)"}')

    envs = scan_env(app)
    print(f'[2/5] 相关环境变量 {len(envs)} 个')
    for e in envs[:8]:
        print(f'      [{e["scope"]}] {e["name"]} = {e["value"]}')

    regs = scan_registry(app)
    print(f'[3/5] 注册表卸载项 {len(regs)} 条')
    for r in regs[:5]:
        print(f'      {r.get("name")}  {r.get("ver")}  {r.get("loc")}')

    cands = list(dict.fromkeys(args.paths + guess_candidates(app, args.drives)))
    # 进程 exe 所在目录、环境变量里的路径也纳入候选
    for p in procs:
        if p['match'] == 'exe' and p['exe']:
            cands.append(os.path.dirname(p['exe']))
    for e in envs:
        v = (e['value'] or '').strip()
        if len(v) > 2 and v[1] == ':' and os.path.isdir(v):
            cands.append(v)
    cands = list(dict.fromkeys(
        c for c in cands if c and os.path.exists(c) and not is_system_path(c)))

    print(f'[4/5] 候选目录 {len(cands)} 个，开始探测规模…')
    if not cands:
        print()
        print('一个候选目录都没找到。这意味着：')
        print('  1) 应用名可能写错了（检查拼写，注意类似 deepseekharness / deepseekharnees 的差异）')
        print('  2) 应用可能装/运行在非默认位置（用 --paths 手动给出目录）')
        print('  3) 应用确实没在这台机器上')
        print()
        print('不做推测，也不生成空清单。请确认后用 --paths 指定目录重跑。')
        sys.exit(3)
    dirs = []
    for c in cands:
        d = probe_dir(c, app)
        dirs.append(d)
        flag = '链接' if d['is_link'] else '目录'
        print(f'      {d["files"]:>7}{"+" if d["capped"] else " "} 文件  '
              f'{d["bytes"] / 1024 / 1024:>9.1f} MB  [{flag}]  {c}')

    inv = {
        'app': app,
        'generated': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        'host': os.environ.get('COMPUTERNAME'),
        'user': os.environ.get('USERNAME'),
        'processes': procs,
        'env': envs,
        'registry': regs,
        'candidates': dirs,
    }
    _console.ensure_parent(args.out)
    with open(args.out, 'w', encoding='utf-8-sig') as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)

    print(f'[5/5] 已写出 {args.out}')
    cfg = sum(len(d['configs']) for d in dirs)
    dbs = sum(len(d['databases']) for d in dirs)
    print(f'      配置线索 {cfg} 个，SQLite {dbs} 个')
    print('\n下一步：python plan.py --inventory inventory.json --root D:\\agents\\<app>')


if __name__ == '__main__':
    main()
