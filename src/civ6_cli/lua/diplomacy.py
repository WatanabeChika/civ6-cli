"""Diplomacy domain — Lua builders and parsers."""

from __future__ import annotations

from civ6_cli.lua._helpers import SENTINEL, _LUA_SAFE_READ, _bail, _bail_lua, _lua_close_diplo_session
from civ6_cli.lua.models import (
    AgendaInfo,
    CivInfo,
    DealItem,
    DealOptions,
    DiplomacyModifier,
    DiplomacySession,
    PendingDeal,
    TestTradeItem,
    TestTradeResult,
    TradeableCity,
    TradeOption,
    VisibleCity,
)


def build_diplomacy_query() -> str:
    """Rich diplomacy query — runs in InGame context for GetDiplomaticAI access."""
    return """
local me = Game.GetLocalPlayer()
local pDiplo = Players[me]:GetDiplomacy()
local pVis = PlayersVisibility[me]
local states = {"ALLIED","DECLARED_FRIEND","FRIENDLY","NEUTRAL","UNFRIENDLY","DENOUNCED","WAR"}
local checkActions = {"DIPLOACTION_DIPLOMATIC_DELEGATION","DIPLOACTION_DECLARE_FRIENDSHIP","DIPLOACTION_DENOUNCE","DIPLOACTION_RESIDENT_EMBASSY","DIPLOACTION_OPEN_BORDERS","DIPLOACTION_MAKE_ALLIANCE"}
for i = 0, 62 do
    if i ~= me and Players[i] and Players[i]:IsAlive() and Players[i]:IsMajor() then
        local cfg = PlayerConfigurations[i]
        local civName = Locale.Lookup(cfg:GetCivilizationShortDescription())
        local leaderName = Locale.Lookup(cfg:GetLeaderName())
        local met = pDiplo:HasMet(i) and "1" or "0"
        local war = pDiplo:IsAtWarWith(i) and "1" or "0"
        if pDiplo:HasMet(i) then
            local ai = Players[i]:GetDiplomaticAI()
            local stateIdx = ai:GetDiplomaticStateIndex(me)
            local stateName = states[stateIdx + 1] or tostring(stateIdx)
            local grievances = pDiplo:GetGrievancesAgainst(i)
            local vis = pDiplo:GetVisibilityOn(i)
            local hasDel = pDiplo:HasDelegationAt(i) and "1" or "0"
            local hasEmb = pDiplo:HasEmbassyAt(i) and "1" or "0"
            local theyDel = Players[i]:GetDiplomacy():HasDelegationAt(me) and "1" or "0"
            local theyEmb = Players[i]:GetDiplomacy():HasEmbassyAt(me) and "1" or "0"
            print("CIV|" .. i .. "|" .. civName .. "|" .. leaderName .. "|" .. met .. "|" .. war .. "|" .. stateName .. "|" .. grievances .. "|" .. vis .. "|" .. hasDel .. "|" .. hasEmb .. "|" .. theyDel .. "|" .. theyEmb)
            local okMil, milStr = pcall(function() return Players[i]:GetStats():GetMilitaryStrength() end)
            local okMyMil, myMilStr = pcall(function() return Players[me]:GetStats():GetMilitaryStrength() end)
            if okMil and okMyMil then print("MILITARY|" .. i .. "|" .. (milStr or 0) .. "|" .. (myMilStr or 0)) end
            local nCivCities = 0
            for _, ec in Players[i]:GetCities():Members() do
                nCivCities = nCivCities + 1
                local ecx, ecy = ec:GetX(), ec:GetY()
                if pVis:IsRevealed(ecx, ecy) then
                    local ecName = Locale.Lookup(ec:GetName())
                    local ecPop = ec:GetPopulation()
                    local ecLoy, ecLoyPT = 100, 0
                    local ecCult = ec:GetCulturalIdentity()
                    if ecCult then ecLoy = ecCult:GetLoyalty(); ecLoyPT = ecCult:GetLoyaltyPerTurn() end
                    local ecWalls, ecDef = 0, 0
                    pcall(function()
                        for _, d in ec:GetDistricts():Members() do
                            local di = GameInfo.Districts[d:GetType()]
                            if di and di.DistrictType == "DISTRICT_CITY_CENTER" then
                                ecWalls = d:GetMaxDamage(DefenseTypes.DISTRICT_OUTER) or 0
                                ecDef = ec:GetStrengthValue() or 0
                                break
                            end
                        end
                    end)
                    print("ECITY|" .. i .. "|" .. ecName:gsub("|","/") .. "|" .. ecx .. "," .. ecy .. "|" .. ecPop .. "|" .. string.format("%.0f|%.1f", ecLoy, ecLoyPT) .. "|" .. ecWalls .. "|" .. ecDef)
                end
            end
            print("CIVCITIES|" .. i .. "|" .. nCivCities)
            local mods = ai:GetDiplomaticModifiers(me)
            if mods then
                for _, mod in ipairs(mods) do
                    local txt = tostring(mod.Text):gsub("|", "/")
                    print("MOD|" .. i .. "|" .. mod.Score .. "|" .. txt)
                end
            end
            if stateIdx == 0 then
                local ok3, aType = pcall(function() return pDiplo:GetAllianceType(i) end)
                if ok3 and aType and aType >= 0 then
                    local aNames = {"RESEARCH","CULTURAL","ECONOMIC","MILITARY","RELIGIOUS"}
                    local aLevel = 1
                    pcall(function() aLevel = pDiplo:GetAllianceLevel(i) or 1 end)
                    print("ALLIANCE|" .. i .. "|" .. (aNames[aType+1] or tostring(aType)) .. "|" .. aLevel)
                end
            end
            local avail = {}
            for _, aName in ipairs(checkActions) do
                local ok2, valid = pcall(function() return pDiplo:IsDiplomaticActionValid(aName, i, false) end)
                if ok2 and valid then
                    local label = aName:gsub("DIPLOACTION_", "")
                    if label == "OPEN_BORDERS" then label = "Open Borders (via propose_trade)" end
                    table.insert(avail, label)
                end
            end
            if not pDiplo:IsAtWarWith(i) then
                local canWar = false
                pcall(function() canWar = pDiplo:CanDeclareWarOn(i) end)
                if canWar then table.insert(avail, "DECLARE_WAR") end
            end
            if #avail > 0 then print("ACTIONS|" .. i .. "|" .. table.concat(avail, ",")) end
            -- Agendas (visibility-gated: historical always, random only at SECRET+)
            local okAg, agendas = pcall(function() return Players[i]:GetAgendaTypes() end)
            if okAg and agendas then
                local histSet = {}
                local leaderType = cfg:GetLeaderTypeName()
                for ha in GameInfo.HistoricalAgendas() do
                    if ha.LeaderType == leaderType then
                        local aDef = GameInfo.Agendas[ha.AgendaType]
                        if aDef then histSet[aDef.Index] = true end
                    end
                end
                local vis = pDiplo:GetVisibilityOn(i)
                for _, agIdx in ipairs(agendas) do
                    local aDef = GameInfo.Agendas[agIdx]
                    if aDef then
                        local isHist = histSet[agIdx] or false
                        if isHist then
                            print("AGENDA|" .. i .. "|HISTORICAL|" .. Locale.Lookup(aDef.Name) .. "|" .. Locale.Lookup(aDef.Description))
                        elseif vis >= 3 then
                            print("AGENDA|" .. i .. "|HIDDEN|" .. Locale.Lookup(aDef.Name) .. "|" .. Locale.Lookup(aDef.Description))
                        else
                            print("AGENDA|" .. i .. "|HIDDEN|???|Requires Secret diplomatic visibility (spy or alliance)")
                        end
                    end
                end
            end
            local okPact, hasPact = pcall(function() return Players[i]:GetDiplomacy():HasDefensivePact(me) end)
            if okPact and hasPact then print("PACT|" .. i .. "|DEFENSIVE") end
        else
            print("CIV|" .. i .. "|Unmet Civilization|Unknown Leader|" .. met .. "|" .. war .. "|UNKNOWN|0|0|0|0|0|0")
        end
    end
end
-- Scan for third-party defensive pacts
for i = 0, 62 do
    if i ~= me and Players[i] and Players[i]:IsAlive() and Players[i]:IsMajor() and pDiplo:HasMet(i) then
        for j = i+1, 62 do
            if j ~= me and Players[j] and Players[j]:IsAlive() and Players[j]:IsMajor() and pDiplo:HasMet(j) then
                local okP, hp = pcall(function() return Players[i]:GetDiplomacy():HasDefensivePact(j) end)
                if okP and hp then print("PACT|" .. i .. "|" .. j .. "|DEFENSIVE") end
            end
        end
    end
end
print("{SENTINEL}")
""".replace("{SENTINEL}", SENTINEL)


