"""Great Work transfers, following GreatWorksOverview's native slot rules.

Work IDs are runtime indices, not GreatWorkType indices. Both reads and writes
resolve the source afresh from owned buildings; writes never trust an old menu.
"""

from ._helpers import SENTINEL, _int


_COMMON = """
local me = Game.GetLocalPlayer()
local player = Players[me]
local function clean(value)
    return tostring(value or ''):gsub('|', '/'):gsub('[\\r\\n]', ' ')
end
local function full(buildings, building)
    for slot = 0, buildings:GetNumGreatWorkSlots(building) - 1 do
        if buildings:GetGreatWorkInSlot(building, slot) < 0 then return false end
    end
    return true
end
local function object(buildings, work)
    local row = GameInfo.GreatWorks[buildings:GetGreatWorkTypeFromIndex(work)]
    return row and row.GreatWorkObjectType or nil
end
local function workLock(buildings, building, work)
    local kind = object(buildings, work)
    if kind == 'GREATWORKOBJECT_ARTIFACT' and not full(buildings, building) then
        return '文物只能在已填满的博物馆之间交换'
    end
    if kind == 'GREATWORKOBJECT_SCULPTURE' or kind == 'GREATWORKOBJECT_LANDSCAPE'
        or kind == 'GREATWORKOBJECT_PORTRAIT' or kind == 'GREATWORKOBJECT_RELIGIOUS' then
        local wait = buildings:GetTurnFromIndex(work)
            + (GlobalParameters.GREATWORK_ART_LOCK_TIME or 10) - Game.GetCurrentGameTurn()
        if wait > 0 then return '艺术品冷却：还需 ' .. wait .. ' 回合' end
    end
    return nil
end
local function fits(buildings, building, slot, kind)
    local row = GameInfo.GreatWorkSlotTypes[buildings:GetGreatWorkSlotType(building, slot)]
    if not row or not kind then return false end
    for valid in GameInfo.GreatWork_ValidSubTypes() do
        if valid.GreatWorkSlotType == row.GreatWorkSlotType
            and valid.GreatWorkObjectType == kind then return true end
    end
    return false
end
local function locate(work)
    for _, city in player:GetCities():Members() do
        local buildings = city:GetBuildings()
        for building in GameInfo.Buildings() do
            if buildings:HasBuilding(building.Index) then
                for slot = 0, buildings:GetNumGreatWorkSlots(building.Index) - 1 do
                    if buildings:GetGreatWorkInSlot(building.Index, slot) == work then
                        return city, buildings, building.Index, slot
                    end
                end
            end
        end
    end
end
local function canMove(src, srcBuilding, srcSlot, dst, dstBuilding, dstSlot)
    local work = src:GetGreatWorkInSlot(srcBuilding, srcSlot)
    local kind = object(src, work)
    if not fits(dst, dstBuilding, dstSlot, kind) then return false, '目的槽位不兼容' end
    local reason = workLock(src, srcBuilding, work)
    if reason then return false, reason end
    local other = dst:GetGreatWorkInSlot(dstBuilding, dstSlot)
    if kind == 'GREATWORKOBJECT_ARTIFACT' and not full(dst, dstBuilding) then
        return false, '文物只能在已填满的博物馆之间交换'
    end
    if other < 0 then
        return kind ~= 'GREATWORKOBJECT_ARTIFACT', '文物不能移入空槽位'
    end
    if not fits(src, srcBuilding, srcSlot, object(dst, other)) then
        return false, '目的巨作无法换入原槽位'
    end
    reason = workLock(dst, dstBuilding, other)
    if reason then return false, '目的巨作：' .. reason end
    return true, nil
end
"""


def _source(work_id: int) -> str:
    return f"""
local workID = {_int(work_id)}
local srcCity, src, srcBuilding, srcSlot = locate(workID)
if not srcCity then print('ERR:GREAT_WORK_NOT_OWNED|未找到己方巨作；用 great-work list 查看巨作 ID'); return end
"""


