"""Isolated Lua regressions: every game/service namespace is lexically shadowed.

Only fake objects receive action requests. No real session, deal or turn changes.
"""
from civ6_cli.lua import congress, diplomacy, governance, great_people, tech
from civ6_cli.actions import parse_trade_items


_SANDBOX = r"""
local function run(source, env)
    local prefix = [[return function(env)
local Game, Players, PlayerConfigurations, GameInfo, Locale, UI =
    env.Game, env.Players, env.PlayerConfigurations, env.GameInfo, env.Locale, env.UI
local DealManager, DealDirection, DealProposalAction, DealItemTypes, DealAgreementTypes =
    env.DealManager, env.DealDirection, env.DealProposalAction, env.DealItemTypes, env.DealAgreementTypes
local DiplomacyManager, DealValidationResult, Events, LuaEvents, ContextPtr =
    env.DiplomacyManager, env.DealValidationResult, env.Events, env.LuaEvents, env.ContextPtr
local GameConfiguration, GameEffects, UnitManager, PlayerOperations =
    env.GameConfiguration, env.GameEffects, env.UnitManager, env.PlayerOperations
local me, target, deal, print = 0, 5, env.deal, env.print
]]
    local compiled, err = loadstring(prefix .. source .. "\nend")
    assert(compiled, err)
    compiled()(env)
end
local function base()
    local env = {records={}}
    env.print = function(value) table.insert(env.records,tostring(value)) end
    env.Locale = {Lookup=function(value) return tostring(value or '') end}
    env.Game = {GetLocalPlayer=function() return 0 end}
    return env
end
local function has(env, needle)
    for _, row in ipairs(env.records) do if row:find(needle,1,true) then return true end end
    return false
end
local function database(rows, typeKey)
    local result = {}
    for _, row in ipairs(rows) do
        result[row.Index] = row
        if typeKey then result[row[typeKey]] = row end
        if row.Hash then result[row.Hash] = row end
    end
    return setmetatable(result,{__call=function() local i=0; return function() i=i+1; return rows[i] end end})
end
local function researchEnv(mode)
    local env = base()
    local technology = {Index=0,Hash=100,Name='Technology',TechnologyType='TECH_TEST',EraType='ERA_ANCIENT'}
    local civic = {Index=0,Hash=200,Name='Civic',CivicType='CIVIC_TEST',EraType='ERA_ANCIENT'}
    local techs = {
        GetResearchingTech=function() return 0 end,
        CanResearch=function() return true end, HasTech=function() return false end,
        GetResearchCost=function() return 100 end, GetResearchProgress=function() return 40 end,
        GetTurnsToResearch=function() return 3 end}
    local culture = {
        GetProgressingCivic=function() return 0 end, HasCivic=function() return false end,
        CanProgress=function() return true end, GetCultureCost=function() return 100 end,
        GetCulturalProgress=function() return 60 end, GetCultureYield=function() return 10 end}
    if mode == 'native' then culture.GetTurnsLeft=function() return 4 end end
    if mode == 'legacy' then culture.GetTurnsLeftOnCurrentCivic=function() return 7 end end
    if mode == 'missing' then
        culture.GetCulturalProgress=nil; culture.GetCultureCost=nil; techs.GetResearchCost=nil
        culture.CanProgress=function() return false end
    end
    env.Players = {[0]={GetTechs=function() return techs end,GetCulture=function() return culture end}}
    env.techs=techs; env.culture=culture
    env.Game.GetEras=function() return {GetCurrentEra=function() return 0 end} end
    env.GameInfo = {
        Technologies=database({technology},'TechnologyType'), Civics=database({civic},'CivicType'),
        Eras=database({{Index=0,EraType='ERA_ANCIENT'}})}
    for _, name in ipairs({'Boosts','TechnologyPrereqs','CivicPrereqs','Units','Buildings',
            'Districts','Improvements','Resources','Projects','Policies','Governments'}) do
        env.GameInfo[name] = database({})
    end
    return env
end
local function tradeEnv(mode)
    local env=base()
    env.items={}; env.sent=0; env.sessions=0; env.secondary=0
    env.DealItemTypes={GOLD=1,RESOURCES=2,FAVOR=3,AGREEMENTS=4,CITIES=5,GREATWORK=6,CAPTIVE=7}
    env.DealAgreementTypes={OPEN_BORDERS=10,ALLIANCE=11,RESEARCH_AGREEMENT=12,JOINT_WAR=13,
        THIRD_PARTY_WAR=14,MAKE_PEACE=15}
    env.DealDirection={OUTGOING=0,INCOMING=1}
    env.DealProposalAction={PROPOSED=1,EQUALIZE=2}
    env.DealValidationResult={VALID=0,MISSING_DEPENDENCY=1}
    env.deal={
        AddItemOfType=function(_,kind,from)
            if mode=='nil-item' then return nil end
            local item={kind=kind,from=from}
            item.SetAmount=function(_,v) item.amount=v end
            item.SetDuration=function(_,v) item.duration=v end
            item.SetSubType=function(_,v) item.subtype=v end
            item.SetValueType=function(_,v) item.value=v end
            item.SetLocked=function() end
            item.SetParameterValue=function(_,k,v) item[k]=v end
            item.GetType=function() return item.kind end
            item.GetFromPlayerID=function() return item.from end
            item.GetSubType=function() return item.subtype end
            item.GetValueType=function() return item.value end
            item.GetValueTypeNameID=function() return 'Test Name' end
            item.GetAmount=function() return item.amount or 0 end
            item.GetDuration=function() return item.duration or 0 end
            table.insert(env.items,item); return item
        end,
        Validate=function() return 0 end,
        IsValid=function() return mode~='invalid-deal' end,
        Items=function() local i=0; return function() i=i+1; return env.items[i] end end}
    env.DealManager={
        GetWorkingDeal=function(direction) if direction==0 then return env.deal end; return nil end,
        ClearWorkingDeal=function() end, HasPendingDeal=function() return false end,
        SendWorkingDeal=function() env.sent=env.sent+1 end,
        GetPossibleDealItems=function(from,to,kind,subtype)
            if mode=='missing-api' then error('Not Implemented') end
            if mode=='unavailable' then return {} end
            if kind==6 then return {{ForType=36,ForTypeDescriptionID=62,SubType=0,IsValid=false,ValidationResult=1}} end
            if kind==7 then return {{ForType=1}} end
            if kind==5 then return {{ForType=65536,SubType=99}} end
            local values={ [10]=-1,[11]=-768844443,[12]=11223,[13]=3,[14]=3 }
            if type(subtype)~='number' then
                local result={}
                for key,value in pairs(values) do
                    table.insert(result,{SubType=key,ForType=value,Duration=30,
                        IsValid=mode~='blocked-agreement',ValidationResult=mode=='blocked-agreement' and 2 or 0})
                end
                return result
            end
            env.secondary=env.secondary+1
            return {{SubType=subtype,ForType=values[subtype],Duration=30,IsValid=true,Parameters={WarType=-566258}}}
        end}
    env.DiplomacyManager={
        RequestSession=function() env.sessions=env.sessions+1 end,
        FindOpenSessionID=function() return -1 end}
    local diplo={HasMet=function() return true end, IsAtWarWith=function() return mode=='peace' end,
        CanMakePeaceWith=function() return true end}
    env.Players={[0]={GetDiplomacy=function() return diplo end},
        [5]={IsAlive=function() return true end,IsMajor=function() return true end}}
    env.PlayerConfigurations={[5]={GetCivilizationShortDescription=function() return 'Other' end}}
    env.GameInfo={
        Resources=database({{Index=0,ResourceType='RESOURCE_IRON',Name='Iron'}},'ResourceType'),
        Technologies=database({{Index=0,Hash=11223,TechnologyType='TECH_TEST'}},'TechnologyType'),
        Alliances=database({{Index=0,Hash=-768844443,AllianceType='ALLIANCE_RESEARCH'}},'AllianceType'),
        GreatWorks=database({{Index=62,Name='Great Work'}})}
    env.Events={HideLeaderScreen=function() end}
    env.LuaEvents={DiplomacyActionView_ShowIngameUI=function() end}
    return env
end
"""


