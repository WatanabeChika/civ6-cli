"""Human-facing read and action commands."""

from __future__ import annotations

import shlex
import time
from typing import Callable

from .actions import (ActionOutcomeUnknown, ActionPlan, ActionRejected,
                      ActionService, OptionPlan, Query, city_plan, congress_plan, diplomacy_plan,
                      great_work_move_plan, great_work_options_plan,
                      option_plan, spy_plan, standalone_plan, todo_plan,
                      trade_plan, unit_batch_plan, unit_plan)

from .game import (PlayerStatus, read_cities, read_known_players, read_status,
                   read_units, read_visible_entities)
from .map_view import read_map, render_map
from .overview import read_overview, render_cities, render_overview, render_units
from .rendering import (ACCENT, DIM, Display, hint, inline, panel,
                        render_records, status_line, table)
from .reports import (bounded_int, city_detail_lua,
                      city_production_lua, path_estimate_lua, run_report,
                      unit_detail_lua, unit_promotions_lua)
from .transport import FireTunerConnection, FireTunerError
from .commands import route_command, show_help
from .lua import espionage, units as unit_lua
from .lua.economy import _parse_compact_yields


class Terminal:
    def __init__(self, connection: FireTunerConnection | None, display: Display = Display(), *,
                 assume_yes: bool = False,
                 confirm: Callable[[str], bool] | None = None) -> None:
        self.connection = connection
        self.display = display
        self.assume_yes = assume_yes
        self.confirm = confirm or _confirm
        self.last_stamp: tuple[int, int] | None = None

    @property
    def actions(self) -> ActionService:
        if self.connection is None:
            raise ValueError("该命令需要连接正在运行的游戏")
        return ActionService(self.connection)

    def overview(self) -> None:
        snapshot = read_overview(self.connection)
        print(render_overview(snapshot, self.display))
        self.last_stamp = (snapshot.status.turn, snapshot.status.player_id)

    def check_turn(self, status: PlayerStatus | None = None) -> bool:
        status = status or read_status(self.connection)
        if status.is_turn_active and self.last_stamp != (status.turn, status.player_id):
            self.overview()
            return True
        return False

    def lines(self, lua: str, *, context: str = "GameCore_Tuner", timeout: float = 10.0,
              title: str | None = None) -> None:
        _show_lines(self.connection.execute_read_lines(lua, context=context, timeout=timeout), self.display, title=title)

    def execute(self, words: list[str]) -> bool:
        if not words:
            return True
        if words[0].lower() == "help":
            show_help(words[1:], self.display)
            return True
        words = route_command(words)
        command, args = words[0].lower(), words[1:]
        if command == "quit" and not args:
            return False
        if command == "reconnect" and not args:
            if self.connection is None:
                raise ValueError("该命令需要游戏连接")
            self.connection.connect()
            print(status_line("success", "已重新连接 FireTuner", self.display))
            self.overview()
            return True
        if command == "status" and not args:
            self.overview()
        elif command == "todo" and not args:
            self.show_options(todo_plan())
        elif command == "wait" and len(args) <= 1:
            seconds = bounded_int(args[0], name="等待秒数", minimum=1, maximum=300) if args else 30
            self.wait_for_turn(seconds)
        elif command == "options" and args:
            self.show_options(option_plan(
                args[0], args[1:], unit_id=lambda value: self.resolve("unit", value, allow_truncated=True).id,
                city_id=lambda value: self.resolve("city", value).id))
            if args[0] == "trades":
                if len(args) > 1:
                    print(hint(f"先试算：trade propose {args[1]} test <give-/want-条款> [...]", self.display))
                else:
                    print(hint("核对实际条款后：trade respond <玩家ID> <accept|reject>", self.display))
            elif args[0] == "research":
                print(hint("选择内部类型后：research set <tech|civic> <TYPE>", self.display))
        elif command == "query" and args:
            name = args[0].lower()
            filter_text = " ".join(args[1:]) if len(args) > 1 else None
            _show_lines(run_report(self.connection, name, filter_text), self.display,
                        title=QUERY_DESCRIPTIONS.get(name, name))
        elif command == "great-work-options" and len(args) == 1:
            self.show_options(great_work_options_plan(args[0]))
        elif command == "great-work-move":
            self.perform(great_work_move_plan(args, city_id=lambda value: self.resolve("city", value).id))
        elif command == "turn" and not args:
            print(read_status(self.connection).turn)
        elif command == "player" and not args:
            s = read_status(self.connection)
            print(table(["玩家ID", "文明", "领袖"], [[s.player_id, s.civilization, s.leader]], self.display,
                        title="本地文明"))
        elif command == "units" and len(args) == 1 and args[0].lower() == "visible":
            units, _ = read_visible_entities(self.connection)
            print(table(["阵营ID", "阵营", "单位ID", "单位", "坐标", "生命值"],
                        [[u.owner_id, u.owner, u.id, u.name, f"({u.x},{u.y})", f"{u.hp}/{u.max_hp}"] for u in units],
                        self.display, title=f"当前可见的其他单位 · {len(units)}"))
        elif command == "units" and not args:
            print(render_units(read_units(self.connection), self.display))
        elif command == "units" and len(args) == 1:
            self.perform(unit_batch_plan(args[0]))
        elif command == "cities" and len(args) == 1 and args[0].lower() == "known":
            _, cities = read_visible_entities(self.connection)
            print(table(["阵营ID", "阵营", "城市ID", "城市", "坐标", "当前可见"],
                        [[c.owner_id, c.owner, c.id, c.name, f"({c.x},{c.y})", "是" if c.visible else "否（迷雾）"] for c in cities], self.display))
        elif command == "cities" and not args:
            print(render_cities(read_overview(self.connection).cities, self.display))
        elif command == "unit-roster" and not args:
            groups = self.actions.options(option_plan("units", [], unit_id=lambda _: 0, city_id=lambda _: 0))
            normalized = _normalize_option_lines("单位与可执行动作", groups[0])
            rows = [line.split("|")[1:] for line in normalized if line.startswith("ACTION_UNIT|")]
            listing = [[r[i] for i in (0, 2, 4, 5, 6, 7, 8)] for r in rows if len(r) >= 19]
            pending = sum(row[5] == "是" for row in listing)
            print(table(["ID", "单位", "坐标", "移动力", "活动状态", "需指令", "生命值"],
                        listing, self.display, title=f"己方单位 · {len(listing)}",
                        caption=f"{pending} 个单位需要指令 · unit options <单位> 查看合法动作"))
        elif command in {"unit-options", "unit-show"} and len(args) == 1:
            unit = self.resolve("unit", args[0], allow_truncated=True)
            if command == "unit-show":
                self.lines(unit_detail_lua(unit.id), context="InGame", timeout=15.0, title="单位详情")
                print(hint(f"合法动作与专业任务：unit options {unit.id}", self.display))
                return True
            self.show_unit_options(unit)
        elif command in {"spy-travel", "spy-mission"}:
            unit = self.resolve("unit", args[0])
            if unit.unit_type != "UNIT_SPY":
                raise ValueError("所选单位不是间谍")
            action_args = [str(unit.id), "travel", *args[1:]] if command == "spy-travel" else [str(unit.id), *args[1:]]
            self.perform(spy_plan(action_args, coordinate=self.coordinate))
        elif command == "probe" and not args:
            print(panel("FireTuner 连接", f"游戏身份  {self.connection.app_identity!r}\n探测结果  {self.connection.probe()!r}", self.display))
        elif command in {"unit", "city", "production", "promotions"} and len(args) == 1:
            identifier = self.resolve("city" if command in {"city", "production"} else "unit", args[0])
            queries = {"unit": (unit_detail_lua, "GameCore_Tuner"), "city": (city_detail_lua, "InGame"),
                       "production": (city_production_lua, "InGame"), "promotions": (unit_promotions_lua, "GameCore_Tuner")}
            titles = {"unit": "单位详情", "city": "城市详情", "production": "城市生产与购买", "promotions": "单位晋升"}
            builder, context = queries[command]
            self.lines(builder(identifier.id), context=context, timeout=15.0, title=titles[command])
            if command == "production":
                print(hint(
                    f"选择内部类型后：city produce {identifier.id} <unit|building|district|project> <TYPE> [x y]；"
                    f"购买使用 city buy {identifier.id} <gold|faith> <unit|building|district> <TYPE> [x y]",
                    self.display,
                ))
        elif command == "unit" and len(args) >= 2:
            unit = self.resolve("unit", args[0])
            self.perform(unit_plan(unit.id, args[1], args[2:], coordinate=self.coordinate))
        elif command == "city" and len(args) >= 2:
            city = self.resolve("city", args[0])
            self.perform(city_plan(city.id, args[1], args[2:], coordinate=self.coordinate))
        elif command in {"research", "policies", "government", "governor", "envoy",
                         "dedication", "religion", "great-person", "capture", "endturn"}:
            plan = standalone_plan(
                command, args,
                city_id=lambda value: self.resolve("city", value).id,
                unit_id=lambda value: self.resolve("unit", value).id,
            )
            self.perform(plan, preflight_endturn=command == "endturn", wait_after=command == "endturn")
        elif command == "diplomacy":
            self.perform(diplomacy_plan(args))
        elif command == "trade":
            self.perform(trade_plan(args))
        elif command == "congress":
            self.perform(congress_plan(args))
        elif command == "spy":
            self.perform(spy_plan(args, coordinate=self.coordinate))
        elif command == "path" and len(args) == 3:
            unit = self.resolve("unit", args[0])
            x, y = self.coordinate(args[1]), self.coordinate(args[2])
            self.lines(path_estimate_lua(unit.id, x, y))
        elif command == "tile" and len(args) in {2, 3}:
            x, y = self.coordinate(args[0]), self.coordinate(args[1])
            radius = self.radius(args[2]) if len(args) == 3 else 0
            area = read_map(self.connection, x, y, radius)
            lines = []
            for t in area.tiles:
                fields = {k: v for k, v in t.fields.items() if k not in {"layout_x", "layout_y", "own_units", "other_units"}}
                lines.append("TILE|" + "|".join(f"{k}={v}" for k, v in fields.items()))
            _show_lines(lines, self.display)
        elif command == "map":
            if len(args) in {2, 3} and args[0].lower() not in {"unit", "city"}:
                x, y = self.coordinate(args[0]), self.coordinate(args[1])
                radius = self.radius(args[2]) if len(args) == 3 else 2
            elif len(args) in {2, 3} and args[0].lower() in {"unit", "city"}:
                entity = self.resolve_map_entity(args[0].lower(), args[1])
                x, y = entity.x, entity.y
                radius = self.radius(args[2]) if len(args) == 3 else 2
            else:
                raise ValueError('用法：map show <x> <y> [半径]、map unit <单位> [半径] 或 map city <城市> [半径]')
            print(render_map(read_map(self.connection, x, y, radius), self.display))
        else:
            raise ValueError("未知命令或参数数量错误；输入 help 查看命令树，help <主题> 查看完整语法。")
        return True

    def show_unit_options(self, unit) -> None:
        self.show_options(OptionPlan("单位操作选项", (Query(unit_lua.build_unit_operations_query(unit.id)),)))
        if unit.unit_type == "UNIT_SPY":
            self.show_options(OptionPlan("间谍任务与派遣", (Query(espionage.build_spy_options_query(unit.id)),)))
        elif unit.unit_type == "UNIT_TRADER":
            self.show_trade_routes(unit.id)
        else:
            groups = self.actions.options(option_plan("units", [], unit_id=int, city_id=int))
            rows = [line for line in groups[0] if line.split("|", 1)[0] == str(unit.id)]
            _show_lines(_normalize_option_lines("单位与可执行动作", rows), self.display)

    def show_trade_routes(self, unit_id: int) -> None:
        plan = option_plan("trade-routes", [str(unit_id)], unit_id=int, city_id=int)
        lines = self.actions.options(plan)[0]
        records, other = [], []
        labels = {"Food": "食", "Prod": "产", "Gold": "金", "Sci": "科", "Cul": "文", "Faith": "信"}
        def yields(value):
            if value == "0":
                return "0"
            result = _parse_compact_yields(value)
            for key, label in labels.items():
                result = result.replace(key + ":", label)
            return result or "未知"
        for line in lines:
            if line.startswith("TDEST|"):
                r = line.split("|")
                if len(r) < 16:
                    raise ValueError("商路查询未返回完整的收益/回合字段")
                records.append([r[1], "国内" if r[2] == "Domestic" else r[2], f"({r[3]})", r[14], r[15], yields(r[12]), yields(r[13])])
                flags = [name for index, name in ((4, "国内"), (5, "城邦"), (6, "完成城邦任务"), (7, "已有贸易站")) if r[index] == "1"]
                if flags or r[8] not in {"", "0"} or r[10] not in {"", "0"}:
                    other.append("ROUTE_EXTRA|city=" + r[1] + "|details=" + "、".join(flags)
                                 + f"|pressure_out={r[8]} {r[9]}|pressure_in={r[10]} {r[11]}")
            elif line != "---END---":
                other.append(line)
        print(table(["目的城市", "文明", "目标坐标", "单程距离", "预计回合", "我方收益/回合", "对方收益/回合"],
                    records, self.display, title="合法商路",
                    caption="收益为每回合；持续时间按路线往返与游戏速度估计"))
        if other:
            _show_lines(other, self.display)
        print(hint(f"执行：unit trade-route {unit_id} <目标x> <目标y>；迁移：unit teleport {unit_id} <己方城市x> <己方城市y>", self.display))

    def show_options(self, plan) -> None:
        groups = self.actions.options(plan)
        lines = [line for group in groups for line in group if line != "NONE"]
        _show_lines(_normalize_option_lines(plan.title, lines), self.display, title=plan.title)

    def perform(self, plan: ActionPlan, *, preflight_endturn: bool = False,
                wait_after: bool = False) -> None:
        if preflight_endturn:
            todo = todo_plan()
            groups = self.actions.options(todo)
            actionable = [line for group in groups for line in group if line != "NONE"]
            if actionable:
                _show_lines(_normalize_option_lines(todo.title, actionable), self.display, title="结束回合前仍有待办")
                raise ActionRejected("请处理或明确跳过这些待办后再结束回合")
        print(panel("行动预览", plan.summary, self.display, subtitle="尚未发送"))
        if plan.dangerous:
            print(status_line("warning", "这是高影响或不可逆操作", self.display, "请核对目标与当前状态"))
        prompt = inline("> ", ACCENT, self.display) + "确认执行？ " + inline("[y/N] ", DIM, self.display)
        if not self.assume_yes and not self.confirm(prompt):
            print(status_line("info", "已取消", self.display))
            return
        before_turn = read_status(self.connection).turn if wait_after else None
        result = self.actions.execute(plan)
        if plan.requires_ack:
            _show_action_result(result.lines, self.display)
        else:
            _show_lines(_normalize_option_lines("交易试算", list(result.lines)), self.display)
        if result.verification:
            _show_lines(list(result.verification), self.display, title="复查结果")
        if result.uncertain:
            print(status_line("warning", "请求或复查未能确认结果", self.display, "请读取相关状态，不要直接重试"))
        if wait_after:
            self.wait_for_turn(30, after_turn=before_turn)

    def wait_for_turn(self, seconds: int, *, after_turn: int | None = None) -> None:
        """Wait for the next local turn or a diplomacy session that needs input."""
        deadline = time.monotonic() + seconds
        saw_inactive = False
        while time.monotonic() < deadline:
            status = read_status(self.connection)
            if status.is_turn_active and (after_turn is None or saw_inactive or status.turn != after_turn):
                print(status_line("success", f"本地回合已可操作：第 {status.turn} 回合", self.display))
                self.overview()
                return
            saw_inactive = saw_inactive or not status.is_turn_active
            sessions = self.actions.options(option_plan(
                "diplomacy", [], unit_id=lambda _value: 0, city_id=lambda _value: 0))[0]
            pending = [line for line in sessions if line != "NONE"]
            if pending:
                _show_lines(pending, self.display, title="非玩家回合需要响应")
                print(hint("使用 diplomacy respond <玩家ID> positive|negative；若含交易条款，先用 trade pending 查看。", self.display))
                return
            time.sleep(1.0)
        print(status_line("warning", f"等待 {seconds} 秒后尚未进入下一本地回合", self.display,
                          "可再次使用 turn wait，或用 turn todo 检查响应"))

    def resolve_map_entity(self, kind: str, selector: str):
        owner_id = None
        raw_selector = selector
        if ":" in selector:
            raw_owner, separator, raw_selector = selector.partition(":")
            if not separator or not raw_owner.isdecimal() or not raw_selector.isdecimal():
                raise ValueError("阵营限定格式应为 <阵营ID>:<单位或城市ID>")
            owner_id = bounded_int(raw_owner, name="阵营ID", minimum=0, maximum=63)
        identifier = bounded_int(raw_selector, name="ID", minimum=0, maximum=2_147_483_647) if raw_selector.isdecimal() else None
        if owner_id is None:
            owned = read_units(self.connection) if kind == "unit" else read_cities(self.connection)
            owned_matches = ([e for e in owned if e.id == identifier] if identifier is not None else
                             [e for e in owned if e.name.casefold() == raw_selector.casefold()])
            if len(owned_matches) == 1:
                return owned_matches[0]
            if len(owned_matches) > 1:
                raise ValueError(f"名称 {selector!r} 对应多个己方对象，请使用 ID：" + ", ".join(str(e.id) for e in owned_matches))
        visible_units, known_cities = read_visible_entities(self.connection)
        others = visible_units if kind == "unit" else known_cities
        if raw_selector.isdecimal():
            matches = [e for e in others if e.id == identifier and (owner_id is None or e.owner_id == owner_id)]
        else:
            matches = [e for e in others if e.name.casefold() == raw_selector.casefold()]
        # The visibility roster deliberately omits owned units. Support the
        # explicit local-player form without making ordinary owned lookups pay
        # for the broader visibility query.
        if not matches and owner_id is not None and kind == "unit" and owner_id == read_status(self.connection).player_id:
            matches = [e for e in read_units(self.connection) if e.id == identifier]
        if not matches:
            hint = "unit visible" if kind == "unit" else "city known"
            raise ValueError(f"未找到玩家可见的{kind}：{selector}；用 {hint} 查看可用标识")
        if len(matches) > 1:
            choices = ", ".join(f"{e.owner_id}:{e.id}" for e in matches)
            raise ValueError(f"名称或 ID {selector!r} 对应多个对象，请使用 阵营ID:对象ID：{choices}")
        return matches[0]

    def resolve(self, kind: str, selector: str, *, allow_truncated: bool = False):
        entities = read_units(self.connection) if kind == "unit" else read_cities(self.connection)
        if selector.isdecimal():
            identifier = bounded_int(selector, name="ID", minimum=0, maximum=2_147_483_647)
            matches = [e for e in entities if e.id == identifier]
            # Read-only lookups may resolve an unambiguous six-digit prefix.
            # State-changing commands still require an exact ID or name.
            if not matches and kind == "unit" and allow_truncated and len(selector) == 6:
                matches = [e for e in entities if str(e.id).startswith(selector)]
                if len(matches) == 1:
                    print(status_line("info", f"单位完整 ID：{matches[0].id}", self.display,
                                      "写操作请使用完整 ID"))
        else:
            matches = [e for e in entities if e.name.casefold() == selector.casefold()]
        if not matches:
            raise ValueError(f"未找到己方{kind}：{selector}；用 unit list 或 city list 查看 ID。")
        if len(matches) > 1:
            raise ValueError(f"名称 {selector!r} 对应多个对象，请使用 ID：" + ", ".join(str(e.id) for e in matches))
        return matches[0]

    @staticmethod
    def coordinate(value: str) -> int:
        return bounded_int(value, name="坐标", minimum=0, maximum=10000)

    @staticmethod
    def radius(value: str) -> int:
        return bounded_int(value, name="半径", minimum=0, maximum=5)


