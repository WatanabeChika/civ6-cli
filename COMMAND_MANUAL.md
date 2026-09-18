# 文明 VI 命令行操作手册

civ6-cli 按游戏领域组织命令，读取与操作使用同一套“主题 → 动词 → 对象 → 参数”结构。命令、参数顺序和内置帮助来自 `src/civ6_cli/commands.py`。

## 开始使用

帮助命令不需要连接游戏：

```text
help
help <主题>
help <完整命令路径>
help tree
```

`status` 显示当前回合总览；其余命令以主题开头：

```text
turn  unit  city  research  government  policy  governor  envoy
era  religion  great-person  great-work  diplomacy  trade  spy
congress  map  economy  victory  session
```

一个典型回合：

```text
status
turn todo
unit list
unit options <需要指令的单位>
city production <需要生产的城市>
<选择并执行操作>
turn todo
turn end
```

单位可以用 `unit skip` 放弃本回合指令；政体可以用 `government keep` 保留；政策槽已填满时可以用 `policy keep` 保留布局。主动交易、购买、外交动作和其他战略选择不会自动执行。

## 参数与输出

- `<...>` 为必填参数，`[...]` 为可选参数；`[x y]` 必须成对提供。
- 己方单位和城市可使用完整 ID 或完整名称；重名时使用 ID，含空格的名称加双引号。
- 单位的只读查询可解析唯一的六位 ID 前缀；写操作必须使用完整 ID 或完整名称。
- 地图可用 `<阵营ID>:<对象ID>` 定位已知外方对象，例如 `map city 2:196610 3`。
- `UNIT_*`、`TECH_*` 等内部类型应从相应选项页复制。
- 坐标使用游戏的 X/Y；地图半径范围为 0–5。
- `list` 提供紧凑列表，`show` 提供对象详情，`options` 提供选择条件与执行命令。
- 未知信息显示为“未知”，不会按 0 处理。

<!-- BEGIN GENERATED COMMAND REFERENCE -->

## turn：回合待办、结束与等待

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `turn number` | 当前回合数 |
| 读 | `turn todo` | 回合阻塞、传入外交与交易及下一步命令 |
| 读 | `turn notifications` | 未关闭的通知与阻塞标记 |
| 写 | `turn end` | 确认无阻塞后结束回合并等待下一本地回合 |
| 读 | `turn wait [秒数]` | 等待本地回合或需要响应的会面；1–300 秒，默认 30 |

## unit：单位信息、合法选项与指令

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `unit list` | 己方单位的活动状态与指令需求 |
| 读 | `unit visible` | 视野内的其他阵营单位，包括野蛮人 |
| 读 | `unit show <单位>` | 单位属性和当前状态 |
| 读 | `unit options <单位>` | 当前可选动作；商人显示商路，间谍显示任务 |
| 读 | `unit path <单位> <x> <y>` | 距离与目标地形预检 |
| 读 | `unit promotions <单位>` | 经验与当前合法晋升 |
| 写 | `unit task <单位> <UNITOPERATION_TYPE> [x y]` | 执行 unit options 中列出的专业地块任务 |
| 写 | `unit skip-all` | 跳过所有需要指令的单位 |
| 写 | `unit fortify-all` | 驻防所有需要指令且可驻防的战斗单位 |
| 写 | `unit move <单位> <x> <y>` | 普通单位移动 |
| 写 | `unit attack <单位> <x> <y>` | 攻击，自动区分近战、远程和空袭 |
| 写 | `unit skip <单位>` | 跳过单位本回合 |
| 写 | `unit fortify <单位>` | 驻防 |
| 写 | `unit heal <单位>` | 休整至满血 |
| 写 | `unit alert <单位>` | 警戒，遇敌自动唤醒 |
| 写 | `unit sleep <单位>` | 持续休眠 |
| 写 | `unit explore <单位>` | 自动探索 |
| 写 | `unit wake <单位>` | 唤醒休眠/驻防单位，恢复手动指令 |
| 写 | `unit cancel <单位>` | 取消当前持续指令或任务 |
| 写 | `unit found-city <单位>` | 开拓者建立城市 |
| 写 | `unit activate <单位>` | 激活当前地块可用的伟人能力 |
| 写 | `unit spread-religion <单位>` | 在当前城市传播宗教 |
| 写 | `unit upgrade <单位>` | 金币/资源升级单位类型 |
| 写 | `unit disband <单位>` | 解散单位，不可逆 |
| 写 | `unit remove-feature <单位>` | 砍伐/清除当前地貌 |
| 写 | `unit repair <单位>` | 修复当前改良 |
| 写 | `unit remove-improvement <单位>` | 移除当前改良 |
| 写 | `unit build-route <单位>` | 军事工程师修道路/铁路 |
| 写 | `unit improve <单位> <IMPROVEMENT_TYPE>` | 在当前地块修建合法改良 |
| 写 | `unit promote <单位> <PROMOTION_TYPE>` | 选择合法晋升 |
| 写 | `unit trade-route <单位> <x> <y>` | 商人建立至指定目标城市的商路 |
| 写 | `unit teleport <单位> <x> <y>` | 空闲商人迁移到合法己方城市 |

