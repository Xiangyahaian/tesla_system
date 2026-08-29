# -*- coding: utf-8 -*-
"""Cabin Runtime entrypoint — ``python run.py``."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.banner import print_banner
    from app.api.server import main as serve

    print_banner()
    serve()


if __name__ == "__main__":
    main()
