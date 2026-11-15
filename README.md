# NeoProbe

把 Neobreach 启动器里那几样有用的能力单独拎出来，做成一个**能查任意地址**的小工具：

- **服务器状态**：在线、人数、延迟、地图、gamemode、玩家列表、400 条服务器规则
- **对局信息**：回合阶段、剩余时间（本地走秒）、剩余局数
- **启动游戏**：一键启动 Garry's Mod，或直接连进某台服务器
- **自动挤服**：满员的服务器挂上排队，一有空位自动进服
- **身份 / VIP**：查本机 Steam 账号是不是 VIP、有没有到期时间、还剩几天

协议层按 `RelayGate.ServerQueryService`（A2S）与 `LaunchService` / `ServerRoundsApiClient` 重写，
同时修掉了原版几个硬伤。

纯标准库，不需要 pip 安装任何东西。Python 3.10+。

---

## 快速开始

```bash
# 1) 查一台服务器
python -m neoprobe 1.2.3.4:27015

# 2) 带玩家列表和 400 条服务器规则
python -m neoprobe 1.2.3.4:27015 --players --rules

# 3) 一次查多台（并发，结果对齐成表格）
python -m neoprobe a.com:27015 b.com:27016 202.189.23.252:27045

# 4) 看对局（回合阶段 / 剩余时间 / 剩余局数）
python -m neoprobe 1.2.3.4:27015

# 5) 启动游戏并直接进服（--dry-run 只打印命令不真启动）
python -m neoprobe --launch 1.2.3.4:27015 --dry-run
python -m neoprobe --launch 1.2.3.4:27015

# 6) 自动挤服：满员就一直等，出现空位自动进服
python -m neoprobe --queue 43.249.193.77:27076 --dry-run
python -m neoprobe --queue 43.249.193.77:27076

# 7) 查自己的身份（是否 VIP、到期天数）
python -m neoprobe --vip

# 8) 导出成可直接分发的成品（exe + zip）
python tools/release.py

# 9) 起一个本地面板（推荐，浏览器里点点就行）
python -m neoprobe --serve
```

Windows 下双击 `start.cmd` 等效于第 4 条。

面板默认地址 <http://127.0.0.1:8777/>，只监听本机回环，不对外暴露。

---

## 面板能做什么

- **添加任意地址**：`1.2.3.4:27015`、`play.example.com:27015`、`[2001:db8::1]:27015`、
  `steam://connect/1.2.3.4:27015` 都能直接粘
- **批量添加**：点「批量添加」，一行一个，逗号也认；重复的自动跳过
- **实时状态**：在线/离线、人数 X/Y、延迟（取多次采样最优值）、地图、gamemode、VAC
- **回合列**：回合阶段 + 倒计时（本地走秒，不重复请求）+ 剩余局数；接口没数据的服显示 `—`
- **点开一行看详情**：对局状态、玩家列表（名字/分数/在线时长）、全部 A2S_RULES、标签、版本、AppID、进服命令
- **进服**：每行一个「进服」按钮，直接启动 GMod 并 `+connect`；工具栏「启动游戏」则只启动不连服
- **游戏状态**：顶部显示是否找到 GMod / 是否在运行，点一下复制路径，找不到时可手动填写
- **身份标签**：右上角显示 `VIP` / `普通用户`（有到期日时显示剩余天数），点开看详情
- **自动刷新**：5/10/15/30/60 秒可选，可随时暂停；切到别的标签页会自动暂停省资源
- **排序与过滤**：点表头排序（名称/地图/人数/延迟/模式），输入框实时过滤
- **清单持久化**：存在 `%LOCALAPPDATA%\NeoProbe\servers.json`，下次打开还在

---

## 命令行参数

