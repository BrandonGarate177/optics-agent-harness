"""Classical triplet solve: zero the Seidel sums and the two colour terms, hold EFL at 50.

Seidel/paraxial evaluation is far cheaper than the ray-traced grader metric, so this
finds physically sound starting points across many glass choices before any polishing.
"""
from __future__ import annotations
import sys, warnings, numpy as np
warnings.filterwarnings("ignore")
sys.path.insert(0, "/Users/brandongarate/Documents/programming_projects/lens-harness")
from lens_tools import _build_optic
from opt_common import make_spec

def _f(x):
    return float(np.ravel(x)[0])

def paraxial_bfd(p, glasses):
    """Distance from the last glass surface to the paraxial image."""
    q = list(p); q[12] = 10.0
    lens = _build_optic(make_spec(q, glasses))
    lens.updater.update_paraxial()
    y, u = lens.paraxial.marginal_ray()
    y = np.ravel(y); u = np.ravel(u)
    # index -2 is the last real surface (index -1 is the image plane)
    return float(-y[-2] / u[-2])

def residuals(p, glasses, w=None):
    p = list(p)
    try:
        p[12] = paraxial_bfd(p, glasses)
        lens = _build_optic(make_spec(p, glasses))
        lens.updater.update_paraxial()
        S = np.ravel(np.asarray(lens.aberrations.seidels(), dtype=float))
        SI, SII, SIII, SIV, SV = S[:5]
        lch = _f(lens.aberrations.LchC())
        tch = _f(lens.aberrations.TchC())
        efl = _f(lens.paraxial.f2())
        r = np.array([SI, SII, SIII, SV, 0.30 * SIV, 20.0 * lch, 20.0 * tch, 0.5 * (efl - 50.0)])
        if not np.all(np.isfinite(r)):
            return np.full(8, 1e3)
        return r
    except Exception:
        return np.full(8, 1e3)

def solved_bfd(p, glasses):
    q = list(p); q[12] = paraxial_bfd(p, glasses); return q
