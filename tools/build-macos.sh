#!/usr/bin/env bash
# macOS build of Brawl Recompiled on Apple Silicon: extracts the disc, translates the game and compiles it.
#   bash tools/build-macos.sh [--game IMAGE | --disc-root DIRECTORY] [--jobs N] [--skip-translate]
# Each step logs to build-logs/. Output: wiicompiled/build/macos-arm64/WiiCompiled
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
wc=$root/wiicompiled
build=$wc/build/macos-arm64
project=$root/game/recomp-macos.yml
disc_root="$HOME/Library/Application Support/BrawlRecompiled/Disc"
image=
jobs=6
skip_translate=false
decomp_commit=d5154f72ff8a7fc85ae11ad0040d492edfa63123
nodtool_url=https://github.com/encounter/nod/releases/download/v2.0.0-alpha.10/nodtool-macos-arm64
nodtool_sha256=e23ca466999b720c55e6d29c9683fce8cc74451ba64ead2e543d50129f24528a

usage() {
    printf 'Usage: %s [--game IMAGE | --disc-root DIRECTORY] [--jobs N] [--skip-translate]\n' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --game) image=${2:?$(usage)}; shift 2 ;;
        --disc-root) disc_root=${2:?$(usage)}; shift 2 ;;
        --jobs) jobs=${2:?$(usage)}; shift 2 ;;
        --skip-translate) skip_translate=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 1 ;;
    esac
done

[[ $(uname -s) == Darwin && $(uname -m) == arm64 ]] || { echo 'Run this build natively on an Apple Silicon Mac.' >&2; exit 1; }
[[ $jobs =~ ^[1-9][0-9]*$ ]] || { echo '--jobs must be a positive integer.' >&2; exit 1; }
export PATH="$root/toolchain:$root/toolchain/dotnet:$PATH"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
for tool in cmake ninja uv dotnet git curl; do
    command -v "$tool" >/dev/null || { printf 'Required tool not found: %s\n' "$tool" >&2; exit 1; }
done
mkdir -p "$root/build-logs" "$root/toolchain"

step() {
    local name=$1 log
    shift
    log=$(mktemp "$root/build-logs/macos-$name-XXXXXX.log")
    printf '%s: %s\n' "$name" "$log"
    "$@" >"$log" 2>&1 || { printf '%s failed; see %s\n' "$name" "$log" >&2; return 1; }
}

if ! $skip_translate; then
    if [[ -n $image && ! -e $disc_root ]]; then
        nodtool=$root/toolchain/nodtool-macos-arm64
        if [[ ! -x $nodtool ]]; then
            curl -fL --retry 3 "$nodtool_url" -o "$nodtool"
            printf '%s  %s\n' "$nodtool_sha256" "$nodtool" | shasum -a 256 -c -
            chmod +x "$nodtool"
        fi
        mkdir -p "$(dirname "$disc_root")"
        step extract "$nodtool" extract "$image" "$disc_root"
    fi
    decomp=$root/extras/brawl-decomp
    if [[ ! -d $decomp/.git ]]; then
        step decomp-clone git clone --no-checkout https://github.com/doldecomp/brawl.git "$decomp"
    fi
    git -C "$decomp" checkout --quiet --detach "$decomp_commit"
    step prepare uv run "$root/tools/prepare-brawl-macos.py" --disc-root "$disc_root" --decomp "$decomp"
    step translator dotnet build "$wc/translator/src/Translator.Cli/Translator.Cli.csproj" -c Release
    translator=$wc/translator/src/Translator.Cli/bin/Release/net8.0/Translator.Cli.dll
    cd "$wc"
    step translate dotnet "$translator" translate-recursive 0x8000403C --project "$project" \
        --outdir generated/functions --output-metadata generated/base_translation_output.json \
        --production-source-bundle generated/base_translation_sources.bin --no-function-files \
        --no-state-free-abi --data-in-text projects/brawl/resident_data_ranges.txt --prune-stale --threads "$jobs"
    step data-init dotnet "$translator" generate-data-init --project "$project"
    step shards dotnet "$translator" emit-build-shards --project "$project" \
        --base-metadata generated/base_translation_output.json --base-functions-dir generated/functions \
        --native-source-dir runtime/src --out generated/build_shards --base-shards 600
fi

[[ -f $project && -f $wc/generated/build_shards/shards.cmake ]] || {
    echo 'Translation is missing; run without --skip-translate first.' >&2; exit 1
}
step configure cmake -S "$wc/runtime" -B "$build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=/usr/bin/clang -DCMAKE_CXX_COMPILER=/usr/bin/clang++ \
    -DCMAKE_ASM_COMPILER=/usr/bin/clang -DCMAKE_MAKE_PROGRAM="$(command -v ninja)" \
    -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=14.7 \
    -DCMAKE_C_FLAGS="-ffile-prefix-map=$root=." -DCMAKE_CXX_FLAGS="-ffile-prefix-map=$root=." \
    -DMKW_BUILD_PRODUCTS=ON -DMKW_BRAWL_DISC_REVISION=2 -DMKW_TRANSLATED_COMPILE_JOBS="$jobs" \
    -DAURORA_SDL3_PROVIDER=vendor -DAURORA_SDL3_LINKAGE=static -DAURORA_DAWN_LINKAGE=static -DBUILD_SHARED_LIBS=OFF
step compile cmake --build "$build" --target WiiCompiled --parallel "$jobs"
printf 'Built: %s/WiiCompiled\n' "$build"
