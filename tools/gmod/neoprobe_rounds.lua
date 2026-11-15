--[[
NeoProbe 回合探针（客户端）

背景：GMod 的 A2S 查询只有 名称/地图/人数/规则，没有回合状态；社区 status.php
对 9 台正式服完全不上报。但**客户端一定知道回合状态**（HUD 的倒计时必须靠网络同步），
所以这个脚本在客户端把能看到的回合字段抓下来写到 garrysmod/data/neoprobe_rounds.json，
由 NeoProbe 读取显示。

设计原则：
  * 不猜字段名。全局表、GAMEMODE、所有实体的 NWVar 全扫一遍，按关键词筛。
  * 抓不到就写空，绝不编数据；面板据此显示"客户端未提供"。
  * 每 2 秒一次，最多扫 300 个实体，避免卡帧。

安装位置：garrysmod/lua/autorun/client/neoprobe_rounds.lua
删除即完全卸载，不留残留。
]]

if not CLIENT then return end

local OUT = "neoprobe_rounds.json"
local MAX_ENTS = 300
local MAX_CANDS = 140

-- 关键词：命中任意一个就收录
local WORDS = {
    "round", "phase", "state", "status", "timer", "time", "left",
    "remain", "countdown", "wave", "stage", "回", "倒", "秒",
}

local function hit(key)
    local k = string.lower(tostring(key))
    for i = 1, #WORDS do
        if string.find(k, WORDS[i], 1, true) then return true end
    end
    return false
end

local function push(out, src, k, v)
    if #out.cands >= MAX_CANDS then return end
    local tv = type(v)
    if tv == "number" then
        if v ~= v then return end                 -- NaN
        if math.abs(v) > 1e9 then return end
    elseif tv == "string" then
        if #v > 64 then v = string.sub(v, 1, 64) end
        if v == "" then return end
    elseif tv ~= "boolean" then
        return
    end
    out.cands[#out.cands + 1] = { src = src, k = tostring(k), v = v, t = tv }
end

local function scan_table(out, src, tbl, depth)
    if type(tbl) ~= "table" or depth > 2 then return end
    local n = 0
    for k, v in pairs(tbl) do
        n = n + 1
        if n > 120 then return end
        if type(k) == "string" and hit(k) then
            if type(v) ~= "table" or depth < 1 then push(out, src, k, v) end
        end
        if type(v) == "table" and depth < 2 and type(k) == "string" and hit(k) then
            scan_table(out, src .. "." .. k, v, depth + 1)
        end
    end
end

local function scan_ent(out, ent)
    if not IsValid(ent) then return end
    local ok, t = pcall(function() return ent:GetNWVarTable() end)
    if not ok or type(t) ~= "table" then return end
    local cls = ent:GetClass()
    for k, v in pairs(t) do
        if hit(k) then push(out, "nw:" .. cls, k, v) end
    end
end

local function collect()
    local out = {
        ts = os.time(),
        curtime = CurTime(),
        addr = "",
        map = game.GetMap(),
        mode = engine.ActiveGamemode and engine.ActiveGamemode() or "",
        playing = false,
        cands = {},
    }

    local ok, ip = pcall(function() return game.GetIPAddress() end)
    if ok and type(ip) == "string" and ip ~= "" and ip ~= "0.0.0.0:0" then
        out.addr = ip
        out.playing = true
    end

    -- 1) 世界实体 + 本地玩家 + 前几个玩家（回合状态最常挂在这里）
    scan_ent(out, game.GetWorld())
    scan_ent(out, LocalPlayer())
    local pls = player.GetAll()
    for i = 1, math.min(#pls, 3) do scan_ent(out, pls[i]) end

    -- 2) 其余实体（限量、跳过刚才扫过的）
    local ents_list = ents.GetAll()
    local scanned = math.min(#ents_list, MAX_ENTS)
    for i = 1, scanned do
        local e = ents_list[i]
        if e ~= game.GetWorld() and e ~= LocalPlayer() then scan_ent(out, e) end
        if #out.cands >= MAX_CANDS then break end
    end

    -- 3) 客户端 gamemode 表
    scan_table(out, "GAMEMODE", GAMEMODE, 1)

    -- 4) 全局表里名字带关键词的
    local seen = 0
    for name, val in pairs(_G) do
        seen = seen + 1
        if seen > 3000 then break end
        if type(val) == "table" and type(name) == "string" and hit(name) then
            scan_table(out, "G:" .. name, val, 1)
        end
    end

    -- 5) 服端回合配置（不是状态，但能和状态对照算出上限）
    if engine.ActiveGamemode then
        local gm = engine.ActiveGamemode()
        for _, cv in ipairs({ "br_time_round", "ttt_roundtime_minutes", "ttt_round_limit" }) do
            local c = GetConVar(cv)
            if c then push(out, "cvar", cv, c:GetFloat()) end
        end
        push(out, "info", "gamemode", gm)
    end

    return out
end

local function write()
    local ok, data = pcall(collect)
    if not ok then
        file.Write(OUT, util.TableToJSON({ ts = os.time(), error = tostring(data),
                                            addr = "", playing = false, cands = {} }))
        return
    end
    local ok2, js = pcall(util.TableToJSON, data)
    if ok2 and js then file.Write(OUT, js) end
end

-- 首帧之后开始，避免 LocalPlayer 还没就绪
hook.Add("InitPostEntity", "NeoProbeRoundsInit", function()
    timer.Simple(2, write)
end)

timer.Create("NeoProbeRounds", 2, 0, write)

-- 主动校验：连服后立即写一次，退服时也写一次
hook.Add("OnEntityCreated", "NeoProbeRoundsFirst", function()
    hook.Remove("OnEntityCreated", "NeoProbeRoundsFirst")
    timer.Simple(3, write)
end)
