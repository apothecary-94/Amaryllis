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
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate rendered WinGet/Homebrew/Flathub channel manifests for publish-ready contract."
        )
    )
    parser.add_argument(
        "--render-report",
        default="artifacts/distribution-channels-rendered-report.json",
        help="Path to render_distribution_channel_manifests report JSON.",
    )
    parser.add_argument(
        "--expected-version",
        default="",
        help="Optional expected version to enforce across manifests.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report output path.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(repo_root: Path, raw: str) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _load_json_object(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _first_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        return ""
    value = match.group(1)
    return str(value).strip()


def _all_groups(pattern: str, text: str) -> list[str]:
    return [str(item).strip() for item in re.findall(pattern, text, flags=re.MULTILINE)]


def _is_https_url(value: str) -> bool:
    return str(value).strip().startswith("https://")


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _add_check(
    checks: list[dict[str, Any]],
    *,
    check_id: str,
    ok: bool,
    details: dict[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "ok": bool(ok),
            "details": details or {},
        }
    )


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    render_report_path = _resolve_path(repo_root, str(args.render_report))
    expected_version = str(args.expected_version or "").strip()

    checks: list[dict[str, Any]] = []

    if not render_report_path.exists():
        print(f"[distribution-channel-render-gate] missing render report: {render_report_path}", file=sys.stderr)
        return 2

    try:
        render_report = _load_json_object(render_report_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"[distribution-channel-render-gate] invalid render report: {render_report_path} error={exc}",
            file=sys.stderr,
        )
        return 2

    suite = str(render_report.get("suite") or "").strip()
    if suite != "render_distribution_channel_manifests_v1":
        print("[distribution-channel-render-gate] unexpected render report suite", file=sys.stderr)
        return 2

    summary = render_report.get("summary") if isinstance(render_report.get("summary"), dict) else {}
    files_raw = render_report.get("files")
    files = files_raw if isinstance(files_raw, list) else []
    file_map: dict[str, Path] = {}
    for entry in files:
        if not isinstance(entry, dict):
            continue
        output_raw = str(entry.get("output") or "").strip()
        if not output_raw:
            continue
        output_path = Path(output_raw).expanduser()
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        file_map[output_path.name] = output_path.resolve()

    expected_names = {
        "Amaryllis.installer.yaml",
        "Amaryllis.locale.en-US.yaml",
        "amaryllis.rb",
        "org.amaryllis.Amaryllis.yaml",
    }

    status_pass = str(summary.get("status") or "").strip().lower() == "pass"
    rendered_count = max(0, _safe_int(summary.get("rendered_count"), default=0))
    summary_errors = summary.get("errors") if isinstance(summary.get("errors"), list) else []
    _add_check(
        checks,
        check_id="render_report.summary_pass",
        ok=status_pass,
        details={"actual": str(summary.get("status") or "")},
    )
    _add_check(
        checks,
        check_id="render_report.rendered_count",
        ok=rendered_count == 4,
        details={"actual": rendered_count, "expected": 4},
    )
    _add_check(
        checks,
        check_id="render_report.errors_empty",
        ok=len(summary_errors) == 0,
        details={"actual": len(summary_errors), "errors": [str(item) for item in summary_errors]},
    )

    missing_names = sorted(name for name in expected_names if name not in file_map)
    _add_check(
        checks,
        check_id="render_report.required_outputs_present",
        ok=not missing_names,
        details={"missing": missing_names},
    )

    winget_installer = file_map.get("Amaryllis.installer.yaml")
    winget_locale = file_map.get("Amaryllis.locale.en-US.yaml")
    homebrew_formula = file_map.get("amaryllis.rb")
    flathub_manifest = file_map.get("org.amaryllis.Amaryllis.yaml")

    versions: list[str] = []

    if winget_installer and winget_installer.exists():
        text = _safe_text(winget_installer)
        unresolved = sorted(set(_PLACEHOLDER_RE.findall(text)))
        version = _first_group(r"^PackageVersion:\s*([^\s]+)\s*$", text)
        installer_url = _first_group(r"^\s*InstallerUrl:\s*([^\s]+)\s*$", text)
        installer_sha = _first_group(r"^\s*InstallerSha256:\s*([^\s]+)\s*$", text)
        versions.append(version)
        _add_check(
            checks,
            check_id="winget.installer.placeholders_resolved",
            ok=not unresolved,
            details={"unresolved": unresolved},
        )
        _add_check(
            checks,
            check_id="winget.installer.url_https",
            ok=_is_https_url(installer_url),
            details={"value": installer_url},
        )
        _add_check(
            checks,
            check_id="winget.installer.sha256_format",
            ok=bool(_SHA256_RE.match(installer_sha)),
            details={"value": installer_sha},
        )
        _add_check(
            checks,
            check_id="winget.installer.version_present",
            ok=bool(version),
            details={"value": version},
        )

    if winget_locale and winget_locale.exists():
        text = _safe_text(winget_locale)
        unresolved = sorted(set(_PLACEHOLDER_RE.findall(text)))
        locale_version = _first_group(r"^PackageVersion:\s*([^\s]+)\s*$", text)
        versions.append(locale_version)
        _add_check(
            checks,
            check_id="winget.locale.placeholders_resolved",
            ok=not unresolved,
            details={"unresolved": unresolved},
        )
        _add_check(
            checks,
            check_id="winget.locale.version_present",
            ok=bool(locale_version),
            details={"value": locale_version},
        )

    if homebrew_formula and homebrew_formula.exists():
        text = _safe_text(homebrew_formula)
        unresolved = sorted(set(_PLACEHOLDER_RE.findall(text)))
        formula_version = _first_group(r'^\s*version\s+"([^"]+)"\s*$', text)
        urls = _all_groups(r'^\s*url\s+"([^"]+)"\s*$', text)
        shas = _all_groups(r'^\s*sha256\s+"([^"]+)"\s*$', text)
        versions.append(formula_version)
        _add_check(
            checks,
            check_id="homebrew.placeholders_resolved",
            ok=not unresolved,
            details={"unresolved": unresolved},
        )
        _add_check(
            checks,
            check_id="homebrew.version_present",
            ok=bool(formula_version),
            details={"value": formula_version},
        )
        _add_check(
            checks,
            check_id="homebrew.urls_https",
            ok=bool(urls) and all(_is_https_url(item) for item in urls),
            details={"values": urls},
        )
        _add_check(
            checks,
            check_id="homebrew.sha256_format",
            ok=bool(shas) and all(bool(_SHA256_RE.match(item)) for item in shas),
            details={"values": shas},
        )

    if flathub_manifest and flathub_manifest.exists():
        text = _safe_text(flathub_manifest)
        unresolved = sorted(set(_PLACEHOLDER_RE.findall(text)))
        url = _first_group(r"^\s*url:\s*([^\s]+)\s*$", text)
        sha = _first_group(r"^\s*sha256:\s*([^\s]+)\s*$", text)
        _add_check(
            checks,
            check_id="flathub.placeholders_resolved",
            ok=not unresolved,
            details={"unresolved": unresolved},
        )
        _add_check(
            checks,
            check_id="flathub.url_https",
            ok=_is_https_url(url),
            details={"value": url},
        )
        _add_check(
            checks,
            check_id="flathub.sha256_format",
            ok=bool(_SHA256_RE.match(sha)),
            details={"value": sha},
        )

    normalized_versions = sorted({item for item in versions if item})
    _add_check(
        checks,
        check_id="manifest.version_consistent",
        ok=len(normalized_versions) == 1,
        details={"versions": normalized_versions},
    )

    resolved_version = normalized_versions[0] if len(normalized_versions) == 1 else ""
    _add_check(
        checks,
        check_id="manifest.version_semver_like",
        ok=bool(resolved_version and _SEMVER_RE.match(resolved_version)),
        details={"value": resolved_version},
    )

    if expected_version:
        _add_check(
            checks,
            check_id="manifest.expected_version_match",
            ok=resolved_version == expected_version,
            details={"actual": resolved_version, "expected": expected_version},
        )

    failed = [item for item in checks if not bool(item.get("ok"))]
    summary_payload = {
        "status": "pass" if not failed else "fail",
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "render_report": str(render_report_path),
    }
    report = {
        "generated_at": _utc_now_iso(),
        "suite": "distribution_channel_render_gate_v1",
        "summary": summary_payload,
        "checks": checks,
    }

    output_raw = str(args.output or "").strip()
    if output_raw:
        output_path = _resolve_path(repo_root, output_raw)
        _write_json(output_path, report)

    if failed:
        print("[distribution-channel-render-gate] FAILED")
        for item in failed:
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            print(f"- {item.get('id')}: {json.dumps(details, ensure_ascii=False)}")
        return 1

    print("[distribution-channel-render-gate] OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[distribution-channel-render-gate] interrupted", file=sys.stderr)
        raise SystemExit(130)
