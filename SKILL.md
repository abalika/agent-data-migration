---
name: agent-data-migration
description: 把 AI agent / 桌面应用散落在磁盘各处的数据（项目、对话、运行时、缓存、备份）收敛到统一目录骨架，并保证应用照常运行、历史可打开、可回滚。当用户提出「整理我的 agent 数据」「把 D 盘散落的文件归拢」「应用数据搬到统一目录」「迁移后会话打不开/插件异常」时使用；也用于迁移后的故障排查与验收。支持 DeepSeek Harness、WorkBuddy、Codex、Antigravity 等应用，并提供通用测绘/规划/执行/验收脚本，可套用到任意应用。
agent_created: true
---

# Agent 数据迁移与验收

## 用途

把一个应用（通常是 AI agent 桌面端）散落在多个盘、多个根目录下的数据，收敛成"一个应用一个根"的规范结构，
并且保证：**应用能启动、历史能打开、引用零残留、随时可回滚**。

这套流程由四次真实迁移（Codex / WorkBuddy / DeepSeek Harness / Antigravity）反推而成，
里面每一条"注意"都对应一次真实事故。

## 何时使用

- 用户说"帮我整理某个 agent 的数据 / 把散落的文件归到一个目录"
- 用户说某个应用的数据占了 C 盘，想搬到 D 盘
- 迁移之后出现：会话列表空、点开是空白、插件异常、批处理报错
- 需要为迁移做验收（"到底迁移成功没有"）

## 目标结构（先建骨架，再搬东西）

```
D:\agents\<应用>\
├─ projects\        用户长期工程（README / git / 产物）
├─ chats\           一次性对话工作区、时间戳目录、交付物
├─ _runtime\        应用自己会去找的：数据根、插件、缓存、运行时、共享工具链
└─ maintenance\     备份、归档、诊断脚本、旧版本安装
```

判定口诀：**"应用会不会自己去拼路径找它？"** 会 → `_runtime`（或原位保留）；不会 → `projects`/`chats`。

## 六步流程（第 0 步是确认，必须做）

### 第 0 步：先确认目标应用（不要跳过，也不要替用户决定）

**迁移是不可逆的高风险操作，永远先问清楚再做。**

```bash
python scripts/discover.py --list-apps
```

输出分两层：

1. **已知 agent**（有内置签名的，进程链 / 环境变量 / 数据目录三重证据）
2. **未收录但疑似**（启发式：点目录、含 `sessions`/`projects`/`skills` 类子目录、有 SQLite、有配置）

拿到结果后，用**一句话**问用户确认，不要自己选：

> 这台机器上检测到 WorkBuddy（7 分）、DSH（5 分）、Codex（2 分）；
> 另外发现 `.codebuddy`、`.cc-switch` 两个没收录但像 agent 数据目录的。
> 这次要整理哪一个？

**这份名单是快捷方式，不是能力边界。**未收录的应用照样能整理：

```bash
# 知道名字
python scripts/discover.py --app <名字> --out inventory.json
# 知道目录（更可靠）
python scripts/discover.py --app <名字> --paths "<目录>" --out inventory.json
```

脚本本身不含任何应用知识——它只认"进程路径、环境变量、注册表、磁盘特征"。
应用特有的坑放在 `references/apps/`，没有对应文档的应用按通用流程走即可。

规则：

- 用户没明确回答之前，**不写任何文件、不生成计划、不动一个字节**
- 即使证据分很高，也只说"我判断是 X"，然后等确认
- 用户说的和目标不一致（例如说"整理 DSH"但 DSH 数据在别处），把矛盾摆出来再问
- 用户只想"看一下"时，停在测绘阶段，不要顺势往下走

### 第 1 步：测绘（从应用本体出发，不要靠名字猜）

优先级从高到低：

1. **设置界面** → 找"数据目录/存储位置/高级"
2. **右键菜单** → 会话/项目右键"在文件夹中显示"，直接给出单条记录的真实路径
3. **进程命令行** → 应用此刻在用哪些路径（含 `--user-data-dir`、`HOME=` 之类的参数）
4. **环境变量** → `XXX_HOME` 这类根变量（User 和 Machine 两级都要看）
5. **配置与数据库** → `config.toml`、sqlite 的 `cwd`/`path` 列
6. **扫磁盘** → 最后兜底，只用来找漏网的

用脚本一次拿全（`--app` 必须是第 0 步确认过的那个名字）：

```bash
python scripts/discover.py --app <应用名> --paths "<可疑目录>" --out inventory.json
```

`--app auto` 只会列出候选、给出建议，**不会自己开始测绘**；确认后必须用显式名字重跑。
这是有意设计的：宁可多问一句，也不要在用户没确认目标的情况下动数据。

输出的 `inventory.json` 含：进程（带证据强度）、环境变量、注册表卸载项、候选目录的规模与配置线索。

**三源对齐**：只有"应用说它在用 + 配置里有它 + 磁盘上确实存在"三者同时成立，才敢动。
三者不一致的地方就是事故点。

### 第 2 步：规划（先写施工图，不动文件）

```bash
python scripts/plan.py --inventory inventory.json --root D:\agents\<应用> \
    --expand "<应用那个堆满东西的根目录>" --out plan.json
```

产出 `plan.json`（机器可读）+ `plan.txt`（人可读）。每项含：源、目标、分类、风险、方式、是否需停机。

应用把东西堆在一个根下时，用 `--expand` 把它的子项逐个分类。

**必须先审一遍 plan.txt 再执行。** 分类错了可以改 JSON，改完照样能跑。

风险分级：

