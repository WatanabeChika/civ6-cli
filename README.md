# civ6-cli

面向 Sid Meier's Civilization VI 单人游戏的 Windows 命令行控制台。它通过游戏的 FireTuner 通道读取当前局势，并以经过确认的命令执行回合操作。

civ6-cli 使用清晰的策略游戏信息层级展示总览、单位、城市、研究、外交、贸易和六边形地图。它是普通 CLI 与持久 REPL，不是全屏 TUI。

## 特性

- 统一的“主题 → 动词 → 对象 → 参数”命令结构
- 回合总览、待办、单位与城市决策、外交交易、世界议会等完整领域命令
- 保留可见性规则的六边形地图，不读取未探索或迷雾中的实时信息
- 写操作遵循“预览 → 确认 → 发送一次 → 复查”，结果不明时不会自动重试
- 基于 Rich 的自适应输出，支持窄终端、ASCII、显式宽度和无颜色模式
- 固定 Lua 模板与严格参数校验，不接受任意脚本

完整命令与操作说明见 [COMMAND_MANUAL.md](COMMAND_MANUAL.md)。

## 环境要求

- Windows 10/11
- Steam 版 Civilization VI 单人游戏
- Python 3.11 或更高版本
- 已在游戏配置中启用 Tuner
- 推荐 Windows Terminal 与支持中文的等宽字体

运行依赖声明在 `pyproject.toml` 中，无需单独维护 `requirements.txt`。

## 安装

在项目根目录执行：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
```

开发安装及可选测试依赖：

```powershell
python -m pip install -e ".[test]"
```

## 启用游戏连接

1. 退出 Civilization VI。
2. 找到游戏的 `AppOptions.txt`。常见位置如下：
   - `%USERPROFILE%\Documents\My Games\Sid Meier's Civilization VI\AppOptions.txt`
   - `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\AppOptions.txt`
3. 将 `EnableTuner` 设为 `1`。
4. 启动游戏并进入一局单人地图。
5. 关闭 FireTuner GUI、MCP 服务或其他占用通道的客户端。

可运行只读环境检查：

```powershell
.\scripts\check_environment.ps1
```

FireTuner 通常监听 `127.0.0.1:4318`，且同一时间只接受一个客户端。启用 Tuner 通常会禁用当前存档的 Steam 成就；本工具不会修改游戏配置或存档。

## 快速开始

启动持久 REPL：

```powershell
civ6
```

进入后先使用：

```text
help
help tree
status
turn todo
```

一个典型回合：

```text
status
turn todo
unit list
unit options <单位>
city production <城市>
research options
turn todo
turn end
```

尖括号表示必填参数，不要原样输入。己方单位和城市可使用完整 ID 或完整名称；名称含空格时加双引号。内部类型应从 `options` 或详情页复制。

常用命令示例：

```text
unit show 851973
unit move 851973 31 25
city production 开罗
city produce 开罗 unit UNIT_BUILDER
research set tech TECH_STEEL
trade options 2
trade propose 2 test give-resource=RESOURCE_SILK want-gpt=5
map city "New York" 3
great-work options 36
```

帮助命令无需连接游戏：

```powershell
civ6 help trade
civ6 help city production
civ6 help tree
```

## 输出与显示选项

全局选项写在命令前：

```powershell
civ6 --width 100 status
civ6 --ascii --color never map show 31 25 2
civ6 --color always help trade
```

- `--color auto|always|never`：控制颜色；同时遵守 `NO_COLOR`
- `--ascii`：使用 ASCII 表框与地图符号
- `--width <列数>`：固定输出宽度，最小 30
- `--host` / `--port`：指定 FireTuner 地址
- `--yes`：显式跳过写操作确认，适合已核对参数的脚本

列表使用紧凑表格，单个对象使用信息块，生产与交易等决策页会突出可执行选项和下一步命令。`status` 只提供回合总览；完整单位状态见 `unit list`。

## 地图与可见性

```text
map show <x> <y> [半径]
map unit <单位> [半径]
map city <城市> [半径]
map tile <x> <y> [半径]
```

地图按真正的六边形距离筛选，半径范围为 0–5。标记包括城市、单位、资源、区域、奇观、改良、河流、中心点、迷雾和未探索地块。窄终端会调整布局，但不会缩小请求范围。

未探索地块不显示地形；迷雾地块不显示实时单位、城市、归属、设施或产出；未解锁战略资源与不可见单位不会出现在输出中。

## 写操作与失败处理

写命令会先展示动作、对象和参数，只有明确确认后才发送一次。成功结果可以不附复查；异步操作或无法确认的结果会提示继续读取相关状态。

如果发送后超时或断线：

1. 不要直接重试。
2. 使用 `session reconnect` 重新连接。
3. 读取相关单位、城市、研究或待办，确认游戏中的实际状态。

工具不会自动代选回合阻塞项，不会自动保存或覆盖存档，也不会重放写请求。联机和热座模式不受支持。

## 开发与测试

运行离线测试：

```powershell
python -m unittest discover -s tests -q
```

可选的 `test` 依赖提供隔离的 Lua 5.1 契约测试；不安装时相应用例会跳过。连接游戏后的只读核验：

```powershell
python scripts/verify_readonly.py
```

`verify_readonly.py` 不发送动作，也不推进回合。

构建 wheel 与源码包：

```powershell
python -m pip install ".[release]"
python -m build
```

项目结构：

```text
src/civ6_cli/       CLI、渲染、游戏读取与 FireTuner 传输
src/civ6_cli/lua/   按领域划分的固定 Lua 模板
tests/              离线单元测试与契约测试
scripts/            环境检查、只读核验与视觉样例
COMMAND_MANUAL.md   完整命令手册
```

## 许可

本项目采用 MIT License，见 [LICENSE](LICENSE)。部分 Lua 构建器改编自 MIT 许可的 `civ6-mcp`，详情见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