def build_diplomacy_session_query() -> str:
    """Check for open diplomacy sessions and return choices (InGame context).

    Also reads the DiplomacyActionView UI controls to capture the leader's
    actual dialogue text, reason/agenda subtext, and visible button labels.
    Button info helps detect goodbye phase (only "Goodbye" button visible).
    """
    return f"""\n{_LUA_DEAL_METADATA}
local me = Game.GetLocalPlayer()
local found = false
local dialogueText = ""
local reasonText = ""
local ctrl1 = ContextPtr:LookUpControl("/InGame/DiplomacyActionView/LeaderResponseText")
local ctrl2 = ContextPtr:LookUpControl("/InGame/DiplomacyActionView/LeaderReasonText")
if ctrl1 then local ok, t = pcall(ctrl1.GetText, ctrl1); if ok and t and t ~= "" then dialogueText = t end end
if ctrl2 then local ok, t = pcall(ctrl2.GetText, ctrl2); if ok and t and t ~= "" then reasonText = t end end
local dealCtrl = ContextPtr:LookUpControl("/InGame/DiplomacyDealView/LeaderResponseText")
if dealCtrl and not dealCtrl:IsHidden() then local ok, t = pcall(dealCtrl.GetText, dealCtrl); if ok and t and t ~= "" then dialogueText = t end end
local btnTexts = {{}}
for _, path in ipairs({{
    "/InGame/DiplomacyActionView/SelectionStack/Selection1Button/SelectionText",
    "/InGame/DiplomacyActionView/SelectionStack/Selection2Button/SelectionText",
}}) do
    local btn = ContextPtr:LookUpControl(path)
    if btn then
        local par = btn:GetParent()
        if par and not par:IsHidden() then
            local ok, t = pcall(btn.GetText, btn)
            if ok and t and t ~= "" then btnTexts[#btnTexts + 1] = t end
        end
    end
end
local goodbyeBtn = ContextPtr:LookUpControl("/InGame/DiplomacyActionView/GoodbyeButton")
if goodbyeBtn and not goodbyeBtn:IsHidden() then btnTexts[#btnTexts + 1] = "GOODBYE" end
local buttonInfo = table.concat(btnTexts, ";")
for i = 0, 62 do
    if i ~= me and Players[i] and Players[i]:IsAlive() then
        local sid = DiplomacyManager.FindOpenSessionID(me, i)
        if sid and sid >= 0 then
            local cfg = PlayerConfigurations[i]
            local civName = Locale.Lookup(cfg:GetCivilizationShortDescription())
            local leaderName = Locale.Lookup(cfg:GetLeaderName())
            local atWar = Players[me]:GetDiplomacy():IsAtWarWith(i) and "1" or "0"
            print("SESSION|" .. sid .. "|" .. i .. "|" .. civName .. "|" .. leaderName .. "|" .. dialogueText .. "|" .. reasonText .. "|" .. buttonInfo .. "|" .. atWar)
            found = true
            local okD, deal = pcall(function() return DealManager.GetWorkingDeal(DealDirection.INCOMING, me, i) end)
            if okD and deal then
                local okN, cnt = pcall(function() return deal:GetItemCount() end)
                if okN and cnt and cnt > 0 then
                    for item in deal:Items() do
                        local fromTag = "THEM"
                        local okF, fromID = pcall(function() return item:GetFromPlayerID() end)
                        if okF and fromID == me then fromTag = "US" end
                        local amount = safe(function() return item:GetAmount() end,-1)
                        local duration = safe(function() return item:GetDuration() end,-1)
                        local typeName = dealType(item)
                        local itemName = dealDescription(item)
                        if itemName == "" then itemName = typeName end
                        if itemName ~= "" and itemName ~= "Unknown" then
                            print("DEAL_ITEM|" .. i .. "|" .. fromTag .. "|" .. typeName .. "|" .. itemName:gsub("|","/") .. "|" .. amount .. "|" .. duration)
                        end
                    end
                end
            end
        end
    end
end
if not found then print("NONE") end
print("{SENTINEL}")
"""


def build_diplomacy_choices_query(other_player_id: int) -> str:
    """Get available dialogue choices for an open session with a specific player."""
    return f"""
local me = Game.GetLocalPlayer()
local sid = DiplomacyManager.FindOpenSessionID(me, {other_player_id})
if sid == nil or sid < 0 then {_bail("DIPLO_NOTE|当前没有需要响应的外交会面；交易使用 trade options")} end
print("SESSION|" .. sid)
local ctrl = ContextPtr:LookUpControl("/InGame/DiplomacyActionView")
local isVisible = ctrl and not ctrl:IsHidden() or false
print("VISIBLE|" .. tostring(isVisible))
for row in GameInfo.DiplomacySelections() do
    if string.find(row.Type, "FIRST_MEET") or string.find(row.Type, "GREETING") or string.find(row.Type, "DECLARE_FRIEND") or string.find(row.Type, "DENOUNCE") then
        local text = Locale.Lookup(row.Text)
        print("CHOICE|" .. row.Type .. "|" .. row.Key .. "|" .. text)
    end
end
print("{SENTINEL}")
"""


def build_diplomacy_respond(other_player_id: int, response: str) -> str:
    """Respond to a diplomacy session.

    response is 'POSITIVE', 'NEGATIVE', or 'EXIT'.
    EXIT closes the session directly (last-resort for orphaned sessions).
    POSITIVE/NEGATIVE sends AddResponse only — does NOT call CloseSession.
    The C++ engine handles session lifecycle through its own callbacks.
    Caller must check session state in a SEPARATE call to allow the engine
    time to process the response (same-frame checks see stale state).
    """
    return f"""
local me = Game.GetLocalPlayer()
local sid = DiplomacyManager.FindOpenSessionID(me, {other_player_id})
if sid == nil or sid < 0 then {_bail("ERR:NO_SESSION")} end
if "{response}" == "EXIT" then
    DiplomacyManager.CloseSession(sid)
    LuaEvents.DiplomacyActionView_ShowIngameUI()
    pcall(function() Events.HideLeaderScreen() end)
    print("OK:SESSION_CLOSED")
    print("{SENTINEL}"); return
end
DiplomacyManager.AddResponse(sid, me, "{response}")
print("OK:RESPONSE_SENT|{response}")
print("{SENTINEL}")
"""


def build_check_diplomacy_session_state(other_player_id: int) -> str:
    """Check if a diplomacy session is still open after AddResponse.

    Must be called in a SEPARATE TCP round-trip from AddResponse to give
    the C++ engine time to process the response and transition/close
    the session naturally.  Returns SESSION_OPEN or SESSION_CLOSED.
    """
    return f"""
local me = Game.GetLocalPlayer()
local sid = DiplomacyManager.FindOpenSessionID(me, {other_player_id})
if sid and sid >= 0 then
    print("SESSION_OPEN|" .. sid)
else
    pcall(function() LuaEvents.DiplomacyActionView_ShowIngameUI() end)
    pcall(function() Events.HideLeaderScreen() end)
    print("SESSION_CLOSED")
end
print("{SENTINEL}")
"""