## city：城市信息、生产、购买与占领处置

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `city list` | 己方城市与当前生产进度 |
| 读 | `city known` | 已探索城市，包括迷雾中的已知城市 |
| 读 | `city show <城市>` | 人口、宜居度、电力、区域内建筑与奇观 |
| 读 | `city production <城市>` | 当前项目及生产、购买选项的费用与效果 |
| 读 | `city tiles <城市>` | 合法可购地块及价格 |
| 读 | `city focus-options <城市>` | 当前产出侧重 |
| 读 | `city district-sites <城市> <DISTRICT_TYPE>` | 合法区域选址、邻接和评分 |
| 读 | `city wonder-sites <城市> <BUILDING_TYPE>` | 合法奇观选址、地形与代价 |
| 读 | `city captures` | 待处置城市与合法处置选项 |
| 写 | `city capture <城市> <keep\|reject\|raze\|liberate-founder\|liberate-previous>` | 处置指定的占领或叛变城市 |
| 写 | `city produce <城市> <unit\|building\|district\|project> <TYPE> [x y]` | 替换当前生产；区域/奇观带合法坐标 |
| 写 | `city buy <城市> <gold\|faith> <unit\|building\|district> <TYPE> [x y]` | 立即购买；区域需坐标 |
| 写 | `city buy-tile <城市> <x> <y>` | 购买指定地块 |
| 写 | `city focus <城市> <food\|production\|gold\|science\|culture\|faith\|default>` | 设置或清除产出侧重 |
| 写 | `city attack <城市> <x> <y>` | 城防远程攻击 |

## research：科技与市政

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `research options` | 研究进度及可选科技、市政的前置、加速与解锁 |
| 写 | `research set <tech\|civic> <TYPE>` | 选择科技或市政 |

## government：政体

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `government options` | 当前状态、外交支持及已解锁政体的槽位与奖励 |
| 写 | `government change <GOVERNMENT_TYPE>` | 更换政体 |
| 写 | `government keep` | 保留当前政体 |

## policy：政策卡

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `policy options` | 当前槽位和可用政策卡的类型与效果 |
| 写 | `policy set <槽位=POLICY_TYPE> [...]` | 调整指定槽位，其余保留；NONE 显式清空 |
| 写 | `policy keep` | 保留已填满的政策布局 |

## governor：总督任命、派遣与升级

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `governor options` | 点数、已任命总督、可任命类型和升级 |
| 写 | `governor appoint <GOVERNOR_TYPE>` | 任命总督 |
| 写 | `governor assign <GOVERNOR_TYPE> <城市>` | 派遣总督 |
| 写 | `governor promote <GOVERNOR_TYPE> <GOVERNOR_PROMOTION_TYPE>` | 升级总督 |

## envoy：城邦与使者

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `envoy options` | 可用使者、已相遇城邦类型、已派使者、宗主国与派遣可用性 |
| 写 | `envoy send <城邦玩家ID>` | 派遣一名使者 |

## era：时代、时代分与着力点

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `era options` | 时代/时代分/年龄阈值、游戏速度、当前与可选着力点及效果 |
| 写 | `era choose <索引>` | 选择着力点 |

