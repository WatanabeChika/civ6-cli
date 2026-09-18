"""Validated action plans and human-oriented option queries.

This module is the only bridge from CLI arguments to state-changing Lua.  It
accepts identifiers and a small set of enumerated operations, never arbitrary
Lua.  Every action is executed once: transport failures are reported as an
unknown outcome and are never retried automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Callable, Iterable

from .game import read_status
from .lua import (cities, congress, diplomacy, economy, espionage,
                  governance, great_people, great_works, map as lua_map, notifications,
                  religion, tech, units)
from .transport import FireTunerConnection, FireTunerError
from .commands import DIPLOMATIC_ACTIONS


INGAME = "InGame"
GAMECORE = "GameCore_Tuner"
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


class ActionRejected(ValueError):
    """The game definitively rejected an action before applying it."""


class ActionOutcomeUnknown(FireTunerError):
    """The command may have applied; the caller must inspect live state."""


@dataclass(frozen=True)
class Query:
    lua: str
    context: str = INGAME
    timeout: float = 15.0


@dataclass(frozen=True)
class ActionPlan:
    summary: str
    lua: str
    context: str = INGAME
    timeout: float = 15.0
    verify: Query | None = None
    allow_inactive_turn: bool = False
    dangerous: bool = False
    requires_ack: bool = True
    followups: tuple[tuple[float, Query], ...] = ()


@dataclass(frozen=True)
class ActionResult:
    lines: tuple[str, ...]
    verification: tuple[str, ...]
    uncertain: bool = False


@dataclass(frozen=True)
class OptionPlan:
    title: str
    queries: tuple[Query, ...]


def clean_lines(lines: Iterable[str]) -> list[str]:
    """Remove the vendored builders' marker; transport has its own marker."""
    return [line for line in lines if line and line != "---END---"]


def game_symbol(value: str, *prefixes: str, name: str = "游戏类型") -> str:
    value = value.strip().upper().replace("-", "_")
    if not _SYMBOL.fullmatch(value):
        raise ValueError(f"{name}格式无效：{value!r}")
    if prefixes and not value.startswith(prefixes):
        raise ValueError(f"{name}必须以 {' / '.join(prefixes)} 开头")
    return value


