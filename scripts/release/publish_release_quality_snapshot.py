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
            "Publish release quality dashboard snapshot into a stable runtime path "
            "for Prometheus/Grafana export."
        )
    )
    parser.add_argument(
        "--snapshot-report",
        default="artifacts/release-quality-dashboard-final.json",
        help="Path to release quality dashboard snapshot JSON.",
    )
    parser.add_argument(
        "--trend-report",
        default="",
        help="Optional path to release quality trend JSON.",
    )
    parser.add_argument(
        "--install-root",
        default=str(Path.home() / ".local" / "share" / "amaryllis"),
        help="Install root for default publish location.",
    )
    parser.add_argument(
        "--output-snapshot",
        default="",
        help=(
            "Optional explicit output path for published snapshot. "
            "Defaults to <install-root>/observability/release-quality-dashboard-latest.json."
        ),
    )
    parser.add_argument(
        "--output-trend",
        default="",
        help=(
            "Optional explicit output path for published trend report. "
            "Defaults to <install-root>/observability/release-quality-dashboard-trend-latest.json "
            "when --trend-report is provided."
        ),
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
        print(f"[release-quality-publish] missing snapshot report: {snapshot_path}", file=sys.stderr)
        return 2

    try:
        snapshot = _load_json_object(snapshot_path)
    except Exception as exc:
        print(f"[release-quality-publish] invalid snapshot report: {snapshot_path} error={exc}", file=sys.stderr)
        return 2

    snapshot_suite = str(snapshot.get("suite") or "").strip()
    if snapshot_suite != "release_quality_dashboard_v1":
        print(
            (
                "[release-quality-publish] unexpected snapshot suite: "
                f"{snapshot_suite!r} (expected 'release_quality_dashboard_v1')"
            ),
            file=sys.stderr,
        )
        return 2

    trend: dict[str, Any] | None = None
    trend_path: Path | None = None
    trend_raw = str(args.trend_report or "").strip()
    if trend_raw:
        trend_path = _resolve_path(project_root, trend_raw)
        if not trend_path.exists():
            print(f"[release-quality-publish] missing trend report: {trend_path}", file=sys.stderr)
            return 2
        try:
            trend = _load_json_object(trend_path)
        except Exception as exc:
            print(f"[release-quality-publish] invalid trend report: {trend_path} error={exc}", file=sys.stderr)
            return 2
        trend_suite = str(trend.get("suite") or "").strip()
        if trend_suite != "release_quality_dashboard_trend_v1":
            print(
                (
                    "[release-quality-publish] unexpected trend suite: "
                    f"{trend_suite!r} (expected 'release_quality_dashboard_trend_v1')"
                ),
                file=sys.stderr,
            )
            return 2
    elif str(args.output_trend or "").strip():
        print("[release-quality-publish] --output-trend requires --trend-report", file=sys.stderr)
        return 2

    install_root = Path(str(args.install_root)).expanduser()
    output_snapshot_raw = str(args.output_snapshot or "").strip()
    if output_snapshot_raw:
        output_snapshot = _resolve_path(project_root, output_snapshot_raw)
    else:
        output_snapshot = install_root / "observability" / "release-quality-dashboard-latest.json"

    output_trend: Path | None = None
    if trend is not None:
        output_trend_raw = str(args.output_trend or "").strip()
        if output_trend_raw:
            output_trend = _resolve_path(project_root, output_trend_raw)
        else:
            output_trend = install_root / "observability" / "release-quality-dashboard-trend-latest.json"

    _write_json_atomically(output_snapshot, snapshot)
    print(f"[release-quality-publish] snapshot={output_snapshot}")
    if trend is not None and output_trend is not None:
        _write_json_atomically(output_trend, trend)
        print(f"[release-quality-publish] trend={output_trend}")

    print("[release-quality-publish] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
