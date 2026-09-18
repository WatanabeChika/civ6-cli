"""Isolated Lua contract checks. Every game namespace is a fake lexical shadow."""

from civ6_cli.lua.great_works import build_move


_SANDBOX = r"""
local function database(rows, typeKey)
    local result = {}
    for _, row in ipairs(rows) do
        if row.Index ~= nil then result[row.Index] = row end
        if typeKey then result[row[typeKey]] = row end
    end
    return setmetatable(result, {__call=function()
        local i = 0
        return function() i=i+1; return rows[i] end
    end})
end
local function makeEnvironment()
    local env = {records={}, requested=nil, rejected=false, created={}}
    local types = {[4]=0,[72]=0,[36]=1,[65]=2,[38]=2,[88]=2,[10]=2,[11]=2,[12]=2,
        [91]=3,[13]=1,[98]=3,[61]=3,[57]=3,[94]=3}
    local slotCounts = {[0]=2,[1]=1,[2]=3,[3]=3}
    local slotKinds = {[0]=0,[1]=1,[2]=2,[3]=3}
    local function buildings(slots)
        return {slots=slots,
            HasBuilding=function(self,b) return self.slots[b] ~= nil end,
            GetNumGreatWorkSlots=function(self,b) return self.slots[b] and slotCounts[b] or 0 end,
            GetGreatWorkInSlot=function(self,b,s) return self.slots[b][s] end,
            GetGreatWorkTypeFromIndex=function(self,w) return types[w] end,
            GetGreatWorkSlotType=function(self,b,s) return slotKinds[b] end,
            GetTurnFromIndex=function(self,w) return env.created[w] or 0 end}
    end
    env.src = buildings({[0]={[0]=4,[1]=-1}, [1]={[0]=36},
        [2]={[0]=65,[1]=38,[2]=88}, [3]={[0]=91,[1]=13,[2]=98}})
    env.dst = buildings({[0]={[0]=72,[1]=-1}, [1]={[0]=-1},
        [2]={[0]=10,[1]=11,[2]=12}, [3]={[0]=61,[1]=57,[2]=94}})
    local function city(id,b)
        return {GetID=function() return id end, GetBuildings=function() return b end}
    end
    local cities = {city(65536,env.src),city(131073,env.dst)}
    env.Players = {[0]={GetCities=function() return {
        Members=function()
            local i=0
            return function() i=i+1; if cities[i] then return i,cities[i] end end
        end,
        FindID=function(_,id)
            if id == 65536 or id == 0 then return cities[1] end
            if id == 131073 or id == 1 then return cities[2] end
        end} end}}
    env.Game = {GetLocalPlayer=function() return 0 end, GetCurrentGameTurn=function() return 100 end}
    env.GameInfo = {
        Buildings=database({{Index=0,BuildingType='BUILDING_AMPHITHEATER'},
            {Index=1,BuildingType='BUILDING_PALACE'}, {Index=2,BuildingType='BUILDING_MUSEUM_ARTIFACT'},
            {Index=3,BuildingType='BUILDING_MUSEUM_ART'}},'BuildingType'),
        GreatWorks=database({{Index=0,GreatWorkObjectType='GREATWORKOBJECT_WRITING'},
            {Index=1,GreatWorkObjectType='GREATWORKOBJECT_SCULPTURE'},
            {Index=2,GreatWorkObjectType='GREATWORKOBJECT_ARTIFACT'},
            {Index=3,GreatWorkObjectType='GREATWORKOBJECT_PORTRAIT'}}),
        GreatWorkSlotTypes=database({{Index=0,GreatWorkSlotType='WRITING'},
            {Index=1,GreatWorkSlotType='ANY'}, {Index=2,GreatWorkSlotType='ARTIFACT'},
            {Index=3,GreatWorkSlotType='ART'}}),
        GreatWork_ValidSubTypes=database({
            {GreatWorkSlotType='WRITING',GreatWorkObjectType='GREATWORKOBJECT_WRITING'},
            {GreatWorkSlotType='ANY',GreatWorkObjectType='GREATWORKOBJECT_WRITING'},
            {GreatWorkSlotType='ANY',GreatWorkObjectType='GREATWORKOBJECT_SCULPTURE'},
            {GreatWorkSlotType='ANY',GreatWorkObjectType='GREATWORKOBJECT_ARTIFACT'},
            {GreatWorkSlotType='ANY',GreatWorkObjectType='GREATWORKOBJECT_PORTRAIT'},
            {GreatWorkSlotType='ARTIFACT',GreatWorkObjectType='GREATWORKOBJECT_ARTIFACT'},
            {GreatWorkSlotType='ART',GreatWorkObjectType='GREATWORKOBJECT_SCULPTURE'},
            {GreatWorkSlotType='ART',GreatWorkObjectType='GREATWORKOBJECT_PORTRAIT'}})}
    env.GlobalParameters = {GREATWORK_ART_LOCK_TIME=10}
    env.Locale = {Lookup=function(value) return value end}
    env.PlayerOperations = {MOVE_GREAT_WORK='move',PARAM_PLAYER_ONE='player',PARAM_CITY_SRC='srcCity',
        PARAM_CITY_DEST='dstCity',PARAM_BUILDING_SRC='srcBuilding',PARAM_BUILDING_DEST='dstBuilding',
        PARAM_GREAT_WORK_INDEX='work',PARAM_SLOT='slot'}
    env.UI = {RequestPlayerOperation=function(player,operation,params)
        env.requested = {player=player,operation=operation,params=params}
        return not env.rejected
    end}
    env.print = function(value) table.insert(env.records,tostring(value)) end
    return env
end
local function testcase(name,source,setup,expected,work,city,building,slot)
    local env = makeEnvironment()
    setup(env)
    local prefix = [[return function(env)
local Game, Players, GameInfo, UI, Locale, GlobalParameters, PlayerOperations, print =
    env.Game, env.Players, env.GameInfo, env.UI, env.Locale, env.GlobalParameters, env.PlayerOperations, env.print
]]
    local compiled,err = loadstring(prefix .. source .. '\nend')
    if not compiled then error(err) end
    compiled()(env)
    local found=false
    for _,record in ipairs(env.records) do
        if string.sub(record,1,#expected) == expected then found=true end
    end
    if not found then error(name .. ': ' .. table.concat(env.records,';')) end
    if string.sub(expected,1,3) == 'OK:' then
        local requested=env.requested
        if not requested or requested.player ~= 0 or requested.operation ~= 'move' then error(name .. ': no fake request') end
        local p=requested.params
        if p.player ~= 0 or p.srcCity ~= 65536 or p.dstCity ~= city or p.work ~= work
            or p.dstBuilding ~= building or p.slot ~= slot or p.srcBuilding == nil then
            error(name .. ': incorrect native parameters')
        end
    elseif expected ~= 'ERR:GREAT_WORK_MOVE_REJECTED' and env.requested then
        error(name .. ': invalid transfer reached fake request')
    end
end
"""