def choice(value: str, allowed: Iterable[str], *, name: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    values = tuple(allowed)
    if normalized not in values:
        raise ValueError(f"{name}应为：" + " / ".join(values))
    return normalized


def parse_policy_assignments(values: Iterable[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for token in values:
        for assignment in token.split(","):
            raw_slot, separator, raw_policy = assignment.partition("=")
            if not separator or not raw_slot.isdecimal():
                raise ValueError("政策格式应为 槽位=POLICY_TYPE，可用逗号分隔")
            slot = int(raw_slot)
            if not 0 <= slot <= 31 or slot in result:
                raise ValueError(f"政策槽位无效或重复：{raw_slot}")
            result[slot] = ("NONE" if raw_policy.upper() == "NONE" else
                            game_symbol(raw_policy, "POLICY_", name="政策卡"))
    if not result:
        raise ValueError("至少提供一个政策槽位")
    return result


def parse_vote_specs(values: Iterable[str]) -> list[dict[str, int]]:
    votes: list[dict[str, int]] = []
    for value in values:
        parts = value.split(":")
        if len(parts) != 4:
            raise ValueError("投票格式应为 <决议Hash>:<A或B>:<目标ID>:<票数>")
        raw_hash, raw_option, raw_target, raw_votes = parts
        if not (raw_hash.lstrip("-").isdecimal() and raw_target.lstrip("-").isdecimal()
                and raw_votes.isdecimal()):
            raise ValueError("决议 Hash、目标和票数必须是整数")
        option = {"A": 1, "B": 2, "1": 1, "2": 2}.get(raw_option.upper())
        count = int(raw_votes)
        if option is None or not 1 <= count <= 100:
            raise ValueError("选项应为 A/B，票数范围为 1–100")
        votes.append({"hash": int(raw_hash), "option": option,
                      "target": int(raw_target), "votes": count})
    if not votes:
        raise ValueError("至少提供一项世界议会投票")
    return votes


def _positive_int(value: str, *, name: str, maximum: int = 1_000_000) -> int:
    if not value.isdecimal() or not 0 < int(value) <= maximum:
        raise ValueError(f"{name}必须是 1–{maximum} 的整数")
    return int(value)


def _nonnegative_int(value: str, *, name: str, maximum: int = 2_147_483_647) -> int:
    if not value.isdecimal() or not 0 <= int(value) <= maximum:
        raise ValueError(f"{name}必须是 0–{maximum} 的整数")
    return int(value)


def great_work_options_plan(value: str) -> OptionPlan:
    work_id = _nonnegative_int(value, name="巨作ID")
    return OptionPlan("巨作移动与交换目标", (Query(great_works.build_destinations_query(work_id)),))


def great_work_move_plan(args: list[str], *, city_id: Callable[[str], int]) -> ActionPlan:
    _require_count(args, 4, "great-work move <巨作ID> <目标城市> <BUILDING_TYPE> <槽位>")
    work_id = _nonnegative_int(args[0], name="巨作ID")
    destination = city_id(args[1])
    building = game_symbol(args[2], "BUILDING_", name="建筑代号")
    slot = _nonnegative_int(args[3], name="巨作槽位", maximum=255)
    return ActionPlan(f"将巨作 {work_id} 移至城市 {destination} / {building} / 槽位 {slot}；"
                      "若目的槽位已有巨作则交换",
                      great_works.build_move(work_id, destination, building, slot))


def _signed_int(value: str, *, name: str) -> int:
    if not re.fullmatch(r"-?\d+", value) or not -(2**31) <= int(value) < 2**31:
        raise ValueError(f"{name}必须是 32 位整数")
    return int(value)


def parse_trade_items(tokens: Iterable[str], *, allow_empty: bool = False) -> tuple[list[dict], list[dict]]:
    """Parse readable trade terms such as ``give-gold=100 want-gpt=5``."""
    offer: list[dict] = []
    request: list[dict] = []
    for token in tokens:
        key, separator, raw = token.partition("=")
        key = key.lower().replace("_", "-")
        if key in {"give-open-borders", "want-open-borders"} and not separator:
            raw, separator = "yes", "="
        if not separator:
            raise ValueError(f"交易条款缺少 =：{token}")
        if key.startswith("give-"):
            target, kind = offer, key[5:]
        elif key.startswith("want-"):
            target, kind = request, key[5:]
        else:
            raise ValueError(f"交易条款应以 give- 或 want- 开头：{key}")
        if kind in {"gold", "gpt", "favor"}:
            amount = _positive_int(raw, name=kind)
            if kind == "favor":
                target.append({"type": "FAVOR", "amount": amount})
            else:
                target.append({"type": "GOLD", "amount": amount,
                               "duration": 30 if kind == "gpt" else 0})
        elif kind == "resource":
            bits = raw.split(":")
            resource_type = game_symbol(bits[0], "RESOURCE_", name="资源")
            if len(bits) > 3:
                raise ValueError("资源条款格式为 RESOURCE_TYPE[:数量[:持续回合]]")
            amount = _positive_int(bits[1], name="资源数量", maximum=999) if len(bits) >= 2 else 1
            duration = _positive_int(bits[2], name="持续回合", maximum=999) if len(bits) == 3 else 30
            target.append({"type": "RESOURCE", "name": resource_type,
                           "amount": amount, "duration": duration})
        elif kind == "open-borders":
            if raw.lower() not in {"yes", "true", "1"}:
                raise ValueError("开放边界条款使用 give-open-borders 或 want-open-borders")
            target.append({"type": "AGREEMENT", "subtype": "OPEN_BORDERS"})
        elif kind in {"city", "great-work", "captive"}:
            item_type, field = {"city": ("CITY", "city_id"), "great-work": ("GREAT_WORK", "value_id"),
                                "captive": ("CAPTIVE", "value_id")}[kind]
            target.append({"type": item_type, field: _nonnegative_int(raw, name=kind + " ID")})
        elif kind == "research-agreement":
            target.append({"type": "AGREEMENT", "subtype": "RESEARCH_AGREEMENT",
                           "technology": game_symbol(raw, "TECH_", name="研究协议科技")})
        elif kind == "alliance":
            alliance = choice(raw, ("research", "cultural", "economic", "military", "religious"), name="同盟类型")
            target.append({"type": "AGREEMENT", "subtype": "ALLIANCE",
                           "alliance_type": "ALLIANCE_" + alliance.upper()})
        elif kind in {"joint-war", "third-party-war"}:
            bits = raw.split(":")
            if len(bits) > 2:
                raise ValueError("战争协议格式为 第三方玩家ID[:WarType]，从 trade options 复制")
            target.append({"type": "AGREEMENT", "subtype": kind.upper().replace("-", "_"),
                           "value_id": _player_id(bits[0]),
                           "war_type": _signed_int(bits[1], name="WarType") if len(bits) == 2 else None})
        else:
            raise ValueError("支持的交易条款：gold、gpt、resource、favor、open-borders、city、great-work、captive、research-agreement、alliance、joint-war、third-party-war")
    if not allow_empty and not offer and not request:
        raise ValueError("交易至少需要一个 give-/want- 条款")
    for items in (offer, request):
        seen = set()
        for item in items:
            kind = item["type"]
            identity = (kind, item.get("duration", 0) if kind == "GOLD" else
                        item.get("name") if kind == "RESOURCE" else
                        item.get("subtype") if kind == "AGREEMENT" else
                        item.get("city_id", item.get("value_id")))
            if identity in seen:
                raise ValueError("同一提供方的交易条款重复；请合并金额/数量，不要重复添加相同物品或协议")
            seen.add(identity)
    return offer, request


class ActionService:
    def __init__(self, connection: FireTunerConnection) -> None:
        self.connection = connection

    def query(self, query: Query) -> list[str]:
        return clean_lines(self.connection.execute_read_lines(
            query.lua, context=query.context, timeout=query.timeout))

    def options(self, plan: OptionPlan) -> list[list[str]]:
        return [self.query(query) for query in plan.queries]

    def execute(self, plan: ActionPlan) -> ActionResult:
        """Validate the live turn, execute exactly once, then read back state."""
        if not plan.allow_inactive_turn:
            status = read_status(self.connection)
            if not status.is_turn_active:
                raise ActionRejected("当前不是本地玩家回合；请先用 turn todo 查看外交或交易响应")
        try:
            lines = clean_lines(self.connection.execute_action_lines(
                plan.lua, context=plan.context, timeout=plan.timeout))
        except FireTunerError as exc:
            raise ActionOutcomeUnknown(
                "发送动作后连接中断或超时，结果未知；不要重试，先重新连接并读取状态"
            ) from exc
        errors = [line for line in lines if line.startswith("ERR:")]
        runtime_errors = [line for line in lines if line.startswith("ERROR|")]
        if runtime_errors:
            raise ActionOutcomeUnknown("Lua 在动作期间出错，结果可能已部分生效；请读取状态后判断：" + runtime_errors[0])
        if errors:
            raise ActionRejected(errors[0][4:].replace("|", "：", 1))
        negatives = [line for line in lines if line.startswith(("NO_", "NOT_SET", "NOT_FOUND"))]
        if negatives:
            raise ActionRejected(negatives[0].replace("|", "：", 1))
        recognized = any(line.startswith(("OK:", "MAYBE:", "WARN:")) for line in lines)
        if plan.requires_ack and not recognized:
            raise ActionOutcomeUnknown("游戏未返回明确的成功或拒绝结果；不要盲目重试，请读取状态")
        for delay, followup in plan.followups:
            if delay > 0:
                time.sleep(delay)
            try:
                followup_lines = clean_lines(self.connection.execute_action_lines(
                    followup.lua, context=followup.context, timeout=followup.timeout))
                if any(line.startswith(("ERR:", "ERROR|")) for line in followup_lines):
                    lines.append("WARN:CLEANUP_FAILED|" + " / ".join(followup_lines))
                else:
                    lines.extend(followup_lines)
            except FireTunerError as exc:
                lines.append("WARN:CLEANUP_FAILED|外交界面清理失败，主动作可能已成功：" + str(exc))
        verification: list[str] = []
        if plan.verify is not None:
            try:
                verification = self.query(plan.verify)
            except FireTunerError as exc:
                raise ActionOutcomeUnknown(
                    "动作已发送，但复查连接失败；结果未知，请重新连接后读取状态"
                ) from exc
        uncertain = (any(line.startswith(("MAYBE:", "WARN:")) for line in lines)
                     or any(line.startswith(("ERROR|", "ERR:", "NOT_SET", "NOT_FOUND")) for line in verification))
        return ActionResult(tuple(lines), tuple(verification), uncertain)


def todo_plan() -> OptionPlan:
    return OptionPlan("回合待办与外部响应", (
        Query(notifications.build_end_turn_blocking_query()),
        Query(diplomacy.build_diplomacy_session_query()),
        Query(diplomacy.build_pending_deals_query()),
    ))


def option_plan(topic: str, args: list[str], *, unit_id: Callable[[str], int],
                city_id: Callable[[str], int]) -> OptionPlan:
    topic = topic.lower().replace("_", "-")
    canonical = {
        "todo": "turn todo", "blockers": "turn todo", "units": "unit list",
        "research": "research options", "policies": "policy options",
        "governors": "governor options", "envoys": "envoy options",
        "pantheon": "religion pantheon-options", "religion": "religion belief-options",
        "dedications": "era options", "governments": "government options",
        "great-people": "great-person options", "great-person": "great-person options",
        "congress": "congress options", "captures": "city captures",
    }
    no_args = lambda: _require_count(args, 0, canonical.get(topic, topic))
    if topic in {"todo", "blockers"}:
        no_args()
        return todo_plan()
    if topic == "units":
        no_args(); return OptionPlan("单位与可执行动作", (Query(units.build_units_query()),))
    if topic == "production":
        _require_count(args, 1, "city production <城市>")
        return OptionPlan("城市生产与购买", (Query(cities.build_city_production_query(city_id(args[0]))),))
    if topic == "research":
        no_args(); return OptionPlan("可选科技与市政", (Query(tech.build_tech_civics_query()),))
    if topic == "policies":
        no_args(); return OptionPlan("政策槽位与可用政策卡", (Query(governance.build_policies_query()),))
    if topic == "governors":
        no_args(); return OptionPlan("总督任命、派遣与升级", (Query(governance.build_governors_query()),))
    if topic == "promotions":
        _require_count(args, 1, "unit promotions <单位>")
        return OptionPlan("单位晋升", (Query(governance.build_unit_promotions_query(unit_id(args[0]))),))
    if topic == "envoys":
        no_args(); return OptionPlan("可派遣使者的城邦", (Query(governance.build_city_states_query()),))
    if topic == "pantheon":
        no_args(); return OptionPlan("可选万神殿", (Query(religion.build_pantheon_status_query()),))
    if topic == "religion":
        no_args(); return OptionPlan("可用宗教与信条", (Query(religion.build_religion_beliefs_query()),))
    if topic == "dedications":
        no_args(); return OptionPlan("时代着力点", (Query(governance.build_dedications_query()),))
    if topic == "governments":
        no_args(); return OptionPlan("可用政体", (Query(governance.build_available_governments_query()),))
    if topic in {"great-people", "great-person"}:
        no_args(); return OptionPlan("伟人招募与赞助", (Query(great_people.build_great_people_query()),))
    if topic == "trade-routes":
        _require_count(args, 1, "unit options <商人单位>")
        return OptionPlan("可选贸易路线", (Query(economy.build_trade_destinations_query(unit_id(args[0]))),))
    if topic == "trades":
        if not args:
            return OptionPlan("待响应交易", (Query(diplomacy.build_pending_deals_query()),))
        _require_count(args, 1, "trade options <玩家ID>")
        return OptionPlan("可交易内容", (Query(diplomacy.build_deal_options_query(_player_id(args[0]))),))
    if topic == "diplomacy":
        if not args:
            return OptionPlan("待响应外交会面", (Query(diplomacy.build_diplomacy_session_query()),))
        _require_count(args, 1, "diplomacy options <玩家ID>")
        pid = _player_id(args[0])
        return OptionPlan("外交会面选项", (Query(diplomacy.build_diplomacy_choices_query(pid)),))
    if topic == "congress":
        no_args(); return OptionPlan("世界议会决议、目标与票价", (Query(congress.build_world_congress_query()),))
    if topic == "spies":
        if args:
            _require_count(args, 1, "unit options <间谍>")
            return OptionPlan("间谍任务与派遣", (Query(espionage.build_spy_options_query(unit_id(args[0]))),))
        return OptionPlan("间谍与可用任务", (Query(espionage.build_get_spies_query()),))
    if topic == "spy-destinations":
        _require_count(args, 1, "spy destinations <间谍>")
        return OptionPlan("间谍派遣目的地", (Query(espionage.build_spy_options_query(unit_id(args[0]), destinations_only=True)),))
    if topic == "captures":
        no_args(); return OptionPlan("待处置城市", (Query(cities.build_pending_captures_query()),))
    if topic == "tiles":
        _require_count(args, 1, "city tiles <城市>")
        return OptionPlan("可购买地块", (Query(lua_map.build_purchasable_tiles_query(city_id(args[0]))),))
    if topic == "focus":
        _require_count(args, 1, "city focus-options <城市>")
        return OptionPlan("城市产出侧重", (Query(cities.build_city_yield_focus_query(city_id(args[0]))),))
    if topic == "district":
        _require_count(args, 2, "city district-sites <城市> <DISTRICT_TYPE>")
        return OptionPlan("区域选址", (Query(lua_map.build_district_advisor_query(
            city_id(args[0]), game_symbol(args[1], "DISTRICT_", name="区域"))),))
    if topic == "wonder":
        _require_count(args, 2, "city wonder-sites <城市> <BUILDING_TYPE>")
        return OptionPlan("奇观选址", (Query(lua_map.build_wonder_advisor_query(
            city_id(args[0]), game_symbol(args[1], "BUILDING_", name="奇观"))),))
    raise ValueError("未知选项主题；输入 help 查看规范命令树")


def _require_count(args: list[str], count: int, usage: str) -> None:
    if len(args) != count:
        raise ValueError("用法：" + usage)


def _player_id(raw: str) -> int:
    if not raw.isdecimal() or not 0 <= int(raw) <= 63:
        raise ValueError("玩家ID必须是 0–63 的整数")
    return int(raw)


def unit_plan(unit_id: int, action: str, args: list[str], *, coordinate: Callable[[str], int]) -> ActionPlan:
    action = action.lower().replace("_", "-")
    verify = Query(units.build_unit_position_query(unit_id), GAMECORE)
    if action in {"wake", "cancel"}:
        _require_count(args, 0, f"unit {action} <单位>")
        return ActionPlan(f"单位 {unit_id} {'唤醒，恢复接受指令' if action == 'wake' else '取消当前持续指令/任务'}",
                          units.build_unit_control(unit_id, action.upper()), verify=verify, dangerous=action == "cancel")
    if action == "task":
        if len(args) not in {1, 3}:
            raise ValueError("用法：unit task <单位> <UNITOPERATION_TYPE> [x y]")
        operation = game_symbol(args[0], "UNITOPERATION_", name="单位任务")
        x, y = (coordinate(args[1]), coordinate(args[2])) if len(args) == 3 else (None, None)
        return ActionPlan(f"单位 {unit_id} 执行 {operation}" + (f"，目标 ({x},{y})" if x is not None else "，目标当前地块"),
                          units.build_plot_task(unit_id, operation, x, y), verify=verify, dangerous=True)
    simple = {
        "skip": (units.build_skip_unit, GAMECORE, "跳过单位本回合"),
        "fortify": (units.build_fortify_unit, INGAME, "驻防单位"),
        "heal": (units.build_heal_unit, INGAME, "休整至痊愈"),
        "alert": (units.build_alert_unit, INGAME, "单位进入警戒"),
        "sleep": (units.build_sleep_unit, INGAME, "单位休眠"),
        "explore": (units.build_automate_explore, INGAME, "自动探索"),
        "found-city": (lua_map.build_found_city, INGAME, "建立城市"),
        "remove-feature": (units.build_remove_feature, INGAME, "移除地貌"),
        "repair": (units.build_repair_improvement, INGAME, "修复改良设施"),
        "remove-improvement": (units.build_remove_improvement, INGAME, "移除改良设施"),
        "build-route": (units.build_build_route, INGAME, "修建道路或铁路"),
        "activate": (great_people.build_activate_great_person, INGAME, "激活伟人"),
        "spread-religion": (religion.build_spread_religion, INGAME, "传播宗教"),
        "upgrade": (governance.build_upgrade_unit, INGAME, "升级单位"),
        "disband": (units.build_delete_unit, INGAME, "解散单位"),
    }
    if action in simple:
        _require_count(args, 0, f"unit <单位> {action}")
        builder, context, title = simple[action]
        return ActionPlan(f"{title}（单位 {unit_id}）", builder(unit_id), context,
                          verify=verify, dangerous=action in {"disband", "found-city"})
    if action in {"move", "attack", "trade-route", "teleport"}:
        _require_count(args, 2, f"unit <单位> {action} <x> <y>")
        x, y = coordinate(args[0]), coordinate(args[1])
        builders = {"move": units.build_move_unit, "attack": units.build_attack_unit,
                    "trade-route": economy.build_make_trade_route,
                    "teleport": economy.build_teleport_to_city}
        return ActionPlan(f"单位 {unit_id} 执行 {action}，目标 ({x},{y})",
                          builders[action](unit_id, x, y), verify=verify,
                          dangerous=action == "attack")
    if action == "improve":
        _require_count(args, 1, "unit <单位> improve <IMPROVEMENT_TYPE>")
        improvement = game_symbol(args[0], "IMPROVEMENT_", name="改良设施")
        return ActionPlan(f"单位 {unit_id} 修建 {improvement}",
                          units.build_improve_tile(unit_id, improvement), verify=verify)
    if action == "promote":
        _require_count(args, 1, "unit <单位> promote <PROMOTION_TYPE>")
        promotion = game_symbol(args[0], "PROMOTION_", name="晋升")
        return ActionPlan(f"单位 {unit_id} 选择晋升 {promotion}",
                          governance.build_promote_unit(unit_id, promotion), verify=verify)
    raise ValueError("未知单位动作；输入 help unit 查看完整列表")


def unit_batch_plan(action: str) -> ActionPlan:
    action = action.lower().replace("_", "-")
    if action == "skip-all":
        return ActionPlan("跳过所有当前需要指令的单位", units.build_skip_remaining_units(),
                          GAMECORE, dangerous=True)
    if action == "fortify-all":
        return ActionPlan("让可驻防的剩余战斗单位驻防/休整", units.build_fortify_remaining_units(),
                          dangerous=True)
    raise ValueError("用法：unit skip-all 或 unit fortify-all")


def city_plan(city_id: int, action: str, args: list[str], *, coordinate: Callable[[str], int]) -> ActionPlan:
    action = action.lower().replace("_", "-")
    if action == "produce":
        if len(args) not in {2, 4}:
            raise ValueError("用法：city produce <城市> <unit|building|district|project> <TYPE> [x y]")
        kind = choice(args[0], ("unit", "building", "district", "project"), name="生产类型").upper()
        item = game_symbol(args[1], f"{kind}_", name="生产项目")
        x = y = None
        if len(args) == 4:
            x, y = coordinate(args[2]), coordinate(args[3])
        if kind == "DISTRICT" and x is None:
            raise ValueError("生产区域必须提供 x y；先用 city district-sites 查看合法选址")
        return ActionPlan(f"城市 {city_id} 改为生产 {item}" + (f"，选址 ({x},{y})" if x is not None else ""),
                          cities.build_produce_item(city_id, kind, item, x, y))
    if action == "buy":
        if len(args) not in {3, 5}:
            raise ValueError("用法：city buy <城市> <gold|faith> <unit|building|district> <TYPE> [x y]")
        currency = choice(args[0], ("gold", "faith"), name="购买货币")
        kind = choice(args[1], ("unit", "building", "district"), name="购买类型").upper()
        item = game_symbol(args[2], f"{kind}_", name="购买项目")
        x = y = None
        if len(args) == 5:
            x, y = coordinate(args[3]), coordinate(args[4])
        if kind == "DISTRICT" and x is None:
            raise ValueError("购买区域必须提供 x y；先用 city district-sites 查看合法选址")
        return ActionPlan(f"城市 {city_id} 用{('金币' if currency == 'gold' else '信仰')}购买 {item}" + (f"，选址 ({x},{y})" if x is not None else ""),
                          cities.build_purchase_item(city_id, kind, item, f"YIELD_{currency.upper()}", x, y),
                          verify=Query(cities.build_city_production_query(city_id)))
    if action == "buy-tile":
        _require_count(args, 2, "city buy-tile <城市> <x> <y>")
        x, y = coordinate(args[0]), coordinate(args[1])
        return ActionPlan(f"城市 {city_id} 购买地块 ({x},{y})",
                          lua_map.build_purchase_tile(city_id, x, y), dangerous=True)
    if action == "focus":
        _require_count(args, 1, "city focus <城市> <food|production|gold|science|culture|faith|default>")
        focus = choice(args[0], ("food", "production", "gold", "science", "culture", "faith", "default"), name="城市侧重")
        return ActionPlan(f"城市 {city_id} 设置 {focus} 侧重",
                          cities.build_set_yield_focus(city_id, focus),
                          verify=Query(cities.build_city_yield_focus_query(city_id)))
    if action == "attack":
        _require_count(args, 2, "city attack <城市> <x> <y>")
        x, y = coordinate(args[0]), coordinate(args[1])
        return ActionPlan(f"城市 {city_id} 远程攻击 ({x},{y})",
                          cities.build_city_attack(city_id, x, y), dangerous=True)
    raise ValueError("未知城市动作；输入 help city 查看完整列表")


def standalone_plan(command: str, args: list[str], *, city_id: Callable[[str], int],
                    unit_id: Callable[[str], int] = int) -> ActionPlan:
    command = command.lower().replace("_", "-")
    if command == "research":
        _require_count(args, 2, "research set <tech|civic> <TYPE>")
        category = choice(args[0], ("tech", "civic"), name="研究类别")
        prefix = "TECH_" if category == "tech" else "CIVIC_"
        item = game_symbol(args[1], prefix, name="研究项目")
        builder = tech.build_set_research if category == "tech" else tech.build_set_civic
        # UI.RequestPlayerOperation already reports a definitive acknowledgement.
        # A second full research query has failed on some game builds after a
        # successful civic choice, so successful requests deliberately stop here.
        return ActionPlan(f"选择{('科技' if category == 'tech' else '市政')} {item}", builder(item))
    if command == "policies":
        if args == ["keep"]:
            return ActionPlan("保留当前政策卡", governance.build_keep_policies())
        if not args or args[0].lower() != "set":
            raise ValueError("用法：policy set <槽位=POLICY_TYPE> [...]")
        assignments = parse_policy_assignments(args[1:])
        return ActionPlan("更换政策卡：" + ", ".join(f"{k}={v}" for k, v in assignments.items()),
                          governance.build_set_policies(assignments),
                          verify=Query(governance.build_policies_query()))
    if command == "government":
        if args == ["keep"]:
            return ActionPlan("保留当前政体", governance.build_keep_government())
        _require_count(args, 2, "government change <GOVERNMENT_TYPE>")
        if args[0].lower() != "change":
            raise ValueError("用法：government change <GOVERNMENT_TYPE>")
        gov = game_symbol(args[1], "GOVERNMENT_", name="政体")
        return ActionPlan(f"更换政体为 {gov}", governance.build_change_government(gov),
                          verify=Query(governance.build_available_governments_query()), dangerous=True)
    if command == "governor":
        if not args:
            raise ValueError("用法：governor appoint|assign|promote ...")
        verb = args[0].lower()
        if verb == "appoint":
            _require_count(args, 2, "governor appoint <GOVERNOR_TYPE>")
            gov = game_symbol(args[1], "GOVERNOR_", name="总督")
            lua = governance.build_appoint_governor(gov)
        elif verb == "assign":
            _require_count(args, 3, "governor assign <GOVERNOR_TYPE> <城市>")
            gov = game_symbol(args[1], "GOVERNOR_", name="总督")
            lua = governance.build_assign_governor(gov, city_id(args[2]))
        elif verb == "promote":
            _require_count(args, 3, "governor promote <GOVERNOR_TYPE> <PROMOTION_TYPE>")
            gov = game_symbol(args[1], "GOVERNOR_", name="总督")
            promo = game_symbol(args[2], "GOVERNOR_PROMOTION_", name="总督升级")
            lua = governance.build_promote_governor(gov, promo)
        else:
            raise ValueError("用法：governor appoint|assign|promote ...")
        return ActionPlan("总督操作：" + " ".join(args), lua,
                          verify=Query(governance.build_governors_query()))
    if command == "envoy":
        _require_count(args, 2, "envoy send <城邦玩家ID>")
        if args[0].lower() != "send": raise ValueError("用法：envoy send <城邦玩家ID>")
        pid = _player_id(args[1])
        return ActionPlan(f"向城邦玩家 {pid} 派遣 1 名使者", governance.build_send_envoy(pid),
                          verify=Query(governance.build_city_states_query()))
    if command == "dedication":
        _require_count(args, 2, "era choose <选项索引>")
        if args[0].lower() != "choose" or not args[1].isdecimal():
            raise ValueError("用法：era choose <选项索引>")
        index = int(args[1])
        return ActionPlan(f"选择时代着力点索引 {index}", governance.build_choose_dedication(index),
                          verify=Query(governance.build_dedications_query()))
    if command == "religion":
        if not args: raise ValueError("用法：religion pantheon|found ...")
        if args[0].lower() == "pantheon":
            _require_count(args, 2, "religion pantheon <BELIEF_TYPE>")
            belief = game_symbol(args[1], "BELIEF_", name="万神殿信条")
            return ActionPlan(f"选择万神殿 {belief}", religion.build_choose_pantheon(belief),
                              verify=Query(religion.build_pantheon_status_query()))
        if args[0].lower() == "found":
            _require_count(args, 4, "religion found <RELIGION_TYPE> <FOLLOWER_BELIEF> <FOUNDER_BELIEF>")
            rel = game_symbol(args[1], "RELIGION_", name="宗教")
            follower = game_symbol(args[2], "BELIEF_", name="追随者信条")
            founder = game_symbol(args[3], "BELIEF_", name="创始人信条")
            return ActionPlan(f"创立宗教 {rel}，信条 {follower} / {founder}",
                              religion.build_found_religion(rel, follower, founder),
                              verify=Query(religion.build_religion_beliefs_query()), dangerous=True)
        if args[0].lower() == "evangelize":
            _require_count(args, 2, "religion evangelize <使徒>")
            apostle = unit_id(args[1])
            return ActionPlan(f"使徒 {apostle} 传播信仰并获得待选信条",
                              religion.build_evangelize_belief(apostle), dangerous=True)
        if args[0].lower() == "add-belief":
            _require_count(args, 2, "religion add-belief <BELIEF_TYPE>")
            belief = game_symbol(args[1], "BELIEF_", name="宗教信条")
            return ActionPlan(f"为己方宗教新增信条 {belief}",
                              religion.build_add_belief(belief), dangerous=True)
        raise ValueError("用法：religion pantheon|found|evangelize|add-belief ...")
    if command == "great-person":
        if len(args) < 2: raise ValueError("用法：great-person recruit|pass|patronize ...")
        verb = args[0].lower()
        if verb in {"recruit", "pass"}:
            _require_count(args, 2, f"great-person {verb} <伟人ID>")
            gp = _nonnegative_int(args[1], name="伟人ID")
            builder = great_people.build_recruit_great_person if verb == "recruit" else great_people.build_reject_great_person
            lua = builder(gp)
        elif verb == "patronize":
            _require_count(args, 3, "great-person patronize <gold|faith> <伟人ID>")
            currency = choice(args[1], ("gold", "faith"), name="赞助货币")
            gp = _nonnegative_int(args[2], name="伟人ID")
            lua = great_people.build_patronize_great_person(gp, f"YIELD_{currency.upper()}")
        else:
            raise ValueError("用法：great-person recruit|pass|patronize ...")
        return ActionPlan("伟人操作：" + " ".join(args), lua,
                          verify=Query(great_people.build_great_people_query()), dangerous=verb in {"pass", "patronize"})
    if command == "capture":
        _require_count(args, 2, "city capture <城市> <keep|reject|raze|liberate-founder|liberate-previous>")
        target = city_id(args[0])
        verb = choice(args[1], ("keep", "reject", "raze", "liberate-founder", "liberate-previous"), name="占领城市处置")
        return ActionPlan(f"处置待决定城市 {target}：{verb}", cities.build_resolve_city_capture(verb.replace("-", "_"), target),
                          dangerous=verb in {"reject", "raze"})
    if command == "endturn":
        _require_count(args, 0, "turn end")
        return ActionPlan("结束当前回合", notifications.build_end_turn(), dangerous=True)
    raise ValueError("未知操作命令；输入 help 查看命令树")


def diplomacy_plan(args: list[str]) -> ActionPlan:
    if not args: raise ValueError("用法：diplomacy respond|action|alliance ...")
    verb = args[0].lower()
    if verb == "respond":
        _require_count(args, 3, "diplomacy respond <玩家ID> <positive|negative>")
        pid = _player_id(args[1])
        response = choice(args[2], ("positive", "negative"), name="外交响应").upper()
        return ActionPlan(f"对玩家 {pid} 作出 {response} 外交响应",
                          diplomacy.build_diplomacy_respond(pid, response),
                          allow_inactive_turn=True, verify=Query(diplomacy.build_diplomacy_session_query()))
    if verb == "action":
        _require_count(args, 3, "diplomacy action <玩家ID> <外交动作>")
        pid = _player_id(args[1])
        action = game_symbol(args[2], name="外交动作")
        if action not in DIPLOMATIC_ACTIONS: raise ValueError("不支持的外交动作；输入 help diplomacy action 查看列表")
        followups = ()
        if action.startswith("DECLARE_") and action.endswith("_WAR"):
            followups = ((8.0, Query(diplomacy.build_war_close_session(pid))),
                         (1.0, Query(diplomacy.build_war_dismiss_view())))
        return ActionPlan(f"对玩家 {pid} 执行 {action}", diplomacy.build_send_diplo_action(pid, action),
                          dangerous="_WAR" in action, followups=followups)
    if verb == "alliance":
        _require_count(args, 3, "diplomacy alliance <玩家ID> <military|research|cultural|economic|religious>")
        pid = _player_id(args[1])
        alliance = choice(args[2], ("military", "research", "cultural", "economic", "religious"), name="同盟类型").upper()
        return ActionPlan(f"与玩家 {pid} 缔结 {alliance} 同盟", diplomacy.build_form_alliance(pid, alliance))
    raise ValueError("用法：diplomacy respond|action|alliance ...")


def trade_plan(args: list[str]) -> ActionPlan:
    if not args: raise ValueError("用法：trade respond|propose|peace ...")
    verb = args[0].lower()
    if verb == "respond":
        _require_count(args, 3, "trade respond <玩家ID> <accept|reject>")
        pid = _player_id(args[1])
        decision = choice(args[2], ("accept", "reject"), name="交易响应")
        return ActionPlan(f"{('接受' if decision == 'accept' else '拒绝')}玩家 {pid} 的交易",
                          diplomacy.build_respond_to_deal(pid, decision == "accept"),
                          allow_inactive_turn=True, dangerous=decision == "accept")
    if verb == "propose":
        if len(args) < 4:
            raise ValueError("用法：trade propose <玩家ID> <test|send> <give-/want-条款...>")
        pid = _player_id(args[1])
        mode = choice(args[2], ("test", "send"), name="交易模式")
        offer, request = parse_trade_items(args[3:])
        builder = diplomacy.build_test_trade if mode == "test" else diplomacy.build_propose_trade
        return ActionPlan(f"向玩家 {pid} {('试算' if mode == 'test' else '发送')}交易",
                          builder(pid, offer, request), dangerous=mode == "send",
                          requires_ack=mode == "send")
    if verb == "peace":
        if len(args) < 3:
            raise ValueError("用法：trade peace <玩家ID> <test|send> [give-/want-条款 ...]")
        pid = _player_id(args[1])
        mode = choice(args[2], ("test", "send"), name="和平协议模式")
        offer, request = parse_trade_items(args[3:], allow_empty=True)
        builder = diplomacy.build_test_peace if mode == "test" else diplomacy.build_propose_peace
        terms = "仅停战" if not offer and not request else "附带交换条件"
        return ActionPlan(f"与玩家 {pid} {('试算' if mode == 'test' else '发送')}和平协议（{terms}）",
                          builder(pid, offer, request), dangerous=mode == "send",
                          requires_ack=mode == "send")
    raise ValueError("用法：trade respond|propose|peace ...")


def congress_plan(args: list[str]) -> ActionPlan:
    if not args: raise ValueError("用法：congress queue|vote|submit ...")
    verb = args[0].lower()
    if verb == "queue":
        votes = parse_vote_specs(args[1:])
        return ActionPlan("登记下次世界议会投票：" + " ".join(args[1:]),
                          congress.build_register_wc_voter(votes), dangerous=True)
    if verb == "vote":
        votes = parse_vote_specs(args[1:])
        if len(votes) != 1: raise ValueError("congress vote 每次只接受一项投票")
        v = votes[0]
        return ActionPlan("投出世界议会票：" + args[1], congress.build_congress_vote(
            v["hash"], v["option"], v["target"], v["votes"]), dangerous=True)
    if verb == "submit":
        _require_count(args, 1, "congress submit")
        return ActionPlan("提交世界议会投票", congress.build_congress_submit(), dangerous=True)
    raise ValueError("用法：congress queue|vote|submit ...")


def spy_plan(args: list[str], *, coordinate: Callable[[str], int]) -> ActionPlan:
    if args == ["escape"]:
        return ActionPlan("为被捕间谍选择最快逃跑路线", espionage.build_spy_escape_route(),
                          allow_inactive_turn=True, dangerous=True,
                          verify=Query(espionage.build_get_spies_query()))
    if len(args) != 4:
        raise ValueError("用法：spy escape、spy travel <间谍> <x> <y> 或 spy mission <间谍> <任务类型> <x> <y>")
    unit = _nonnegative_int(args[0], name="间谍单位ID")
    action = args[1].upper().replace("-", "_")
    x, y = coordinate(args[2]), coordinate(args[3])
    action = game_symbol(action, name="间谍任务").removeprefix("UNITOPERATION_SPY_")
    if action == "TRAVEL": lua = espionage.build_spy_travel(unit, x, y)
    else: lua = espionage.build_spy_mission(unit, action, x, y)
    return ActionPlan(f"间谍 {unit} 执行 {action}，目标 ({x},{y})", lua,
                      verify=Query(espionage.build_get_spies_query()), dangerous=action != "TRAVEL")