| 参数 | 说明 |
| --- | --- |
| `ADDR...` | 一个或多个服务器地址 |
| `-p, --players` | 附加查询玩家列表（A2S_PLAYER） |
| `-r, --rules` | 附加查询服务器规则（A2S_RULES） |
| `-j, --json` | JSON 输出，方便接脚本 |
| `-t, --timeout` | 单次请求超时秒数，默认 1.5 |
| `-n, --samples` | INFO 采样次数，取最快 RTT，默认 2 |
| `--retries` | 失败后的短重试次数，默认 3（满载服务器会丢包） |
| `-w, --watch SEC` | 循环刷新（终端里当监控用） |
| `--serve` | 启动本地 Web 面板 |
| `--host` / `--port` | 面板监听地址/端口，默认 127.0.0.1:8777 |
| `--no-browser` | 启动面板时不自动开浏览器 |
| `--add ADDR...` | 只往收藏列表里加，不查询 |
| `--list` | 查收藏列表里的全部服务器 |
| `--data-dir DIR` | 自定义数据目录 |
| `--no-rounds` | 不查回合状态 |
| `--rounds-api URL` | 回合接口地址，默认启动器用的 `status.php` |
| `--gmod PATH` | 指定 Garry's Mod 目录或 exe，跳过自动探测 |
| `--launch [ADDR]` | 启动游戏；带地址则直接进服 |
| `--dry-run` | 只打印将要执行的启动命令 |
| `--vip` | 查本机 Steam 账号的身份（是否 VIP、到期天数） |
| `--vip-expire DATE` | 登记本地到期日（YYYY-MM-DD），空串清除 |
| `--vip-api URL` | 身份接口地址，默认由 `--rounds-api` 推导 |
| `--queue ADDR` | 自动挤服：等空位后自动进服 |
| `--queue-interval SEC` | 挤服探测间隔，默认 3 |
| `--game` | 只打印 GMod / Steam 的检测结果 |

示例：

```bash
# 每 5 秒刷新，盯着看人数
python -m neoprobe 202.189.23.252:27045 -w 5

# 把收藏列表导出成 JSON 给别处用
python -m neoprobe --list --json
```

---

## 对局信息从哪来

`status.php` 返回的是全局回合表，靠 `ip:port` 匹配：

```json
{"server_time": 1794631318, "servers": [
  {"ip": "202.189.21.228", "port": 31284, "rounds_left": -1,
   "round_time_left": -1, "round_phase": "空闲", "updated_at": 1794631318}]}
```

两个细节：

1. **时间差补偿**：`round_time_left` 是"数据生成那一刻"的剩余秒数，要按
   `server_time - updated_at` 补掉路上的延迟（上限 300 秒，和原启动器一致）。
2. **本地走秒**：拿到一次数据后，界面自己按秒递减，不再重复请求 —— 原版是每 2 秒拉一次，
   单客户端每小时 1800 次。这个接口有 **1 次/秒的限流**，命中会回
   `{"error": "rate limit exceeded", "retry_after": N}`，客户端按 `retry_after` 退避。

接口没覆盖到的服务器（很常见 —— 只有装了上报插件的服才有数据），详情面板会退一步展示
`A2S_RULES` 里的**回合参数**（单局时长 / 准备阶段 / 回合结束 / 总局数上限），至少能看出节奏。

## 启动游戏做了什么

对齐原 `LaunchService`：

| 情况 | 行为 |
| --- | --- |
| 游戏在运行 + 指定了服务器 | `steam://rungame/4000/<token>/+connect ip:port` 让 Steam 切服 |
| 游戏未运行，找到了 gmod.exe | 直接起进程，参数 `-steam -game garrysmod +connect ip:port`，环境变量 `SteamAppId=4000` |
| Steam 没起来 | 先把 Steam 叫起来，提示登录后再点一次 |
| 找不到游戏 | 报错并提示手动指定路径（面板里点游戏状态那栏即可填写） |

自动定位走注册表（`HKLM\SOFTWARE\WOW6432Node\Valve\Steam` / `HKCU\Software\Valve\Steam`）
+ 解析 `libraryfolders.vdf`，所以装在 D 盘的库也能找到。

## 自动挤服

对齐原 `StartServerQueue` 的语义：满员服务器挂上排队，一有空位就自动启动并进服。

**面板**：满员的服务器那一行，「进服」会变成橙色的「挤服」。点一下就开始排队，
顶栏出现一条横幅——服务器、当前人数、探测次数、已等时长，排队中的那一行变成
「排队 03:12」，随时可以取消。抢到空位时横幅变绿并提示已进服。

**命令行**：

