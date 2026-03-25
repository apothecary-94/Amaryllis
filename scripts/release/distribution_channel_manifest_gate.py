#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate distribution channel manifest templates for WinGet, Homebrew, and Flathub."
        )
    )
    parser.add_argument(
        "--root",
        default="distribution/channels",
        help="Channel manifest root path (default: distribution/channels).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report output path.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _check_file(
    *,
    path: Path,
    required_snippets: list[str],
    required_placeholders: list[str],
) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "ok": False,
            "error": "file_missing",
            "missing_snippets": required_snippets,
            "missing_placeholders": required_placeholders,
        }

    text = path.read_text(encoding="utf-8")
    missing_snippets = [item for item in required_snippets if item not in text]
    missing_placeholders = [item for item in required_placeholders if item not in text]
    ok = not missing_snippets and not missing_placeholders
    return {
        "path": str(path),
        "ok": ok,
        "error": "" if ok else "contract_mismatch",
        "missing_snippets": missing_snippets,
        "missing_placeholders": missing_placeholders,
    }


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    root = Path(str(args.root)).expanduser()
    if not root.is_absolute():
        root = repo_root / root
    root = root.resolve()

    checks: list[dict[str, Any]] = []
    checks.append(
        _check_file(
            path=root / "winget" / "Amaryllis.installer.yaml",
            required_snippets=[
                "PackageIdentifier: Amaryllis.Amaryllis",
                "Installers:",
                "InstallerUrl:",
                "InstallerSha256:",
            ],
            required_placeholders=[
                "{{VERSION}}",
                "{{WINDOWS_X64_URL}}",
                "{{WINDOWS_X64_SHA256}}",
            ],
        )
    )
    checks.append(
        _check_file(
            path=root / "winget" / "Amaryllis.locale.en-US.yaml",
            required_snippets=[
                "PackageIdentifier: Amaryllis.Amaryllis",
                "PackageLocale: en-US",
                "ShortDescription:",
            ],
            required_placeholders=["{{VERSION}}"],
        )
    )
    checks.append(
        _check_file(
            path=root / "homebrew" / "amaryllis.rb",
            required_snippets=[
                "class Amaryllis < Formula",
                "homepage",
                "bin.install \"amaryllis-runtime\"",
            ],
            required_placeholders=[
                "{{VERSION}}",
                "{{MACOS_ARM64_URL}}",
                "{{MACOS_ARM64_SHA256}}",
                "{{MACOS_X64_URL}}",
                "{{MACOS_X64_SHA256}}",
            ],
        )
    )
    checks.append(
        _check_file(
            path=root / "flathub" / "org.amaryllis.Amaryllis.yaml",
            required_snippets=[
                "app-id: org.amaryllis.Amaryllis",
                "runtime:",
                "modules:",
                "type: archive",
            ],
            required_placeholders=[
                "{{FLATHUB_ARCHIVE_URL}}",
                "{{FLATHUB_ARCHIVE_SHA256}}",
            ],
        )
    )

    failed = [item for item in checks if not bool(item.get("ok"))]
    report = {
        "generated_at": _utc_now_iso(),
        "suite": "distribution_channel_manifest_gate_v1",
        "summary": {
            "status": "pass" if not failed else "fail",
            "checks_total": len(checks),
            "checks_failed": len(failed),
            "root": str(root),
        },
        "checks": checks,
    }

    if args.output:
        output_path = Path(str(args.output)).expanduser()
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        _write_json(output_path.resolve(), report)

    if failed:
        print("[distribution-channel-manifest-gate] FAILED")
        for item in failed:
            print(f"- {item.get('path')}: {item.get('error')}")
            missing_snippets = item.get("missing_snippets", [])
            missing_placeholders = item.get("missing_placeholders", [])
            if missing_snippets:
                print(f"  missing snippets: {', '.join(str(x) for x in missing_snippets)}")
            if missing_placeholders:
                print(f"  missing placeholders: {', '.join(str(x) for x in missing_placeholders)}")
        return 1

    print(
        "[distribution-channel-manifest-gate] OK "
        f"checks={len(checks)} root={root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