| 级别 | 含义 | 做法 |
| --- | --- | --- |
| green | 纯归档，无人引用 | 直接搬 |
| yellow | 被配置引用，应用可重启 | 搬 + 重绑 + 校验 |
| red | 运行中锁定的数据根/数据库/二进制 | **单独一批**，停机 + 全量验收 + 回滚演练 |

### 第 3 步：执行

```bash
python scripts/apply.py --plan plan.json --dry-run   # 先演练
python scripts/apply.py --plan plan.json             # 逐项确认执行
python scripts/apply.py --journal journal.json --rollback   # 回滚
```

脚本行为：

- 同盘 → `rename`（瞬时、原子、保留 ACL）
- 跨盘 → robocopy 复制 → 校验文件数与字节 → 删源 → 在原位建 junction
- **校验不通过绝不删源**
- 每步写入 `journal.json`，可整体回滚
- 有进程占用的 red 项会拒绝执行，并提示用 `who-locks.ps1` 查占用者

执行前确认应用完全退出。判据不是进程名，而是**可执行文件路径前缀**：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.ExecutablePath -like "$env:USERPROFILE\.<应用>\*" -or
                 $_.ExecutablePath -like "D:\<安装目录>\*" } |
  Select-Object ProcessId,ProcessName,ExecutablePath
```

### 第 4 步：重绑（最容易漏的一步）

改配置文件远远不够。**七个层面逐层过**，详见 `references/rebinding.md`：

| 层 | 内容 |
| --- | --- |
| L1 环境变量 | `XXX_HOME` 等，User + Machine |
| L2 配置文件 | toml/yaml/json 里的绝对路径 |
| L3 数据库 | `sessions.cwd`、`workspaces.path` |
| L4 索引/缓存 | projcache、artifact-index |
| L5 二进制内嵌 | venv 的 `Scripts\*.exe` shebang、`.lnk` 图标 |
| L6 符号链接 | `node_modules/<包>`，**含 `@scope/` 层** |
| L7 系统集成 | 计划任务、启动项、桌面脚本 |

替换必须覆盖四种写法：`D:\x`、`D:/x`、`D:\\x`（JSON 转义）、`\\?\D:\x`。
替换必须幂等：跑第二遍应 0 处改动。

### 第 5 步：验收

```bash
python scripts/verify.py --plan plan.json
```

四组判据：目标存在且源处理正确、无悬空链接、数量不少于基线、幂等。
但脚本只能验"结构和数量"，**必须再补两层人工项**（见 `references/verification.md`）：

- **格式不变量**：会话文件首帧必须是一行、数据库 `cwd` 与目录名一致、venv 启动器 shebang 正确
- **功能真跑**：从新位置执行 `node --version`、打开一条历史会话、写一条再读回

判定"迁移成功"的最低标准是**点开有内容**，不是"文件在"。

## 各应用适配

按被迁移的应用读对应说明，里面有该应用特有的坑：

| 应用 | 说明文件 | 关键点 |
| --- | --- | --- |
| DeepSeek Harness | `references/apps/dsh.md` | 会话是多帧 zstd；`DSH_HOME` 是用户级环境变量 |
| WorkBuddy | `references/apps/workbuddy.md` | 40+ junction；`binaries` 需停机；数据库 WAL |
| Codex | `references/apps/codex.md` | `state_5.sqlite` 的 `threads.cwd` |
| Antigravity | `references/apps/antigravity.md` | app/data/installer 三类分开 |

其他应用：把上面这套流程走一遍即可，通用的坑见 `references/platform.md` 与 `references/pitfalls.md`。

## 排障

迁移后出问题，按**上游到下游**的顺序查，不要瞎猜：

```
应用日志 → 应用读取代码 → 数据文件本身 → 目录与路径 → 应用状态
```

常见症状速查见 `references/pitfalls.md`（23 条，全部来自真实事故）。

## 红线

**保守优先**——这是不可逆操作，宁可慢一步：

- 目标应用没确认不动手；计划没审过不执行；出了问题先回滚再排查
- 每个阶段结束都停下来，把结果摊给用户看，等确认再进下一阶段
- 只做用户点名的范围，不"顺手"把别的东西也整理了
- 拿不准的一律问，不写"应该没问题"
- 用户说"看一下"就只测绘，不要顺势迁移

**技术红线**：

- 不测可能下单、付费、发消息、连手机、改网络的功能
- 不全库改写历史消息正文、验收报告、日志（历史不是索引）
- 不绕过安全策略（Defender、自动审批、程序黑名单）
- 需要管理员/停服务/账户切换的操作，交给用户决策

## 编码约定（避免乱码）

- Python 脚本入口调用 `scripts/_console.py` 的 `setup()`，把控制台切到 UTF-8
- 报告文件统一用 `utf-8-sig`（带 BOM）写，记事本/Excel/VSCode 打开都正常
- **`.cmd`/`.bat` 里不要写非 ASCII，也不要用 LF 换行**（cmd.exe 按字节解析会错位断行）
- 输出被管道接到别的程序（如 PowerShell 的 `Select-Object`）时，中文可能按 GBK 解码出错；
  优先直接看脚本生成的 `.txt` / `.json` 报告

## 脚本清单

| 脚本 | 作用 |
| --- | --- |
| `scripts/discover.py` | 测绘：进程/环境变量/注册表/候选目录 |
| `scripts/plan.py` | 生成分类与风险计划（plan.json + plan.txt） |
| `scripts/apply.py` | 执行/演练/回滚 |
| `scripts/verify.py` | 结构与数量验收 |
| `scripts/scan_links.py` | 扫悬空符号链接（含 `@scope`） |
| `scripts/who-locks.ps1` | 查谁占用某个文件（Restart Manager） |
| `scripts/_console.py` | 控制台编码与报告写出 |