def contract_query(quote) -> str:
    cases = [
        ("book move", 4, 131073, "BUILDING_AMPHITHEATER", 1, "", "OK:", 0),
        ("book swap", 4, 131073, "BUILDING_AMPHITHEATER", 0, "", "OK:", 0),
        ("incompatible destination", 4, 131073, "BUILDING_MUSEUM_ART", 0, "", "ERR:GREAT_WORK_MOVE_BLOCKED", 3),
        ("incompatible reverse swap", 4, 65536, "BUILDING_PALACE", 0, "", "ERR:GREAT_WORK_MOVE_BLOCKED", 1),
        ("art move", 36, 131073, "BUILDING_PALACE", 0, "", "OK:", 1),
        ("art swap", 36, 131073, "BUILDING_MUSEUM_ART", 0, "", "OK:", 3),
        ("source cooldown", 36, 131073, "BUILDING_PALACE", 0, "env.created[36]=100", "ERR:GREAT_WORK_MOVE_BLOCKED", 1),
        ("destination cooldown", 36, 131073, "BUILDING_MUSEUM_ART", 0, "env.created[61]=100", "ERR:GREAT_WORK_MOVE_BLOCKED", 3),
        ("cooldown boundary", 36, 131073, "BUILDING_PALACE", 0, "env.created[36]=90", "OK:", 1),
        ("artifact swap", 65, 131073, "BUILDING_MUSEUM_ARTIFACT", 0, "", "OK:", 2),
        ("source museum incomplete", 65, 131073, "BUILDING_MUSEUM_ARTIFACT", 0, "env.src.slots[2][2]=-1", "ERR:GREAT_WORK_MOVE_BLOCKED", 2),
        ("destination museum incomplete", 65, 131073, "BUILDING_MUSEUM_ARTIFACT", 0, "env.dst.slots[2][2]=-1", "ERR:GREAT_WORK_MOVE_BLOCKED", 2),
        ("artifact empty slot", 65, 131073, "BUILDING_PALACE", 0, "", "ERR:GREAT_WORK_MOVE_BLOCKED", 1),
        ("same slot", 4, 65536, "BUILDING_AMPHITHEATER", 0, "", "ERR:SAME_GREAT_WORK_SLOT", 0),
        ("unowned city", 4, 999, "BUILDING_AMPHITHEATER", 0, "", "ERR:CITY_NOT_OWNED", 0),
        ("stale short city ID", 4, 1, "BUILDING_AMPHITHEATER", 0, "", "ERR:CITY_NOT_OWNED", 0),
        ("slot out of range", 4, 131073, "BUILDING_AMPHITHEATER", 2, "", "ERR:INVALID_GREAT_WORK_SLOT", 0),
        ("missing building", 4, 131073, "BUILDING_PALACE", 0, "env.dst.slots[1]=nil", "ERR:BUILDING_NOT_OWNED", 1),
        ("unowned work", 999, 131073, "BUILDING_AMPHITHEATER", 0, "", "ERR:GREAT_WORK_NOT_OWNED", 0),
        ("native refusal", 4, 131073, "BUILDING_AMPHITHEATER", 1, "env.rejected=true", "ERR:GREAT_WORK_MOVE_REJECTED", 0),
    ]
    statements = [_SANDBOX]
    for name, work, city, building, slot, setup, expected, building_index in cases:
        source = build_move(work, city, building, slot)
        statements.append(f"testcase({quote(name)},{quote(source)},function(env) {setup} end,"
                          f"{quote(expected)},{work},{city},{building_index},{slot})")
    statements.append(f"print('CONTRACT_CHECK|{len(cases)} isolated Great Work cases passed; no native writes')")
    return "\n".join(statements)