```bash
python -m neoprobe --queue 43.249.193.77:27076            # 一直等，有空位就进
python -m neoprobe --queue 43.249.193.77:27076 --dry-run  # 只看会执行什么命令
python -m neoprobe --queue 1.2.3.4:27015 --queue-interval 3
```

判断"有没有空位"用的是 `players < max_players`。三个和原版不同的地方：

| 项 | 原实现 | 这里 |
| --- | --- | --- |
| 探测间隔 / 超时 | 每 5 秒，3 秒超时、1 次采样 | 每 3 秒（可调），2 秒超时 + 短重试 |
| 抢位前 | 读到一次 `players < max` 立刻启动 | 隔 300ms **复核一次**，两次都是空位才进 |
| 探测失败 | 直接跳过（`error != null` 就不进） | 明确区分"失败"和"有空位"，失败只记错误继续等 |

第二条是实测出来的：这 9 台常年 70/70，一次采样读到 69 的概率不低，但等你把游戏拉起来
（十几秒）位置早被抢了。复核能把这种假空位挡掉大半。

另外照原版保留了两处行为：**预留位提示**（上限 70、人数 ≥62 时提醒"普通玩家可能挤不进"），
以及**一次只排一台**（已有排队时再点会提示先取消）。

限制：排队状态存在内存里，面板重启就没了（原版关掉窗口也会丢）；也只盯一台服务器，
不支持"哪台先空先进"。

## 身份 / VIP

原启动器在登录后会请求 `identity.php?steamid64=...`，把返回的 `identity` 直接显示成"身份信息"，
并在 `identity` 里含"普通用户"时判定为普通用户（连服时提示可能因预留位进不去）。
这里保留同一套判定，并把字段拆开来看。

**实测服务端返回**（就这四个字段）：

```json
{"steamid64":"7656119...","is_admin":false,"is_vip":true,"identity":"VIP"}
```

**没有到期时间。** 我查了响应头、`vip.php` / `membership.php` / `user.php` 等常见路径（都 404）、
网站首页（只是更新器下载页），以及 `identity.php` 加 `detail=1` 等参数，都没有任何到期字段。
所以：

- 服务端哪天加了字段（`vip_expire` / `expires_at` / `vip_until` / `days_left` ...），这里**自动识别**，
  嵌套结构也吃得下；`identity` 文本里带 "至 2026-12-01" 或 "剩 30 天" 也能解析出来
- 服务端什么都不给时，界面如实显示"服务端未提供"，并提供**本地登记到期日**：填一次就倒数，
  且明确标注"本地记录（手动填写）"，绝不会伪装成服务器数据
- **接口地址可换**：`--vip-api URL` 或面板「设置身份接口」。哪天找到真正返回到期时间的接口
  （商店后台、兑换记录查询等），填进去即可，不用改代码——字段名照样自动识别

面板：右上角一个身份标签——`VIP`（绿）/`普通用户`（灰），有到期日时显示 `VIP · 剩 12 天`；
点开是详情面板：身份、是否 VIP、到期时间、剩余天数、SteamID、数据来源、查询时间，以及
「刷新」「登记本地到期日」。也可用 `?vip=1` 直接展开。

CLI：

```bash
python -m neoprobe --vip
python -m neoprobe --vip-expire 2026-12-01   # 登记本地到期日
python -m neoprobe --vip-expire ""           # 清除
python -m neoprobe --vip --vip-api https://example.com/vip.php   # 换一个身份接口
```

### 找到期时间这件事，查到哪儿了

按"能不碰游戏就不碰"的顺序排查过：

| 途径 | 结果 |
| --- | --- |
| `identity.php` 原样返回 | 只有 4 个字段，无到期 |
| `identity.php?detail=1` / `?full=1` / `?fields=...` | 还是那 4 个字段（或 429） |
| `vip.php` / `membership.php` / `user.php` / `profile.php` / `vip_info.php` | 全 404 |
| 响应头 | 无自定义字段 |
| 网站根目录 | 只有更新器下载页 |
| 启动器里的捐赠页 / 规则页（kdocs） | 需要 WPS 登录 |
| 客户端工作坊合集（286 项）与本地 addons | 只有模型/内容包，无 VIP 插件 |
| 服务端下发的 Lua 缓存（7672 个文件） | 二进制，不可读 |
| 兑换服的 396 条 A2S_RULES | 无任何 URL / 中文提示 |
| 域名子域枚举 | 本机代理返回 fake-IP（198.18.x.x），无效 |
| FastDL（`/fastdl/` 等常见路径） | 404 |

