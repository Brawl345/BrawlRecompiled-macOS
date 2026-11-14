#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["click", "rich", "pyyaml"]
# ///

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console

console = Console()


@click.command()
@click.option("--disc-root", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--decomp", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
def main(disc_root: Path, decomp: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    wc = root / "wiicompiled"
    disc_root = disc_root.resolve()
    decomp = decomp.resolve()
    boot = disc_root / "sys/boot.bin"
    if not boot.is_file():
        raise click.ClickException("The extracted disc folder must contain sys/boot.bin and files/.")
    header = boot.read_bytes()[:8]
    if len(header) != 8 or header[:6] != b"RSBE01" or header[7] != 2:
        raise click.ClickException("The macOS build requires a clean USA RSBE01 revision 2 disc.")
    config_dir = decomp / "config/RSBE01_02"
    config = yaml.safe_load((config_dir / "config.yml").read_text())
    inputs = [(config["object"], config["hash"])]
    inputs.extend((module["object"], module["hash"]) for module in config["modules"])
    for name, expected in inputs:
        path = disc_root / name
        if not path.is_file() or hashlib.sha1(path.read_bytes()).hexdigest() != expected:
            raise click.ClickException(f"Disc file does not match clean RSBE01 revision 2: {name}")
    console.print(f"Verified main.dol and {len(inputs) - 1} modules.")
    game = root / "game"
    game.mkdir(exist_ok=True)
    shutil.copy2(disc_root / "sys/main.dol", game / "main.dol")
    subprocess.run(
        [
            sys.executable,
            str(wc / "projects/brawl/tools/build_modules.py"),
            str(disc_root / "files/module"),
            str(config_dir),
            str(game / "brawl_modules.rel"),
            str(wc),
            str(game / "main.dol"),
        ],
        check=True,
    )
    manifest = yaml.safe_load((wc / "projects/brawl/recomp.yml").read_text())
    manifest["workspace_root"] = str(wc)
    manifest["inputs"]["dol"]["sha256"] = hashlib.sha256((game / "main_translate.dol").read_bytes()).hexdigest()
    (game / "recomp-macos.yml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    console.print("Prepared game/recomp-macos.yml for USA revision 2.")


if __name__ == "__main__":
    main()
