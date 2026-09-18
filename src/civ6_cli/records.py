"""Lossless parsing of the fixed pipe-delimited query records."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Record:
    kind: str
    values: tuple[str, ...]
    fields: dict[str, str]


def parse_records(lines: list[str]) -> list[Record]:
    records = []
    for line in lines:
        parts = line.split("|")
        fields, values = {}, []
        for part in parts[1:]:
            key, separator, value = part.partition("=")
            if separator and re.fullmatch(r"[a-z_]+", key):
                fields[key] = value
            else:
                values.append(part)
        records.append(Record(parts[0], tuple(values), fields))
    return records


def number(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
