"""Persistent REPL and one-shot Civilization VI commands."""

from __future__ import annotations

import argparse
import sys

from .rendering import Display, status_line
from .repl import Terminal, run
from .transport import FireTunerConnection, FireTunerError
from .commands import offline_command


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="文明 VI 命令行终端：读取状态并执行经确认的回合操作")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--ascii", action="store_true", help="使用 ASCII 表框和地图符号")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--width", type=int, help="输出宽度（至少 30 列）")
    parser.add_argument("--yes", action="store_true", help="跳过写操作的交互确认；适合明确的脚本调用")
    parser.add_argument("command", nargs="?")
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
    if args.width is not None and args.width < 30:
        parser.error("--width 至少为 30")
    display = Display.terminal(ascii=args.ascii, color=args.color, width=args.width)
    if args.command is None:
        try:
            with FireTunerConnection(args.host, args.port) as connection:
                return run(connection, display=display, assume_yes=args.yes)
        except (FireTunerError, ValueError) as exc:
            print(status_line("error", f"查询失败：{exc}", display), file=sys.stderr)
            return 2
    words = [args.command] + args.arguments
    try:
        offline = offline_command(words)
    except ValueError as exc:
        print(status_line("error", f"命令失败：{exc}", display), file=sys.stderr)
        return 2
    if offline:
        try:
            Terminal(None, display).execute(words)
            return 0
        except ValueError as exc:
            print(status_line("error", f"查询失败：{exc}", display), file=sys.stderr)
            return 2
    try:
        with FireTunerConnection(args.host, args.port) as connection:
            Terminal(connection, display, assume_yes=args.yes).execute([args.command] + args.arguments)
    except (FireTunerError, ValueError) as exc:
        print(status_line("error", f"查询失败：{exc}", display), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
