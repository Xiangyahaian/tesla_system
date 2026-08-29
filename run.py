# -*- coding: utf-8 -*-
"""Project entrypoint: ``python run.py``."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.api.server import main

if __name__ == "__main__":
    main()
