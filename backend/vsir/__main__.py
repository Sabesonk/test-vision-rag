"""``python -m vsir`` — the same entry point as the ``vsir`` console script."""
from __future__ import annotations

import sys

from vsir.cli import main

if __name__ == "__main__":
    sys.exit(main())
