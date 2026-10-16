"""Microsoft Foundry code-deploy entry point for the PMO Agent."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fde_pmo_agent.hosting.foundry import main


if __name__ == "__main__":
    main()