QUERY_DESCRIPTIONS = {
    "research": "当前科技、市政和可选研究", "economy": "金币、收入、维护费与战略库存", "diplomacy": "我方与已相遇文明的产出、国库、关系与军力",
    "government": "政府、政策槽位与总督", "religion": "万神殿、宗教与城市信徒", "victory": "已知文明的胜利指标",
    "great-people": "伟人能力、招募进度与费用", "great-works": "已有巨作、存放位置、产出与空槽位", "notifications": "通知与回合阻塞", "blockers": "回合待办条件",
    "trade": "贸易路线、容量与商人", "resources": "已探索的资源地块与改良；可按资源名筛选", "city-states": "城邦类型、可用/已派使者与宗主国",
    "spies": "间谍位置、等级与任务", "congress": "世界议会时间与投票费用", "era": "时代分、阈值与游戏速度",
}


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().casefold() in {"y", "yes", "是", "确认"}
    except EOFError:
        return False


def _show_action_result(lines: tuple[str, ...], display: Display) -> None:
    rows = []
    for line in lines:
        head, separator, detail = line.partition("|")
        state, colon, result = head.partition(":")
        queued = result.endswith("REQUESTED") or result in {"MOVING_TO", "CAPTURE_MOVE", "SPY_TRAVEL", "SPY_MISSION", "PRODUCING"}
        rows.append([("请求已发送" if state == "OK" and queued else {"OK": "成功", "WARN": "警告", "MAYBE": "待复查"}.get(state, state)),
                     result if colon else head, detail if separator else ""])
    print(table(["状态", "结果", "详情"], rows, display))