结论：**到期时间不在任何客户端可见的接口里**。要么服务端本来就没有这个概念（VIP 由管理员手动开通、
长期有效），要么只存在于服务端的数据库和游戏内面板里。所以这里如实显示"服务端未提供"，
同时留好两条路：服务端加字段（自动识别），或本地登记。

SteamID64 从本机取：优先 `config/loginusers.vdf` 里最近登录的账号（`MostRecent` 优先，
其次时间戳最大），取不到再读注册表 `HKCU\Software\Valve\Steam\ActiveProcess\ActiveUser`。
身份查询缓存 5 分钟、后台每 10 分钟刷一次——`identity.php` 有 **1 次/秒**的限流，
刷太勤会直接 429。

## 性能

三条原则：**请求路径上不做重活**、**没变化就不重复算**、**用不到的东西不导入**。

| 指标 | 优化前 | 现在 | 怎么来的 |
| --- | --- | --- | --- |
| 启动（`-V`，含 site 开销） | 631 ms | 382 ms | 去掉 `dataclasses`（连带 `inspect`），`urllib` / `webbrowser` / `pkgutil` 改按需导入 |
| 每秒轮询载荷 | 9.7 KB | **24 B** | 新增 `/api/pulse`，只回一个版本号 |
| 全量快照序列化 | 0.11 ms/次，每秒一次 | 0（命中缓存） | 数据没变就复用上次的 bytes |
| 游戏状态检测 | 10 ms，每 2 秒压在 HTTP 请求里 | 0.7 ms，且**不在请求路径** | Toolhelp 全量枚举 ≈7 ms，改为后台线程 + PID 快路径 |
| 空闲 CPU（3 个页面轮询） | 0.9% 单核 | 0.68% 单核 | 上面两项 |
| 内存（Private） | 24.9 MB | 21.9 MB | 少导入模块 + `__slots__` 值对象 |
| 分发体积 | 源码目录 285 KB | 单文件 **47 KB** | `python tools/pack.py` |

几个关键点：

**1. 每秒的轮询不该拉全量。** 前端原来每秒 `/api/state`，把 10 台服务器的完整快照（含玩家对象、回合状态、
历史点）重新序列化一遍。现在每秒只问 `/api/pulse`，服务端回 `{"ok":true,"rev":[10,0]}`——24 字节；
版本号变了才去拉全量。数据每 15 秒才变一次，等于 15 次里 14 次是白拉。

**2. 进程枚举不能放在请求里。** 判断"游戏在不在跑"要枚举全部进程（这台机器约 400 个），
`CreateToolhelp32Snapshot` 一次 7 ms。原来每 2 秒在 HTTP 线程里做一次，就是那 0.35% 的空闲 CPU。
现在：记住 gmod 的 PID，之后每 30 µs 用 `OpenProcess + GetExitCodeProcess` 探活；
真需要重新枚举时（游戏刚启动/退出）才扫一次，并且放到后台线程，请求永远不阻塞。

**3. 启动时间。** `dataclasses` 为了生成 `__init__` 会拉 `inspect`/`enum`，光 import 就 90 ms；
两个值对象换成 `__slots__` 手写 `__init__` 就够了。`urllib.request` 会连带 `http.client`/`email`/`ssl`
约 130 ms，而只有真要联网时才需要它，改成函数内导入。

**4. 长连接。** 默认 `BaseHTTPRequestHandler` 是 HTTP/1.0，每次轮询都新建一条 TCP。改成 1.1 后
`curl` 连续请求的 `num_connects` 从 1,1,1 变成 1,0,0，浏览器侧也不再反复握手。

想压成单文件带走：

```bash
python tools/pack.py          # 生成 dist/neoprobe.pyz（47 KB，纯标准库）
python dist/neoprobe.pyz --serve
```

`.pyz` 里 `web/index.html` 在 zip 内不是真实路径，所以静态资源读取用 `pkgutil.get_data` 兜底——
这点在源码模式下不会走到。