def contract_query(quote) -> str:
    parts = [_SANDBOX]

    def case(name, setup, source, assertion):
        parts.append(f"do {setup}\nrun({quote(source)}, env)\n{assertion}\n"
                     f"print('CONTRACT_CHECK|{name}') end")

    research = tech.build_tech_civics_query()
    case("native civic turns, no legacy method", "local env=researchEnv('native')", research,
         "assert(has(env,'CURRENT|Technology|3|Civic|4')); assert(has(env,'CIVIC|Civic|CIVIC_TEST|100|60|4|unknown'))")
    case("legacy civic turns fallback", "local env=researchEnv('legacy')", research,
         "assert(has(env,'CURRENT|Technology|3|Civic|7'))")
    case("optional research APIs missing", "local env=researchEnv('missing')", research,
         "assert(has(env,'CURRENT|Technology|3|Civic|-1')); assert(has(env,'civic_cost=?')); assert(not has(env,'CIVIC|Civic|'))")

    proposals = [
        ("great work subtype is description ID", "give-great-work=36", "env.items[1].subtype==62 and env.items[1].value==36"),
        ("captive instance ID", "give-captive=1", "env.items[1].value==1"),
        ("city subtype retained", "want-city=65536", "env.items[1].subtype==99 and env.items[1].from==5"),
        ("research agreement technology hash", "give-research-agreement=TECH_TEST", "env.items[1].value==11223"),
        ("alliance native hash", "give-alliance=research", "env.items[1].value==-768844443"),
        ("joint war signed native type", "give-joint-war=3:-566258", "env.items[1].WarType==-566258"),
        ("third party war native type", "want-third-party-war=3", "env.items[1].WarType==-566258"),
        ("open borders", "give-open-borders", "env.items[1].subtype==10"),
        ("gold per turn", "want-gpt=5", "env.items[1].amount==5 and env.items[1].duration==30"),
        ("resource", "give-resource=RESOURCE_IRON:20:30", "env.items[1].amount==20 and env.items[1].value==0"),
    ]
    for name, token, assertion in proposals:
        offer, request = parse_trade_items([token])
        case(name, "local env=tradeEnv('valid')", diplomacy.build_propose_trade(5, offer, request),
             f"assert({assertion}); assert(env.sent==1)")
    offer, request = parse_trade_items(["give-great-work=36", "want-great-work=36"])
    case("missing dependency resolved by full combination", "local env=tradeEnv('valid')",
         diplomacy.build_propose_trade(5, offer, request), "assert(#env.items==2 and env.sent==1)")
    for mode, error in [("nil-item", "DEAL_ITEM_FAILED"), ("unavailable", "DEAL_ITEM_UNAVAILABLE"),
                        ("missing-api", "DEAL_OPTIONS_UNAVAILABLE"), ("invalid-deal", "INVALID_DEAL")]:
        case(mode + " cannot send", f"local env=tradeEnv('{mode}')",
             diplomacy.build_propose_trade(5, offer, request), f"assert(env.sent==0); assert(has(env,'ERR:{error}'))")
    case("no silently discarded unknown resource", "local env=tradeEnv('valid')",
         diplomacy.build_propose_trade(5,[{"type":"RESOURCE","name":"RESOURCE_MISSING"}],[]),
         "assert(env.sent==0); assert(has(env,'ERR:RESOURCE_NOT_FOUND'))")
    case("peace uses same great work terms", "local env=tradeEnv('peace'); env.DiplomacyManager.FindOpenSessionID=function() return 1 end",
         diplomacy.build_propose_peace(5, offer, request), "assert(env.sent==1); assert(env.items[2].subtype==62)")
    case("invalid test cannot equalize", "local env=tradeEnv('invalid-deal')",
         diplomacy.build_test_trade(5,offer,request), "assert(env.sent==0); assert(has(env,'ERR:INVALID_DEAL'))")
    agreement_offer, _ = parse_trade_items(['give-alliance=research'])
    case("blocked primary agreement never queries secondary API", "local env=tradeEnv('blocked-agreement')",
         diplomacy.build_propose_trade(5,agreement_offer,[]),
         "assert(env.secondary==0 and env.sent==0); assert(has(env,'ERR:DEAL_ITEM_UNAVAILABLE'))")
    native_options = (diplomacy._LUA_DEAL_METADATA +
                      "\nlocal pDiplo=Players[me]:GetDiplomacy()\n" + diplomacy._LUA_AVAILABLE_TRADE)
    case("read options respect primary agreement gate", "local env=tradeEnv('blocked-agreement')",
         native_options, "assert(env.secondary==0); assert(has(env,'TRADE_GREAT_WORK')); assert(has(env,'available=false'))")
    case("congress getter absent", "local env=base(); env.Players={ [0]={GetDiplomacy=function() return {} end} }",
         congress.build_world_congress_query(), "assert(has(env,'CONGRESS_NOTE'))")
    case("era getter absent", "local env=base()", governance.build_dedications_query(), "assert(has(env,'ERA_NOTE'))")
    case("no current research does not query negative index", """
local env=researchEnv('native')
env.techs.GetResearchingTech=function() return nil end
env.culture.GetProgressingCivic=function() return -1 end
local get=env.techs.GetResearchProgress
env.techs.GetResearchProgress=function(_,idx) assert(idx>=0,'negative research index'); return get() end
""", research, "assert(has(env,'tech_type=NONE|tech_progress=?')); assert(has(env,'civic_type=NONE|civic_progress=?'))")
    case("present congress object with optional APIs missing", """
local env=base()
env.Game.GetWorldCongress=function() return {} end
env.Players={ [0]={GetDiplomacy=function() return {} end} }
""", congress.build_world_congress_query(), "assert(has(env,'CONGRESS_NOTE')); assert(has(env,'WC_STATUS'))")
    case("nil government and missing policy slot API", """
local env=base()
env.Players={ [0]={GetCulture=function() return {GetCurrentGovernment=function() return nil end} end} }
env.GameInfo={Policies=database({}),Governments=database({})}
""", governance.build_policies_query(), "assert(has(env,'GOVERNMENT_STATE|state=unknown')); assert(has(env,'POLICY_NOTE'))")
    case("one missing great person API does not discard other metadata", """
local env=base()
env.Game.GetGreatPeople=function() return {
    GetTimeline=function() return {{Class=0,Individual=1,Era=0,Cost=100}} end,
    GetPatronizeCost=function(_,me,id,yield) if yield==2 then error('Not Implemented') end; return 200 end,
    CanRecruitPerson=function() return true end} end
env.Players={ [0]={IsAlive=function() return true end,IsMajor=function() return true end,
    GetGreatPeoplePoints=function() return {GetPointsTotal=function() return 10 end} end} }
env.PlayerConfigurations={ [0]={GetCivilizationShortDescription=function() return 'Test' end} }
env.GameInfo={
    GreatPersonClasses=database({{Index=0,Name='Artist'}}),
    GreatPersonIndividuals=database({{Index=1,Name='Person',GreatPersonIndividualType='PERSON'}}),
    Eras=database({{Index=0,Name='Ancient'}}),
    GreatPersonIndividualActionModifiers=database({}),GreatPersonIndividualBirthModifiers=database({}),
    GreatWorks=database({})}
""", great_people.build_great_people_query(),
         "assert(has(env,'gold_cost=?|faith_cost=200')); assert(has(env,'can_recruit=true'))")
    case("missing equality API does not pretend counteroffer", """
local env=tradeEnv('valid')
env.deal.GetItemCount=function() return #env.items end
env.DealManager.GetWorkingDeal=function() return env.deal end
""", diplomacy.build_test_trade(5,offer,request),
         "assert(has(env,'RESULT|UNKNOWN')); assert(has(env,'[ID 36]')); assert(not has(env,'RESULT|COUNTEROFFER'))")
    return "\n".join(parts)
