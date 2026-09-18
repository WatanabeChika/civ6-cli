"""Refresh the generated command reference in COMMAND_MANUAL.md."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from civ6_cli.commands import manual_command_tables  # noqa: E402


START = "<!-- BEGIN GENERATED COMMAND REFERENCE -->"
END = "<!-- END GENERATED COMMAND REFERENCE -->"


def main() -> None:
    manual_path = ROOT / "COMMAND_MANUAL.md"
    manual = manual_path.read_text(encoding="utf-8")
    before, marker, remainder = manual.partition(START)
    generated, end_marker, after = remainder.partition(END)
    if not marker or not end_marker:
        raise RuntimeError("COMMAND_MANUAL.md 缺少命令参考标记")
    content = (
        before.rstrip()
        + "\n\n"
        + START
        + "\n\n"
        + manual_command_tables()
        + "\n\n"
        + END
        + "\n\n"
        + after.lstrip()
    )
    manual_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
