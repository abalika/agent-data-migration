# 重绑：七层引用，逐层过

迁移只搬了文件，应用还在用旧路径找东西。**只改配置文件远远不够**——四层引用，每层都单独出过事故。

## L1 环境变量

很多应用的数据根不在配置文件里，而在**用户级环境变量**里。

```powershell
# 两级都要看
'User','Machine' | ForEach-Object {
  [pscustomobject]@{ scope=$_; name='DSH_HOME';
    value=[Environment]::GetEnvironmentVariable('DSH_HOME',$_) }
}

# 改用户级
[Environment]::SetEnvironmentVariable('DSH_HOME','D:\agents\dsh\_runtime\home','User')
```

> 事故：只改了启动脚本 `Start-XXX.bat` 里的 `set DSH_HOME=`，没改环境变量。
> 结果从别的入口（开始菜单、桌面快捷方式）启动时，应用读到的是旧路径，表现为"数据没了"。

改完必须**新开进程**才生效（当前 shell 不会刷新）。

## L2 配置文件

覆盖四种写法，缺一种就会漏：

| 写法 | 出现场景 |
| --- | --- |
| `D:\x\y` | 普通文本、YAML、TOML、PowerShell |
| `D:/x/y` | JSON（部分应用统一用正斜杠）、`package.json` 的 `file:` 依赖 |
| `D:\\x\\y` | JSON 转义后的字符串 |
| `\\?\D:\x` | 长路径前缀 |

做法：

1. 按"最长前缀优先"排序做替换，避免 `D:\root` 先吃掉 `D:\root\sub`
2. 跑第二遍应该 0 处改动（幂等）；不为 0 说明有自指或循环
3. **区分"操作性引用"与"历史记录"**：会话正文、验收报告、日志里写死的旧路径**不改**

判据：改完之后应用行为会不会变？会 → 改；不会 → 不改。

## L3 数据库

索引类字段必须改，否则应用找不到工作区/会话。

```python
import sqlite3
con = sqlite3.connect('file:app.db?mode=ro', uri=True)   # 先只读核对
rows = con.execute("select id,cwd from sessions where cwd like '%旧根%'").fetchall()

# 改的时候：一致性快照 + 单事务 + quick_check
con = sqlite3.connect('app.db')
with con:
    con.execute("update sessions set cwd=? where cwd=?", (new, old))
con.execute("pragma quick_check").fetchone()
```

注意：

- 有的库路径**以正斜杠存储**，因此用 `LIKE '%关键字%'` 而不是带反斜杠的前缀匹配
- 提交前用 backup API 或 `VACUUM INTO` 做一致快照（见 `platform.md` 的 SQLite 段）
- 只改操作性索引，不改消息正文、不改已软删记录的留痕字段

## L4 索引与缓存

`*-index.json`、`session_projcache/`、`artifact-index`、`file-tree-manifests` 这类文件里也存绝对路径。

- 改完必须能被 `json.load` 解析
- 条目数、键结构不能变（只改值里的路径，不改结构）
- 缓存类可以容忍重生成，但**能改就别删**——删了可能触发全量重建，反而慢

## L5 二进制内嵌路径

有些路径不在文本里，而在二进制内部：

| 位置 | 现象 | 处理 |
| --- | --- | --- |
| venv 的 `Scripts\*.exe` | 改目录后 `pip.exe` 无输出、exit 1 | 用 distlib 重建（`regen_launchers.py --check`） |
| `.lnk` 快捷方式 | Target/WorkingDir 对了但图标是白的 | 分别改 `IconLocation` 与 `Target` |
| `.exe` 里嵌的绝对路径 | 启动报找不到资源 | 一般不迁移，改为原位保留 |

> 不要用"二进制字符串替换"去改 venv 启动器——长度变了会破坏 PE 结构。用 distlib 重新生成。

## L6 符号链接 / Junction

包管理器的 `file:` 依赖是指向源码目录的**符号链接**：

```
node_modules/dsh-session-delete -> D:\旧根\dsh-session-delete
node_modules/@vendor/dsh-screenshot -> D:\旧根\_plugins\...
```

源码一搬，链接就悬空，插件加载失败。

- 扫描必须进 `node_modules/@scope/` 这一层（只扫直接子项会漏）
- 判断是否联接：`os.lstat(p).st_file_attributes & 0x400`，**`os.path.islink()` 认不出 junction**
- 重建：`New-Item -ItemType Junction -Path <link> -Target <target>`
- 删除：`[System.IO.Directory]::Delete($link, $false)`（目标已移走时 `Remove-Item` 会报路径不存在）
- 同时改 `package.json` 里的 `file:` spec，否则下次 `pnpm install` 会再把链接指回旧路径

用脚本扫：

```bash
python scripts/scan_links.py --root D:\agents\<应用>
```

## L7 系统集成

```powershell
# 计划任务
Get-ScheduledTask | ForEach-Object { $t=$_; $t.Actions | ForEach-Object {
  if ("$($_.Execute) $($_.Arguments)" -match '旧根') { $t.TaskName } } }

# 改（注意 WorkingDirectory 为空的要单独处理，New-ScheduledTaskAction 不接受 null）
Set-ScheduledTask -TaskName X -Action (New-ScheduledTaskAction -Execute $exe -Argument $args)

# 启动项
Get-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
```

桌面 `.cmd` / `.ps1` 里写死的备份路径也要改。

## 重绑完成判据

| 层 | 判据 |
| --- | --- |
| L1 | 新开进程读到的是新值 |
| L2 | 旧路径引用计数 = 0，二次替换 0 处 |
| L3 | `quick_check` = ok，旧路径行数 = 0 |
| L4 | JSON 可解析，条目数不变 |
| L5 | `regen_launchers.py --check` 全部 ok |
| L6 | 悬空链接 = 0，`package.json` spec 已更新 |
| L7 | 任务/启动项/桌面脚本无旧路径 |
