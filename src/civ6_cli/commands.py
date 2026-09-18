"""Canonical command tree shared by routing, offline help and the manual.

Only paths registered here are accepted as user-facing commands.  The ``route``
field is an implementation detail used by the existing domain handlers; it is
not a second, public command language.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.columns import Columns
from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text

from .rendering import (ACCENT, BORDER, DIM, FAINT, HEADING, INFO, WARNING,
                        Display, hint, render_rich, rich_table)

DIPLOMATIC_ACTIONS = (
    "DIPLOMATIC_DELEGATION", "DECLARE_FRIENDSHIP", "RESIDENT_EMBASSY", "DENOUNCE",
    "DECLARE_SURPRISE_WAR", "DECLARE_FORMAL_WAR", "DECLARE_HOLY_WAR",
    "DECLARE_LIBERATION_WAR", "DECLARE_RECONQUEST_WAR", "DECLARE_PROTECTORATE_WAR",
    "DECLARE_COLONIAL_WAR", "DECLARE_TERRITORIAL_WAR",
)


@dataclass(frozen=True)
class Command:
    path: str
    arguments: str
    description: str
    mode: str
    route: tuple[str, ...]
    minimum: int = 0
    maximum: int | None = 0

    @property
    def usage(self) -> str:
        return (self.path + " " + self.arguments).strip()

    def translate(self, args: list[str]) -> list[str]:
        if len(args) < self.minimum or (self.maximum is not None and len(args) > self.maximum):
            raise ValueError("用法：" + self.usage)
        if "[x y]" in self.arguments and len(args) not in {self.minimum, self.minimum + 2}:
            raise ValueError("用法：" + self.usage + "（坐标 x/y 必须成对提供）")
        words = []
        for token in self.route:
            if token == "$*":
                words.extend(args)
            elif token == "$rest":
                words.extend(args[1:])
            elif token.startswith("$"):
                words.append(args[int(token[1:]) - 1])
            else:
                words.append(token)
        return words


TOPICS = {
    "turn": "回合待办、结束与等待", "unit": "单位信息、合法选项与指令",
    "city": "城市信息、生产、购买与占领处置", "research": "科技与市政",
    "government": "政体", "policy": "政策卡",
    "governor": "总督任命、派遣与升级", "envoy": "城邦与使者",
    "era": "时代、时代分与着力点", "religion": "宗教分布、万神殿与信条",
    "great-person": "伟人招募、放弃与赞助", "diplomacy": "文明关系与外交响应",
    "great-work": "巨作、空槽位与移动交换",
    "trade": "商路概览与文明间交易", "spy": "间谍派遣、任务与逃跑",
    "congress": "世界议会", "map": "六边形地图与地块详情",
    "economy": "国库、收支、资源库存与资源地块", "victory": "已知文明的胜利进度",
    "session": "连接诊断、重连与退出",
}


def _c(path, args, description, route, minimum=0, maximum=0, mode="读"):
    return Command(path, args, description, mode, tuple(route.split()), minimum, maximum)


COMMANDS = [
    _c("status", "", "回合总览：产出、研究、城市发展与通知", "status"),
    _c("turn number", "", "当前回合数", "turn"),
    _c("turn todo", "", "回合阻塞、传入外交与交易及下一步命令", "todo"),
    _c("turn notifications", "", "未关闭的通知与阻塞标记", "query notifications"),
    _c("turn end", "", "确认无阻塞后结束回合并等待下一本地回合", "endturn", mode="写"),
    _c("turn wait", "[秒数]", "等待本地回合或需要响应的会面；1–300 秒，默认 30", "wait $*", 0, 1),
    _c("unit list", "", "己方单位的活动状态与指令需求", "unit-roster"),
    _c("unit visible", "", "视野内的其他阵营单位，包括野蛮人", "units visible"),
    _c("unit show", "<单位>", "单位属性和当前状态", "unit-show $*", 1, 1),
    _c("unit options", "<单位>", "当前可选动作；商人显示商路，间谍显示任务", "unit-options $*", 1, 1),
    _c("unit path", "<单位> <x> <y>", "距离与目标地形预检", "path $*", 3, 3),
    _c("unit promotions", "<单位>", "经验与当前合法晋升", "options promotions $*", 1, 1),
    _c("unit task", "<单位> <UNITOPERATION_TYPE> [x y]", "执行 unit options 中列出的专业地块任务", "unit $1 task $rest", 2, 4, "写"),
    _c("unit skip-all", "", "跳过所有需要指令的单位", "units skip-all", mode="写"),
    _c("unit fortify-all", "", "驻防所有需要指令且可驻防的战斗单位", "units fortify-all", mode="写"),
    _c("city list", "", "己方城市与当前生产进度", "cities"),
    _c("city known", "", "已探索城市，包括迷雾中的已知城市", "cities known"),
    _c("city show", "<城市>", "人口、宜居度、电力、区域内建筑与奇观", "city $*", 1, 1),
    _c("city production", "<城市>", "当前项目及生产、购买选项的费用与效果", "production $*", 1, 1),
    _c("city tiles", "<城市>", "合法可购地块及价格", "options tiles $*", 1, 1),
    _c("city focus-options", "<城市>", "当前产出侧重", "options focus $*", 1, 1),
    _c("city district-sites", "<城市> <DISTRICT_TYPE>", "合法区域选址、邻接和评分", "options district $*", 2, 2),
    _c("city wonder-sites", "<城市> <BUILDING_TYPE>", "合法奇观选址、地形与代价", "options wonder $*", 2, 2),
    _c("city captures", "", "待处置城市与合法处置选项", "options captures"),
    _c("city capture", "<城市> <keep|reject|raze|liberate-founder|liberate-previous>", "处置指定的占领或叛变城市", "capture $*", 2, 2, "写"),
    _c("research options", "", "研究进度及可选科技、市政的前置、加速与解锁", "options research"),
    _c("research set", "<tech|civic> <TYPE>", "选择科技或市政", "research $*", 2, 2, "写"),
    _c("government options", "", "当前状态、外交支持及已解锁政体的槽位与奖励", "options governments"),
    _c("government change", "<GOVERNMENT_TYPE>", "更换政体", "government change $*", 1, 1, "写"),
    _c("government keep", "", "保留当前政体", "government keep", mode="写"),
    _c("policy options", "", "当前槽位和可用政策卡的类型与效果", "options policies"),
    _c("policy set", "<槽位=POLICY_TYPE> [...]", "调整指定槽位，其余保留；NONE 显式清空", "policies set $*", 1, None, "写"),
    _c("policy keep", "", "保留已填满的政策布局", "policies keep", mode="写"),
    _c("governor options", "", "点数、已任命总督、可任命类型和升级", "options governors"),
    _c("governor appoint", "<GOVERNOR_TYPE>", "任命总督", "governor appoint $*", 1, 1, "写"),
    _c("governor assign", "<GOVERNOR_TYPE> <城市>", "派遣总督", "governor assign $*", 2, 2, "写"),
    _c("governor promote", "<GOVERNOR_TYPE> <GOVERNOR_PROMOTION_TYPE>", "升级总督", "governor promote $*", 2, 2, "写"),
    _c("envoy options", "", "可用使者、已相遇城邦类型、已派使者、宗主国与派遣可用性", "options envoys"),
    _c("envoy send", "<城邦玩家ID>", "派遣一名使者", "envoy send $*", 1, 1, "写"),
    _c("era options", "", "时代/时代分/年龄阈值、游戏速度、当前与可选着力点及效果", "options dedications"),
    _c("era choose", "<索引>", "选择着力点", "dedication choose $*", 1, 1, "写"),
    _c("religion show", "", "己方宗教、万神殿及可见城市信徒与宗教压力", "query religion"),
    _c("religion pantheon-options", "", "万神殿状态与可选信条", "options pantheon"),
    _c("religion belief-options", "", "可用宗教、信条类别与效果", "options religion"),
    _c("religion pantheon", "<BELIEF_TYPE>", "选择万神殿", "religion pantheon $*", 1, 1, "写"),
    _c("religion found", "<RELIGION_TYPE> <FOLLOWER_BELIEF> <FOUNDER_BELIEF>", "创立宗教并选择初始信条", "religion found $*", 3, 3, "写"),
    _c("religion evangelize", "<使徒>", "使徒执行传播信仰，获得一个待选宗教信条", "religion evangelize $*", 1, 1, "写"),
    _c("religion add-belief", "<BELIEF_TYPE>", "为己方宗教选择使徒传播获得的新信条", "religion add-belief $*", 1, 1, "写"),
    _c("great-person options", "", "候选、能力、巨作、招募进度与赞助费用", "options great-people"),
    _c("great-person recruit", "<伟人ID>", "招募伟人", "great-person recruit $*", 1, 1, "写"),
    _c("great-person pass", "<伟人ID>", "明确放弃候选伟人", "great-person pass $*", 1, 1, "写"),
    _c("great-person patronize", "<gold|faith> <伟人ID>", "金币或信仰赞助伟人", "great-person patronize $*", 2, 2, "写"),
    _c("great-work list", "", "己方巨作、创作者、产出、城市/建筑代号和空槽位", "query great-works"),
    _c("great-work options", "<巨作ID>", "可用槽位、移动或交换命令及限制", "great-work-options $*", 1, 1),
    _c("great-work move", "<巨作ID> <目标城市> <BUILDING_TYPE> <槽位>", "移动巨作；目的槽位已有巨作时交换，槽位从 0 开始", "great-work-move $*", 4, 4, "写"),
    _c("diplomacy players", "", "自己与已相遇文明的 ID、关系、军力、产出、国库与可见度", "query diplomacy"),
    _c("diplomacy self", "", "本地玩家 ID、文明与领袖", "player"),
    _c("diplomacy pending", "", "待响应会面与对话选项", "options diplomacy"),
    _c("diplomacy options", "<玩家ID>", "指定玩家当前会面的响应；交易内容用 trade options", "options diplomacy $*", 1, 1),
    _c("diplomacy respond", "<玩家ID> <positive|negative>", "响应 AI 会面；允许非玩家回合", "diplomacy respond $*", 2, 2, "写"),
    _c("diplomacy action", "<玩家ID> <DIPLOMATIC_ACTION>", "使团、友谊、使馆、谴责与宣战", "diplomacy action $*", 2, 2, "写"),
    _c("diplomacy alliance", "<玩家ID> <military|research|cultural|economic|religious>", "发送同盟提案；用 trade pending 检查实际回应", "diplomacy alliance $*", 2, 2, "写"),
    _c("trade routes", "", "使用中商路、容量和商人", "query trade"),
    _c("trade pending", "", "待响应交易及实际条款", "options trades"),
    _c("trade options", "<玩家ID>", "双方可交易的资产、协议、可用性与条款", "options trades $*", 1, 1),
    _c("trade respond", "<玩家ID> <accept|reject>", "接受/拒绝传入交易；允许非玩家回合", "trade respond $*", 2, 2, "写"),
    _c("trade propose", "<玩家ID> <test|send> <give-/want-条款> [...]", "试算或发送交易；发送前建议先试算", "trade propose $*", 3, None, "写"),
    _c("trade peace", "<玩家ID> <test|send> [give-/want-条款 ...]", "试算或发送和平协议；无附加条款即双方只停战", "trade peace $*", 2, None, "写"),
    _c("spy list", "", "全部间谍、等级、当前任务与剩余回合", "query spies"),
    _c("spy destinations", "<间谍>", "合法派遣城市与旅行、建立情报网及合计回合", "options spy-destinations $*", 1, 1),
    _c("spy travel", "<间谍> <x> <y>", "派遣至合法城市，不能普通行走", "spy-travel $*", 3, 3, "写"),
    _c("spy mission", "<间谍> <MISSION_TYPE> <x> <y>", "执行当前合法任务；坐标从任务表复制", "spy-mission $*", 4, 4, "写"),
    _c("spy escape", "", "出现逃跑待办时选择最快可用逃跑路线", "spy escape", mode="写"),
    _c("congress options", "", "会议时间、决议 A/B、目标和累计票价", "options congress"),
    _c("congress queue", "<Hash>:<A|B>:<目标ID>:<票数> [...]", "结束回合前预登记下一次会议投票", "congress queue $*", 1, None, "写"),
    _c("congress vote", "<Hash>:<A|B>:<目标索引>:<票数>", "会议中直接投一项", "congress vote $*", 1, 1, "写"),
    _c("congress submit", "", "提交会议内全部投票", "congress submit", mode="写"),
    _c("map show", "<x> <y> [半径]", "坐标周围六边形地图；默认半径 2，范围 0–5", "map $*", 2, 3),
    _c("map unit", "<单位或阵营ID:单位ID> [半径]", "定位己方/当前可见单位", "map unit $*", 1, 2),
    _c("map city", "<城市或阵营ID:城市ID> [半径]", "定位己方或已探索城市", "map city $*", 1, 2),
    _c("map tile", "<x> <y> [半径]", "地块详情与魅力值；默认半径 0，范围 0–5", "tile $*", 2, 3),
    _c("economy show", "", "国库、收入、维护费与战略资源库存/净变化", "query economy"),
    _c("economy resources", "[资源名筛选词]", "已探索资源地块、归属与改良；可按本地化名称筛选", "query resources $*", 0, 1),
    _c("victory show", "", "已知文明的分数、科技、外交、旅游与宗教胜利指标", "query victory"),
    _c("session probe", "", "连接身份与通道探测", "probe"),
    _c("session reconnect", "", "重连 FireTuner 并刷新总览", "reconnect"),
    _c("session quit", "", "退出终端，不退出游戏", "quit"),
]

for verb, args, desc, count in (
    ("move", "<x> <y>", "普通单位移动", 2),
    ("attack", "<x> <y>", "攻击，自动区分近战、远程和空袭", 2),
    ("skip", "", "跳过单位本回合", 0), ("fortify", "", "驻防", 0),
    ("heal", "", "休整至满血", 0), ("alert", "", "警戒，遇敌自动唤醒", 0),
    ("sleep", "", "持续休眠", 0), ("explore", "", "自动探索", 0),
    ("wake", "", "唤醒休眠/驻防单位，恢复手动指令", 0),
    ("cancel", "", "取消当前持续指令或任务", 0),
    ("found-city", "", "开拓者建立城市", 0), ("activate", "", "激活当前地块可用的伟人能力", 0),
    ("spread-religion", "", "在当前城市传播宗教", 0), ("upgrade", "", "金币/资源升级单位类型", 0),
    ("disband", "", "解散单位，不可逆", 0),
    ("remove-feature", "", "砍伐/清除当前地貌", 0), ("repair", "", "修复当前改良", 0),
    ("remove-improvement", "", "移除当前改良", 0), ("build-route", "", "军事工程师修道路/铁路", 0),
    ("improve", "<IMPROVEMENT_TYPE>", "在当前地块修建合法改良", 1),
    ("promote", "<PROMOTION_TYPE>", "选择合法晋升", 1),
    ("trade-route", "<x> <y>", "商人建立至指定目标城市的商路", 2),
    ("teleport", "<x> <y>", "空闲商人迁移到合法己方城市", 2),
):
    COMMANDS.append(_c("unit " + verb, ("<单位> " + args).strip(), desc,
                       "unit $1 " + verb + " $rest", count + 1, count + 1, "写"))

for verb, args, desc, minimum, maximum in (
    ("produce", "<unit|building|district|project> <TYPE> [x y]", "替换当前生产；区域/奇观带合法坐标", 2, 4),
    ("buy", "<gold|faith> <unit|building|district> <TYPE> [x y]", "立即购买；区域需坐标", 3, 5),
    ("buy-tile", "<x> <y>", "购买指定地块", 2, 2),
    ("focus", "<food|production|gold|science|culture|faith|default>", "设置或清除产出侧重", 1, 1),
    ("attack", "<x> <y>", "城防远程攻击", 2, 2),
):
    COMMANDS.append(_c("city " + verb, "<城市> " + args, desc,
                       "city $1 " + verb + " $rest", minimum + 1, maximum + 1, "写"))


def route_command(words: list[str]) -> list[str]:
    """Validate a canonical leaf and translate it to an internal handler route."""
    lowered = [word.lower() for word in words]
    for command in COMMANDS:
        path = command.path.split()
        if lowered[:len(path)] == path:
            return command.translate(words[len(path):])
    raise ValueError("未知命令；输入 help 查看命令树，help <主题> 查看完整语法")


def offline_command(words: list[str]) -> bool:
    if not words:
        return False
    if words[0].lower() == "help":
        return True
    normalized = route_command(words)
    return normalized == ["quit"]


def show_help(args: list[str] | None = None, display: Display = Display()) -> None:
    args = [arg.lower() for arg in (args or [])]
    if not args:
        intro = Text()
        intro.append("主题 → 动词 → 对象 → 参数", style="bold")
        intro.append("\n读取立即执行；写入先预览并确认。", style=DIM)
        intro.append("\n总览  ", style=DIM)
        intro.append("status", style=ACCENT)
        intro.append("    完整命令树  ", style=DIM)
        intro.append("help tree", style=ACCENT)
        topic_items = []
        for name, description in TOPICS.items():
            item = Text()
            item.append(name, style=HEADING)
            item.append("  " + description, style=DIM)
            item.append("\n  help " + name, style=ACCENT)
            topic_items.append(item)
        renderables: list[RenderableType] = [
            Panel(
                intro,
                title=Text("文明 VI 命令帮助", style=HEADING),
                title_align="left",
                border_style=ACCENT,
                box=box.ASCII if display.ascii else box.ROUNDED,
                padding=(0, 1),
                expand=True,
            ),
            Columns(topic_items, equal=True, expand=True, padding=(0, 3), column_first=True),
        ]
        print(render_rich(renderables, display))
    elif args == ["tree"]:
        tree = Text()
        tree.append("status", style=ACCENT)
        tree.append("  [读]\n", style=INFO)
        tree.append("help [主题或完整命令路径]\nhelp tree\n", style=ACCENT)
        branch, last = (("|-- ", "`-- ") if display.ascii else ("├─ ", "└─ "))
        for topic in TOPICS:
            commands = [command for command in COMMANDS if command.path.split()[0] == topic]
            tree.append("\n" + topic, style=HEADING)
            tree.append("  " + TOPICS[topic] + "\n", style=DIM)
            for index, command in enumerate(commands):
                tree.append("  " + (last if index == len(commands) - 1 else branch), style=FAINT)
                tree.append(command.usage.removeprefix(topic + " "), style=ACCENT)
                tree.append("  [" + command.mode + "]\n", style=WARNING if command.mode == "写" else INFO)
        print(render_rich([
            Panel(
                tree,
                title=Text("完整命令树", style=HEADING),
                subtitle=Text(f"{len(COMMANDS)} 个叶子命令", style=DIM),
                title_align="left",
                subtitle_align="right",
                border_style=BORDER,
                box=box.ASCII if display.ascii else box.ROUNDED,
                padding=(0, 1),
                expand=True,
            )
        ], display))
    else:
        prefix = " ".join(args)
        selected = [c for c in COMMANDS if c.path == prefix or c.path.startswith(prefix + " ")]
        if not selected:
            raise ValueError("未知帮助主题；输入 help 或 help tree")
        topic = args[0]
        description = TOPICS.get(topic, selected[0].description)
        summary = Text()
        summary.append(prefix, style=HEADING)
        summary.append("\n" + description, style=DIM)
        renderables = [
            Panel(
                summary,
                title=Text("命令参考", style=HEADING),
                subtitle=Text(f"{len(selected)} 个命令", style=DIM),
                title_align="left",
                subtitle_align="right",
                border_style=ACCENT,
                box=box.ASCII if display.ascii else box.ROUNDED,
                padding=(0, 1),
                expand=True,
            ),
            rich_table(["R/W", "完整命令", "用途"], [[c.mode, c.usage, c.description] for c in selected], display),
        ]
        notes = Text()
        if args == ["map"]:
            notes.append("对象定位\n", style="bold")
            notes.append("重名或 ID 冲突时使用 ", style=DIM)
            notes.append("<阵营ID>:<城市ID>", style=ACCENT)
            notes.append(" 或 ", style=DIM)
            notes.append("<阵营ID>:<单位ID>", style=ACCENT)
            notes.append("；外方对象来自 city known / unit visible。", style=DIM)
        if prefix in {"diplomacy", "diplomacy action"}:
            notes.append("外交动作常量\n", style="bold")
            notes.append("\n".join("  " + action for action in DIPLOMATIC_ACTIONS), style=ACCENT)
        if prefix in {"unit task"}:
            from .lua.units import PLOT_TASKS
            notes.append("专业地块任务\n", style="bold")
            notes.append("以 unit options 的当前可用性为准。\n", style=DIM)
            notes.append("\n".join("  UNITOPERATION_" + name for name in PLOT_TASKS), style=ACCENT)
        if prefix in {"trade", "trade propose", "trade peace"}:
            notes.append("交易条款\n", style="bold")
            notes.append("give-/want-", style=ACCENT)
            notes.append(" 后接以下类型：\n", style=DIM)
            notes.append("  gold, gpt, favor, resource, open-borders, city\n", style=ACCENT)
            notes.append("  great-work, captive, research-agreement, alliance\n", style=ACCENT)
            notes.append("  joint-war, third-party-war\n", style=ACCENT)
            notes.append("条款与 ID 从 trade options 复制；先 test 检查接受、还价或拒绝。\n", style=DIM)
            notes.append("  trade propose 2 test give-resource=RESOURCE_SILK want-gpt=5\n", style=ACCENT)
            notes.append("  trade peace 2 test want-city=65536 want-gold=200\n", style=ACCENT)
            notes.append("不带附加条款的 peace 表示仅停战。", style=DIM)
        if prefix in {"great-work", "great-work move", "great-work options"}:
            notes.append("巨作移动与交换\n", style="bold")
            notes.append("先用 great-work list 取得巨作 ID，再从 great-work options <巨作ID> 复制目标命令。槽位使用从 0 开始的编号；已有巨作时交换。艺术品冷却和满文物博物馆限制与游戏相同。", style=DIM)
        if prefix in {"city", "city captures", "city capture"}:
            notes.append("城市处置\n", style="bold")
            notes.append("从 city captures 复制城市 ID；处理后重新查询列表。", style=DIM)
        if notes.plain:
            renderables.append(Panel(
                notes,
                title=Text("用法提示", style=HEADING),
                title_align="left",
                border_style=BORDER,
                box=box.ASCII if display.ascii else box.ROUNDED,
                padding=(0, 1),
                expand=True,
            ))
        print(render_rich(renderables, display))
    print(hint('己方对象可用 ID 或完整名称，空格名称加双引号。写操作先预览再确认。\n完整说明：COMMAND_MANUAL.md', display))


def manual_command_tables() -> str:
    """Generate the reference tables from the exact same routing definitions."""
    sections = []
    for topic, description in TOPICS.items():
        commands = [c for c in COMMANDS if c.path.split()[0] == topic]
        rows = ["| 读/写 | 完整命令 | 输出 / 效果 |", "|---|---|---|"]
        rows.extend("| {} | `{}` | {} |".format(c.mode, c.usage.replace("|", "\\|"), c.description.replace("|", "/")) for c in commands)
        sections.append(f"## {topic}：{description}\n\n" + "\n".join(rows))
    return "\n\n".join(sections)