def _normalize_option_lines(title: str, lines: list[str]) -> list[str]:
    """Add stable record tags to compact upstream option rows for tables."""
    if not lines or lines == ["NONE"]:
        return []
    if title == "单位与可执行动作":
        activity_labels = {
            "ready": "待命", "hold": "已跳过", "sleep": "休眠", "heal": "休整",
            "sentry": "警戒", "fortify": "驻防", "fortify_or_alert": "驻防/警戒",
            "intercept": "拦截", "operation": "执行持续任务", "auto_explore": "自动探索",
            "trade_route": "执行商路",
            "spy_mission": "执行间谍任务", "build": "建造中", "dig": "挖掘中",
            "cut": "移除地貌中", "repair": "修复中", "spread_religion": "传播宗教中",
            "launch_inquisition": "发起宗教审判", "evangelize_belief": "传播信条",
            "excavate": "考古发掘中", "designate_park": "建立国家公园",
            "found_religion": "创立宗教", "create_district": "建造区域中",
            "create_wonder": "建造奇观中", "exhausted": "行动力耗尽",
            "busy": "执行持续任务", "awake": "待命", "none": "无活动",
            "unknown": "未知",
        }
        needs_labels = {"yes": "是", "no": "否", "unknown": "未知"}
        normalized = []
        for line in lines:
            fields = line.split("|")
            if len(fields) >= 19:
                raw_activity = fields[6]
                fields[6] = activity_labels.get(raw_activity, f"未知（{raw_activity}）")
                fields[7] = needs_labels.get(fields[7], "未知")
            normalized.append("ACTION_UNIT|" + "|".join(fields))
        return normalized
    if title == "间谍与可用任务":
        return ["ACTION_SPY|" + line for line in lines]
    mappings = {
        "回合待办与外部响应": {"SESSION": "DIPLO_SESSION", "DEAL": "PENDING_DEAL", "DEAL_ITEM": "DEAL_ITEM", "ITEM": "DEAL_ITEM"},
        "城市生产与购买": {"UNIT": "BUILD_UNIT", "BUILDING": "BUILD_BUILDING",
                         "DISTRICT": "BUILD_DISTRICT", "PROJECT": "BUILD_PROJECT"},
        "可选科技与市政": {"CURRENT": "RESEARCH_CURRENT"},
        "政策槽位与可用政策卡": {"GOV": "POLICY_GOV", "SLOT": "POLICY_SLOT", "AVAIL": "POLICY_AVAILABLE"},
        "总督任命、派遣与升级": {"STATUS": "GOVERNOR_STATUS"},
        "单位晋升": {"UNIT": "PROMOTION_UNIT", "XP": "PROMOTION_XP", "PROMO": "PROMOTION_OPTION"},
        "可派遣使者的城邦": {"TOKENS": "ENVOY_TOKENS", "CS": "ENVOY_CITY_STATE"},
        "可选万神殿": {"STATUS": "PANTHEON_STATUS", "BELIEF": "PANTHEON_BELIEF"},
        "可用宗教与信条": {"STATUS": "RELIGION_STATUS", "BELIEF": "RELIGION_BELIEF"},
        "时代着力点": {"STATUS": "DEDICATION_STATUS", "ACTIVE": "DEDICATION_ACTIVE", "CHOICE": "DEDICATION_CHOICE"},
        "可用政体": {"GOV": "GOVERNMENT_OPTION"},
        "伟人招募与赞助": {"GP": "GREAT_PERSON_OPTION"},
        "可选贸易路线": {"TDEST": "TRADE_DESTINATION"},
        "待响应交易": {"DEAL": "PENDING_DEAL", "ITEM": "DEAL_ITEM"},
        "可交易内容": {"CIV": "TRADE_CIV", "ECON": "TRADE_ECON", "RES": "TRADE_RESOURCE",
                       "OB": "TRADE_OPEN_BORDERS", "ALLIANCE": "TRADE_ALLIANCE", "CITY": "TRADE_CITY"},
        "外交会面选项": {"SESSION": "DIPLO_SESSION", "CHOICE": "DIPLO_CHOICE", "DEAL_ITEM": "DEAL_ITEM",
                         "CIV": "TRADE_CIV", "ECON": "TRADE_ECON", "RES": "TRADE_RESOURCE",
                         "OB": "TRADE_OPEN_BORDERS", "ALLIANCE": "TRADE_ALLIANCE", "CITY": "TRADE_CITY"},
        "待响应外交会面": {"SESSION": "DIPLO_SESSION", "DEAL_ITEM": "DEAL_ITEM"},
        "世界议会决议、目标与票价": {"WC_STATUS": "CONGRESS_STATUS", "WC_RES": "CONGRESS_RESOLUTION", "WC_PROP": "CONGRESS_PROPOSAL"},
        "可购买地块": {"PTILE": "PURCHASABLE_TILE"},
        "城市产出侧重": {"FOCUS": "CITY_FOCUS"},
        "区域选址": {"DPLOT": "DISTRICT_PLOT"},
        "奇观选址": {"WPLOT": "WONDER_PLOT"},
        "交易试算": {"CIV": "TRADE_CIV", "ITEM": "TRADE_TEST_ITEM", "RESULT": "TRADE_TEST_RESULT",
                     "PROPOSED_ITEMS": "TRADE_TEST_STAGE", "AI_COUNTER": "TRADE_TEST_STAGE",
                     "REJECTED": "TRADE_TEST_STAGE"},
    }
    mapping = mappings.get(title, {})
    output = []
    for line in lines:
        if line in {"UNITS:", "BUILDINGS:", "DISTRICTS:", "PROJECTS:", "REPAIRS:"}:
            continue
        head, separator, rest = line.partition("|")
        if title == "回合待办与外部响应" and head == "BLOCKING":
            blocker, _, message = rest.partition("|")
            message = message.split("|", 1)[0]
            output.append(f"TODO|type={blocker}|message={message}|next={_todo_hint(blocker)}")
            continue
        if title == "回合待办与外部响应" and head == "BLOCKING_CITY":
            output.append("CAPTURE_OPTION|" + rest)
            continue
        if title == "交易试算" and not separator and head in {"PROPOSED_ITEMS", "AI_COUNTER", "REJECTED"}:
            stage = {"PROPOSED_ITEMS": "我方提案", "AI_COUNTER": "AI 返回的条款", "REJECTED": "AI 拒绝"}[head]
            output.append("TRADE_TEST_STAGE|" + stage)
            continue
        output.append(mapping.get(head, head) + (("|" + rest) if separator else ""))
    if title == "可用政体":
        output.append("KEEP_OPTION|name=保留当前政体|next=government keep")
    if title == "政策槽位与可用政策卡":
        empty = any(line.startswith("SLOT|") and line.split("|")[3] == "NONE" for line in lines)
        no_slots = any(line.startswith("GOV|") and len(line.split("|")) >= 4 and line.split("|")[3] == "0" for line in lines)
        unknown_slots = any(line.startswith("GOV|") and len(line.split("|")) >= 4 and line.split("|")[3] == "-1" for line in lines)
        output.append("KEEP_OPTION|name=保留当前政策卡|available=" + ("unknown" if unknown_slots else "no" if empty else "yes")
                      + "|requirements=" + ("槽位信息未知" if unknown_slots else "当前没有政策槽位" if no_slots else "全部槽位已填满")
                      + "|next=policy keep")
    return output


