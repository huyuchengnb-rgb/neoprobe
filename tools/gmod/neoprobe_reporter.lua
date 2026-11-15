--[[
NeoProbe 回合上报插件（**服务端**，装在游戏服务器上）

作用：把本服的回合状态（剩余局数 / 剩余秒数 / 阶段）POST 给一个 HTTP 接口，
让所有玩家在面板里都能看到——这才是"挑服、提前安排"真正需要的数据。

为什么必须装在服务器上：
  玩家客户端只能在"自己正在玩的那台服"上读到回合状态；
  Garry's Mod 的公开查询协议（A2S）里根本没有回合字段
  （实测 400 条规则全是静态配置，两次快照差异 0 条）。
  所以想让九台服都显示，只能由服务器自己上报。

安装：
  1. 把本文件放到服务器的  garrysmod/addons/neoprobe_rounds/lua/autorun/server/rounds_reporter.lua
  2. 改下面的 ENDPOINT 为你自己的接收地址（附带 status-receiver.php 可直接用）
  3. 重启服务器。控制台会打印 [NeoProbe] 上报状态。

协议（和社区 status.php 完全一致，面板可直接吃）：
  POST ENDPOINT  application/json
  {"server_name":"...","ip":"...","port":27015,
   "rounds_left":3,"round_time_left":245,"round_phase":"回合中",
   "updated_at":1794660000}

字段怎么来的：
  rounds_left / round_time_left 依赖具体 gamemode 的实现。下面按常见命名顺序探测，
  全都找不到时会明确上报 -1（"未知"），**绝不编一个数字**——
  面板看到 -1 就显示"未上报"，而不是"空闲"。
]]

if not SERVER then return end

local ENDPOINT = "https://example.com/rounds.php"   -- ← 改这里
local INTERVAL = 5                                   -- 秒
local SECRET   = ""                                  -- 与接收端约定，可留空

-- 把可能的全局表/字段名都试一遍；找到即用，找不到如实上报 -1
local ROUND_TABLES = { "BR", "Round", "ROUND", "Breach", "SCP", "RXSEND", "Neo" }
local TIME_KEYS = { "RoundEndTime", "RoundEnd", "EndTime", "RoundEndsAt" }
local LEFT_KEYS = { "RoundTimeLeft", "TimeLeft", "Remaining", "RoundRemaining" }
local ROUNDS_KEYS = { "RoundsLeft", "RoundsRemaining", "Rounds" }
local PHASE_KEYS = { "RoundPhase", "Phase", "State", "RoundState" }

local function first_num(...)
    for i = 1, select("#", ...) do
        local v = select(i, ...)
        if type(v) == "number" and v == v then return v end
    end
    return nil
end

local function first_str(...)
    for i = 1, select("#", ...) do
        local v = select(i, ...)
        if type(v) == "string" and v ~= "" then return v end
    end
    return nil
end

local function dig(tbl, keys)
    if type(tbl) ~= "table" then return nil end
    local vals = {}
    for _, k in ipairs(keys) do vals[#vals + 1] = tbl[k] end
    return vals
end

local function collect_state()
    local end_at, left, rounds, phase

    -- 1) 常见全局表
    for _, name in ipairs(ROUND_TABLES) do
        local t = _G[name]
        if type(t) == "table" then
            end_at = end_at or first_num(unpack(dig(t, TIME_KEYS) or {}))
            left   = left   or first_num(unpack(dig(t, LEFT_KEYS) or {}))
            rounds = rounds or first_num(unpack(dig(t, ROUNDS_KEYS) or {}))
            phase  = phase  or first_str(unpack(dig(t, PHASE_KEYS) or {}))
        end
    end

    -- 2) GM / GAMEMODE
    local gm = GM or GAMEMODE
    if type(gm) == "table" then
        end_at = end_at or first_num(unpack(dig(gm, TIME_KEYS) or {}))
        left   = left   or first_num(unpack(dig(gm, LEFT_KEYS) or {}))
        rounds = rounds or first_num(unpack(dig(gm, ROUNDS_KEYS) or {}))
        phase  = phase  or first_str(unpack(dig(gm, PHASE_KEYS) or {}))
    end

    -- 3) 绝对结束时刻 → 剩余秒数（用服务器 CurTime 换算，避免时钟漂移）
    if left == nil and end_at then
        left = math.max(0, math.floor(end_at - CurTime()))
    end

    -- 4) 阶段：找不到就按剩余时间给一个**描述性**状态，不冒充官方阶段名
    if phase == nil then
        if left == nil then
            phase = "未知"
        elseif left <= 0 then
            phase = "回合结束"
        else
            phase = "回合中"
        end
    end

    return {
        rounds_left = rounds and math.floor(rounds) or -1,
        round_time_left = left and math.floor(left) or -1,
        round_phase = phase,
    }
end

local function escape(s)
    return (tostring(s):gsub('[%c"\\]', function(c)
        if c == '"' then return '\\"' end
        if c == "\\" then return "\\\\" end
        return string.format("\\u%04x", string.byte(c))
    end))
end

local function report()
    local st = collect_state()
    local body = string.format(
        '{"server_name":"%s","ip":"%s","port":%d,"rounds_left":%d,' ..
        '"round_time_left":%d,"round_phase":"%s","updated_at":%d%s}',
        escape(GetHostName()), escape(game.GetIPAddress() or "0.0.0.0"),
        game.GetIPAddress() and tonumber(string.match(game.GetIPAddress(), ":(%d+)$") or 0) or 0,
        st.rounds_left, st.round_time_left, escape(st.round_phase), os.time(),
        SECRET ~= "" and (',"secret":"' .. escape(SECRET) .. '"') or ""
    )

    HTTP({
        method = "POST",
        url = ENDPOINT,
        headers = { ["Content-Type"] = "application/json" },
        body = body,
        success = function(code)
            if code ~= 200 then
                print("[NeoProbe] 上报失败 HTTP " .. tostring(code))
            end
        end,
        failed = function(err)
            print("[NeoProbe] 上报失败: " .. tostring(err))
        end,
    })
end

timer.Create("NeoProbeRoundsReport", INTERVAL, 0, report)
print("[NeoProbe] 回合上报已启动 -> " .. ENDPOINT)