def build_send_diplo_action(other_player_id: int, action_name: str) -> str:
    """Send a proactive diplomatic action and detect acceptance/rejection.

    action_name is e.g. DIPLOMATIC_DELEGATION, DECLARE_FRIENDSHIP, DENOUNCE,
    RESIDENT_EMBASSY, DECLARE_SURPRISE_WAR, DECLARE_FORMAL_WAR, etc.

    Open Borders is NOT supported here — it's a trade deal, not a diplomatic
    action. Use propose_trade with AGREEMENT/OPEN_BORDERS items instead.

    Key discovery: RequestSession uses DIFFERENT action strings from DIPLOACTION_ names:
    - DECLARE_FRIENDSHIP -> session string "DECLARE_FRIEND" (not "DECLARE_FRIENDSHIP")
    - Others use same name as action_name

    Flow: RequestSession -> 2x AddResponse(POSITIVE) -> CloseSession
    No AddStatement needed (that crashes on mismatched session types).
    """
    # Map action_name to the correct RequestSession string
    # Game source: DiplomacyActionView.lua line 472 uses "DECLARE_FRIEND"
    session_string_map = {
        "DECLARE_FRIENDSHIP": "DECLARE_FRIEND",
        "DIPLOMATIC_DELEGATION": "DIPLOMATIC_DELEGATION",
        "RESIDENT_EMBASSY": "RESIDENT_EMBASSY",
        "DENOUNCE": "DENOUNCE",
        # War declarations — session strings match action names
        "DECLARE_SURPRISE_WAR": "DECLARE_SURPRISE_WAR",
        "DECLARE_FORMAL_WAR": "DECLARE_FORMAL_WAR",
        "DECLARE_HOLY_WAR": "DECLARE_HOLY_WAR",
        "DECLARE_LIBERATION_WAR": "DECLARE_LIBERATION_WAR",
        "DECLARE_RECONQUEST_WAR": "DECLARE_RECONQUEST_WAR",
        "DECLARE_PROTECTORATE_WAR": "DECLARE_PROTECTORATE_WAR",
        "DECLARE_COLONIAL_WAR": "DECLARE_COLONIAL_WAR",
        "DECLARE_TERRITORIAL_WAR": "DECLARE_TERRITORIAL_WAR",
    }
    is_war = action_name.endswith("_WAR") and action_name.startswith("DECLARE_")
    session_str = session_string_map.get(action_name, action_name)

    # War declarations use CanDeclareWarOn; other actions use IsDiplomaticActionValid
    if is_war:
        validation_block = f"""
local me = Game.GetLocalPlayer()
local pDiplo = Players[me]:GetDiplomacy()
local target = {other_player_id}
local action = "{action_name}"
if pDiplo:IsAtWarWith(target) then
    {_bail("ERR:ALREADY_AT_WAR|Already at war with this player")}
end
local canWar = false
pcall(function() canWar = pDiplo:CanDeclareWarOn(target) end)
if not canWar then
    {_bail("ERR:CANNOT_DECLARE_WAR|Cannot declare war. Possible reasons: friendship/alliance active, 10-turn peace cooldown, or target is invalid.")}
end"""
    else:
        validation_block = f"""
local me = Game.GetLocalPlayer()
local pDiplo = Players[me]:GetDiplomacy()
local target = {other_player_id}
local action = "{action_name}"
local fullAction = "DIPLOACTION_" .. action
local valid, results = pDiplo:IsDiplomaticActionValid(fullAction, target, true)
if not valid then
    local reasons = "unknown"
    if results and results.FailureReasons then
        local parts = {{}}
        for _, r in ipairs(results.FailureReasons) do
            local s = tostring(r or "")
            if s:find("OBSOLETE_CIVIC") or s:find("ObsoleteCivic") then
                table.insert(parts, "obsolete (Diplomatic Service civic researched — use embassy instead)")
            else
                local loc = Locale.Lookup(s)
                if loc and loc ~= "" then table.insert(parts, loc) else table.insert(parts, s) end
            end
        end
        if #parts > 0 then reasons = table.concat(parts, "; ") end
    end
    if reasons == "unknown" and action == "DIPLOMATIC_DELEGATION" then
        local dipSvcCivic = GameInfo.Civics["CIVIC_DIPLOMATIC_SERVICE"]
        if dipSvcCivic then
            local hasCivic = false
            pcall(function() hasCivic = Players[me]:GetCulture():HasCivic(dipSvcCivic.Index) end)
            if hasCivic then
                reasons = "obsolete (Diplomatic Service civic researched — use embassy instead)"
            end
        end
    end
    {_bail_lua('"ERR:INVALID|" .. reasons')}
end"""

    # War declarations leave the session open so the leader animation plays.
    # Python schedules cleanup after ~8s via build_war_diplo_cleanup().
    close_session_lua = "" if is_war else "    DiplomacyManager.CloseSession(sid)"
    cleanup_lua = "" if is_war else _lua_close_diplo_session()

    return f"""
{validation_block}
-- Clean stale session for THIS target only (not all session IDs).
-- Mass-closing sessions via IsSessionIDOpen loop corrupts AI diplomacy state.
local staleSid = DiplomacyManager.FindOpenSessionID(me, target)
if staleSid and staleSid >= 0 then
    DiplomacyManager.CloseSession(staleSid)
end
-- Open session with the correct action string
DiplomacyManager.RequestSession(me, target, "{session_str}")
local sid = DiplomacyManager.FindOpenSessionID(me, target)
local sessionCompleted = false
if sid and sid >= 0 then
    DiplomacyManager.AddResponse(sid, me, "POSITIVE")
    DiplomacyManager.AddResponse(sid, me, "POSITIVE")
{close_session_lua}
    sessionCompleted = true
end
{cleanup_lua}
-- Report result.
-- NOTE: All post-state queries (HasDelegationAt, HasEmbassyAt, IsDiplomaticActionValid,
-- GetGoldBalance, GetVisibilityOn) are STALE same-frame after CloseSession. The C++ engine
-- commits state changes on the next frame. So we cannot reliably detect acceptance by
-- comparing pre/post state. Instead: IsDiplomaticActionValid passed the pre-check (line above),
-- meaning the action was valid. If the session completed, the game accepted it.
local name = Locale.Lookup(PlayerConfigurations[target]:GetCivilizationShortDescription())
if action:find("_WAR") then
    local atWar = pDiplo:IsAtWarWith(target)
    if atWar then
        print("OK:WAR_DECLARED|" .. action .. " on " .. name .. " — now at war")
    else
        print("WARN:WAR_UNCERTAIN|" .. action .. " session completed but war state not yet confirmed for " .. name .. ". Check next turn.")
    end
elseif action == "DIPLOMATIC_DELEGATION" then
    if sessionCompleted then
        print("OK:ACCEPTED|" .. name .. " accepted your delegation")
    else
        print("OK:ACCEPTED|Delegation sent to " .. name)
    end
elseif action == "RESIDENT_EMBASSY" then
    print("OK:ACCEPTED|" .. name .. " accepted your embassy")
elseif action == "DECLARE_FRIENDSHIP" then
    print("OK:ACCEPTED|" .. name .. " accepted your friendship declaration")
elseif action == "DENOUNCE" then
    print("OK:SENT|Denounced " .. name)
else
    print("OK:SENT|" .. action .. " sent to " .. name)
end
print("{SENTINEL}")
"""


def build_war_close_session(other_player_id: int) -> str:
    """Phase 1: close the war diplomacy session (InGame context).

    After this, DiplomacyActionView transitions to OVERVIEW_MODE (intel screen).
    Must wait ~1s for the engine event to process before phase 2.
    """
    sentinel = SENTINEL
    return f"""
local me = Game.GetLocalPlayer()
local target = {other_player_id}
local sid = DiplomacyManager.FindOpenSessionID(me, target)
if sid and sid >= 0 then
    DiplomacyManager.CloseSession(sid)
end
print("OK:SESSION_CLOSED")
print("{sentinel}")
"""


def build_war_dismiss_view() -> str:
    """Phase 2: force-dismiss DiplomacyActionView from OVERVIEW_MODE (InGame context).

    NaturalWonderPopup_Shown triggers OnBlockingPopupShown → OnForceClose →
    CloseFocusedState(true) → Close() which calls UninitializeView + ShowIngameUI
    (balancing InitializeView's HideIngameUI).  NaturalWonderPopup_Closed then
    balances NW's own BulkHide(true) entry.

    Must be called in a SEPARATE Lua execution from CloseSession — the engine
    fires OnDiplomacySessionClosed asynchronously, so the view needs a frame to
    transition from CONVERSATION_MODE to OVERVIEW_MODE first.
    """
    return """
LuaEvents.NaturalWonderPopup_Shown()
LuaEvents.NaturalWonderPopup_Closed()
pcall(function() Events.HideLeaderScreen() end)
print("OK:VIEW_DISMISSED")
print("{SENTINEL}")
""".replace("{SENTINEL}", SENTINEL)


