"""QuantConnect cloud entrypoint for fx-lean-engine."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_lean_engine.lean.algorithm import FxLeanEngineAlgorithm


class main(FxLeanEngineAlgorithm):
    """Default QC cloud class name."""

