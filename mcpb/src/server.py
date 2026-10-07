"""Vstupní bod MCPB balíčku (Claude Desktop, runtime uv).

`uv run --directory <balíček> src/server.py` nainstaluje závislosti z pyproject.toml;
samotný balíček isir_mcp leží vedle (není instalován jako distribuce), proto ho přidáme na sys.path.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from isir_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()
