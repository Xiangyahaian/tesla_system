# -*- coding: utf-8 -*-
"""Allow ``python -m app`` (same server as ``python run.py``)."""
from app.banner import print_banner
from app.api.server import main as serve


def main() -> None:
    print_banner()
    serve()


if __name__ == "__main__":
    main()