## religion：宗教分布、万神殿与信条

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `religion show` | 己方宗教、万神殿及可见城市信徒与宗教压力 |
| 读 | `religion pantheon-options` | 万神殿状态与可选信条 |
| 读 | `religion belief-options` | 可用宗教、信条类别与效果 |
| 写 | `religion pantheon <BELIEF_TYPE>` | 选择万神殿 |
| 写 | `religion found <RELIGION_TYPE> <FOLLOWER_BELIEF> <FOUNDER_BELIEF>` | 创立宗教并选择初始信条 |
| 写 | `religion evangelize <使徒>` | 使徒执行传播信仰，获得一个待选宗教信条 |
| 写 | `religion add-belief <BELIEF_TYPE>` | 为己方宗教选择使徒传播获得的新信条 |

## great-person：伟人招募、放弃与赞助

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `great-person options` | 候选、能力、巨作、招募进度与赞助费用 |
| 写 | `great-person recruit <伟人ID>` | 招募伟人 |
| 写 | `great-person pass <伟人ID>` | 明确放弃候选伟人 |
| 写 | `great-person patronize <gold\|faith> <伟人ID>` | 金币或信仰赞助伟人 |

## diplomacy：文明关系与外交响应

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `diplomacy players` | 自己与已相遇文明的 ID、关系、军力、产出、国库与可见度 |
| 读 | `diplomacy self` | 本地玩家 ID、文明与领袖 |
| 读 | `diplomacy pending` | 待响应会面与对话选项 |
| 读 | `diplomacy options <玩家ID>` | 指定玩家当前会面的响应；交易内容用 trade options |
| 写 | `diplomacy respond <玩家ID> <positive\|negative>` | 响应 AI 会面；允许非玩家回合 |
| 写 | `diplomacy action <玩家ID> <DIPLOMATIC_ACTION>` | 使团、友谊、使馆、谴责与宣战 |
| 写 | `diplomacy alliance <玩家ID> <military\|research\|cultural\|economic\|religious>` | 发送同盟提案；用 trade pending 检查实际回应 |

## great-work：巨作、空槽位与移动交换

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `great-work list` | 己方巨作、创作者、产出、城市/建筑代号和空槽位 |
| 读 | `great-work options <巨作ID>` | 可用槽位、移动或交换命令及限制 |
| 写 | `great-work move <巨作ID> <目标城市> <BUILDING_TYPE> <槽位>` | 移动巨作；目的槽位已有巨作时交换，槽位从 0 开始 |

## trade：商路概览与文明间交易

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `trade routes` | 使用中商路、容量和商人 |
| 读 | `trade pending` | 待响应交易及实际条款 |
| 读 | `trade options <玩家ID>` | 双方可交易的资产、协议、可用性与条款 |
| 写 | `trade respond <玩家ID> <accept\|reject>` | 接受/拒绝传入交易；允许非玩家回合 |
| 写 | `trade propose <玩家ID> <test\|send> <give-/want-条款> [...]` | 试算或发送交易；发送前建议先试算 |
| 写 | `trade peace <玩家ID> <test\|send> [give-/want-条款 ...]` | 试算或发送和平协议；无附加条款即双方只停战 |

## spy：间谍派遣、任务与逃跑

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `spy list` | 全部间谍、等级、当前任务与剩余回合 |
| 读 | `spy destinations <间谍>` | 合法派遣城市与旅行、建立情报网及合计回合 |
| 写 | `spy travel <间谍> <x> <y>` | 派遣至合法城市，不能普通行走 |
| 写 | `spy mission <间谍> <MISSION_TYPE> <x> <y>` | 执行当前合法任务；坐标从任务表复制 |
| 写 | `spy escape` | 出现逃跑待办时选择最快可用逃跑路线 |

## congress：世界议会

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `congress options` | 会议时间、决议 A/B、目标和累计票价 |
| 写 | `congress queue <Hash>:<A\|B>:<目标ID>:<票数> [...]` | 结束回合前预登记下一次会议投票 |
| 写 | `congress vote <Hash>:<A\|B>:<目标索引>:<票数>` | 会议中直接投一项 |
| 写 | `congress submit` | 提交会议内全部投票 |

## map：六边形地图与地块详情

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `map show <x> <y> [半径]` | 坐标周围六边形地图；默认半径 2，范围 0–5 |
| 读 | `map unit <单位或阵营ID:单位ID> [半径]` | 定位己方/当前可见单位 |
| 读 | `map city <城市或阵营ID:城市ID> [半径]` | 定位己方或已探索城市 |
| 读 | `map tile <x> <y> [半径]` | 地块详情与魅力值；默认半径 0，范围 0–5 |