_LUA_DEAL_METADATA = _LUA_SAFE_READ + """
local function cleanDeal(value)
    return tostring(value or ''):gsub('|','/'):gsub('[\\r\\n]',' ')
end
local function validationName(value)
    for name, code in pairs(DealValidationResult or {}) do
        if code == value then return name end
    end
    return tostring(value or 'unknown')
end
local function possible(from, to, kind, deal, subtype)
    if kind == nil or deal == nil then return nil end
    local ok, result = pcall(function()
        if subtype ~= nil then return DealManager.GetPossibleDealItems(from,to,kind,subtype,deal) end
        return DealManager.GetPossibleDealItems(from,to,kind,deal)
    end)
    if not ok or result == nil then return nil end
    return result
end
local function dealDescription(item)
    local value = safe(function() return item:GetValueType() end,
        safe(function() return item:GetValueTypeID() end, '?'))
    local subtype = safe(function() return item:GetSubType() end,
        safe(function() return item:GetSubTypeID() end, '?'))
    local key = safe(function() return item:GetValueTypeNameID() end, nil)
    local name = key and safe(function() return Locale.Lookup(key) end, key) or nil
    local kind = item:GetType()
    if kind == DealItemTypes.GREATWORK then
        local work = safe(function() return GameInfo.GreatWorks[subtype] end,nil)
        name = name or (work and Locale.Lookup(work.Name)) or 'Great Work'
    elseif kind == DealItemTypes.CAPTIVE then name = name or 'Captive spy'
    elseif kind == DealItemTypes.CITIES then name = name or 'City'
    elseif kind == DealItemTypes.RESOURCES then
        local resource = safe(function() return GameInfo.Resources[value] end,nil)
        name = name or (resource and Locale.Lookup(resource.Name)) or 'Resource'
    elseif kind == DealItemTypes.AGREEMENTS then
        local key = safe(function() return item:GetSubTypeNameID() end,nil)
        local agreement = key and safe(function() return Locale.Lookup(key) end,key) or tostring(subtype)
        name = agreement .. (name and (' / ' .. name) or '')
    else return cleanDeal(name or '') end
    return cleanDeal(name) .. ' [ID ' .. cleanDeal(value) .. ']'
end
local function dealType(item)
    for _, pair in ipairs({{'GOLD','GOLD'},{'RESOURCES','RESOURCE'},{'AGREEMENTS','AGREEMENT'},
        {'FAVOR','FAVOR'},{'CITIES','CITY'},{'GREATWORK','GREAT_WORK'},{'CAPTIVE','CAPTIVE'}}) do
        if item:GetType() == DealItemTypes[pair[1]] then return pair[2] end
    end
    return 'UNKNOWN'
end
local function printTestItems(working, me)
    for item in working:Items() do
        local fromTag = item:GetFromPlayerID() == me and 'US' or 'THEM'
        local value = safe(function() return item:GetValueTypeID() end,
            safe(function() return item:GetValueType() end,'?'))
        local subtype = safe(function() return item:GetSubTypeID() end,
            safe(function() return item:GetSubType() end,'?'))
        print('ITEM|' .. fromTag .. '|' .. dealType(item)
            .. '|' .. safe(function() return item:GetAmount() end,-1)
            .. '|' .. safe(function() return item:GetDuration() end,-1)
            .. '|' .. cleanDeal(value) .. '|' .. cleanDeal(subtype) .. '|name=' .. dealDescription(item))
    end
end
"""


_LUA_AVAILABLE_TRADE = """
local outgoing = safe(function() return DealManager.GetWorkingDeal(DealDirection.OUTGOING, me, target) end,nil)
local agreements = {'OPEN_BORDERS','RESEARCH_AGREEMENT','ALLIANCE','JOINT_WAR','THIRD_PARTY_WAR'}
for _, side in ipairs({{me,target,'OURS','give-'},{target,me,'THEIRS','want-'}}) do
    local from, to, tag, prefix = side[1],side[2],side[3],side[4]
    for _, definition in ipairs({{'GREATWORK','great-work','TRADE_GREAT_WORK'},
                                 {'CAPTIVE','captive','TRADE_CAPTIVE'},
                                 {'CITIES','city','CITY'}}) do
        local entries = possible(from,to,DealItemTypes[definition[1]],outgoing)
        if entries == nil then
            print('TRADE_NOTE|type=' .. definition[2] .. '|message=选项不可用')
        else
            for _, entry in ipairs(entries) do
                local term = prefix .. definition[2] .. '=' .. tostring(entry.ForType)
                local name = safe(function() return Locale.Lookup(entry.ForTypeName) end,entry.ForTypeName or '?')
                local meta = '|available=' .. tostring(entry.IsValid == true)
                    .. '|reason=' .. validationName(entry.ValidationResult) .. '|term=' .. term
                if definition[1] == 'CITIES' then
                    local city = safe(function() return Players[from]:GetCities():FindID(entry.ForType) end,nil)
                    print('CITY|' .. tag .. '|' .. tostring(entry.ForType) .. '|' .. cleanDeal(name)
                        .. '|' .. safe(function() return city:GetPopulation() end,-1)
                        .. '|' .. (safe(function() return city:IsCapital() end,false) and '1' or '0') .. meta)
                else
                    local work = definition[1] == 'GREATWORK' and safe(function() return GameInfo.GreatWorks[entry.ForTypeDescriptionID] end,nil) or nil
                    local effect = work and safe(function() return Locale.Lookup(work.GreatWorkObjectType) end,'') or ''
                    print(definition[3] .. '|side=' .. tag .. '|id=' .. tostring(entry.ForType)
                        .. '|name=' .. cleanDeal(name) .. '|effect=' .. cleanDeal(effect) .. meta)
                end
            end
        end
    end
    local baseAgreements = possible(from,to,DealItemTypes.AGREEMENTS,outgoing)
    if baseAgreements == nil then
        print('TRADE_NOTE|type=AGREEMENTS|message=协议选项不可用')
    else
        for _, base in ipairs(pDiplo:IsAtWarWith(target) and {} or baseAgreements) do
            local subtypeName = nil
            for _, name in ipairs(agreements) do
                if DealAgreementTypes[name] == base.SubType then subtypeName = name; break end
            end
            if subtypeName then
                local canExpand = base.IsValid == true or (DealValidationResult and base.ValidationResult == DealValidationResult.MISSING_DEPENDENCY)
                local entries
                if subtypeName == 'OPEN_BORDERS' then entries = {base}
                elseif canExpand then entries = possible(from,to,DealItemTypes.AGREEMENTS,outgoing,base.SubType)
                else entries = {} end
                if entries == nil then
                    print('TRADE_NOTE|type=' .. subtypeName .. '|message=详细选项不可用')
                elseif #entries == 0 then
                    local name = safe(function() return Locale.Lookup(base.SubTypeName) end,subtypeName)
                    print('TRADE_AGREEMENT|side=' .. tag .. '|type=' .. subtypeName .. '|name=' .. cleanDeal(name)
                        .. '|turns=' .. (base.Duration or 0) .. '|available=false|reason=' .. validationName(base.ValidationResult)
                        .. '|term=unknown')
                else
                    for _, entry in ipairs(entries) do
                        local term = prefix .. subtypeName:lower():gsub('_','-')
                        if subtypeName == 'ALLIANCE' then
                            local alliance = GameInfo.Alliances[entry.ForType]
                            term = term .. '=' .. (alliance and alliance.AllianceType:gsub('ALLIANCE_',''):lower() or tostring(entry.ForType))
                        elseif subtypeName == 'RESEARCH_AGREEMENT' then
                            local technology = GameInfo.Technologies[entry.ForType]
                            term = term .. '=' .. (technology and technology.TechnologyType or tostring(entry.ForType))
                        elseif subtypeName == 'JOINT_WAR' or subtypeName == 'THIRD_PARTY_WAR' then
                            term = term .. '=' .. tostring(entry.ForType)
                            if entry.Parameters and entry.Parameters.WarType ~= nil then term = term .. ':' .. tostring(entry.Parameters.WarType) end
                        end
                        local name = safe(function() return Locale.Lookup(entry.ForTypeDisplayName or entry.SubTypeName or entry.ForTypeName) end,subtypeName)
                        local effect = ''
                        if entry.Parameters and entry.Parameters.WarType ~= nil then
                            local war = safe(function() return GameInfo.Wars[entry.Parameters.WarType] end,nil)
                            effect = war and Locale.Lookup(war.Name) or tostring(entry.Parameters.WarType)
                        end
                        local turns = entry.Duration or base.Duration or 0
                        if subtypeName == 'RESEARCH_AGREEMENT' then
                            turns = safe(function() return Players[from]:GetDiplomacy():ComputeResearchAgreementTurns(Players[to],entry.ForType) end,turns)
                        end
                        print('TRADE_AGREEMENT|side=' .. tag .. '|type=' .. subtypeName .. '|name=' .. cleanDeal(name) .. '|effect=' .. cleanDeal(effect)
                            .. '|turns=' .. turns .. '|available=' .. tostring(entry.IsValid == true)
                            .. '|reason=' .. validationName(entry.ValidationResult) .. '|term=' .. term)
                    end
                end
            end
        end
    end
end
if pDiplo:IsAtWarWith(target) then print('TRADE_NOTE|message=战时不列出和平期协议；停战谈判使用 trade peace') end
print('TRADE_NOTE|message=available=false 表示当前组合有约束；MISSING_DEPENDENCY 或巨作槽位限制可能由交换条款解决，最终以整份交易校验为准')
"""


