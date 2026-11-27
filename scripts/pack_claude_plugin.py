#!/usr/bin/env python3
"""Package codex-bridge as a clean Claude Desktop .plugin/.zip archive."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent

PLUGIN_FILES: tuple[str, ...] = (
    ".claude-plugin/plugin.json",
    ".mcp.json",
    "server/codex_mcp_server.py",
    "skills/codex-delegate/SKILL.md",
    "skills/codex-delegate/references/playbook.md",
    "LICENSE",
)


def build_plugin_archive(output_path: Path) -> Path:
    """Create a ZIP-based .plugin archive containing only Claude-compatible plugin files."""
    missing = [rel for rel in PLUGIN_FILES if not (REPO_ROOT / rel).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing required plugin file(s): {', '.join(missing)}")

    resolved_out = (output_path if output_path.is_absolute() else (REPO_ROOT / output_path)).resolve()
    source_paths = {(REPO_ROOT / rel).resolve() for rel in PLUGIN_FILES}
    if resolved_out in source_paths or (
        resolved_out.exists() and any(os.path.samefile(resolved_out, src) for src in source_paths)
    ):
        raise ValueError(f"Refusing to overwrite whitelisted plugin source file: {resolved_out}")
    resolved_out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(resolved_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in PLUGIN_FILES:
            zf.write(REPO_ROOT / rel, arcname=rel)

    return resolved_out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a clean Claude Desktop .plugin archive at dist/codex-bridge.plugin."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=REPO_ROOT / "dist" / "codex-bridge.plugin",
        help="Output .plugin or .zip path (default: dist/codex-bridge.plugin)",
    )
    args = parser.parse_args(argv)

    out_path = build_plugin_archive(args.output)
    print(f"Built {out_path}")
    with zipfile.ZipFile(out_path, "r") as zf:
        for info in zf.infolist():
            print(f"  {info.filename}\t{info.file_size}B\t({info.compress_size}B compressed)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
