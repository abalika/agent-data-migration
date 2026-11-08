# 验收：五层，缺一层都不算完

脚本能验"结构和数量"，验不了"应用能不能用"。真正的验收要五层。

## V1 静态（机器可判）

```bash
python scripts/verify.py --plan plan.json
```

| 判据 | 说明 |
| --- | --- |
| 目标目录全部存在 | |
| 源处理正确 | 改名后应消失；跨盘复制后应变成指向目标的联接 |
| 无悬空链接 | 含 `node_modules/@scope/` 层 |
| 数量不少于计划基线 | 文件数、字节数 |
| 幂等 | 重跑会被"目标已存在"跳过 |

补充项（脚本不覆盖，手工跑）：

```powershell
# 旧路径引用计数应为 0（只看配置，不看历史记录）
Select-String -Path <配置> -Pattern '旧根' -SimpleMatch
# 计划任务
Get-ScheduledTask | ForEach-Object { $t=$_; $t.Actions | ForEach-Object {
  if ("$($_.Execute) $($_.Arguments)" -match '旧根') { $t.TaskName } } }
```

## V2 格式不变量（最容易被忽略）

**文件"能打开"≠"应用能读"。** 每种数据格式都有隐含契约：

| 数据 | 不变量 | 怎么验 |
| --- | --- | --- |
| 多帧 zstd 会话日志 | 第 1 帧必须恰好是头部一行；每帧在行边界结束；`seq` 连续 | 逐帧解压后断言 |
| SQLite | `sessions.cwd` 与所在目录名一致；`quick_check` ok | SQL 对账 |
| venv | `Scripts\*.exe` 的内嵌 shebang = 当前 python 路径 | `regen_launchers.py --check` |
| `.cmd`/`.bat` | 纯 ASCII、无裸 LF | 字节检查 |
| `.lnk` | Target / WorkingDir / IconLocation 三者分别正确 | 解析后回读 |
| JSON 索引 | 可 `json.load`，条目数与结构不变 | 解析 + 计数 |

实测方法：把应用的校验逻辑从源码里找出来，照着复刻一遍。例如 DSH 的
`assertZstdHeaderFrame` 要求"首帧只有一个换行且在末尾"，那就对所有会话文件跑这个断言。

## V3 功能（真跑，不是看目录）

- 从新位置执行二进制：`node --version`、`python --version`、`bash --version`
- 打开一条历史会话，确认**有内容**
- 写一条再读回，确认可写
- 数据库 `quick_check` / `integrity_check` = ok

> "点开有内容"是判定迁移成功的最低标准。文件在、大小对、但打开是空白，不算成功。

## V4 真实环境

- 进程数正常（不是 0，也不是翻倍）
- 启动日志无 `corrupt` / `skipped plugin` / `failed to load`
- 数量核对：工作区 N 个、会话登记 M 条、文件 K 个
- 抽样哈希：迁移前后逐文件 SHA-256 一致（大目录抽 20 个即可）

```powershell
# 抽样哈希
Get-ChildItem $dir -Recurse -File | Get-Random -Count 20 |
  ForEach-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash + '  ' + $_.FullName }
```

## V5 演练沙盘（动真数据之前）

用假目录把整条流程跑一遍：

1. 造 fixture：几百到几千文件，含中文名、空格、深层嵌套、只读文件、空目录
2. 把脚本里的根路径换成 fixture 路径（用 Python 改文本，不要手改）
3. 跑「迁移 → 断言 → 回滚 → 断言 → 二次迁移」
4. 断言项：文件数、字节数、抽样哈希、联接可读、空目录保留

成本约 10 分钟，收益是"真跑时一次成功"。本项目这一步救过两次：
一次抓出 `/COPYALL` 权限问题，一次抓出安全门判据不完整。

## 验收报告模板

见 `assets/REPORT-template.md`。至少要包含：

- 映射表（原路径 → 新路径 → 引用方 → 重绑方式）
- 外部引用改动清单（环境变量/任务/快捷方式）
- 五层验收结果（PASS/FAIL 逐项）
- 事故与修复
- 回退步骤（可照着做）
- 已知项（明确保留、不打算修的）