def build_deal_options_query(other_player_id: int) -> str:
    """Show what both sides can trade — resources, gold, favor, agreements (InGame)."""
    return f"""
{_LUA_DEAL_METADATA}
local me = Game.GetLocalPlayer()
local target = {other_player_id}
local pDiplo = Players[me]:GetDiplomacy()
if target == me or not Players[target] or not Players[target]:IsAlive() or not Players[target]:IsMajor() then {_bail(f"ERR:INVALID_PLAYER|Player {other_player_id} must be another living major civilization")} end
if not pDiplo:HasMet(target) then {_bail(f"ERR:NOT_MET|Have not met player {other_player_id}")} end
local name = Locale.Lookup(PlayerConfigurations[target]:GetCivilizationShortDescription())
print("CIV|" .. target .. "|" .. name:gsub("|","/"))
local ourGold = math.floor(Players[me]:GetTreasury():GetGoldBalance())
local ourGPT = math.floor(Players[me]:GetTreasury():GetGoldYield() - Players[me]:GetTreasury():GetTotalMaintenance())
local ourFavor = 0
pcall(function() ourFavor = math.floor(Players[me]:GetFavor() or 0) end)
local theirGold = math.floor(Players[target]:GetTreasury():GetGoldBalance())
local theirGPT = math.floor(Players[target]:GetTreasury():GetGoldYield() - Players[target]:GetTreasury():GetTotalMaintenance())
local theirFavor = 0
pcall(function() theirFavor = math.floor(Players[target]:GetFavor() or 0) end)
print("ECON|" .. ourGold .. "|" .. ourGPT .. "|" .. ourFavor .. "|" .. theirGold .. "|" .. theirGPT .. "|" .. theirFavor)
for row in GameInfo.Resources() do
    local ourAmt = Players[me]:GetResources():GetResourceAmount(row.Index)
    local theirAmt = Players[target]:GetResources():GetResourceAmount(row.Index)
    if ourAmt > 0 or theirAmt > 0 then
        local rClass = row.ResourceClassType or ""
        local rName = Locale.Lookup(row.Name)
        print("RES|" .. rName:gsub("|","/") .. "|" .. row.ResourceType .. "|" .. rClass .. "|" .. ourAmt .. "|" .. theirAmt)
    end
end
local hasOB = safe(function() return pDiplo:HasOpenBordersFrom(target) end,false)
print("OB|" .. (hasOB and "1" or "0"))
local ai = Players[target]:GetDiplomaticAI()
local stateIdx = ai:GetDiplomaticStateIndex(me)
local hasDiploService = false
pcall(function()
    local civic = GameInfo.Civics["CIVIC_DIPLOMATIC_SERVICE"]
    if civic then hasDiploService = Players[me]:GetCulture():HasCivic(civic.Index) end
end)
local allianceEligible = (stateIdx == 1 and hasDiploService)
local currentAlliance = ""
if stateIdx == 0 then
    local ok3, aType = pcall(function() return pDiplo:GetAllianceType(target) end)
    if ok3 and aType and aType >= 0 then
        local aNames = {{"RESEARCH","CULTURAL","ECONOMIC","MILITARY","RELIGIOUS"}}
        currentAlliance = aNames[aType+1] or ""
    end
end
print("ALLIANCE|" .. (allianceEligible and "1" or "0") .. "|" .. currentAlliance)
{_LUA_AVAILABLE_TRADE}
print("{SENTINEL}")
"""


def parse_deal_options_response(lines: list[str]) -> DealOptions:
    """Parse the deal options query response."""
    opts = DealOptions(other_player_id=0, other_civ_name="")
    for line in lines:
        if line.startswith(("TRADE_GREAT_WORK|", "TRADE_CAPTIVE|", "TRADE_AGREEMENT|")):
            kind, *parts = line.split("|")
            values = dict(part.split("=", 1) for part in parts if "=" in part)
            opts.native_options.append(TradeOption(
                kind=kind.removeprefix("TRADE_"), side=values.get("side", ""),
                name=values.get("name", ""), term=values.get("term", ""),
                available=None if "available" not in values else values["available"] == "true",
                reason=values.get("reason", ""), instance_id=int(values["id"]) if "id" in values else None,
                turns=int(values.get("turns", 0))))
            continue
        if line.startswith("CIV|"):
            parts = line.split("|")
            if len(parts) >= 3:
                opts.other_player_id = int(parts[1])
                opts.other_civ_name = parts[2]
        elif line.startswith("ECON|"):
            parts = line.split("|")
            if len(parts) >= 7:
                opts.our_gold = int(parts[1])
                opts.our_gpt = int(parts[2])
                opts.our_favor = int(parts[3])
                opts.their_gold = int(parts[4])
                opts.their_gpt = int(parts[5])
                opts.their_favor = int(parts[6])
        elif line.startswith("RES|"):
            parts = line.split("|")
            if len(parts) >= 6:
                name = parts[1]
                res_type = parts[2]
                res_class = parts[3]
                our_amt = int(parts[4])
                their_amt = int(parts[5])
                is_luxury = "LUXURY" in res_class
                is_strategic = "STRATEGIC" in res_class
                if our_amt > 0:
                    label = f"{name} x{our_amt}" if our_amt > 1 else name
                    if is_luxury:
                        opts.our_luxuries.append(label)
                    elif is_strategic:
                        opts.our_strategics.append(label)
                if their_amt > 0:
                    label = f"{name} x{their_amt}" if their_amt > 1 else name
                    if is_luxury:
                        opts.their_luxuries.append(label)
                    elif is_strategic:
                        opts.their_strategics.append(label)
        elif line.startswith("OB|"):
            opts.has_open_borders = line.split("|")[1] == "1"
        elif line.startswith("ALLIANCE|"):
            parts = line.split("|")
            if len(parts) >= 3:
                opts.alliance_eligible = parts[1] == "1"
                if parts[2]:
                    opts.current_alliance = parts[2]
        elif line.startswith("CITY|"):
            parts = line.split("|")
            if len(parts) >= 6:
                city = TradeableCity(
                    city_id=int(parts[2]),
                    name=parts[3],
                    population=int(parts[4]),
                    is_capital=parts[5] == "1",
                )
                fields = dict(part.split("=", 1) for part in parts[6:] if "=" in part)
                city.available = None if "available" not in fields else fields["available"] == "true"
                city.reason = fields.get("reason", "")
                city.term = fields.get("term", "")
                if parts[1] == "OURS":
                    opts.our_cities.append(city)
                else:
                    opts.their_cities.append(city)
    return opts


def build_pending_deals_query() -> str:
    """Scan all met players for incoming trade deal offers (InGame context)."""
    return _LUA_DEAL_METADATA + """
local me = Game.GetLocalPlayer()
local pDiplo = Players[me]:GetDiplomacy()
for i = 0, 62 do
    if i ~= me and Players[i] and Players[i]:IsAlive() and Players[i]:IsMajor() and pDiplo:HasMet(i) then
        local sid = DiplomacyManager.FindOpenSessionID(me, i)
        if sid and sid >= 0 then
        local ok, deal = pcall(function() return DealManager.GetWorkingDeal(DealDirection.INCOMING, me, i) end)
        if ok and deal then
            local count = deal:GetItemCount()
            if count and count > 0 then
                local cfg = PlayerConfigurations[i]
                local civName = Locale.Lookup(cfg:GetCivilizationShortDescription())
                local leaderName = Locale.Lookup(cfg:GetLeaderName())
                print("DEAL|" .. i .. "|" .. civName:gsub("|","/") .. "|" .. leaderName:gsub("|","/"))
                for item in deal:Items() do
                    local fromID = item:GetFromPlayerID()
                    local amount = safe(function() return item:GetAmount() end,-1)
                    local duration = safe(function() return item:GetDuration() end,-1)
                    local typeName = dealType(item)
                    local itemName = dealDescription(item)
                    if itemName == "" then itemName = typeName end
                    if itemName ~= "" and itemName ~= "Unknown" then
                        local fromTag = "THEM"
                        if fromID == me then fromTag = "US" end
                        print("ITEM|" .. i .. "|" .. fromTag .. "|" .. typeName .. "|" .. itemName:gsub("|","/") .. "|" .. amount .. "|" .. duration)
                    end
                end
            end
        end
        end
    end
end
print("{SENTINEL}")
""".replace("{SENTINEL}", SENTINEL)