def build_destinations_query(work_id: int) -> str:
    return _COMMON + _source(work_id) + """
local workRow = GameInfo.GreatWorks[src:GetGreatWorkTypeFromIndex(workID)]
local sourceLock = workLock(src, srcBuilding, workID)
print('GREAT_WORK_SOURCE|id=' .. workID .. '|name=' .. clean(Locale.Lookup(workRow.Name))
    .. '|city=' .. clean(Locale.Lookup(srcCity:GetName())) .. '|city_id=' .. srcCity:GetID()
    .. '|building=' .. GameInfo.Buildings[srcBuilding].BuildingType .. '|slot=' .. srcSlot
    .. '|requirements=' .. clean(sourceLock or '无额外限制'))
local count = 0
for _, city in player:GetCities():Members() do
    local dst = city:GetBuildings()
    for building in GameInfo.Buildings() do
        if dst:HasBuilding(building.Index) then
            for slot = 0, dst:GetNumGreatWorkSlots(building.Index) - 1 do
                local same = city:GetID() == srcCity:GetID() and building.Index == srcBuilding and slot == srcSlot
                if not same and fits(dst, building.Index, slot, workRow.GreatWorkObjectType) then
                    count = count + 1
                    local allowed, reason = canMove(src, srcBuilding, srcSlot, dst, building.Index, slot)
                    local other = dst:GetGreatWorkInSlot(building.Index, slot)
                    local otherRow = other >= 0 and GameInfo.GreatWorks[dst:GetGreatWorkTypeFromIndex(other)] or nil
                    local command = 'great-work move ' .. workID .. ' ' .. city:GetID() .. ' ' .. building.BuildingType .. ' ' .. slot
                    print('GREAT_WORK_DEST|city=' .. clean(Locale.Lookup(city:GetName())) .. '|city_id=' .. city:GetID()
                        .. '|building=' .. clean(Locale.Lookup(building.Name)) .. '|building_type=' .. building.BuildingType
                        .. '|slot=' .. slot .. '|mode=' .. (other < 0 and '移动' or '交换')
                        .. '|name=' .. clean(otherRow and Locale.Lookup(otherRow.Name) or '空槽位')
                        .. '|available=' .. (allowed and 'yes' or 'no') .. '|requirements=' .. clean(allowed and '无额外限制' or reason)
                        .. '|next=' .. (allowed and command or '先解除上述限制'))
                end
            end
        end
    end
end
if count == 0 then print('GREAT_WORK_DEST|当前没有其他兼容槽位') end
""" + f'\nprint("{SENTINEL}")\n'


def build_move(work_id: int, city_id: int, building_type: str, slot: int) -> str:
    # building_type is validated as BUILDING_* by the action-plan boundary.
    return _COMMON + _source(work_id) + f"""
local dstCity = player:GetCities():FindID({_int(city_id)})
if not dstCity or dstCity:GetID() ~= {_int(city_id)} then print('ERR:CITY_NOT_OWNED|目的城市不是己方城市，或城市 ID 无效'); return end
local building = GameInfo.Buildings["{building_type}"]
local dst = dstCity:GetBuildings()
if not building or not dst:HasBuilding(building.Index) then
    print('ERR:BUILDING_NOT_OWNED|目的城市没有指定建筑'); return
end
local slot = {_int(slot)}
if slot < 0 or slot >= dst:GetNumGreatWorkSlots(building.Index) then
    print('ERR:INVALID_GREAT_WORK_SLOT|槽位超出范围；从 great-work options 复制编号'); return
end
if srcCity:GetID() == dstCity:GetID() and srcBuilding == building.Index and srcSlot == slot then
    print('ERR:SAME_GREAT_WORK_SLOT|巨作已在该槽位'); return
end
local allowed, reason = canMove(src, srcBuilding, srcSlot, dst, building.Index, slot)
if not allowed then print('ERR:GREAT_WORK_MOVE_BLOCKED|' .. clean(reason)); return end
local params = {{}}
params[PlayerOperations.PARAM_PLAYER_ONE] = me
params[PlayerOperations.PARAM_CITY_SRC] = srcCity:GetID()
params[PlayerOperations.PARAM_CITY_DEST] = dstCity:GetID()
params[PlayerOperations.PARAM_BUILDING_SRC] = srcBuilding
params[PlayerOperations.PARAM_BUILDING_DEST] = building.Index
params[PlayerOperations.PARAM_GREAT_WORK_INDEX] = workID
params[PlayerOperations.PARAM_SLOT] = slot
local requested = UI.RequestPlayerOperation(me, PlayerOperations.MOVE_GREAT_WORK, params)
if requested == false then print('ERR:GREAT_WORK_MOVE_REJECTED|游戏未接受移动请求'); return end
print('OK:GREAT_WORK_MOVE_REQUESTED|已提交巨作移动/交换请求；great-work list 查看实时位置')
print("{SENTINEL}")
"""
