<div align="center">

<img src="assets/neoprobe.png" alt="NeoProbe Logo" width="72" height="72" />

# NeoProbe

**Garry's Mod / Source 服务器监控 · 3 秒实时挤服 · 回合倒计时 · GOC 奇术终端 · RX 美化资源站**

[![Releases 桌面版下载](https://img.shields.io/badge/Releases-Windows%20桌面版%20v1.10.0-2ea44f?style=for-the-badge&logo=windows)](https://github.com/huyuchengnb-rgb/neoprobe/releases/latest)
[![GitHub Pages 在线版](https://img.shields.io/badge/GitHub%20Pages-在线网页版-5b4bd6?style=for-the-badge)](https://huyuchengnb-rgb.github.io/neoprobe/)
[![GOC 奇术终端](https://img.shields.io/badge/GOC%20奇术终端-训练模式-05c9f4?style=for-the-badge)](https://huyuchengnb-rgb.github.io/neoprobe/#goc)
[![RX 美化资源站](https://img.shields.io/badge/RX%20美化资源站-直连网盘-1f7a4d?style=for-the-badge)](https://huyuchengnb-rgb.github.io/neoprobe/#rx)

核心探测与后端采用 **纯 Python 标准库实现**（Python 3.10+），同时提供 **Windows 独立桌面软件版（v1.10.0）** 与 **GitHub Pages 免安装在线网页版** 两个并行版本。

</div>

---

## 两个并行版本

NeoProbe 提供两套可独立使用、亦可协同桥接的并行形态，界面与核心功能保持同步：

### 版本一：Windows 独立桌面软件版（`v1.10.0`，Releases 下载）

- **下载地址**：<https://github.com/huyuchengnb-rgb/neoprobe/releases/latest>
  - 提供免安装单文件 `NeoProbe.exe`（双击即用，无需安装 Python）、完整分发包 `NeoProbe-1.10.0-win64.zip` 以及跨平台单文件包 `neoprobe.pyz`。
- **原生 WebView2 桌面窗口**：
  - 双击 `NeoProbe.exe` 直接打开原生桌面窗口，**无黑色命令行窗口、不拉起外部浏览器**。
  - 内置单实例互斥锁（重复双击自动唤醒已有窗口，防止多开）、窗口位置与尺寸自动记忆、支持文件下载以及调用系统默认浏览器打开外部链接。
- **本机直发 UDP 探测与毫秒级抢位**：
  - 本机直发 UDP 并发 A2S 探测（反映真实本机 RTT，默认 15s 自动刷新）。
  - **3 秒 UDP 实时挤服 + 300ms 二次复核**：过滤瞬时假空位，确认空位后自动拉起本机 Garry's Mod 并直连服务器。
  - 自动识别本机 Steam 账号查询 VIP 身份（`identity.php`）、读取可选本机客户端探针（`neoprobe_rounds.json`）及换图/空位节奏统计。
- **`v1.10.0` 全功能整合**：
  - **内置 GOC 奇术终端（训练模式）**：含能量校准、西蒙符印、密码破解、符文转轮 4 关训练与考试计时，打包内置离线背景音乐（`goc-yuai.mp3`）。
  - **内置 RX 美化资源站**：顶栏直连 `rx.l1ght.xyz` OpenList 接口，支持目录浏览、当前页过滤、全站搜索、一键下载、复制直链及清爽列表/原站视图切换。
  - **后台排队常驻**：挂机挤服期间顶部排队状态条全程常驻，切换到 GOC 练手或浏览下载 RX 美化包均不会中断后台 UDP 抢位。
- **保留本地 Web 与全功能 CLI**：同时支持 `--serve` 浏览器面板模式与完整命令行参数（单次/批量探测、JSON 导出、终端监控与 CLI 挤服）。

### 版本二：GitHub Pages 在线网页版（免安装，浏览器即用）

- **访问入口**：
  - 主面板：<https://huyuchengnb-rgb.github.io/neoprobe/>
  - 直达 GOC 奇术终端：<https://huyuchengnb-rgb.github.io/neoprobe/#goc>
  - 直达 RX 美化资源站：<https://huyuchengnb-rgb.github.io/neoprobe/#rx>
- **云端快照 + 浏览器直连倒计时**：
  - **A2S 状态快照**：由 GitHub Actions 每 5 分钟采集全部服务器的 `INFO / PLAYER / RULES` 快照（延迟为云端采集节点视角）。
  - **回合倒计时实时走秒**：访客浏览器每 10 秒直连 `status.php`，完成时间差补偿后在本地按秒递减。
  - **纯网页守候挤服**：零配置轮询快照，检测到空位时触发响铃 + 桌面通知并调用 `steam://connect/<ip>:<port>`。
  - **同样内置 GOC 奇术终端与 RX 美化资源站**：打开浏览器即可直接练习 GOC 四关考试或检索下载 RX 美化包。
- **支持「本机桥接」升级为完整桌面级能力**：
  - 在本机启动桌面版/CLI 并开启跨域白名单后，点击网页右上角「**本机桥接**」，即可在在线网页中获得 **真实本机 RTT 延迟** 与 **3 秒 UDP 实时挤服**：
    ```bash
    NeoProbe.exe --serve --cors-origin https://huyuchengnb-rgb.github.io
    # 或使用 Python 源码 / pyz：
    python -m neoprobe --serve --cors-origin https://huyuchengnb-rgb.github.io
    ```

### 双版本核心能力对照

| 模块 | Windows 独立桌面软件版（`v1.10.0`） | GitHub Pages 在线网页版 |
| --- | --- | --- |
| **获取与运行方式** | [Releases 下载](https://github.com/huyuchengnb-rgb/neoprobe/releases/latest) `NeoProbe.exe`，双击原生窗口即用 | 浏览器访问 [在线地址](https://huyuchengnb-rgb.github.io/neoprobe/)，免安装跨平台 |
| **运行载体** | 原生 WebView2 桌面窗口（无黑框、单实例、记忆窗口） / `--serve` / CLI | 任意现代浏览器 |
| **服务器状态监控** | 本机直发 UDP 并发探测，默认 15s 自动刷新，显示**真实本机 RTT** | GitHub Actions 每 5 分钟采集 A2S 快照（配合本机桥接可切为本机 UDP） |
| **对局与回合倒计时** | 每 10 秒拉取 `status.php` 本地走秒 + 可选本机客户端探针 + 空位/换图节奏观测 | 访客浏览器每 10 秒直连 `status.php`，时间差补偿后本地走秒 |
| **一键进服与自动挤服** | **3 秒一次 UDP 探测 + 300ms 二次复核**，空位自动拉起本机 GMod 直连 | 纯网页守候（响铃 + 桌面通知 + `steam://connect`），或连接**本机桥接**启用 3 秒 UDP 挤服 |
| **GOC 奇术终端** | 内置 4 关训练与考试计时（含本地离线 BGM），挤服时切换练手不中断抢位 | 内置同款 4 关训练与考试计时，顶部排队状态条常驻 |
| **RX 美化资源站** | 顶栏直连 `rx.l1ght.xyz`（目录浏览、过滤、全站检索、下载/复制直链、原站视图切换） | 顶栏直连 `rx.l1ght.xyz`（目录浏览、过滤、全站检索、下载/复制直链、原站视图切换） |
| **身份 / VIP 查询** | 自动识别本机 Steam 账号查询 `identity.php` 并支持到期倒数 | 连接本机桥接或使用本地桌面版查看 |

> [!TIP]
> **一边挤服一边练 GOC / 找美化包**：无论在 Windows 桌面版还是在线网页版挂上挤服队列后，顶部排队状态条都会全程保持可见；切换到「GOC 奇术终端」或「RX 美化资源站」不会中断后台抢位与进服提醒。

---

## 快速开始

### 1. Windows 桌面软件版（推荐日常使用）

1. 前往 [GitHub Releases](https://github.com/huyuchengnb-rgb/neoprobe/releases/latest) 下载 `NeoProbe.exe`（或 `NeoProbe-1.10.0-win64.zip` 解压）。
2. 双击 `NeoProbe.exe` 直接弹出原生桌面窗口（源码环境下双击 `start.cmd` 等效于 `python -m neoprobe --desktop`）。
3. 关闭窗口即完全退出，后台不驻留进程；重复双击会自动激活已打开的窗口。

### 2. Python 源码与 CLI 命令行

```bash
# 1) 打开原生桌面窗口（推荐；打包后的 NeoProbe.exe 双击默认就是此模式）
python -m neoprobe --desktop

# 2) 或者启动本地 Web 面板，通过浏览器访问 http://127.0.0.1:8777/
python -m neoprobe --serve

# 3) 查单台服务器（默认含 status.php 对局回合阶段 / 剩余时间 / 剩余局数）
python -m neoprobe 1.2.3.4:27015

# 4) 带玩家列表和服务器规则（A2S_PLAYER + A2S_RULES）
python -m neoprobe 1.2.3.4:27015 --players --rules

# 5) 一次并发查多台服务器（结果对齐成表格）
python -m neoprobe a.com:27015 b.com:27016 202.189.23.252:27045

# 6) 启动游戏并直接进服（--dry-run 只打印命令不真启动）
python -m neoprobe --launch 1.2.3.4:27015 --dry-run
python -m neoprobe --launch 1.2.3.4:27015

# 7) 自动挤服：满员时持续探测，出现空位并复核通过后自动启动进服
python -m neoprobe --queue 43.249.193.77:27076 --dry-run
python -m neoprobe --queue 43.249.193.77:27076

# 8) 查询本机 Steam 账号身份（是否 VIP、到期天数）
python -m neoprobe --vip

# 9) 终端持续监控（每 5 秒刷新一次）或把收藏列表导出为 JSON
python -m neoprobe 202.189.23.252:27045 -w 5
python -m neoprobe --list --json

# 10) 一键导出可分发成品（exe + pyz + 使用说明 + zip）
python tools/release.py
```

> **安全性说明**：桌面窗口版内置的本地 HTTP 服务仅绑定 `127.0.0.1` 的随机回环端口，供窗口内部 WebView2 消费，关窗口即退出；`--serve` 模式默认固定监听 `http://127.0.0.1:8777/`，同样不对外网暴露。

---

## 面板功能一览

- **多格式地址添加**：支持直接粘贴 `1.2.3.4:27015`、`play.example.com:27015`、`[2001:db8::1]:27015` 或 `steam://connect/1.2.3.4:27015`。
- **批量导入与在线目录同步**：支持一行一个或逗号分隔批量添加（自动去重），同时支持从 `server_catalog.php` 自动合并社区新增服务器。
- **实时 A2S 状态**：在线/离线、人数 `X/Y`、本机真实延迟（多次采样取最优 RTT）、当前地图、Gamemode、VAC 状态。
- **回合与倒计时列**：显示回合阶段 + 本地走秒倒计时 + 剩余局数；已收录但未开局的服显示「空闲 · 无对局」，未上报的服如实显示「未上报 / `—`」并提供空位节奏与本图持续时长参考。
- **展开服务器详情**：查看对局详情、在线玩家列表（名称/得分/在线时长）、完整 `A2S_RULES`、标签、版本、AppID 与一键复制进服命令。
- **一键进服与自动挤服**：未满员显示「进服」（直接拉起 GMod 并 `+connect`），满员自动变为橙色「挤服」（顶部常驻横幅显示当前人数、探测次数与等待时长，抢位成功横幅变绿并自动进服）。
- **GOC 奇术终端（训练模式）**：顶栏一键切换，内置能量校准、西蒙符印、密码破解、符文转轮 4 关训练与考试计时及背景音乐。
- **RX 美化资源站**：顶栏一键切换，直连 `rx.l1ght.xyz` OpenList 接口，支持目录树浏览、当前目录过滤、全站搜索、目录说明查看、一键下载、复制直链与原站视图切换。
- **游戏状态与身份标签**：顶栏实时显示本机 GMod 路径与运行状态（找不到时可手动指定）；右上角显示 `VIP` / `普通用户` 身份标签与剩余天数。
- **自动刷新、排序与过滤**：支持 5/10/15/30/60 秒刷新档位或手动暂停；支持按表头（名称/地图/人数/延迟/模式）排序与关键词实时过滤。
- **本地数据持久化**：保存在 `%LOCALAPPDATA%\NeoProbe\` 下（删除该目录即可恢复初始设置）：
  - `servers.json`：服务器监控清单与配置
  - `window.json`：桌面窗口大小与位置记忆
  - `webview\`：界面排序、筛选等本地偏好
  - `desktop.log`：桌面窗口运行与排障日志

---

## 命令行参数

| 参数 | 说明 |
| --- | --- |
| `ADDR...` | 一个或多个服务器地址 |
| `-p, --players` | 附加查询玩家列表（`A2S_PLAYER`） |
| `-r, --rules` | 附加查询服务器规则（`A2S_RULES`） |
| `-j, --json` | JSON 格式输出，方便接入脚本 |
| `-t, --timeout` | 单次请求超时秒数，默认 `1.5` |
| `-n, --samples` | `A2S_INFO` 采样次数，取最快 RTT，默认 `2` |
| `--retries` | 失败后的短重试次数，默认 `3`（满载服务器易丢 UDP 包） |
| `-w, --watch SEC` | 按指定秒数循环刷新（终端实时监控） |
| `--desktop` | 打开原生 WebView2 桌面窗口（双击 `NeoProbe.exe` 的默认行为，不开浏览器） |
| `--debug-window` | 在桌面窗口中启用开发者工具（排查界面问题） |
| `--serve` | 启动本地 Web 面板（浏览器模式） |
| `--host` / `--port` | 本地 Web 面板监听地址与端口，默认 `127.0.0.1:8777` |
| `--cors-origin URL` | 允许跨域访问本地 API 的来源（供 GitHub Pages 在线版桥接），可多次指定 |
| `--no-browser` | `--serve` 启动面板时不自动打开浏览器 |
| `--add ADDR...` | 仅向收藏列表添加服务器，不执行查询 |
| `--list` | 查询收藏列表中的全部服务器 |
| `--data-dir DIR` | 自定义数据存储目录（默认 `%LOCALAPPDATA%\NeoProbe`） |
| `--no-rounds` | 不查询回合状态 |
| `--rounds-api URL` | 回合接口地址，默认使用原启动器同款 `status.php` |
| `--gmod PATH` | 手动指定 Garry's Mod 目录或 `gmod.exe` 路径，跳过自动探测 |
| `--launch [ADDR]` | 启动游戏；附带服务器地址则直接连服 |
| `--dry-run` | 仅打印将要执行的启动命令，不实际拉起进程 |
| `--vip` | 查询本机 Steam 账号身份（是否 VIP、到期天数） |
| `--vip-expire DATE` | 登记本地 VIP 到期日（`YYYY-MM-DD`），传入空字符串 `""` 清除 |
| `--vip-api URL` | 自定义身份接口地址，默认由 `--rounds-api` 推导 |
| `--queue ADDR` | 自动挤服：持续监视满员服务器，确认空位后自动进服 |
| `--queue-interval SEC` | 挤服 UDP 探测间隔秒数，默认 `3` |
| `--game` | 仅打印本机 Garry's Mod 与 Steam 的检测结果 |

---

## 核心机制详解

### 1. 对局回合信息与倒计时

社区回合接口 `status.php` 返回全局回合快照，按 `ip:port` 匹配：

```json
{"server_time": 1794631318, "servers": [
  {"ip": "202.189.21.228", "port": 31284, "rounds_left": -1,
   "round_time_left": -1, "round_phase": "空闲", "updated_at": 1794631318}]}
```

- **时间差补偿**：`round_time_left` 是服务端数据生成时刻的剩余秒数，客户端按 `server_time - updated_at` 自动扣除传输与缓存延迟（上限 300 秒，与原启动器一致）。
- **本地走秒与限流退避**：面板每 10 秒拉取一次，拿到数据后由前端本地时钟按秒递减，不再高频重复请求（原版每 2 秒轮询一次，单客户端每小时高达 1800 次请求）。该接口设有 **1 次/秒限流**，命中 `{"error": "rate limit exceeded", "retry_after": N}` 时客户端严格按 `retry_after` 自动退避。
- **在线目录同步**：自动从 `server_catalog.php` 同步社区服务器列表，新服上线后重启面板即可自动合入。
- **多级回退与自建上报套件**：
  - 正在游玩的服务器可通过本机客户端探针（`neoprobe_rounds.json`）读取实测回合（列表标注「本机」）。
  - 未接入 `status.php` 的服务器，详情面板会自动提取 `A2S_RULES` 中的回合参数（单局时长 / 准备阶段 / 回合结束 / 总局数上限），并统计实测**空位节奏**（平均多久空出一次位置）与**本图已持续时间**。
  - 仓库随附服务端上报插件 `tools/gmod/neoprobe_reporter.lua` 与接收端 `tools/server/rounds.php`，服主部署后将面板回合接口指向 `rounds.php` 即可获得完整回合倒计时。

### 2. 游戏定位与启动机制

严格对齐原启动器 `LaunchService` 行为，通过注册表（`HKLM\SOFTWARE\WOW6432Node\Valve\Steam` / `HKCU\Software\Valve\Steam`）结合 `libraryfolders.vdf` 自动跨盘定位 Steam 库目录：

| 当前本机状态 | 执行行为 |
| --- | --- |
| 游戏已在运行 + 指定了服务器 | 调用 `steam://rungame/4000/<token>/+connect ip:port` 让 Steam 直接切服 |
| 游戏未运行，已定位到 `gmod.exe` | 直接拉起进程，传参 `-steam -game garrysmod +connect ip:port`，注入环境变量 `SteamAppId=4000` |
| Steam 客户端未启动 | 先拉起 Steam 客户端，提示完成登录后再次点击 |
| 未找到 Garry's Mod | 报错并提示手动指定路径（可在面板顶部「游戏状态」栏直接填写） |

### 3. 自动挤服与 300ms 二次复核

对齐原启动器 `StartServerQueue` 语义，满员服务器点击橙色「挤服」（或命令行 `--queue ADDR`）即可挂机排队。判定空位依据 `players < max_players`，并在原版基础上做了三项关键改进：

| 维度 | 原启动器实现 | NeoProbe 实现 |
| --- | --- | --- |
| **探测间隔 / 超时** | 每 5 秒一次，3 秒超时、单次采样 | **每 3 秒一次**（可调），2 秒超时 + 短重试 |
| **抢位前校验** | 读到一次 `players < max` 立即拉起游戏 | **隔 300ms 二次复核**，连续两次确认空位才启动进服 |
| **探测失败处理** | 直接跳过（`error != null` 不进） | 明确区分「探测超时/丢包」与「真实空位」，失败仅记数并继续守候 |

> **为什么需要 300ms 二次复核**：热门服务器常年 `70/70`，单次采样读到 `69/70` 的瞬时抖动或他人切图瞬间并不少见；若立刻拉起游戏（耗时十余秒），进服时位置早已被占。300ms 二次复核可滤除绝大多数假空位。

同时保留原版两项保护：**预留位提示**（上限 70 且当前人数 ≥ 62 时提示普通玩家可能受预留位限制）与**单队列限制**（同一时刻只盯一台服务器，排队状态保存在内存中）。

### 4. 身份 / VIP 查询与排查记录

原启动器登录后请求 `identity.php?steamid64=...`，将返回的 `identity` 显示为身份信息，并在包含 `"普通用户"` 时触发预留位提醒。NeoProbe 完整保留该判定逻辑并拆解字段展示。

**实测 `identity.php` 服务端返回**（仅含以下 4 个字段，无到期时间）：

```json
{"steamid64":"7656119...","is_admin":false,"is_vip":true,"identity":"VIP"}
```

为此 NeoProbe 设计了兼容性与本地补充方案：

1. **自动识别未来扩展字段**：若服务端后续新增 `vip_expire` / `expires_at` / `vip_until` / `days_left` 等字段（含嵌套结构），或在 `identity` 文本中附带 `"至 2026-12-01"` / `"剩 30 天"`，客户端会自动解析并计算剩余天数。
2. **如实展示与本地到期日登记**：当服务端未返回到期字段时，界面如实标注「服务端未提供」，并提供**本地登记到期日**功能（手动填写后自动倒数，明确标注「本地记录（手动填写）」，绝不伪装成服务端数据）。
3. **支持自定义身份接口**：可通过 `--vip-api URL` 或面板「设置身份接口」随时切换至其他返回到期时间的后台接口。
4. **SteamID64 定位与限流保护**：优先读取 Steam 目录 `config/loginusers.vdf` 中最近登录账号（`MostRecent` 优先，其次取最大时间戳），回退读取注册表 `HKCU\Software\Valve\Steam\ActiveProcess\ActiveUser`。鉴于 `identity.php` 同样存在 **1 次/秒限流**，身份结果本地缓存 5 分钟、后台每 10 分钟刷新一次。

<details>
<summary><b>附：VIP 到期时间接口排查记录（点击展开）</b></summary>

按「不侵入游戏进程」原则排查过的全部客户端可见途径：

| 排查途径 | 实测结果 |
| --- | --- |
| `identity.php` 原样返回 | 仅 4 个基础字段，无到期时间 |
| `identity.php?detail=1` / `?full=1` / `?fields=...` | 仍为同一 4 字段（高频请求返回 429） |
| `vip.php` / `membership.php` / `user.php` / `profile.php` / `vip_info.php` | 全部 404 |
| HTTP 响应头 | 无自定义扩展字段 |
| 站点根目录 | 仅为更新器下载页 |
| 启动器内置捐赠页 / 规则页（kdocs） | 需 WPS 账号登录 |
| 客户端创意工坊合集（286 项）与本地 `addons` | 均为模型/内容包，无 VIP 逻辑插件 |
| 服务端下发的客户端 Lua 缓存（7672 个文件） | 二进制格式，不可读 |
| 兑换服 396 条 `A2S_RULES` | 无相关 URL 或到期提示 |
| 域名子域枚举 | 本地代理解析为 fake-IP（`198.18.x.x`），无额外子站 |
| FastDL（`/fastdl/` 等常见路径） | 404 |

**结论**：VIP 到期时间不存在于任何客户端可见的公开 HTTP/A2S 接口中（可能仅存于服务端内部数据库或游戏内 ULX/点券面板）。因此客户端如实显示「服务端未提供」并开放本地登记与字段自适应。

</details>

---

## 性能优化与原启动器对比

### 性能优化指标

遵循三条工程原则：**请求路径上不做重活**、**数据未变绝不重复序列化**、**冷路径模块按需延迟导入**。

| 指标 | 优化前 | 当前表现 | 核心优化手段 |
| --- | --- | --- | --- |
| **CLI 冷启动（`-V`，含 site 开销）** | 631 ms | **382 ms** | 移除 `dataclasses`（避免连带导入 `inspect`/`enum` 耗时 ≈90ms），`urllib` / `webbrowser` / `pkgutil` 改为按需函数内导入（省 ≈130ms） |
| **每秒轮询网络载荷** | 9.7 KB/s | **24 B/s** | 新增轻量心跳接口 `/api/pulse`（仅返回 `{"ok":true,"rev":[10,0]}`），版本号变化时才拉取 `/api/state` 全量快照 |
| **全量快照 JSON 序列化** | 0.11 ms/次（每秒触发） | **0 ms（命中缓存）** | 状态未变更时直接复用上一次序列化好的 `bytes` |
| **本机游戏进程检测** | 10 ms（每 2 秒阻塞 HTTP 线程） | **0.7 ms（移出请求路径）** | 缓存 `gmod.exe` PID，常规探活用 `OpenProcess + GetExitCodeProcess`（≈30 µs）；仅在启动/退出时于后台线程执行 `CreateToolhelp32Snapshot` 全量枚举（≈7 ms） |
| **空闲 CPU（3 页面同时轮询）** | 0.90% 单核 | **0.68% 单核** | `/api/pulse` 轻量心跳 + 后台 PID 快路径探活 + `HTTP/1.1` Keep-Alive 复用 TCP 连接 |
| **私有内存占用（Private）** | 24.9 MB | **21.9 MB** | 精简常驻导入模块 + 核心值对象改用 `__slots__` |

### 相比原启动器（`RelayGate`）改了什么

| 对比项 | 原启动器实现（`RelayGate.ServerQueryService`） | NeoProbe 实现 |
| --- | --- | --- |
| **服务器地址管理** | 9 台服务器硬编码在 `ServerCatalog` 中 | 支持任意地址运行时增删，自动同步 `server_catalog.php` |
| **A2S Challenge 握手** | 每轮重试均重新发起握手 | 同会话缓存 Challenge 30 秒，大幅减少往返包 |
| **Source 分包重组** | 仅支持 10/12 字节头的未压缩分包，遇压缩包直接抛异常 | 锚点探测包头长度（兼容 4 种包头布局）+ 完整支持 `bzip2` 解压 |
| **采样与重试策略** | 固定跑满 N 次循环，成功后也不提前退出 | 采样次数可配，成功即止，失败短重试不重复解析同一包 |
| **C 字符串解码** | 逐字节塞入 `List<byte>` 再 `ToArray` | 直接在 `memoryview` / `buffer` 上定位 `\0` 切片解码 |
| **线程与 UI 模型** | WinForms `Timer` + `ThreadPool` 回调阻塞 UI 线程 | 后台线程池并发采样 + 本地 HTTP 快照缓存，前端读取零阻塞 |
| **`A2S_RULES` 查询** | 每次刷新全表时无条件附带查询（每台服多 2 个 RTT） | 列表刷新只查 `INFO`，仅在点开服务器详情时按需查 `RULES` |
| **回合数据轮询** | 固定 2 秒轮询，忽略服务端限流 | 默认 10 秒轮询，严格遵守 `retry_after` 退避，前端本地按秒走秒 |
| **启动前进程判定** | 单次点击触发约 9 次全系统进程枚举 | 后台单次 Toolhelp 快照 + PID 缓存快路径 |
| **自动挤服机制** | 5 秒探测窗口 + 单次采样，读到空位立刻拉起 | **3 秒探测 + 300ms 二次复核**，探测报错与真实空位严格区分 |

> 注：原版 `client.conf` 中的 `202.189.7.25:27265` 目前整段主机已无在线实例（超时），其余三个节点（`43.249.193.77:27076`、`202.189.23.252:27045`、`202.189.21.228:27265`）均正常在线。

---

## 已收录的服务器（10 台）

默认清单已内置原启动器 `ServerCatalog.CreateDefault()` 的 9 台服务器及 `status.php` 上报的兑换服（也可一键复制至面板「批量添加」）：

| 备注名称 | 服务器地址 | 常见状态与回合覆盖说明 |
| --- | --- | --- |
| **mio服①** | `43.249.193.77:27076` | 在线 70/70 |
| **mio服②** | `43.249.193.77:27265` | 在线 70/70 |
| **mio服③** | `43.249.193.77:27852` | 在线 70/70 |
| **mio服④** | `202.189.23.252:27045` | 在线 70/70 |
| **mio服⑤** | `202.189.23.252:27235` | 在线 69/70 |
| **mio服⑥** | `202.189.23.252:27265` | 在线 70/70 |
| **娘娘测试服** | `202.189.21.228:27076` | 在线 70/70，`status.php` 提供实时回合数据 |
| **白菜测试服** | `202.189.21.228:27265` | 在线 70/70，`status.php` 提供实时回合数据 |
| **猫娘窝测试服** | `202.189.21.228:27852` | 在线 69/70，`status.php` 提供实时回合数据 |
| **兑换服** | `202.189.21.228:31284` | 在线 3/64，`status.php` 已收录但回合字段恒为 `-1`（显示「空闲」） |

如需扫描相关主机网段确认是否有新增端口实例（仅发送标准 `A2S_INFO` 请求）：

```bash
python tools/scan_ports.py 43.249.193.77 202.189.23.252 202.189.21.228
python tools/scan_ports.py --ports 27000-27900,31000-32000 --timeout 1.6 202.189.21.228
```

> 满载服务器在高峰期约有 20% 的单次 UDP A2S 丢包率，因此 NeoProbe 默认启用 `--retries 3` 短重试保障列表稳定。

---

## GitHub Pages 在线网页版部署与预览

仓库内置了完整的静态网页版（[`docs/index.html`](docs/index.html)、[`docs/goc.html`](docs/goc.html)）与定时采集部署工作流（[`.github/workflows/pages.yml`](.github/workflows/pages.yml)）：

1. **云端定时采集**：GitHub Actions 每 5 分钟执行一次 `python tools/build_pages.py --out _site`，并发采集全部服务器的 `INFO / PLAYER / RULES` 生成 `data/state.json` 并直接发布至 GitHub Pages（不会向 `main` 分支刷自动提交记录）。
2. **Fork 后开启 Pages 步骤**：
   - 将仓库推送到你的 GitHub 账号下（`main` 分支）。
   - 打开仓库 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。
   - 进入 **Actions → Deploy NeoProbe Pages** 手动点击一次 **Run workflow**（或等待定时任务触发），部署完成后即可通过 `https://<你的用户名>.github.io/<仓库名>/` 访问。
3. **本地构建与预览网页版**：
   ```bash
   python tools/build_pages.py --out docs --skip-copy
   python -m http.server -d docs 8080
   ```

---

## 导出与打包分发（`v1.10.0`）

```bash
python tools/release.py            # 一键产出全套成品：exe + pyz + 使用说明 + zip
python tools/release.py --pyz-only # 未安装 PyInstaller 的环境下仅生成 .pyz
```

产物统一输出在 `dist/` 目录：

| 产物文件 | `v1.10.0` 体积 | 说明 |
| --- | --- | --- |
| `NeoProbe.exe` | **15.4 MB** | Windows 64 位免安装单文件桌面程序，**无需安装 Python**，双击直接打开原生 WebView2 窗口 |
| `NeoProbe-1.10.0-win64.zip` | **17.9 MB** | 完整发行压缩包：含 `NeoProbe.exe`、`使用说明.txt`、备用 `neoprobe.pyz` 及技术说明 |
| `neoprobe.pyz` | **2.6 MB** | 纯 Python 标准库跨平台单文件归档（需本机已安装 Python 3.10+） |

- **体积构成说明**：`v1.10.0` 将原生 WebView2 桌面壳、完整的 **GOC 奇术终端（含离线背景音乐 `goc-yuai.mp3`）** 与 **RX 美化资源站** 全部打包进了离线资源中（静态资源通过 `sys._MEIPASS` / `pkgutil.get_data` 读取，本地 HTTP 服务支持 `Range` 分片音频流）；因此相比早期纯文本面板，`neoprobe.pyz` 为 2.6 MB，而内嵌了 CPython 运行时的单文件 `NeoProbe.exe` 为 15.4 MB。若仅需打包不含额外发行附件的 `.pyz`，也可直接运行 `python tools/pack.py`。
- **双击与命令行兼容**：
  - 直接双击 `NeoProbe.exe`（无参数）默认等同于 `--desktop`，启动原生 WebView2 桌面窗口。
  - 若在老旧 Win10 上未安装 WebView2 运行时，可根据弹窗引导安装微软官方运行时，或使用 `NeoProbe.exe --serve` 切换为浏览器模式（配合环境变量 `NEOPROBE_NO_BROWSER=1` 可静默启动后台服务）。
  - 所有 CLI 参数对 `NeoProbe.exe` 与 `neoprobe.pyz` 均可用（例如 `NeoProbe.exe --vip` 或 `python neoprobe.pyz --help`）。
- **Windows SmartScreen 提示**：由于未购买商业代码签名证书，首次在 Windows 上运行 `NeoProbe.exe` 时若遇到「Windows 已保护你的电脑」拦截，点击「**更多信息 → 仍要运行**」即可。可执行文件已内嵌完整的版本属性与多尺寸高清图标（256/128/64/48/32/16）。

---

## 自动化测试（93 个单元测试）

协议解析与业务状态机拥有完整的离线单元测试套件，通过 `tests/mock_server.py` 在本地模拟真实 Source 服务器（涵盖强制 Challenge 握手、3 包分包、4 种包头布局、`bzip2` 压缩分包及 EDF 扩展字段）：

```bash
python -m unittest discover -s tests -v
```

- **测试覆盖范围（共 93 个用例）**：地址解析（IPv4 / 域名 / IPv6 / `steam://`）、Challenge 握手、分包重组、压缩分包、玩家列表、服务器规则、超时与端口关闭、Gamemode 推断、回合解析与时间差补偿、限流退避、服务器目录同步、本机客户端探针读取、换图与空位节奏观测、启动命令构造、GMod 路径归一化（根目录 / `gmod.exe` / `bin\win64`）、挤服状态机、VIP 字段兼容与日期解析、GitHub Pages 静态快照构建及本机桥接 CORS 校验。
- **本地模拟回合接口测试**：
  ```bash
  python tests/mock_rounds_api.py 8799
  python -m neoprobe --serve --rounds-api http://127.0.0.1:8799/status.php
  ```
- **前端调试技巧**：面板 URL 支持 `#open=1.2.3.4:27015` 自动展开指定服务器详情；附加 `?probe=1` 会将渲染状态实时写入页面标题；附加 `?vip=1` 可直接展开 VIP 身份详情弹窗。

---

## 目录结构

```text
neoprobe/
  __init__.py         包入口与版本号定义（v1.10.0）
  __main__.py         CLI 命令行入口
  a2s.py              Source A2S 协议实现（INFO / PLAYER / RULES、分包重组、Challenge 缓存）
  rounds.py           回合接口与目录客户端（status.php / server_catalog.php、时间差补偿、限流退避）
  clientstate.py      本机客户端探针读取（neoprobe_rounds.json 打分挑选）
  slots.py            空位与换图节奏观测（按玩家名单对比统计）
  launch.py           游戏定位与启动（注册表 / libraryfolders.vdf / 进程快照与 PID 快路径）
  queue.py            自动挤服状态机（满员监视 → 300ms 空位二次复核 → 自动拉起进服）
  vip.py              身份查询（本机 SteamID64 定位 / identity.php / 到期字段自适应与本地登记）
  manager.py          清单持久化 + 后台并发查询 + 回合轮询 + 游戏状态缓存
  server.py           本地 HTTP/1.1 服务 + JSON API（含 /api/pulse）+ 静态资源（含 Range 音频流支持）
  desktop.py          原生 WebView2 桌面窗口壳（单实例互斥 / 窗口位置记忆 / 支持下载与外链打开）
  web/
    index.html        桌面与本地 Web 统一面板（服务器监控 + GOC 奇术终端 + RX 美化资源站）
    goc.html          内置 GOC 奇术终端 · 训练模式页面（4 关训练与考试计时）
    favicon.png       面板图标
    assets/
      goc-yuai.mp3    内置 GOC 训练默认离线背景音乐（雨爱）
tools/
  entry.py            PyInstaller exe 启动入口（双击无参数默认进入 --desktop 原生桌面窗口）
  release.py          一键构建发行版（NeoProbe.exe + neoprobe.pyz + 使用说明.txt + win64.zip）
  build_pages.py      构建 GitHub Pages 静态站点与并发采集 A2S 快照（data/state.json）
  pack.py             打包纯标准库单文件 dist/neoprobe.pyz
  make_icon.py        生成多尺寸应用图标（assets/neoprobe.ico）
  version_info.txt    Windows exe 版本属性描述文件
  scan_ports.py       UDP 端口扫描工具（排查同主机其他 Source 实例）
  orig_rounds_probe.py                  对照原启动器 status.php 解析结果
  roundwatch.py / groundtruth.py / gt_analyze.py  回合边界观测与校验脚本
  gmod/               可选 GMod 客户端探针与服务端回合上报 Lua 插件（neoprobe_reporter.lua）
  server/             配套 PHP 回合数据接收端（rounds.php）
docs/
  index.html          GitHub Pages 在线网页版主面板（直连 status.php + 消费 A2S 快照 + 本机桥接）
  goc.html            GitHub Pages 在线版 GOC 奇术终端页面
  favicon.png         站点图标
  assets/
    goc-yuai.mp3      在线版默认背景音乐（雨爱）
  data/
    state.json        初始 A2S 快照（Actions 部署时自动生成最新 _site/data/state.json）
.github/workflows/
  pages.yml           每 5 分钟定时采集 A2S 快照并部署 GitHub Pages 工作流
assets/
  neoprobe.ico        Windows 应用图标（含 256/128/64/48/32/16 六种尺寸）
  neoprobe.png        高清 PNG 图标
dist/                 打包导出产物目录（NeoProbe.exe / NeoProbe-1.10.0-win64.zip / neoprobe.pyz）
tests/
  mock_server.py      本地模拟 Source 服务器（Challenge / 分包 / bzip2 压缩）
  mock_rounds_api.py  本地模拟 status.php 回合接口
  test_a2s.py          14 个用例
  test_catalog.py       7 个用例
  test_clientstate.py  10 个用例
  test_mapinfo.py       4 个用例
  test_pages.py         5 个用例
  test_rounds_launch.py 20 个用例
  test_queue.py         9 个用例
  test_slots.py         8 个用例
  test_vip.py          16 个用例
```

---

## 致谢与说明

- **协议与设计参考**：A2S 探测、游戏拉起与回合接口对齐自原启动器 `RelayGate.ServerQueryService`、`LaunchService` 与 `ServerRoundsApiClient`，在此基础上使用纯 Python 标准库重写并修复了分包解压、限流退避与假空位抢位等痛点。
- **GOC 奇术终端（训练模式）**：整合自 [bairen048-design/RXSEND](https://bairen048-design.github.io/RXSEND/)（原作者：B 站 **小小白仁ovo**），内置于桌面版与在线网页版顶栏，支持挂机挤服期间同屏练习。
- **RX 美化资源站**：数据直连 [rx.l1ght.xyz](https://rx.l1ght.xyz/)（**Powered by L1gHT**，基于 OpenList 接口），支持目录浏览、搜索、直链复制与原站视图切换。
- **安全与隐私边界**：
  - 所有服务器探测均为只读标准 Valve A2S 查询，查询频率与手动打开 Steam 服务器浏览器相当；「启动游戏 / 进服」仅在用户主动点击或传入 `--launch` / `--queue` 时触发本地 Steam / GMod。
  - 本地桌面版与 `--serve` 默认只监听 `127.0.0.1` 回环地址，不对外网暴露；若自行修改 `--host` 对外共享，请注意 UDP 探测将使用运行机器的出口 IP。
