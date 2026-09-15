"""Phase 2 pair universe, cointegration, and validity modules."""

from fx_lean_engine.pairs.cointegration import fit_pair
from fx_lean_engine.pairs.universe import generate_candidate_pairs
from fx_lean_engine.pairs.validity import PairValidityManager, evaluate_pair_validity

__all__ = ["generate_candidate_pairs", "fit_pair", "evaluate_pair_validity", "PairValidityManager"]
