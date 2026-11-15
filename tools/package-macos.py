#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["click", "rich"]
# ///

import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import click
from rich.console import Console

console = Console()
root = Path(__file__).resolve().parent.parent
build = root / "wiicompiled/build/macos-arm64"
dist = root / "dist"


def run(*arguments: str | Path) -> None:
    subprocess.run([str(a) for a in arguments], check=True)


def rpaths(binary: Path) -> list[str]:
    output = subprocess.run(["otool", "-l", str(binary)], check=True, capture_output=True, text=True).stdout
    return re.findall(r"cmd LC_RPATH\n\s*cmdsize \d+\n\s*path (.+) \(offset", output)


def copy_licenses(destination: Path) -> None:
    destination.mkdir()
    for path in (
        root / "wiicompiled/LICENSE",
        root / "wiicompiled/THIRD-PARTY-NOTICES.md",
        root / "tools/CREDITS.txt",
        root / "tools/licenses/Dawn-LICENSE.txt",
        build / "_deps/freetype-src/docs/FTL.TXT",
    ):
        shutil.copy2(path, destination / path.name)
    directories = [
        root / "wiicompiled/aurora-main",
        *(root / "wiicompiled/runtime/third_party").iterdir(),
        *build.glob("_deps/*-src"),
    ]
    for directory in sorted(directories):
        for path in directory.glob("*"):
            if path.is_file() and path.name.lower().startswith(("license", "copying", "notice")):
                shutil.copy2(path, destination / f"{directory.name}-{path.name}")


def make_icon(source: Path, destination: Path, stage: Path) -> None:
    iconset = stage / "Brawl.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            pixels = str(size * scale)
            run("sips", "-z", pixels, pixels, source, "--out", iconset / f"icon_{size}x{size}{suffix}.png")
    run("iconutil", "-c", "icns", iconset, "-o", destination)


@click.command(help="Bundle the macOS build as dist/Brawl Recompiled.app.")
@click.option("--archive", is_flag=True, help="Also create a ZIP for distribution.")
def main(archive: bool) -> None:
    project = (root / "launcher/BrawlRecompiled.Launcher.csproj").read_text()
    if not (match := re.search(r"<Version>([^<]+)</Version>", project)):
        raise click.ClickException("No <Version> in launcher/BrawlRecompiled.Launcher.csproj")
    version = match.group(1)
    app = dist / "Brawl Recompiled.app"
    shutil.rmtree(app, ignore_errors=True)
    dist.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        run(
            "bash", root / "wiicompiled/Launcher/macos/publish-app.command",
            "--build-dir", build, "--product", "WiiCompiled", "--output-dir", stage,
            "--architecture", "arm64", "--minimum-system-version", "14.7",
        )  # fmt: skip
        shutil.move(stage / "WiiCompiled.app", app)
        make_icon(root / "launcher/art/smash_ball.png", app / "Contents/Resources/Brawl.icns", stage)

    resources = app / "Contents/Resources"
    executable_dir = app / "Contents/MacOS"
    (resources / "startup").mkdir()
    shutil.copy2(root / "launcher/art/smash_ball.png", resources / "startup")
    shutil.copy2(root / "tools/cheats-RSBE01.ini", resources / "default-cheats.ini")
    # Data files in Contents/MacOS would be sealed as code and lose their signature in a ZIP.
    (executable_dir / "startup").symlink_to("../Resources/startup")
    (executable_dir / "default-cheats.ini").symlink_to("../Resources/default-cheats.ini")
    copy_licenses(resources / "licenses")

    info = app / "Contents/Info.plist"
    metadata = plistlib.loads(info.read_bytes())
    metadata.update(
        CFBundleIdentifier="de.nyanya.BrawlRecompiled",
        CFBundleName="Brawl Recompiled",
        CFBundleDisplayName="Brawl Recompiled",
        CFBundleShortVersionString=version,
        CFBundleVersion=version,
        CFBundleIconFile="Brawl.icns",
        NSQuitAlwaysKeepsWindows=False,
        LSApplicationCategoryType="public.app-category.action-games",
        LSSupportsGameMode=True,
        GCSupportsGameMode=True,
    )
    info.write_bytes(plistlib.dumps(metadata))

    for binary in (executable_dir / "WiiCompiled", *(app / "Contents/Frameworks").glob("*.dylib")):
        for rpath in rpaths(binary):
            run("install_name_tool", "-delete_rpath", rpath, binary)
        run("strip", "-S", "-x", binary)
    run("xattr", "-cr", app)
    run("codesign", "--force", "--deep", "--sign", "-", app)
    console.print(f"App: {app}")

    if archive:
        zip_path = dist / f"BrawlRecompiled-{version}-macos-arm64.zip"
        zip_path.unlink(missing_ok=True)
        run("ditto", "-c", "-k", "--norsrc", "--noextattr", "--keepParent", app, zip_path)
        with tempfile.TemporaryDirectory() as unpacked:
            run("ditto", "-x", "-k", zip_path, unpacked)
            run("codesign", "--verify", "--deep", "--strict", Path(unpacked) / app.name)
        console.print(f"Archive: {zip_path}")


if __name__ == "__main__":
    main()