def build_respond_to_deal(other_player_id: int, accept: bool) -> str:
    """Accept or reject a pending trade deal (InGame context)."""
    action = "DealProposalAction.ACCEPTED" if accept else "DealProposalAction.REJECTED"
    verb = "ACCEPTED" if accept else "REJECTED"
    return f"""
local me = Game.GetLocalPlayer()
local target = {other_player_id}
local sid = DiplomacyManager.FindOpenSessionID(me, target)
if not sid or sid < 0 then {_bail(f"ERR:NO_DEAL|No active deal session with player {other_player_id}")} end
DealManager.SendWorkingDeal({action}, me, target)
{_lua_close_diplo_session()}
local name = Locale.Lookup(PlayerConfigurations[target]:GetCivilizationShortDescription())
print("OK:DEAL_{verb}|" .. name)
print("{SENTINEL}")
"""


_LUA_VALIDATE_DEAL = """
-- Validate the complete combination, not each item in isolation: a swap can
-- supply an empty Great Work slot or satisfy a missing agreement dependency.
local okValid, valid = pcall(function() deal:Validate(); return deal:IsValid() end)
if not okValid or valid ~= true then
    print("ERR:INVALID_DEAL|交易组合不合法或无法校验；用 trade options 检查槽位、资源、协议依赖和禁用原因")
    print("---END---")
    return
end
"""


def _lua_deal_item(from_var: str, item: dict) -> str:
    """Add every requested term or reject; never silently omit a term."""
    t = item["type"].upper()
    enum = {"GOLD": "GOLD", "RESOURCE": "RESOURCES", "FAVOR": "FAVOR",
            "AGREEMENT": "AGREEMENTS", "CITY": "CITIES",
            "GREAT_WORK": "GREATWORK", "CAPTIVE": "CAPTIVE"}.get(t)
    if enum is None:
        raise ValueError(f"Unsupported deal item: {t}")
    destination = "target" if from_var == "me" else "me"
    setup = ""
    setters = ""
    if t == "GOLD":
        setters = f"di:SetAmount({item['amount']}); di:SetDuration({item.get('duration', 0)})"
    elif t == "RESOURCE":
        setup = (f'local res = GameInfo.Resources["{item["name"]}"]; '
                 f'if not res then {_bail("ERR:RESOURCE_NOT_FOUND")} end ')
        setters = (f"di:SetValueType(res.Index); di:SetAmount({item.get('amount', 1)}); "
                   f"di:SetDuration({item.get('duration', 30)})")
    elif t == "FAVOR":
        setters = f"di:SetAmount({item['amount']})"
    else:
        subtype = item.get("subtype", "")
        if t == "AGREEMENT" and subtype not in {
                "OPEN_BORDERS", "RESEARCH_AGREEMENT", "ALLIANCE", "JOINT_WAR", "THIRD_PARTY_WAR"}:
            raise ValueError(f"Unsupported agreement: {subtype}")
        selection = ""
        if t == "CITY":
            selection = f"entry.ForType == {item['city_id']}"
        elif t in {"GREAT_WORK", "CAPTIVE"}:
            selection = f"entry.ForType == {item['value_id']}"
        elif t == "AGREEMENT":
            selection = f"entry.SubType == DealAgreementTypes.{subtype}"
            if "technology" in item:
                setup += (f'local technology = GameInfo.Technologies["{item["technology"]}"]; '
                          f'if not technology then {_bail("ERR:TECH_NOT_FOUND")} end ')
                selection += " and (entry.ForType == technology.Index or entry.ForType == technology.Hash)"
            elif "alliance_type" in item:
                setup += (f'local alliance = GameInfo.Alliances["{item["alliance_type"]}"]; '
                          f'if not alliance then {_bail("ERR:ALLIANCE_NOT_FOUND")} end ')
                selection += " and (entry.ForType == alliance.Hash or entry.ForType == alliance.Index)"
            elif "value_id" in item:
                selection += f" and entry.ForType == {item['value_id']}"
            if item.get("war_type") is not None:
                selection += f" and entry.Parameters and entry.Parameters.WarType == {item['war_type']}"
        extra = f"DealAgreementTypes.{subtype}, " if t == "AGREEMENT" and subtype != "OPEN_BORDERS" else ""
        if extra:
            setup += (
                f"local okBase, baseChoices = pcall(function() return DealManager.GetPossibleDealItems("
                f"{from_var}, {destination}, DealItemTypes.AGREEMENTS, deal) end); "
                f"if not okBase or baseChoices == nil then {_bail('ERR:DEAL_OPTIONS_UNAVAILABLE')} end "
                "local baseEntry = nil; "
                f"for _, entry in ipairs(baseChoices) do if entry.SubType == DealAgreementTypes.{subtype} then baseEntry = entry; break end end; "
                "if not baseEntry or (baseEntry.IsValid ~= true and (not DealValidationResult or "
                f"baseEntry.ValidationResult ~= DealValidationResult.MISSING_DEPENDENCY)) then {_bail('ERR:DEAL_ITEM_UNAVAILABLE|Agreement prerequisites not satisfied')} end "
            )
        setup += (
            f"local okChoices, choices = pcall(function() return DealManager.GetPossibleDealItems("
            f"{from_var}, {destination}, DealItemTypes.{enum}, {extra}deal) end); "
            f"if not okChoices or choices == nil then {_bail('ERR:DEAL_OPTIONS_UNAVAILABLE|无法读取交易选项')} end "
            "local selected = nil; "
            f"for _, entry in ipairs(choices) do if {selection} then selected = entry; break end end; "
            f"if not selected then {_bail('ERR:DEAL_ITEM_UNAVAILABLE|' + t + ' is not in trade options for this player')} end "
        )
        if t == "GREAT_WORK":
            setup += f"if selected.ForTypeDescriptionID == nil then {_bail('ERR:GREAT_WORK_TYPE_MISSING')} end "
            setters = "di:SetSubType(selected.ForTypeDescriptionID); di:SetValueType(selected.ForType)"
        elif t == "CAPTIVE":
            setters = "di:SetValueType(selected.ForType)"
        else:
            setters = ("di:SetSubType(selected.SubType); di:SetValueType(selected.ForType); "
                       "di:SetDuration(selected.Duration or 0)")
            if subtype in {"JOINT_WAR", "THIRD_PARTY_WAR"}:
                setup += f"if not selected.Parameters or selected.Parameters.WarType == nil then {_bail('ERR:WAR_TYPE_MISSING')} end "
                setters += '; di:SetParameterValue("WarType", selected.Parameters.WarType)'
    return (f"do if DealItemTypes.{enum} == nil then {_bail('ERR:API_UNAVAILABLE|' + t + ' is not supported by this ruleset')} end "
            f"{setup}local di = deal:AddItemOfType(DealItemTypes.{enum}, {from_var}); "
            f"if not di then {_bail('ERR:DEAL_ITEM_FAILED|Could not add ' + t)} end "
            f"{setters} end")


def build_propose_trade(
    other_player_id: int,
    offer_items: list[dict],
    request_items: list[dict],
) -> str:
    """Build a trade deal proposal and send it (InGame context).

    offer_items: items we give to them (from us).
    request_items: items we want from them.
    Each item dict: {type: GOLD|RESOURCE|FAVOR|AGREEMENT|CITY, amount: int, name: str, duration: int, subtype: str, city_id: int}
    """
    offer_lua = " ".join(_lua_deal_item("me", item) for item in offer_items)
    request_lua = " ".join(_lua_deal_item("target", item) for item in request_items)

    return f"""
local me = Game.GetLocalPlayer()
local target = {other_player_id}
if target == me or not Players[target] or not Players[target]:IsAlive() or not Players[target]:IsMajor() then {_bail("ERR:INVALID_PLAYER|Choose another living major civilization")} end
local pDiplo = Players[me]:GetDiplomacy()
if not pDiplo:HasMet(target) then {_bail("ERR:NOT_MET|Have not met player " + str(other_player_id))} end
if pDiplo:IsAtWarWith(target) then {_bail("ERR:AT_WAR|Cannot trade while at war")} end
if DealManager.HasPendingDeal(me, target) then
    {_bail("ERR:PENDING_DEAL|Resolve the existing offer with trade pending / trade respond before proposing another")}
end
local name = Locale.Lookup(PlayerConfigurations[target]:GetCivilizationShortDescription())
DealManager.ClearWorkingDeal(DealDirection.OUTGOING, me, target)
local deal = DealManager.GetWorkingDeal(DealDirection.OUTGOING, me, target)
if not deal then {_bail("ERR:NO_DEAL_OBJECT|Failed to get working deal")} end
{offer_lua}
{request_lua}
{_LUA_VALIDATE_DEAL}
DiplomacyManager.RequestSession(me, target, "MAKE_DEAL")
DealManager.SendWorkingDeal(DealProposalAction.PROPOSED, me, target)
-- Human CLI safety: never auto-accept the first incoming working deal.  It may
-- be a counter-offer with terms different from the proposal.  Leave the
-- session open so `trade pending` can display the exact terms and the player
-- can explicitly accept or reject them with a second confirmed command.
do
print("OK:PROPOSED|Trade proposal sent to " .. name .. ". Inspect the incoming terms before accepting.")
print("{SENTINEL}")
return
end
"""