def _todo_hint(blocker: str) -> str:
    special = (("CIVIC_SLOT", "policy options / policy keep（槽位须填满）"),
               ("INFLUENCE_TOKEN", "envoy options"), ("COMMEMORATION", "era options"),
               ("DISLOYAL_CITY", "city captures / city capture <城市> keep 或 reject"),
               ("SPY_CHOOSE_ESCAPE", "spy escape"),
               ("STACKED_UNITS", "unit list / unit move <单位> <x> <y>（不能通过跳过解除堆叠）"),
               ("CHOOSE_BELIEF", "religion belief-options"))
    for token, hint in special:
        if token in blocker:
            return hint
    hints = (
        ("PRODUCTION", "city production <城市>"), ("UNITS", "unit list / unit options <单位> / unit skip <单位>"),
        ("RESEARCH", "research options"), ("CIVIC", "research options"),
        ("GOVERNOR", "governor options"), ("PROMOTION", "unit promotions <单位>"),
        ("POLICY", "policy options / policy keep（槽位须填满）"), ("PANTHEON", "religion pantheon-options"),
        ("RELIGION", "religion belief-options"), ("ENVOY", "envoy options"),
        ("CITY_STATE", "envoy options"), ("DEDICATION", "era options"),
        ("GREAT_PERSON", "great-person options"), ("TRADE_ROUTE", "trade routes / unit options <商人>"),
        ("CONGRESS", "congress options"), ("SPY", "spy list / unit options <间谍>"),
        ("CAPTURE", "city captures / city capture <城市> <处置>"), ("GOVERNMENT", "government options / government keep"),
        ("RAZE_CITY", "city captures / city capture <城市> <处置>"),
        ("FREE_CITY", "city captures / city capture <城市> <处置>"),
    )
    return next((hint for token, hint in hints if token in blocker), "help")


def _show_lines(lines: list[str], display: Display = Display(), *, title: str | None = None) -> None:
    print(render_records(lines, display, title=title))


def run(connection: FireTunerConnection, *, display: Display = Display(), assume_yes: bool = False) -> int:
    terminal = Terminal(connection, display, assume_yes=assume_yes)
    print(panel("Civilization VI", "策略命令终端  ·  输入 help 查看命令", display,
                subtitle="已连接 FireTuner"))
    try:
        terminal.overview()
    except (FireTunerError, ValueError) as exc:
        print(status_line("error", f"总览读取失败：{exc}", display, "用 session reconnect 重连，或用 status 重试"))
    while True:
        try:
            prompt = inline("civ6", ACCENT, display) + inline(" > ", DIM, display)
            raw = input(prompt)
            words = shlex.split(raw)
            if not words:
                continue
            if not terminal.execute(words):
                return 0
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        except (ActionOutcomeUnknown, FireTunerError, ValueError) as exc:
            print(status_line("error", f"命令失败：{exc}", display))
