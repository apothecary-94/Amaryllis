# Distribution Channels (WinGet, Homebrew, Flathub)

## Goal

Keep mainstream discovery channels publish-ready for every release:

- WinGet (Windows),
- Homebrew (macOS),
- Flathub (Linux).

## Manifest Templates

Template files live in:

- `distribution/channels/winget/Amaryllis.installer.yaml`
- `distribution/channels/winget/Amaryllis.locale.en-US.yaml`
- `distribution/channels/homebrew/amaryllis.rb`
- `distribution/channels/flathub/org.amaryllis.Amaryllis.yaml`

Placeholders are release-time values:

- `{{VERSION}}`
- `{{WINDOWS_X64_URL}}`, `{{WINDOWS_X64_SHA256}}`
- `{{MACOS_ARM64_URL}}`, `{{MACOS_ARM64_SHA256}}`
- `{{MACOS_X64_URL}}`, `{{MACOS_X64_SHA256}}`
- `{{FLATHUB_ARCHIVE_URL}}`, `{{FLATHUB_ARCHIVE_SHA256}}`

## CI Gate

Validate channel manifest readiness:

```bash
python scripts/release/distribution_channel_manifest_gate.py \
  --output artifacts/distribution-channel-manifest-report.json
```

The gate fails when:

- a required channel manifest file is missing,
- required contract snippets are missing,
- release placeholders are missing.

## Rendering for Release

Render templates with concrete release metadata:

```bash
python scripts/release/render_distribution_channel_manifests.py \
  --version "1.2.3" \
  --windows-x64-url "https://example.org/amaryllis-windows-x64.zip" \
  --windows-x64-sha256 "<sha256>" \
  --macos-arm64-url "https://example.org/amaryllis-macos-arm64.tar.gz" \
  --macos-arm64-sha256 "<sha256>" \
  --macos-x64-url "https://example.org/amaryllis-macos-x64.tar.gz" \
  --macos-x64-sha256 "<sha256>" \
  --flathub-archive-url "https://example.org/amaryllis-flatpak.tar.gz" \
  --flathub-archive-sha256 "<sha256>" \
  --output-dir "artifacts/distribution-channels-rendered" \
  --report "artifacts/distribution-channels-rendered-report.json"
```