## 相比原启动器改了什么

| 项 | 原实现（RelayGate.ServerQueryService） | 这里 |
| --- | --- | --- |
| 地址 | 9 台写死在 `ServerCatalog` 里 | 任意地址，运行时增删 |
| challenge | 每轮重试都重新握手 | 缓存 30 秒，同会话复用 |
| 分包 | 只支持 10/12 字节头的未压缩分包，压缩包直接抛异常 | 用锚点探测头长度（兼容 4 种布局）+ bzip2 解压 |
| 重试 | 固定跑满 N 次，成功也不 break | 采样次数可配，失败不重试同一包 |
| 字符串解码 | 逐字节塞 `List<byte>` 再 `ToArray` | 直接在 buffer 上定位 `\0` |
| 线程模型 | WinForms `Timer` + `ThreadPool`，结果回 UI 线程 | 后台线程池 + 本地 HTTP，UI 只读快照 |
| 规则查询 | 每次刷新都查（2 个额外 RTT） | 只在打开详情时按需查 |
| 回合数据 | 固定 2 秒轮询，忽略限流 | 默认 10 秒，尊重 `retry_after` 退避；前端本地走秒 |
| 启动判定 | 一次点击 ≈ 9 次全进程枚举 | 一次 Toolhelp 快照搞定 |
| 自动挤服 | 5 秒窗口 + 单次采样，读到空位立刻启动 | 3 秒探测 + 抢位前复核，失败不误判 |

顺带一提：原版 `client.conf` 里的 `202.189.7.25:27265` 目前是超时状态，
其余三个节点（`43.249.193.77:27076`、`202.189.23.252:27045`、`202.189.21.228:27265`）正常。

---

## 自测

协议实现有一组不依赖外网的单元测试，用 `tests/mock_server.py` 模拟真实服务器：
强制 challenge、3 包分包、四种包头布局、bzip2 压缩、EDF 扩展字段。

```bash
python -m unittest discover -s tests -v
```

覆盖：地址解析（IPv4/域名/IPv6/steam://）、challenge 握手、分包重组、压缩分包、
玩家、规则、超时、端口关闭、gamemode 推断、回合解析与时间补偿、限流响应、服务器目录同步、
客户端状态读取、换图与空位观测、启动命令构造、GMod 路径归一（目录 / exe / bin\win64 三种写法）、
挤服状态机、VIP 字段兼容与日期解析、GitHub Pages 静态快照构建。共 91 个用例。

不想连真服时，还有个假接口可以喂数据：

```bash
python tests/mock_rounds_api.py 8799
python -m neoprobe --serve --rounds-api http://127.0.0.1:8799/status.php
```

面板支持 `#open=1.2.3.4:27015` 直接展开某台服务器；调试时加 `?probe=1` 会把渲染状态写进标签页标题。

---

## 已收录的服务器

首次使用可以把下面这批一次性粘进面板的「批量添加」（当前清单里已经在了）：

| 备注 | 地址 | 状态 |
| --- | --- | --- |
| mio服① | `43.249.193.77:27076` | 在线 70/70 |
| mio服② | `43.249.193.77:27265` | 在线 70/70 |
| mio服③ | `43.249.193.77:27852` | 在线 70/70 |
| mio服④ | `202.189.23.252:27045` | 在线 70/70 |
| mio服⑤ | `202.189.23.252:27235` | 在线 69/70 |
| mio服⑥ | `202.189.23.252:27265` | 在线 70/70 |
| 娘娘测试服 | `202.189.21.228:27076` | 在线 70/70，`status.php` 有回合数据 |
| 白菜测试服 | `202.189.21.228:27265` | 在线 70/70，`status.php` 有回合数据 |
| 猫娘窝测试服 | `202.189.21.228:27852` | 在线 69/70，`status.php` 有回合数据 |
| 兑换服 | `202.189.21.228:31284` | 在线 3/64，`status.php` 有收录但回合字段恒为 -1 |

来源：原启动器 `ServerCatalog.CreateDefault()` 里的 9 条硬编码 + `status.php` 上报的兑换服。
原 `client.conf` 里的 `202.189.7.25:27265` 已失效（该主机整段没有在线实例），没有收录。

