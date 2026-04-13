#!/usr/bin/env python3
"""Sync the canonical version from [ProjectName]/config.h to all satellite files.

Reads PLUG_VERSION_STR and PLUG_VERSION_HEX from config.h and propagates
them to plist files, the Inno Setup installer script, and CMakeLists.txt.

Usage:
    python3 scripts/sync-version.py <ProjectName>          # apply updates
    python3 scripts/sync-version.py <ProjectName> --check  # exit 1 if anything is out of sync
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_config_version(config_h: Path) -> str:
    """Extract PLUG_VERSION_STR from config.h."""
    text = config_h.read_text()
    m = re.search(r'#define\s+PLUG_VERSION_STR\s+"([^"]+)"', text)
    if not m:
        sys.exit(f"ERROR: PLUG_VERSION_STR not found in {config_h}")
    return m.group(1)


def expected_hex(version: str) -> str:
    """Convert 'M.N.P' to '0xMMMMNNPP' hex string matching iPlug2 convention."""
    parts = version.split(".")
    if len(parts) != 3:
        sys.exit(f"ERROR: version '{version}' is not in M.N.P format")
    major, minor, patch = (int(p) for p in parts)
    val = (major << 16) | (minor << 8) | patch
    return f"0x{val:08x}"


def check_config_hex(version: str, config_h: Path) -> None:
    """Verify PLUG_VERSION_HEX matches PLUG_VERSION_STR.

    A mismatch is a hard error because this script does not rewrite config.h,
    so continuing would leave the canonical source of truth out of sync while
    other satellite files may have been updated.
    """
    text = config_h.read_text()
    m = re.search(r"#define\s+PLUG_VERSION_HEX\s+(0x[0-9a-fA-F]+)", text)
    if not m:
        sys.exit(f"ERROR: {config_h}: PLUG_VERSION_HEX not found")
    actual = m.group(1).lower()
    want = expected_hex(version)
    if actual != want:
        sys.exit(f"ERROR: {config_h}: PLUG_VERSION_HEX is {actual}, expected {want}")


def sync_plists(version: str, check_only: bool, plist_dir: Path) -> list[str]:
    """Update CFBundleShortVersionString and CFBundleVersion in all plists."""
    diffs = []
    if not plist_dir.exists():
        return []
    plist_files = sorted(plist_dir.glob("*.plist"))
    # Regex matches the <string>...</string> line after a version key
    ver_pattern = re.compile(
        r"(<key>CFBundle(?:ShortVersionString|Version)</key>\s*\n\s*<string>)"
        r"([^<]+)"
        r"(</string>)"
    )
    for plist in plist_files:
        text = plist.read_text()
        matches = ver_pattern.findall(text)
        for _prefix, val, _suffix in matches:
            if val.strip() != version:
                rel = plist.relative_to(REPO_ROOT)
                diffs.append(f"{rel}: '{val.strip()}' != '{version}'")
        if not check_only:
            new_text = ver_pattern.sub(rf"\g<1>{version}\3", text)
            if new_text != text:
                plist.write_text(new_text)
    return diffs


def sync_iss(version: str, check_only: bool, iss_file: Path) -> list[str]:
    """Update AppVersion and VersionInfoVersion in .iss file."""
    if not iss_file.exists():
        return []
    diffs = []
    text = iss_file.read_text()
    for key in ("AppVersion", "VersionInfoVersion"):
        pattern = re.compile(rf"^({key}=)(.+)$", re.MULTILINE)
        m = pattern.search(text)
        if m and m.group(2) != version:
            rel = iss_file.relative_to(REPO_ROOT)
            diffs.append(f"{rel}: {key}={m.group(2)}, expected {version}")
            if not check_only:
                text = pattern.sub(rf"\g<1>{version}", text)
    if not check_only:
        iss_file.write_text(text)
    return diffs


def sync_cmake(version: str, check_only: bool, cmakelists: Path, project_name: str) -> list[str]:
    """Update project(Name VERSION x.y.z) in CMakeLists.txt."""
    if not cmakelists.exists():
        return []
    diffs = []
    text = cmakelists.read_text()
    pattern = re.compile(rf"(project\s*\(\s*{re.escape(project_name)}\s+VERSION\s+)([\d.]+)(\s*\))")
    m = pattern.search(text)
    if m and m.group(2) != version:
        rel = cmakelists.relative_to(REPO_ROOT)
        diffs.append(f"{rel}: VERSION {m.group(2)}, expected {version}")
        if not check_only:
            text = pattern.sub(rf"\g<1>{version}\3", text)
            cmakelists.write_text(text)
    return diffs


def main():
    parser = argparse.ArgumentParser(description="Sync version from config.h")
    parser.add_argument("project", help="Name of the project (folder name)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode: exit 1 if files are out of sync, don't modify anything",
    )
    args = parser.parse_args()

    project_dir = REPO_ROOT / args.project
    config_h = project_dir / "config.h"
    cmakelists = project_dir / "CMakeLists.txt"
    iss_file = project_dir / "installer" / f"{args.project}.iss"
    plist_dir = project_dir / "resources"

    if not config_h.exists():
        sys.exit(f"ERROR: {config_h} not found. Is '{args.project}' the correct project name?")

    version = read_config_version(config_h)
    print(f"Project: {args.project}")
    print(f"Canonical version: {version}")

    check_config_hex(version, config_h)

    all_diffs: list[str] = []
    all_diffs.extend(sync_plists(version, args.check, plist_dir))
    all_diffs.extend(sync_iss(version, args.check, iss_file))
    all_diffs.extend(sync_cmake(version, args.check, cmakelists, args.project))

    if all_diffs:
        label = "Out of sync" if args.check else "Fixed"
        for d in all_diffs:
            print(f"  {label}: {d}")
        if args.check:
            print(
                f"\n{len(all_diffs)} file(s) out of sync. Run: python3 scripts/sync-version.py {args.project}"
            )
            sys.exit(1)
        else:
            print(f"\nUpdated {len(all_diffs)} value(s).")
    else:
        print("All files in sync.")


if __name__ == "__main__":
    main()
