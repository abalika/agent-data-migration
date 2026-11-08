# 测绘：从应用本体出发

> 最常见的失败：靠"目录名像不像应用名"去猜。
> 真实反例：`D:\deepseekharnees`（少个 s，真正在跑的安装）vs `D:\deepseekharness`（旧版本）；
> `D:\wb2api` 从名字完全看不出和 DSH 有关；`unsecapp.exe` 因为含 `capp` 子串被误认成应用进程。

## 顺序：应用 → 配置 → 磁盘

### A. 问应用（最优先）

| 手段 | 操作 | 得到 |
| --- | --- | --- |
| 设置界面 | 设置 → 数据/存储/工作目录/高级 | 应用**明示**的数据根 |
| 右键菜单 | 会话或项目上右键 → "在文件夹中显示" / "打开所在位置" | 单条记录的**真实**落盘路径 |
| 关于/诊断 | 帮助 → 关于 / 打开日志目录 | 安装路径、日志路径、版本 |
| 快捷方式 | 右键属性 → 目标 / 起始位置 | exe 路径、工作目录、是否带环境变量 |
| 进程命令行 | 见下 | 应用**此刻**在用哪些路径 |
| 启动日志 | 前台启动一次抓 stdout | 加载了哪个 profile、监听端口、报错 |

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -like '*应用名*' } |
  Select-Object ProcessId, Name, ExecutablePath, CommandLine | Format-List
```

重点看命令行里的：`--user-data-dir=`、`--profile-directory=`、`HOME=`、`*_HOME=`、配置文件路径参数。

### B. 查配置与索引

| 目标 | 位置 |
| --- | --- |
| 主配置 | `config.toml` / `settings.json` / `*.yml` 里的绝对路径 |
| 数据库 | `sessions.cwd`、`threads.cwd`、`workspaces.path`、`project_roots.path` |
| 索引缓存 | `*-index.json`、`session_projcache/`、`artifact-index` |
| 依赖声明 | `package.json` 的 `file:`、`pnpm-lock.yaml`、`.modules.yaml` |
| 系统集成 | 计划任务、Run 键、服务 |

### C. 扫磁盘（兜底）

只在 A/B 之后用来找漏网的。方法：

- 按名字匹配（**按词元**，不要子串——`unsecapp` 含 `capp`）
- 按体积、最近修改时间、父子目录聚类
- 找孤儿：磁盘上存在但没有任何配置/数据库引用的大目录

## 三源对齐

对每个候选路径，三项必须同时成立：

```
① 应用说它在用     （设置 / 右键 / 命令行 / 日志）
② 配置或数据库里有它（绝对路径）
③ 磁盘上确实存在    （体积与预期相符）
```

不一致处就是事故点。**本项目三起事故全部因为只验了 ②③**：

- 会话被整文件重压 → 没验"应用怎么读"
- `.cmd` 里放中文 → 没验"系统怎么解析"
- 插件链接悬空 → 没验"依赖怎么解析"

## 用脚本批量测绘

```bash
python scripts/discover.py --app <名> --paths "<可疑目录1>" "<可疑目录2>" --out inventory.json
```

输出字段：

| 字段 | 含义 |
| --- | --- |
| `processes[].match` | `exe`=可执行文件路径含应用词元（强证据）；`cmdline`=只在命令行里被提到（弱证据） |
| `env[]` | 名字或值含应用词元的 User/Machine 环境变量 |
| `registry[]` | 卸载项（InstallLocation 是"不能动"的强依据） |
| `candidates[]` | 每个候选目录的规模、顶层条目、浅层配置与 SQLite 线索 |
| `capped` | 文件数触顶（默认 30 万），说明没数完 |

系统目录（`%WINDIR%`、`Program Files`、`ProgramData`）会被自动排除。

## 测绘报告要回答的问题

1. 这个应用有几个根？（通常 2~5 个：安装、数据、缓存、项目、日志）
2. 每个根多大、多少文件？
3. 每个根**被谁引用**（应用自己 / 配置 / 数据库 / 计划任务 / 其他应用）？
4. 哪些根在应用运行时是**被锁的**？
5. 哪些根**绝对不能动**（注册表卸载项指向的安装目录、系统集成服务）？

答完这五问，才能进下一步。
