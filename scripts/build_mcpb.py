"""Sestaví balíček isir-mcp-<verze>.mcpb pro Claude Desktop.

Použití:  python scripts/build_mcpb.py [výstupní_adresář]
Výsledek: dist/isir-mcp-<verze>.mcpb

Postup: do dočasné složky zkopíruje manifest, ikonu, vstupní skript, balíček isir_mcp a
pyproject.toml (jen runtime část), sjednotí verzi s pyproject.toml a zabalí buď oficiálním
CLI `mcpb pack` (npx @anthropic-ai/mcpb), nebo – není-li k dispozici – jako ZIP se stejnou
strukturou.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCPB_DIR = ROOT / "mcpb"


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    return data["project"]["version"]


def runtime_pyproject(version: str) -> str:
    """pyproject pro uv: jen název, verze, závislosti; balíček se neinstaluje (package = false)."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    deps = "\n".join(f'    "{d}",' for d in data["project"]["dependencies"])
    return (
        "[project]\n"
        'name = "isir-mcp-bundle"\n'
        f'version = "{version}"\n'
        'description = "isir-mcp (MCPB bundle)"\n'
        f'requires-python = "{data["project"]["requires-python"]}"\n'
        f"dependencies = [\n{deps}\n]\n\n"
        "[tool.uv]\n"
        "package = false\n"
    )


def stage(dst: Path, version: str) -> None:
    dst.mkdir(parents=True)
    manifest = json.loads((MCPB_DIR / "manifest.json").read_text("utf-8"))
    manifest["version"] = version
    (dst / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copy(MCPB_DIR / "icon.png", dst / "icon.png")
    shutil.copytree(MCPB_DIR / "src", dst / "src")
    shutil.copytree(ROOT / "isir_mcp", dst / "isir_mcp", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dst / "pyproject.toml").write_text(runtime_pyproject(version), "utf-8")
    shutil.copy(ROOT / "LICENSE", dst / "LICENSE")
    shutil.copy(ROOT / "README.md", dst / "README.md")
    (dst / ".mcpbignore").write_text(".venv/\n__pycache__/\n*.pyc\nuv.lock\n", "utf-8")


def pack(src: Path, out_file: Path) -> str:
    out_file = out_file.resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        out_file.unlink()
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        try:
            subprocess.run([npx, "-y", "@anthropic-ai/mcpb", "validate", str(src / "manifest.json")],
                           check=True, cwd=src)
            subprocess.run([npx, "-y", "@anthropic-ai/mcpb", "pack", str(src), str(out_file)],
                           check=True, cwd=src)
            return "mcpb"
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"[build_mcpb] mcpb CLI selhalo ({e}); použiji ZIP.", file=sys.stderr)
    with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())
    return "zip"


def main() -> None:
    out_dir = (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist").resolve()
    version = project_version()
    out_file = out_dir / f"isir-mcp-{version}.mcpb"
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "isir-mcp"
        stage(staged, version)
        how = pack(staged, out_file)
    print(f"[build_mcpb] {out_file} ({out_file.stat().st_size / 1024:.0f} kB, {how})")


if __name__ == "__main__":
    main()
