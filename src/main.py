#!/usr/bin/env python3
"""Launch the synth rack:  python src/main.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthrack.app import main

if __name__ == "__main__":
    sys.exit(main())
