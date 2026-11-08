# 平台机制速查

迁移时的每一个"为什么"，答案大多在系统行为里。这一页是踩过坑之后核对官方文档得到的结论。

## 1. Junction 与符号链接

| | Junction (`mklink /J`) | 目录符号链接 (`mklink /D`) |
| --- | --- | --- |
| 目标类型 | 仅目录 | 目录或文件 |
| 跨卷 | 可以（指向本机其它卷） | 可以 |
| 网络路径 UNC | **不支持** | 支持 |
| 创建权限 | 普通用户即可 | 需管理员或开发者模式 |
| 兼容性 | 老程序友好，对应用完全透明 | 部分安装器/备份工具识别不了 |
| 删除 | `rmdir` 只删链接，不动目标 | 同左 |

**迁移统一用 junction**：不需要提权、可跨卷、应用看不见差别。

判据与陷阱：

```python
# 正确判据：os.path.islink() 对 junction 返回 False
bool(os.lstat(p).st_file_attributes & 0x400)     # FILE_ATTRIBUTE_REPARSE_POINT

# 删除悬空联接（目标已移走时，Remove-Item 会报"路径不存在"）
import ctypes
ctypes.windll.kernel32.RemoveDirectoryW(p)       # 或 [System.IO.Directory]::Delete(p,$false)
```

`fsutil reparsepoint query <path>` 可以看到联接的详细类型与目标。

## 2. robocopy

**退出码是位标志**，不是一个连续数字：

| 位 | 值 | 含义 |
| --- | --- | --- |
| - | 0 | 无变化，已同步 |
| 0x01 | 1 | 有文件被成功复制 |
| 0x02 | 2 | 目标有额外文件 |
| 0x04 | 4 | 有不匹配项 |
| **0x08** | **8** | **有文件复制失败** |
| **0x10** | **16** | **严重错误：一个文件都没复制**（用法错或权限不足） |

判据：`>= 8` 中止。1 表示"复制成功"，不代表"全部成功"；但只要有一个失败，0x08 必然置位。

参数建议：

```
/E /COPY:DAT /DCOPY:T /R:2 /W:2 /LOG:copy.log
```

- **`/R` 默认 1,000,000 次、`/W` 默认 30 秒**——碰到被锁文件会像卡死几小时，必须显式给
- `/L` 先干跑，确认路径无误再去掉
- `/COPYALL` 含 SACL（审计），需要 `SeSecurityPrivilege`；普通账户直接返回 16

## 3. NTFS 权限（ACL）

| 复制方式 | 显式 ACL | 说明 |
| --- | --- | --- |
| 同盘 rename | 保留 | 只改目录项，安全描述符不动 |
| 跨盘 `/COPY:DAT` | **丢失** | 目标继承父目录权限，源上的自定义 ACE 消失 |
| 跨盘 `/COPY:DATS` 或 `/SEC` | 保留 | 需 `SeRestorePrivilege` |
| 跨盘 `/COPYALL` | 保留 | 另需 `SeSecurityPrivilege` |

迁移前后必须比对：

```powershell
(Get-Acl $src).Access | Format-Table IdentityReference,FileSystemRights,IsInherited
(Get-Acl $dst).Access | Format-Table IdentityReference,FileSystemRights,IsInherited
```

判据：源上 `IsInherited=False` 的条目要能在目标重建；做不到就明确记录为已知偏差。
单用户机器影响小；**有多用户或沙箱账户时要当回事**。

## 4. SQLite / WAL

WAL 模式下已提交的事务可能只存在于 `-wal` 文件里：

- 只拷 `.db` → 得到的是"上次 checkpoint 的快照"，可能少几百行，而 `integrity_check` 仍返回 ok（静默丢数据）
- 三个文件分别读、时间点不同 → 即使全拷也不安全
- 连接打开时 `shutil.copy2` 拷 `-wal`/`-shm` 会 `WinError 1224`

正确做法：

```bash
sqlite3 app.db "VACUUM INTO 'backup/app-snapshot.db'"    # 一致快照，顺便压紧
sqlite3 "backup/app-snapshot.db" "PRAGMA integrity_check;"   # 必须 ok
# 或：sqlite3 app.db ".backup 'backup/app.db'"
```

注意 `VACUUM INTO` 的产物是 rollback-journal 模式；若回灌到 WAL 场景，需重设 `journal_mode=WAL`。

只读打开 WAL 库仍需要写 `-shm`；`immutable=1` 只适用于确实不会再变的文件。

## 5. 长路径与特殊字符

- 路径超过 260 字符：用 `\\?\` 前缀；或开 `LongPathsEnabled`
  （`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`）
- 中文目录名：Git Bash 里 `findstr`/`grep` 的参数会被 MSYS 改写，不可靠 → 用 Python
- Bash heredoc 里写 Windows 路径，`\\` 可能被转成 `//` → 涉及反斜杠的脚本写成 `.py` 文件再执行
- `.cmd`/`.bat` 里放非 ASCII + LF 换行，cmd.exe 会按字节错位断行，一行被切成几段执行

## 6. 文件锁

删不掉、移不动时，别猜，直接问系统。Restart Manager 是 Vista+ 自带机制：

```powershell
powershell -NoProfile -File scripts/who-locks.ps1 "D:\某个文件"
# 输出：16988  WorkBuddy  RmUnknownApp  D:\WorkBuddy\WorkBuddy.exe
```

原理：`RmStartSession` → `RmRegisterResources` → `RmGetList`，不需要第三方工具、不需要管理员。

判断"应用是否完全退出"时，按**可执行文件路径前缀**统计，不要只看进程名——
同一应用常有名字毫无关系的子进程（沙箱、编辑器服务、遥测）。

## 7. 包管理器

- npm/pnpm 的 `file:` 依赖在 `node_modules` 里是**指向源码目录的符号链接**
- 源码一搬，链接悬空；扫描要进 `@scope/` 层
- `package.json` 的 `file:` spec 也要改，否则重装会把链接指回旧路径
- pnpm 的 `.pnpm` 虚拟store 用硬链接，跨卷无法硬链接会退化为复制

## 8. Python venv

- `python.exe` 靠 `pyvenv.cfg` 重定向，**改名后仍可用**
- `pip.exe`/`uvicorn.exe` 等 distlib 启动器内嵌 shebang 绝对路径，**改名后静默失败**（无输出、exit 1）
- 用 `regen_launchers.py <venv> --check` 验收，不要用二进制字符串替换

## 9. 编码

| 场景 | 正确做法 |
| --- | --- |
| Python 输出到 Windows 控制台 | `SetConsoleOutputCP(65001)` + `stdout.reconfigure(encoding='utf-8')` |
| 报告文件 | `utf-8-sig`（带 BOM），记事本/Excel 正常打开 |
| `.cmd`/`.bat` | 纯 ASCII、单行；中文交给 PowerShell 输出 |
| PowerShell 脚本 | 带 UTF-8 BOM + `[Console]::OutputEncoding` |
| 管道输出给别的程序 | 先设对方的输出编码，或直接看落盘报告 |