## economy：国库、收支、资源库存与资源地块

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `economy show` | 国库、收入、维护费与战略资源库存/净变化 |
| 读 | `economy resources [资源名筛选词]` | 已探索资源地块、归属与改良；可按本地化名称筛选 |

## victory：已知文明的胜利进度

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `victory show` | 已知文明的分数、科技、外交、旅游与宗教胜利指标 |

## session：连接诊断、重连与退出

| 读/写 | 完整命令 | 输出 / 效果 |
|---|---|---|
| 读 | `session probe` | 连接身份与通道探测 |
| 读 | `session reconnect` | 重连 FireTuner 并刷新总览 |
| 读 | `session quit` | 退出终端，不退出游戏 |

<!-- END GENERATED COMMAND REFERENCE -->

## 单位与专业操作

`unit list` 显示活动状态、移动力、生命值和“需指令”。驻防、警戒、休整、休眠、自动探索或持续任务中的单位不会仅因剩余移动力而被标为待命。

`unit options <单位>` 显示当前可执行动作、失败条件和可复制命令。需要坐标或类型的动作以该页列出的参数为准。

| 单位 | 操作入口 |
|---|---|
| 商人 | `unit options`、`unit trade-route`、`unit teleport` |
| 间谍 | `spy destinations`、`spy travel`、`unit options`、`spy mission` |
| 空军 | `unit task ... UNITOPERATION_REBASE/DEPLOY`、`unit attack` |
| 建造者 / 军事工程师 | `unit improve`、`unit task`、修复与道路命令 |
| 开拓者 / 伟人 | `unit found-city`、`unit activate` |
| 宗教单位 | `unit spread-religion`、宗教地块任务 |
| 考古学家 / 自然学家 / 摇滚乐队 | 从 `unit options` 复制对应的 `unit task` 命令 |

`unit task` 未提供坐标时作用于当前地块，不会自动移动到目标。

使徒新增信条分两步：

```text
religion evangelize <使徒>
religion belief-options
religion add-belief <BELIEF_TYPE>
```

### 商路

`unit options <商人>` 会列出目的城市、坐标、单程距离、预计持续回合和双方每回合收益：

```text
unit options 851973
unit trade-route 851973 68 22
unit teleport 851973 64 26
```

“预计回合”表示路线持续时间，不是到达目的地的单程时间。

### 间谍

```text
spy list
spy destinations <间谍>
spy travel <间谍> <目的城市x> <目的城市y>
unit options <间谍>
spy mission <间谍> <MISSION_TYPE> <目标x> <目标y>
```

任务页显示合法目标、回合、成功概率和效果。反间谍目标是区域；需要逃跑时使用 `spy escape`。

## 城市

`city production <城市>` 是生产与购买决策页，包含费用、回合、条件、效果和可复制的内部类型。

```text
city production 开罗
city district-sites 开罗 DISTRICT_CAMPUS
city produce 开罗 district DISTRICT_CAMPUS 31 25
city buy 开罗 faith unit UNIT_APOSTLE
city focus 开罗 food
```

区域和奇观生产需要合法坐标；购买区域也需要坐标。`city produce` 会替换当前生产项目。

`city captures` 列出待处置城市及合法选择：

```text
city captures
city capture 4390926 keep
city captures
```

叛变城市可保留或拒绝；征服城市可用的保留、夷平或解放选项取决于当前局势。普通城市不能使用 `city capture`。

## 政体与政策

```text
government options
government change GOVERNMENT_MONARCHY
government keep
policy options
policy set 0=POLICY_AGOGE 1=POLICY_URBAN_PLANNING
policy keep
```

`government keep` 保留当前政体。`policy keep` 保留已填满的政策布局；存在空槽位时应先补卡。`policy set` 未指定的槽位保持不变，`NONE` 表示清空指定槽位。

无政府状态下没有生效的政体或政策槽位；`government options` 会显示剩余回合。keep 命令不会缩短无政府状态。

## 外交与交易

`turn todo` 汇总回合阻塞、AI 会面和传入交易。`trade pending` 显示待响应交易的实际条款；外交或交易响应可以在非玩家回合执行。

