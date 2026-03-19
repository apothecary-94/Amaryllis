#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable


_COMPARATOR_PATTERN = re.compile(r"(===|==|~=|!=|<=|>=|<|>)")


@dataclass(frozen=True)
class RequirementEntry:
    key: str
    raw: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check drift between requirements.txt and requirements.lock")
    parser.add_argument("--requirements", default="requirements.txt", help="Path to source requirements file")
    parser.add_argument("--lock", default="requirements.lock", help="Path to lock requirements file")
    parser.add_argument(
        "--allow-extra-lock-entries",
        action="store_true",
        help="Allow lock entries that are not present in the source requirements file",
    )
    return parser.parse_args()


def _normalize_key(requirement_spec: str) -> str:
    base = requirement_spec.strip()
    if not base:
        return ""
    token = _COMPARATOR_PATTERN.split(base, maxsplit=1)[0].strip().lower()
    return token


def _iter_requirement_lines(path: Path) -> Iterable[str]:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # strip inline comments
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if line:
            yield line


def _parse_entries(path: Path, *, require_pinned: bool) -> tuple[dict[str, RequirementEntry], list[str]]:
    entries: dict[str, RequirementEntry] = {}
    errors: list[str] = []
    for line in _iter_requirement_lines(path):
        req_part = line.split(";", 1)[0].strip()
        if require_pinned and "==" not in req_part:
            errors.append(f"{path}: lock entry must use == pin: {line}")
            continue

        key = _normalize_key(req_part)
        if not key:
            errors.append(f"{path}: could not parse requirement line: {line}")
            continue
        if key in entries:
            errors.append(f"{path}: duplicate requirement key '{key}'")
            continue
        entries[key] = RequirementEntry(key=key, raw=line)
    return entries, errors


def main() -> int:
    args = _parse_args()
    requirements_path = Path(args.requirements)
    lock_path = Path(args.lock)

    if not requirements_path.exists():
        print(f"requirements file not found: {requirements_path}", file=sys.stderr)
        return 2
    if not lock_path.exists():
        print(f"lock file not found: {lock_path}", file=sys.stderr)
        return 2

    req_entries, req_errors = _parse_entries(requirements_path, require_pinned=False)
    lock_entries, lock_errors = _parse_entries(lock_path, require_pinned=True)

    all_errors = [*req_errors, *lock_errors]

    missing = sorted(set(req_entries.keys()) - set(lock_entries.keys()))
    extra = sorted(set(lock_entries.keys()) - set(req_entries.keys()))

    for key in missing:
        all_errors.append(
            f"missing in lock: {key} (source='{req_entries[key].raw}')"
        )

    if not args.allow_extra_lock_entries:
        for key in extra:
            all_errors.append(
                f"extra in lock: {key} (lock='{lock_entries[key].raw}')"
            )

    if all_errors:
        print("dependency drift check failed:", file=sys.stderr)
        for item in all_errors:
            print(f"- {item}", file=sys.stderr)
        return 1

    print(
        "dependency drift check OK: "
        f"{len(req_entries)} source entries, {len(lock_entries)} lock entries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
