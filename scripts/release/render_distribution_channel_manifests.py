#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render WinGet/Homebrew/Flathub channel manifest templates with "
            "release version, URLs, and SHA256 values."
        )
    )
    parser.add_argument("--root", default="distribution/channels", help="Template root directory.")
    parser.add_argument(
        "--output-dir",
        default="artifacts/distribution-channels-rendered",
        help="Output directory for rendered manifests.",
    )
    parser.add_argument("--version", required=True, help="Release version.")
    parser.add_argument("--windows-x64-url", required=True, help="WinGet x64 installer URL.")
    parser.add_argument("--windows-x64-sha256", required=True, help="WinGet x64 installer SHA256.")
    parser.add_argument("--macos-arm64-url", required=True, help="Homebrew arm64 archive URL.")
    parser.add_argument("--macos-arm64-sha256", required=True, help="Homebrew arm64 archive SHA256.")
    parser.add_argument("--macos-x64-url", required=True, help="Homebrew x64 archive URL.")
    parser.add_argument("--macos-x64-sha256", required=True, help="Homebrew x64 archive SHA256.")
    parser.add_argument("--flathub-archive-url", required=True, help="Flathub archive URL.")
    parser.add_argument("--flathub-archive-sha256", required=True, help="Flathub archive SHA256.")
    parser.add_argument("--report", default="", help="Optional JSON report path.")
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_path(repo_root: Path, raw: str) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _required_templates(root: Path) -> list[Path]:
    return [
        root / "winget" / "Amaryllis.installer.yaml",
        root / "winget" / "Amaryllis.locale.en-US.yaml",
        root / "homebrew" / "amaryllis.rb",
        root / "flathub" / "org.amaryllis.Amaryllis.yaml",
    ]


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    root = _resolve_path(repo_root, args.root)
    output_dir = _resolve_path(repo_root, args.output_dir)

    substitutions = {
        "{{VERSION}}": str(args.version),
        "{{WINDOWS_X64_URL}}": str(args.windows_x64_url),
        "{{WINDOWS_X64_SHA256}}": str(args.windows_x64_sha256),
        "{{MACOS_ARM64_URL}}": str(args.macos_arm64_url),
        "{{MACOS_ARM64_SHA256}}": str(args.macos_arm64_sha256),
        "{{MACOS_X64_URL}}": str(args.macos_x64_url),
        "{{MACOS_X64_SHA256}}": str(args.macos_x64_sha256),
        "{{FLATHUB_ARCHIVE_URL}}": str(args.flathub_archive_url),
        "{{FLATHUB_ARCHIVE_SHA256}}": str(args.flathub_archive_sha256),
    }

    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "suite": "render_distribution_channel_manifests_v1",
        "summary": {
            "status": "pass",
            "root": str(root),
            "output_dir": str(output_dir),
            "rendered_count": 0,
            "errors": [],
        },
        "files": [],
    }

    errors: list[str] = []
    rendered: list[dict[str, Any]] = []
    templates = _required_templates(root)
    for template in templates:
        if not template.exists():
            errors.append(f"missing_template:{template}")
            continue

        text = template.read_text(encoding="utf-8")
        output_text = text
        for token, value in substitutions.items():
            output_text = output_text.replace(token, value)

        unresolved = sorted(set(_PLACEHOLDER_RE.findall(output_text)))
        if unresolved:
            errors.append(f"unresolved_placeholders:{template}:{','.join(unresolved)}")
            continue

        relative = template.relative_to(root)
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output_text, encoding="utf-8")
        rendered.append(
            {
                "template": str(template),
                "output": str(target),
            }
        )

    report["files"] = rendered
    summary = report.get("summary")
    assert isinstance(summary, dict)
    summary["rendered_count"] = len(rendered)
    summary["errors"] = errors
    if errors:
        summary["status"] = "fail"

    if args.report:
        report_path = _resolve_path(repo_root, args.report)
        _write_json(report_path, report)

    if errors:
        print("[render-distribution-channel-manifests] FAILED")
        for item in errors:
            print(f"- {item}")
        return 1

    print(
        "[render-distribution-channel-manifests] OK "
        f"rendered={len(rendered)} output_dir={output_dir}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[render-distribution-channel-manifests] interrupted", file=sys.stderr)
        raise SystemExit(130)