想确认有没有漏掉的实例，可以扫一遍端口（只发 A2S_INFO，和启动器自己做的事一样）：

```bash
python tools/scan_ports.py 43.249.193.77 202.189.23.252 202.189.21.228
python tools/scan_ports.py --ports 27000-27900,31000-32000 --timeout 1.6 202.189.21.228
```

满载的服务器会丢 A2S 包（实测单次约 20% 超时），所以查询带 3 次短重试（`--retries`）。

## GitHub Pages 网页版（公网访问）

仓库内置了静态网页版（[`docs/index.html`](docs/index.html)）和采集工作流（[`.github/workflows/pages.yml`](.github/workflows/pages.yml)）：

- **A2S 服务器状态**：浏览器无法直接发送 UDP 包，由 GitHub Actions 每 5 分钟运行 `python tools/build_pages.py --out _site` 采集所有服务器的 `INFO / PLAYER / RULES` 并部署到 `data/state.json`（不向 `main` 分支刷自动提交）。
- **回合 / 倒计时**：`status.php` 返回 `Access-Control-Allow-Origin: *`，网页每 10 秒由访客浏览器直连拉取，并在本地每秒走秒。
- **一键进服与挤服**：点「进服」通过 `steam://connect/<ip>:<port>` 直接拉起 Steam 连服；满员服务器显示「挤服」，支持两种模式：
  - **纯网页守候**（零配置）：轮询静态快照 + Steam 原生排队链接，检测到空位时响铃 + 桌面通知并拉起 `steam://connect`。
  - **本机桥接**（3 秒实时 UDP）：在本地用 `--cors-origin` 启动 NeoProbe 后，网页端可直接遥控本机每 3 秒 UDP 探测并自动拉起游戏：
    ```bash
    python -m neoprobe --serve --cors-origin https://<你的用户名>.github.io
    ```
