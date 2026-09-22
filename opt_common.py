import sys, warnings, numpy as np
warnings.filterwarnings("ignore")
sys.path.insert(0, "/Users/brandongarate/Documents/programming_projects/lens-harness")
from lens_tools import _build_optic, _metrics, _manufacturability

EPD = 11.1111
FIELDS = [0.0, 10.0, 20.0]
WLS = [0.486, 0.587, 0.656]

# p = [r1,r2,r3,r4,r5,r6, t1,t2,t3,t4a,t4b,t5,t6]
# t4a = gap from element-2 rear to stop, t4b = gap from stop to element-3 front
LO = [ 10.0, -8000., -300.,   8.0,   12.0, -400., 2.5, 0.6, 1.6, 0.55, 0.55, 2.5, 20.0]
HI = [150.0,  -18.0,   -7.0, 300.0,  8000.,  -7.0,10.0,16.0, 7.0,14.0, 14.0,10.0, 55.0]

def make_spec(p, glasses, wls=None, fields=None):
    r1,r2,r3,r4,r5,r6, t1,t2,t3,t4a,t4b,t5,t6 = p
    g1,g2,g3 = glasses
    return dict(surfaces=[
        dict(radius=None, thickness=None, material=None, is_stop=False),
        dict(radius=r1, thickness=t1, material=g1, is_stop=False),
        dict(radius=r2, thickness=t2, material=None, is_stop=False),
        dict(radius=r3, thickness=t3, material=g2, is_stop=False),
        dict(radius=r4, thickness=t4a, material=None, is_stop=False),
        dict(radius=None, thickness=t4b, material=None, is_stop=True),
        dict(radius=r5, thickness=t5, material=g3, is_stop=False),
        dict(radius=r6, thickness=t6, material=None, is_stop=False),
        dict(radius=None, thickness=0.0, material=None, is_stop=False),
    ], epd=EPD, fields_deg=fields or FIELDS, wavelengths_um=wls or WLS)

def score(p, glasses, report=False):
    try:
        lens = _build_optic(make_spec(p, glasses))
        m = _metrics(lens)
        w = m["rms_wavefront_waves_per_field"]
        if not all(isinstance(v, (int, float)) for v in w):
            return 1e6
        w = np.asarray(w, dtype=float)
        if not np.all(np.isfinite(w)):
            return 1e6
        viol = _manufacturability(lens)
        spot = np.asarray(m["rms_spot_um_per_field"], dtype=float)
        # Case targets: efl 50 +/-1%, spot <= 25um, track <= 70mm, wfe <= 0.5, no violations.
        # Penalties are flat inside each target with margin, so the search spends its
        # freedom on wavefront instead of chasing an exact focal length.
        pen  = 4.0 * max(0.0, abs(m["efl_mm"] - 50.0) - 0.35) ** 2
        pen += 2.0 * max(0.0, m["total_track_mm"] - 69.0) ** 2
        pen += 0.02 * max(0.0, float(np.max(spot)) - 22.0) ** 2
        pen += 2.0 * len(viol)
        obj = float(np.max(w)) + 0.30 * float(np.mean(w)) + pen
        if report:
            return m, viol, obj
        return obj
    except Exception:
        return 1e6
