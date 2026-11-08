#!/usr/bin/env python3
"""_console.py - 统一控制台输出编码，避免中文乱码。

Windows 控制台默认代码页是 936(GBK)，Python 按本地编码写 stdout，
一旦脚本里有 UTF-8 中文，就会出现两种经典故障：
  1) UnicodeEncodeError（字符不在 GBK 里）
  2) 能写出去但显示成乱码（字节是 UTF-8，终端按 GBK 解释）

做法：
  * 把控制台输入/输出代码页切到 65001(UTF-8)
  * 把 sys.stdout/stderr 重配为 utf-8，遇到无法编码的字符替换而不是崩溃
  * 非 Windows 平台直接跳过

所有脚本在入口处调用 setup()。报告文件统一用 utf-8-sig（带 BOM）写，
这样记事本/Excel/VSCode 打开都不会乱码。
"""
from __future__ import annotations

import os
import sys


def setup() -> None:
    if sys.platform == 'win32':
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleOutputCP(65001)
            k.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


# 报告文件统一用这个编码写，Windows 下打开不乱码
REPORT_ENCODING = 'utf-8-sig'


def ensure_parent(path: str) -> None:
    """写文件前确保父目录存在——用户给的输出路径可能指向还没建的目录。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_report(path: str, text: str) -> None:
    ensure_parent(path)
    with open(path, 'w', encoding=REPORT_ENCODING, newline='\r\n') as f:
        f.write(text)


if __name__ == '__main__':
    setup()
    print('中文输出测试：迁移 / 归档 / 联接 / 校验  -- 如果这行正常显示，编码就没问题')