- **GOC 奇术终端（训练模式）**：顶栏可直接切换到 `GOC 奇术终端`（[`docs/goc.html`](docs/goc.html)，整合自 `bairen048-design/RXSEND` / B站小小白仁ovo），内置能量校准、西蒙符印、密码破解、符文转轮 4 关训练与考试计时，背景排队挤服会继续保留在顶部状态条中。
- **RX 美化资源站**：顶栏可切换到 `RX 美化资源站`（直连 [`rx.l1ght.xyz`](https://rx.l1ght.xyz/) OpenList 接口），支持目录浏览、当前页过滤与全站搜索、一键下载/复制直链、查看目录说明，并可一键切回原站视图。
- **与桌面版的区别**：不连接本机桥接时，网页本身无法直发 UDP 包，因此本机真实延迟、3 秒抢位与本机 Steam VIP 查询需配合桌面版 `NeoProbe.exe`。

### 挂载步骤

1. 在 GitHub 新建仓库并推送本仓库的 `main` 分支：
   ```bash
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```
2. 打开仓库的 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。
3. 到 **Actions → Deploy NeoProbe Pages** 点一次 **Run workflow**（或等待自动触发），完成后即可通过 `https://<你的用户名>.github.io/<仓库名>/` 公开访问。

本地预览网页版：

```bash
python tools/build_pages.py --out docs --skip-copy
python -m http.server -d docs 8080
```

---

## 导出 / 分发

```bash
python tools/release.py            # 出全套：exe + pyz + 使用说明 + zip
python tools/release.py --pyz-only # 没装 PyInstaller 时，只出 .pyz
```

产物都在 `dist/`：

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| `NeoProbe.exe` | 9.2 MB | 单文件，**不需要装 Python**，双击即用 |
| `NeoProbe-1.0.0-win64.zip` | 9.1 MB | 分发用：exe + 使用说明 + 备用 py 版 + 技术说明 |
| `neoprobe.pyz` | 55 KB | 纯标准库单文件，需要 Python 3.10+ |

**为什么 exe 有 9 MB 而 pyz 只有 55 KB**：exe 把整个 CPython 解释器塞进去了，
换来的是对方什么都不用装。如果目标机器本来就有 Python，pyz 更划算——同样功能，体积差 170 倍。

exe 用 PyInstaller `--onefile` 打包，`web/index.html` 通过 `--add-data` 塞进包里，
运行时从 `sys._MEIPASS` 解出来读；启动时先解包，所以比源码模式慢 1 秒左右。

**双击行为**：不带参数等于 `--serve`（起面板并自动开浏览器）。想开机自启又不弹浏览器，
设环境变量 `NEOPROBE_NO_BROWSER=1`。命令行参数照常可用，`NeoProbe.exe --vip` 不会起面板。

**首次运行会被 SmartScreen 拦一下**——没有购买代码签名证书，点「更多信息 → 仍要运行」。
这在任何未签名的 Windows exe 上都会发生，不是文件有问题。

exe 属性里带了版本信息（文件说明 / 版本 / 产品名）和图标，右键属性、任务栏、Alt+Tab 都显示正常。

## 目录

```
neoprobe/
  a2s.py        协议实现（INFO/PLAYER/RULES、分包、challenge）
  rounds.py     回合接口与目录客户端（status.php / server_catalog.php、时间补偿、限流退避）
  clientstate.py 本机客户端探针读取（neoprobe_rounds.json 打分挑选）
  slots.py      空位与换图节奏观测（按玩家名单对比统计）
  launch.py     游戏定位与启动（注册表 / 库路径 / 进程快照）
  queue.py      自动挤服（满员监视 → 空位复核 → 自动进服）
  vip.py        身份查询（SteamID64 定位 / identity.php / 到期解析）
  manager.py    清单持久化 + 后台并发查询 + 回合轮询 + 游戏状态缓存
  server.py     本地 HTTP 服务 + JSON API
  __main__.py   CLI
  web/index.html  面板（单文件，无前端依赖）
tools/
  entry.py      exe 入口（双击无参数 = 起面板）
  release.py    一条命令出成品：exe + pyz + 说明 + zip
  build_pages.py  生成 GitHub Pages 静态站点与 A2S 快照（data/state.json）
  make_icon.py  画应用图标（输出多尺寸 .ico）
  version_info.txt  exe 属性里的版本信息
  scan_ports.py 端口扫描（确认服务器有没有漏加）
  pack.py       打成单文件 dist/neoprobe.pyz
  orig_rounds_probe.py  对照原启动器 status.php 解析结果
  roundwatch.py / groundtruth.py / gt_analyze.py  回合边界观测脚本
  gmod/         可选客户端探针与服务端上报 Lua 脚本
  server/       配套 PHP 回合接收端（rounds.php）
docs/
  index.html    GitHub Pages 静态网页版（直连 status.php + 消费 A2S 快照 + 内嵌 GOC 终端）
  goc.html      GOC 奇术终端 · 训练模式页面
  assets/goc-yuai.mp3  默认背景音乐（雨爱）
  data/state.json  初始快照（Actions 运行时自动生成最新 _site/data/state.json）
.github/workflows/
  pages.yml     每 5 分钟定时采集并部署 GitHub Pages
assets/
  neoprobe.ico  应用图标（256/128/64/48/32/16 六种尺寸）
  neoprobe.png  PNG 图标
dist/           导出产物（不进版本库也不影响运行）
tests/
  mock_server.py       模拟 Source 服务器（挑战 / 分包 / 压缩）
  mock_rounds_api.py   模拟 status.php（带倒计时）
  test_a2s.py          14 个用例
  test_catalog.py      7 个用例
  test_clientstate.py  10 个用例
  test_mapinfo.py      4 个用例
  test_pages.py        3 个用例
  test_rounds_launch.py 20 个用例
  test_queue.py        9 个用例（等待/抢位/取消/预留位/探测失败）
  test_slots.py        8 个用例
  test_vip.py          16 个用例（字段兼容/日期解析/文本解析/接口容错）
```

## 说明

- 查询部分只读；「启动游戏 / 进服」只在你自己点按钮或带 `--launch` 时才执行，且只启动本地游戏。
- 用的是 Valve 公开的 A2S 协议，和任何第三方启动器无关；查询量与手动开服务器浏览器相当。
- 面板只绑定 `127.0.0.1`。要给别人用得自己改 `--host`，注意 UDP 探测会暴露你的出口 IP。