def _build_test_deal(
    other_player_id: int,
    offer_items: list[dict],
    request_items: list[dict],
    *,
    peace: bool = False,
) -> str:
    """Test a trade deal via EQUALIZE — returns what the AI thinks is fair (InGame).

    Same item format as build_propose_trade. Does NOT commit the deal.
    """
    offer_lua = " ".join(_lua_deal_item("me", item) for item in offer_items)
    request_lua = " ".join(_lua_deal_item("target", item) for item in request_items)
    relation_check = (
        f'if not pDiplo:IsAtWarWith(target) then {_bail("ERR:NOT_AT_WAR|A peace deal requires an active war")} end\n'
        f'if not pDiplo:CanMakePeaceWith(target) then {_bail("ERR:CANNOT_MAKE_PEACE|10-turn war cooldown or other restriction")} end'
        if peace else
        f'if pDiplo:IsAtWarWith(target) then {_bail("ERR:AT_WAR|Use trade peace for wartime negotiations")} end'
    )
    peace_item = ""
    if peace:
        peace_item = """
local peaceItem = deal:AddItemOfType(DealItemTypes.AGREEMENTS, me)
if not peaceItem then print("ERR:PEACE_ITEM_FAILED|Could not create peace treaty"); print("---END---"); return end
peaceItem:SetSubType(DealAgreementTypes.MAKE_PEACE)
peaceItem:SetLocked(true)
deal:Validate()
"""

    return f"""\n{_LUA_DEAL_METADATA}
local me = Game.GetLocalPlayer()
local target = {other_player_id}
if target == me or not Players[target] or not Players[target]:IsAlive() or not Players[target]:IsMajor() then {_bail("ERR:INVALID_PLAYER|Choose another living major civilization")} end
local pDiplo = Players[me]:GetDiplomacy()
if not pDiplo:HasMet(target) then {_bail("ERR:NOT_MET|Have not met player " + str(other_player_id))} end
{relation_check}
if DealManager.HasPendingDeal(me, target) then
    {_bail("ERR:PENDING_DEAL|Resolve the existing offer with trade pending / trade respond before testing another")}
end
local name = Locale.Lookup(PlayerConfigurations[target]:GetCivilizationShortDescription())
print("CIV|" .. target .. "|" .. name:gsub("|","/"))
pcall(function()
    local sid = DiplomacyManager.FindOpenSessionID(me, target)
    if sid and sid >= 0 then DiplomacyManager.CloseSession(sid) end
end)
DealManager.ClearWorkingDeal(DealDirection.OUTGOING, me, target)
local deal = DealManager.GetWorkingDeal(DealDirection.OUTGOING, me, target)
if not deal then {_bail("ERR:NO_DEAL_OBJECT|Failed to get working deal")} end
{peace_item}
{offer_lua}
{request_lua}
{_LUA_VALIDATE_DEAL}
print("PROPOSED_ITEMS")
printTestItems(deal, me)
DiplomacyManager.RequestSession(me, target, "MAKE_DEAL")
DealManager.SendWorkingDeal(DealProposalAction.EQUALIZE, me, target)
local okEqual, dealsEqual = pcall(function() return DealManager.AreWorkingDealsEqual(me, target) end)
local inDeal = DealManager.GetWorkingDeal(DealDirection.INCOMING, me, target)
if inDeal and inDeal:GetItemCount() and inDeal:GetItemCount() > 0 then
    if not okEqual or dealsEqual == nil then
        print("RESULT|UNKNOWN|无法自动比较 AI 返回条款；请核对是否与原条件相同")
    elseif dealsEqual then
        print("RESULT|ACCEPTED|AI 同意原提案，可按原条件成交")
    else
        print("RESULT|COUNTEROFFER|AI 不同意原提案，但给出了以下还价")
    end
    print("AI_COUNTER")
    printTestItems(inDeal, me)
else
    print("AI_COUNTER")
    if {len(offer_items)} > 0 and {len(request_items)} == 0 then
        -- The stock UI documents EQUALIZE_FAILED as ambiguous for a pure gift:
        -- the AI accepts the gift but has nothing to add to it.
        print("RESULT|ACCEPTED|这是我方单向赠礼；AI 无需还价，可接受原提案")
    else
        print("RESULT|REJECTED|AI 拒绝原提案，且没有给出可成交的还价")
        print("REJECTED")
    end
end
pcall(function()
    local sid = DiplomacyManager.FindOpenSessionID(me, target)
    if sid and sid >= 0 then DiplomacyManager.CloseSession(sid) end
end)
print("{SENTINEL}")
"""


def build_test_trade(
    other_player_id: int,
    offer_items: list[dict],
    request_items: list[dict],
) -> str:
    return _build_test_deal(other_player_id, offer_items, request_items)


def build_test_peace(
    other_player_id: int,
    offer_items: list[dict],
    request_items: list[dict],
) -> str:
    """Test a peace treaty, including optional reparations, without committing it."""
    return _build_test_deal(other_player_id, offer_items, request_items, peace=True)


def parse_test_trade_response(lines: list[str]) -> TestTradeResult:
    """Parse the test trade response."""
    result = TestTradeResult(
        other_player_id=0,
        other_civ_name="",
        proposed=[],
        counter=[],
        rejected=False,
    )
    section = ""
    for line in lines:
        if line.startswith("CIV|"):
            parts = line.split("|")
            if len(parts) >= 3:
                result.other_player_id = int(parts[1])
                result.other_civ_name = parts[2]
        elif line == "PROPOSED_ITEMS":
            section = "proposed"
        elif line == "AI_COUNTER":
            section = "counter"
        elif line == "REJECTED":
            result.rejected = True
            result.decision = "REJECTED"
        elif line.startswith("RESULT|"):
            parts = line.split("|", 2)
            result.decision = parts[1]
            result.decision_message = parts[2] if len(parts) > 2 else ""
            result.rejected = result.decision == "REJECTED"
        elif line.startswith("ITEM|") and section:
            parts = line.split("|")
            if len(parts) >= 7:
                item = TestTradeItem(
                    side=parts[1],
                    item_type=parts[2],
                    amount=int(parts[3]),
                    duration=int(parts[4]),
                    value_id=parts[5],
                    subtype_id=parts[6],
                    name=next((part[5:] for part in parts[7:] if part.startswith("name=")), ""),
                )
                if section == "proposed":
                    result.proposed.append(item)
                else:
                    result.counter.append(item)
    return result


def build_form_alliance(other_player_id: int, alliance_type: str) -> str:
    """Use the same native agreement terms and safety checks as trade."""
    return build_propose_trade(other_player_id, [
        {"type": "AGREEMENT", "subtype": "ALLIANCE", "alliance_type": "ALLIANCE_" + alliance_type.upper()}
    ], [])


def build_propose_peace(
    other_player_id: int,
    offer_items: list[dict] | None = None,
    request_items: list[dict] | None = None,
) -> str:
    """Propose peace with optional reparations (InGame context).

    The stock DiplomacyActionView represents peace as a locked MAKE_PEACE
    agreement in an ordinary MAKE_DEAL session.  Other deal items (gold,
    resources, cities...) can therefore accompany the treaty.
    """
    offer_items = offer_items or []
    request_items = request_items or []
    offer_lua = " ".join(_lua_deal_item("me", item) for item in offer_items)
    request_lua = " ".join(_lua_deal_item("target", item) for item in request_items)
    term_label = "仅停战" if not offer_items and not request_items else "包含附加交换条件"
    return f"""
local me = Game.GetLocalPlayer()
local target = {other_player_id}
if target == me or not Players[target] or not Players[target]:IsAlive() or not Players[target]:IsMajor() then {_bail("ERR:INVALID_PLAYER|Choose another living major civilization")} end
local pDiplo = Players[me]:GetDiplomacy()
if not pDiplo:IsAtWarWith(target) then {_bail("ERR:NOT_AT_WAR|Not at war with player " + str(other_player_id))} end
local canPeace = pDiplo:CanMakePeaceWith(target)
if not canPeace then {_bail("ERR:CANNOT_MAKE_PEACE|10-turn war cooldown or other restriction")} end
if DealManager.HasPendingDeal(me, target) then
    {_bail("ERR:PENDING_DEAL|Resolve the existing offer with trade pending / trade respond before proposing peace")}
end
local name = Locale.Lookup(PlayerConfigurations[target]:GetCivilizationShortDescription())
DealManager.ClearWorkingDeal(DealDirection.OUTGOING, me, target)
local deal = DealManager.GetWorkingDeal(DealDirection.OUTGOING, me, target)
if not deal then {_bail("ERR:NO_DEAL_OBJECT|Failed to get working peace deal")} end
local peaceItem = deal:AddItemOfType(DealItemTypes.AGREEMENTS, me)
if not peaceItem then {_bail("ERR:PEACE_ITEM_FAILED|Could not create peace treaty")} end
peaceItem:SetSubType(DealAgreementTypes.MAKE_PEACE)
peaceItem:SetLocked(true)
deal:Validate()
{offer_lua}
{request_lua}
{_LUA_VALIDATE_DEAL}
DiplomacyManager.RequestSession(me, target, "MAKE_DEAL")
local sid = DiplomacyManager.FindOpenSessionID(me, target)
if not sid or sid < 0 then {_bail("ERR:NO_SESSION|Failed to open peace deal session")} end
DealManager.SendWorkingDeal(DealProposalAction.PROPOSED, me, target)
-- Keep the deal session open. The AI may accept, counter or reject; the
-- player must inspect the actual incoming terms before explicitly responding.
print("OK:PROPOSED|已向 " .. name .. " 发送和平协议（{term_label}）；用 trade pending 查看回应")
print("{SENTINEL}")
"""