`diplomacy action` 支持以下常量：

```text
DIPLOMATIC_DELEGATION    DECLARE_FRIENDSHIP      RESIDENT_EMBASSY
DENOUNCE                 DECLARE_SURPRISE_WAR    DECLARE_FORMAL_WAR
DECLARE_HOLY_WAR         DECLARE_LIBERATION_WAR  DECLARE_RECONQUEST_WAR
DECLARE_PROTECTORATE_WAR DECLARE_COLONIAL_WAR    DECLARE_TERRITORIAL_WAR
```

交易条款使用 `give-` 表示我方给予，`want-` 表示向对方索取：

| 类型 | 示例 |
|---|---|
| 一次性金币 | `give-gold=100` |
| 每回合金币 | `want-gpt=5` |
| 外交支持 | `give-favor=20` |
| 资源 | `give-resource=RESOURCE_IRON:20:30` |
| 开放边界 | `want-open-borders` |
| 城市 | `want-city=<交易城市ID>` |
| 巨作 | `give-great-work=<巨作实例ID>` |
| 俘虏间谍 | `give-captive=<交易俘虏ID>` |
| 研究协议 | `give-research-agreement=TECH_TYPE` |
| 同盟 | `give-alliance=research` |
| 联合战争 | `give-joint-war=<第三方ID>:<WarType>` |
| 第三方战争 | `want-third-party-war=<第三方ID>:<WarType>` |

从 `trade options <玩家ID>` 复制条款和专用 ID。资源可附加数量与回合；研究协议、同盟和战争条款需要相应的二级选择。

先试算，再发送：

```text
trade options 2
trade propose 2 test give-resource=RESOURCE_SILK want-gpt=5
trade propose 2 send give-resource=RESOURCE_SILK want-gpt=5
trade pending
```

试算会显示接受、还价、拒绝或无法判断。发送提议不会自动接受 AI 还价；应通过 `trade pending` 核对后再响应。试算会建立临时会面并修改交易草稿，因此也需要确认。

和平协议使用同一套条款：

```text
trade peace 2 test
trade peace 2 test want-city=65536 want-gold=200
trade peace 2 send want-city=65536 want-gold=200
```

不带附加条款表示双方只停战。

## 世界议会

会议将在结束回合时触发时，先用 `congress options` 查看决议，再用 `congress queue` 登记投票，最后执行 `turn end`。会议已经打开时使用 `congress vote` 和 `congress submit`。

`queue` 使用玩家 ID，`vote` 使用决议给出的目标索引。投票格式为 `决议Hash:A或B:目标:票数`。

## 巨作

```text
great-work list
great-work options <巨作ID>
great-work move <巨作ID> <目标城市> <BUILDING_TYPE> <槽位>
great-work list
```

命令使用巨作实例 ID 与从 0 开始的操作槽位。目标为空槽时移动，目标已有巨作时交换；类型兼容、冷却和文物博物馆限制会显示在选项页中。

## 地图与可见性

`map show` 默认半径为 2，`map tile` 默认半径为 0。地图按六边形距离筛选，格内坐标始终是游戏坐标。

地图标记：C 城市、U 己方单位、! 其他可见单位、R 资源、D 区域、W 奇观、B 蛮族哨站、V 村庄、I 改良、≈ 河流、@ 中心、~ 迷雾、?? 未探索。

未探索地块不显示地形；迷雾地块不显示实时单位、城市、归属、设施或产出；战略资源须已解锁，可见单位仍受游戏的可见性检查约束。

## 确认、安全与结果状态

读取命令立即执行。写命令先显示动作预览，输入 `y`、`yes`、`是` 或 `确认` 后发送；其他输入取消。全局 `--yes` 可显式免确认：

```powershell
civ6 --yes unit skip 7
```

- **成功**：游戏接受了请求。
- **请求已发送 / 待复查**：请求可能异步处理，应读取目标状态。
- **已拒绝**：条件不满足，应修正选择或参数。
- **结果未知**：发送后超时、断线或执行中断，动作可能已经生效；重连并读取状态，不要直接重试。

工具不会自动重放写请求、代选阻塞项或保存存档。只支持 Windows Steam 单人游戏；启用 Tuner 通常会禁用当前存档的 Steam 成就。
