#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish adoption KPI snapshot into a stable runtime path "
            "for release/nightly observability export."
        )
    )
    parser.add_argument(
        "--snapshot-report",
        default="artifacts/adoption-kpi-snapshot-final.json",
        help="Path to adoption KPI snapshot JSON.",
    )
    parser.add_argument(
        "--channel",
        default="release",
        choices=("release", "nightly"),
        help="Publish channel used for default output filename.",
    )
    parser.add_argument(
        "--expect-release-channel",
        default="auto",
        help=(
            "Optional strict check for snapshot release.release_channel. "
            "Use 'auto' to skip strict check."
        ),
    )
    parser.add_argument(
        "--install-root",
        default=str(Path.home() / ".local" / "share" / "amaryllis"),
        help="Install root for default publish location.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional explicit output path for published snapshot.",
    )
    return parser.parse_args()


def _resolve_path(project_root: Path, raw_path: str) -> Path:
    path = Path(str(raw_path).strip()).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be object: {path}")
    return payload


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[2]

    snapshot_path = _resolve_path(project_root, str(args.snapshot_report))
    if not snapshot_path.exists():
        print(f"[adoption-kpi-publish] missing snapshot report: {snapshot_path}", file=sys.stderr)
        return 2

    try:
        snapshot = _load_json_object(snapshot_path)
    except Exception as exc:
        print(f"[adoption-kpi-publish] invalid snapshot report: {snapshot_path} error={exc}", file=sys.stderr)
        return 2

    suite = str(snapshot.get("suite") or "").strip()
    if suite != "adoption_kpi_snapshot_v1":
        print(
            (
                "[adoption-kpi-publish] unexpected snapshot suite: "
                f"{suite!r} (expected 'adoption_kpi_snapshot_v1')"
            ),
            file=sys.stderr,
        )
        return 2

    expected_release_channel = str(args.expect_release_channel or "auto").strip().lower() or "auto"
    if expected_release_channel != "auto":
        snapshot_release = snapshot.get("release") if isinstance(snapshot.get("release"), dict) else {}
        release_channel = str(snapshot_release.get("release_channel") or "").strip().lower()
        if release_channel != expected_release_channel:
            print(
                (
                    "[adoption-kpi-publish] release channel mismatch: "
                    f"snapshot={release_channel!r} expected={expected_release_channel!r}"
                ),
                file=sys.stderr,
            )
            return 2

    output_raw = str(args.output or "").strip()
    if output_raw:
        output_path = _resolve_path(project_root, output_raw)
    else:
        install_root = Path(str(args.install_root)).expanduser()
        if str(args.channel) == "nightly":
            output_path = install_root / "observability" / "nightly-adoption-kpi-snapshot-latest.json"
        else:
            output_path = install_root / "observability" / "adoption-kpi-snapshot-latest.json"

    _write_json_atomically(output_path, snapshot)
    print(f"[adoption-kpi-publish] snapshot={output_path}")
    print("[adoption-kpi-publish] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