def build_check_war_state(other_player_id: int) -> str:
    """Check if we're still at war with a player (InGame context)."""
    return f"""
local me = Game.GetLocalPlayer()
local atWar = Players[me]:GetDiplomacy():IsAtWarWith({other_player_id})
print(atWar and "AT_WAR" or "AT_PEACE")
print("{SENTINEL}")
"""


def parse_diplomacy_response(lines: list[str]) -> list[CivInfo]:
    civs: dict[int, CivInfo] = {}
    for line in lines:
        if line.startswith("CIV|"):
            parts = line.split("|")
            if len(parts) < 13:
                continue
            pid = int(parts[1])
            total_score = 0  # will sum modifiers below
            civs[pid] = CivInfo(
                player_id=pid,
                civ_name=parts[2],
                leader_name=parts[3],
                has_met=parts[4] == "1",
                is_at_war=parts[5] == "1",
                diplomatic_state=parts[6],
                grievances=int(parts[7]),
                access_level=int(parts[8]),
                has_delegation=parts[9] == "1",
                has_embassy=parts[10] == "1",
                they_have_delegation=parts[11] == "1",
                they_have_embassy=parts[12] == "1",
                modifiers=[],
                available_actions=[],
            )
        elif line.startswith("MOD|"):
            parts = line.split("|")
            if len(parts) >= 4:
                pid = int(parts[1])
                if pid in civs:
                    civs[pid].modifiers.append(
                        DiplomacyModifier(
                            score=int(parts[2]),
                            text=parts[3],
                        )
                    )
                    civs[pid].relationship_score += int(parts[2])
        elif line.startswith("ALLIANCE|"):
            parts = line.split("|")
            if len(parts) >= 3:
                pid = int(parts[1])
                if pid in civs:
                    civs[pid].alliance_type = parts[2]
                    if len(parts) >= 4:
                        try:
                            civs[pid].alliance_level = int(parts[3])
                        except ValueError:
                            pass
        elif line.startswith("MILITARY|"):
            parts = line.split("|")
            if len(parts) >= 4:
                pid = int(parts[1])
                if pid in civs:
                    try:
                        civs[pid].military_strength = int(parts[2])
                        civs[pid]._our_military = int(parts[3])  # type: ignore[attr-defined]
                    except ValueError:
                        pass
        elif line.startswith("ECITY|"):
            parts = line.split("|")
            if len(parts) >= 9:
                pid = int(parts[1])
                if pid in civs:
                    xy = parts[3].split(",")
                    try:
                        vc = VisibleCity(
                            name=parts[2],
                            x=int(xy[0]),
                            y=int(xy[1]),
                            population=int(parts[4]),
                            loyalty=float(parts[5]),
                            loyalty_per_turn=float(parts[6]),
                            has_walls=int(parts[7]) > 0,
                            defense_strength=int(parts[8]),
                        )
                        civs[pid].visible_cities.append(vc)
                    except (ValueError, IndexError):
                        pass
        elif line.startswith("CIVCITIES|"):
            parts = line.split("|")
            if len(parts) >= 3:
                pid = int(parts[1])
                if pid in civs:
                    civs[pid].num_cities = int(parts[2])
        elif line.startswith("ACTIONS|"):
            parts = line.split("|")
            if len(parts) >= 3:
                pid = int(parts[1])
                if pid in civs:
                    civs[pid].available_actions = parts[2].split(",")
        elif line.startswith("AGENDA|"):
            parts = line.split("|")
            if len(parts) >= 5:
                pid = int(parts[1])
                if pid in civs:
                    civs[pid].agendas.append(
                        AgendaInfo(
                            category=parts[2],
                            name=parts[3],
                            description=parts[4],
                        )
                    )
        elif line.startswith("PACT|"):
            parts = line.split("|")
            if len(parts) == 3:
                # PACT|pid|DEFENSIVE — pact between us and pid
                pid = int(parts[1])
                if pid in civs:
                    # Mark that this civ has a defensive pact (with us)
                    pass  # We don't track pacts with us specially
            elif len(parts) == 4:
                # PACT|pid1|pid2|DEFENSIVE — third-party pact
                pid1, pid2 = int(parts[1]), int(parts[2])
                if pid1 in civs:
                    civs[pid1].defensive_pacts.append(pid2)
                if pid2 in civs:
                    civs[pid2].defensive_pacts.append(pid1)
    return list(civs.values())


def parse_diplomacy_sessions(lines: list[str]) -> list[DiplomacySession]:
    """Parse open diplomacy session output."""
    sessions = []
    for line in lines:
        if line == "NONE":
            break
        if line.startswith("SESSION|"):
            parts = line.split("|")
            if len(parts) >= 5:
                sessions.append(
                    DiplomacySession(
                        session_id=int(parts[1]),
                        other_player_id=int(parts[2]),
                        other_civ_name=parts[3],
                        other_leader_name=parts[4],
                        choices=[],
                        dialogue_text=parts[5] if len(parts) > 5 else "",
                        reason_text=parts[6] if len(parts) > 6 else "",
                        buttons=parts[7] if len(parts) > 7 else "",
                        is_at_war=parts[8] == "1" if len(parts) > 8 else False,
                    )
                )
        elif line.startswith("DEAL_ITEM|") and sessions:
            # DEAL_ITEM|playerID|fromTag|typeName|itemName|amount|duration
            parts = line.split("|")
            if len(parts) >= 5:
                from_tag = parts[2]  # "THEM" or "US"
                item_name = parts[4]
                amount = int(parts[5]) if len(parts) > 5 else 0
                duration = int(parts[6]) if len(parts) > 6 else 0
                dur_str = f" ({duration} turns)" if duration > 0 else ""
                amt_str = f" x{amount}" if amount > 0 else ""
                entry = f"{'They offer' if from_tag == 'THEM' else 'You offer'}: {item_name}{amt_str}{dur_str}"
                s = sessions[-1]
                s.deal_summary = (
                    (s.deal_summary + "; " + entry) if s.deal_summary else entry
                )
    return sessions


def parse_pending_deals_response(lines: list[str]) -> list[PendingDeal]:
    """Parse DEAL| and ITEM| lines from build_pending_deals_query."""
    deals: dict[int, PendingDeal] = {}
    for line in lines:
        if line.startswith("DEAL|"):
            parts = line.split("|")
            if len(parts) >= 4:
                pid = int(parts[1])
                deals[pid] = PendingDeal(
                    other_player_id=pid,
                    other_player_name=parts[2],
                    other_leader_name=parts[3],
                )
        elif line.startswith("ITEM|"):
            parts = line.split("|")
            if len(parts) >= 7:
                pid = int(parts[1])
                if pid not in deals:
                    continue
                is_from_us = parts[2] == "US"
                item = DealItem(
                    from_player_id=-1 if is_from_us else pid,
                    from_player_name="Us"
                    if is_from_us
                    else deals[pid].other_player_name,
                    item_type=parts[3],
                    name=parts[4],
                    amount=int(parts[5]),
                    duration=int(parts[6]),
                    is_from_us=is_from_us,
                )
                if is_from_us:
                    deals[pid].items_from_us.append(item)
                else:
                    deals[pid].items_from_them.append(item)
    return list(deals.values())
