#!/usr/bin/env python3
"""Generate the temporary, machine-configured BM-023A Kodi adapter package."""

from __future__ import annotations

import argparse
import ast
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Dict

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from tools.bm023a_adapter_support import ADAPTER_VERSION, DRIVER_ADDON_ID


TEMPLATE_ROOT = PROJECT / "tools" / "bm023a_adapter"
CONFIG_KEYS = (
    "MANIFEST_PATH",
    "ARTIFACT_ROOT",
    "CONFIGURATION_PATH",
    "OVERLAY_SOURCE",
    "DEVICE_PROFILE_ID",
    "EXPECTED_OVERLAY_ID",
)


def read_existing_adapter_config(source: Path) -> Dict[str, str]:
    """Carry forward only literal configuration from a prior adapter source."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename="<previous-adapter>")
    values: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in CONFIG_KEYS:
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, str) or not value:
            raise ValueError("previous adapter configuration is invalid")
        values[target.id] = value
    if set(values) != set(CONFIG_KEYS):
        raise ValueError("previous adapter configuration is incomplete")
    return values


def render_config(values: Dict[str, str]) -> str:
    if set(values) != set(CONFIG_KEYS) or any(not isinstance(v, str) or not v for v in values.values()):
        raise ValueError("adapter configuration is invalid")
    return "\n".join(
        f"{key} = {values[key]!r}" for key in CONFIG_KEYS
    ) + "\n"


def build_adapter(output_dir: Path, values: Dict[str, str]) -> Path:
    """Write versioned source files and a Kodi-installable ZIP under output_dir."""
    output_dir = Path(output_dir)
    package_root = output_dir / DRIVER_ADDON_ID
    package_root.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(TEMPLATE_ROOT / "default.py.in", package_root / "default.py")
    shutil.copyfile(
        PROJECT / "tools" / "bm023a_adapter_support.py",
        package_root / "adapter_support.py",
    )
    shutil.copyfile(TEMPLATE_ROOT / "addon.xml.in", package_root / "addon.xml")
    (package_root / "adapter_config.py").write_text(
        render_config(values), encoding="utf-8"
    )

    archive_path = output_dir / f"{DRIVER_ADDON_ID}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("addon.xml", "default.py", "adapter_config.py", "adapter_support.py"):
            archive.write(package_root / name, f"{DRIVER_ADDON_ID}/{name}")
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--reuse-config-from",
        type=Path,
        help="copy only the six allowlisted literal config fields from an old adapter source",
    )
    for key in CONFIG_KEYS:
        parser.add_argument("--" + key.lower().replace("_", "-"))
    args = parser.parse_args()

    if args.reuse_config_from:
        if any(getattr(args, key.lower()) is not None for key in CONFIG_KEYS):
            parser.error("use --reuse-config-from or explicit config options, not both")
        values = read_existing_adapter_config(args.reuse_config_from)
    else:
        values = {key: getattr(args, key.lower()) for key in CONFIG_KEYS}
        if any(not value for value in values.values()):
            parser.error("all six adapter configuration options are required")

    archive = build_adapter(args.output_dir, values)
    print(f"Generated {DRIVER_ADDON_ID} version {ADAPTER_VERSION}: {archive.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
