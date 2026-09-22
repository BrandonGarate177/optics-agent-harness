"""Thin wrappers over Optiland. Tools return facts, never opinions.

State lives here in a dict keyed by lens_id so the model only ever sees
ids and numbers, never the Optic object.
"""

from __future__ import annotations

import json
import signal
import uuid
from pathlib import Path

import numpy as np
from optiland import optimization
import optiland.backend as be
from optiland.analysis import RmsWavefrontErrorVsField, SpotDiagram
from optiland.wavefront import Wavefront
from optiland.diagnostics import check_system
from optiland.fileio import save_optiland_file, save_zemax_file
from optiland.optic import Optic

STATE: dict[str, Optic] = {}
ITERATIONS: dict[str, int] = {}

VERSION = "2.0"

# Manufacturing floors. v2: diameter/thickness tightened from 15 to 10 on optical
# shop advice, edge air gap and radius/aperture added, aspheres must be declared.
RULES = {
    "min_edge_thickness_mm": 1.0,
    "min_center_thickness_mm": 1.5,
    "max_center_thickness_mm": 25.0,
    "min_air_gap_center_mm": 0.5,
    "min_air_gap_edge_mm": 0.3,
    "max_diameter_to_thickness": 10.0,
    "min_radius_to_semi_aperture": 1.2,
}

# Schott renamed these when it dropped arsenic and lead. The old names still trace
# but you cannot buy the glass.
DEPRECATED_GLASS = {
    "BK7": "N-BK7", "BAK1": "N-BAK1", "BAK4": "N-BAK4", "BALF4": "N-BALF4",
    "BAF10": "N-BAF10", "F2": "N-F2", "F5": "N-F5", "K5": "N-K5",
    "LAK9": "N-LAK9", "LAK22": "N-LAK22", "LAF2": "N-LAF2", "PSK3": "N-PSK3",
    "SF1": "N-SF1", "SF2": "N-SF2", "SF5": "N-SF5", "SF6": "N-SF6",
    "SF10": "N-SF10", "SF11": "N-SF11", "SK2": "N-SK2", "SK4": "N-SK4",
    "SK11": "N-SK11", "SK16": "N-SK16", "SSK5": "N-SSK5", "ZK7": "N-ZK7",
}

GLOBAL_MAXITER = 25
OPTIMIZE_TIMEOUT_S = 240

SOLVERS = {
    "least_squares": optimization.LeastSquares,
    "differential_evolution": optimization.DifferentialEvolution,
    "basin_hopping": optimization.BasinHopping,
}


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _wavelengths_um(lens: Optic) -> list[float]:
    return [w.value for w in lens.wavelengths.wavelengths]


def _build_optic(spec: dict) -> Optic:
    """spec: {surfaces:[{radius,thickness,material,is_stop,conic}], epd, fields_deg:[..],
    wavelengths_um:[..], allow_aspheres: bool}"""
    lens = Optic()
    surfaces = spec["surfaces"]
    for i, s in enumerate(surfaces):
        kwargs = {"index": i}
        radius = s.get("radius")
        thickness = s.get("thickness")
        if radius is not None and np.isfinite(radius) and abs(radius) < 1e8:
            kwargs["radius"] = float(radius)
        if i == 0:
            kwargs["thickness"] = float("inf") if thickness is None or thickness >= 1e6 else float(thickness)
        else:
            if thickness is not None:
                kwargs["thickness"] = float(thickness)
            if s.get("material"):
                kwargs["material"] = s["material"]
            if s.get("is_stop"):
                kwargs["is_stop"] = True
            if s.get("conic") is not None:
                kwargs["conic"] = s["conic"]
        lens.surfaces.add(**kwargs)
    lens.set_aperture(aperture_type="EPD", value=spec["epd"])
    lens.fields.set_type("angle")
    for y in spec.get("fields_deg", [0.0]):
        lens.fields.add(y=y)
    wls = spec.get("wavelengths_um", [0.587])
    for i, w in enumerate(wls):
        lens.wavelengths.add(value=w, is_primary=(i == len(wls) // 2))
    lens._allow_aspheres = bool(spec.get("allow_aspheres", False))
    return lens


def _prescription(lens: Optic) -> list[dict]:
    rows = []
    n = lens.surfaces.num_surfaces
    for i in range(n):
        surf = lens.surfaces.surfaces[i]
        radius = getattr(surf.geometry, "radius", float("inf"))
        rows.append(
            {
                "index": i,
                "radius": None if not np.isfinite(radius) else round(float(radius), 4),
                "thickness": None if not np.isfinite(surf.thickness) else round(float(surf.thickness), 4),
                "material": getattr(surf.material_post, "name", None) or type(surf.material_post).__name__,
                "conic": round(_conic(surf), 4),
                "is_stop": bool(surf.is_stop),
            }
        )
    return rows


def _semi_diameters(lens: Optic) -> list[float]:
    try:
        lens.updater.update_paraxial()
    except Exception:
        pass
    out = []
    for surf in lens.surfaces.surfaces:
        sd = getattr(surf, "semi_aperture", None)
        out.append(float(sd) if sd is not None and np.isfinite(sd) else 0.0)
    return out


def _is_glass(surf) -> bool:
    name = getattr(surf.material_post, "name", "") or ""
    return name.lower() not in ("", "air") and type(surf.material_post).__name__ != "IdealMaterial"


def _conic(surf) -> float:
    """Conic constant. Nonzero means the surface is an asphere, not a sphere."""
    k = getattr(surf.geometry, "k", None)
    if k is None:
        return 0.0
    try:
        return float(np.ravel(k)[0])
    except Exception:
        return 0.0


def _edge_thickness(lens: Optic, i: int) -> float | None:
    """Edge thickness of the space after surface i, at the traced clear aperture.

    v2 bug fix: Optiland returns a (1,) array here and float() on it raises under
    numpy 2. v1 swallowed that in a bare except, so this check never ran and every
    lens passed. See evals/optics-review-2026-09-22.md.
    """
    try:
        problem = optimization.OptimizationProblem()
        problem.add_operand(
            operand_type="edge_thickness",
            target=0,
            input_data={"optic": lens, "surface_number": i},
        )
        return float(np.ravel(problem.operands[0].value)[0])
    except Exception:
        return None


def _manufacturability(lens: Optic) -> list[str]:
    """Violations as plain sentences that say what to change."""
    problems = []
    surfaces = lens.surfaces.surfaces
    sds = _semi_diameters(lens)
    allow_asph = bool(getattr(lens, "_allow_aspheres", False))

    for i in range(1, len(surfaces) - 1):
        surf = surfaces[i]
        t = float(surf.thickness)
        sd = sds[i] if i < len(sds) else 0.0
        edge = _edge_thickness(lens, i)

        # Surface-level checks apply to glass and air alike.
        k = _conic(surf)
        if abs(k) > 1e-9 and not allow_asph:
            problems.append(
                f"surface {i} has a conic of {k:.4f}, which makes it an asphere. The spec "
                f"asked for spherical surfaces. Set conic to 0, or set allow_aspheres in the "
                f"spec if an asphere is genuinely permitted"
            )
        radius = getattr(surf.geometry, "radius", float("inf"))
        if np.isfinite(radius) and sd > 0:
            ratio = abs(float(radius)) / sd
            if ratio < RULES["min_radius_to_semi_aperture"]:
                problems.append(
                    f"surface {i} has a radius of {float(radius):.2f}mm over a semi-aperture of "
                    f"{sd:.2f}mm (ratio {ratio:.2f}). Below {RULES['min_radius_to_semi_aperture']} "
                    f"the surface approaches a hemisphere and cannot be ground and polished. "
                    f"Weaken the curvature or reduce the aperture"
                )

        if not np.isfinite(t):
            continue

        if _is_glass(surf):
            name = (getattr(surf.material_post, "name", "") or "").upper()
            if name in DEPRECATED_GLASS:
                problems.append(
                    f"surface {i} uses {name}, which is discontinued. Use "
                    f"{DEPRECATED_GLASS[name]} instead"
                )
            if t < RULES["min_center_thickness_mm"]:
                problems.append(
                    f"center thickness of the element at surface {i} is {t:.2f}mm, minimum is "
                    f"{RULES['min_center_thickness_mm']}mm, increase it"
                )
            if t > RULES["max_center_thickness_mm"]:
                problems.append(
                    f"center thickness of the element at surface {i} is {t:.2f}mm, maximum is "
                    f"{RULES['max_center_thickness_mm']}mm, reduce it"
                )
            if edge is not None and edge < RULES["min_edge_thickness_mm"]:
                if edge <= 0:
                    problems.append(
                        f"the element at surface {i} has an edge thickness of {edge:.2f}mm, so its "
                        f"two surfaces cross before they reach the clear aperture. This is not a "
                        f"lens. Increase the center thickness, weaken the curvature, or reduce the "
                        f"aperture"
                    )
                else:
                    problems.append(
                        f"edge thickness of the element at surface {i} is {edge:.2f}mm, minimum is "
                        f"{RULES['min_edge_thickness_mm']}mm, increase the center thickness, weaken "
                        f"the curvature, or reduce the aperture"
                    )
            if sd and t > 0 and (2 * sd) / t > RULES["max_diameter_to_thickness"]:
                problems.append(
                    f"the element at surface {i} is {2 * sd:.1f}mm across and only {t:.2f}mm thick "
                    f"(ratio {(2 * sd) / t:.1f}, limit {RULES['max_diameter_to_thickness']}). It "
                    f"will sag under its own weight and during polishing. Thicken it"
                )
        else:
            if 0 < t < RULES["min_air_gap_center_mm"]:
                problems.append(
                    f"the air gap after surface {i} is {t:.2f}mm on axis, minimum is "
                    f"{RULES['min_air_gap_center_mm']}mm"
                )
            if t > 0 and edge is not None and edge < RULES["min_air_gap_edge_mm"]:
                problems.append(
                    f"the air gap after surface {i} closes to {edge:.2f}mm at the edge, minimum is "
                    f"{RULES['min_air_gap_edge_mm']}mm. The two elements touch or nearly touch off "
                    f"axis even though the gap looks fine on axis"
                )
    return problems


class _WfeAtFields(RmsWavefrontErrorVsField):
    """RmsWavefrontErrorVsField samples a linspace of fields. This one samples ours."""

    def __init__(self, optic, fields, num_rays=12):
        Wavefront.__init__(self, optic, fields, "all", num_rays, "hexapolar")
        self._field = be.array(fields)
        self._wavefront_error = be.array(self._rms_wavefront_error())


def _norm_fields(lens: Optic) -> list[tuple[float, float]]:
    ys = [float(f.y) for f in lens.fields.fields]
    m = max(abs(y) for y in ys) or 1.0
    return [(0.0, y / m) for y in ys]


def _efl_per_wavelength(lens: Optic) -> dict[float, float]:
    """Focal length at each wavelength. The spread is the chromatic focal shift."""
    wls = lens.wavelengths.wavelengths
    original = [w.is_primary for w in wls]
    out = {}
    try:
        for w in wls:
            for other in wls:
                other.is_primary = other is w
            lens.updater.update_paraxial()
            out[round(float(w.value), 4)] = float(np.ravel(lens.paraxial.f2())[0])
    except Exception:
        out = {}
    finally:
        for w, was in zip(wls, original):
            w.is_primary = was
        try:
            lens.updater.update_paraxial()
        except Exception:
            pass
    return out


def _back_focal_distance(lens: Optic) -> float:
    """Air gap from the last glass surface to the image plane."""
    surfaces = lens.surfaces.surfaces
    for i in range(len(surfaces) - 2, 0, -1):
        t = float(surfaces[i].thickness)
        if np.isfinite(t) and not _is_glass(surfaces[i]):
            return round(t, 3)
    return 0.0


def _metrics(lens: Optic) -> dict:
    lens.updater.update_paraxial()
    efl = float(np.ravel(lens.paraxial.f2())[0])
    fields = _norm_fields(lens)

    sd = SpotDiagram(lens, fields=fields)
    # v2: RMS across wavelengths, not mean. The mean read a few percent optimistic
    # exactly where the spot threshold binds.
    spot_um = [
        round(float(np.sqrt(np.mean(np.asarray([float(v) for v in per_wl], dtype=float) ** 2))) * 1000, 2)
        for per_wl in sd.rms_spot_radius()
    ]

    try:
        w = _WfeAtFields(lens, fields)
        arr = np.asarray(be.to_numpy(w._wavefront_error) if hasattr(be, "to_numpy") else w._wavefront_error, dtype=float)
        if arr.ndim > 1:
            wfe_waves = [round(float(np.sqrt(np.mean(row ** 2))), 4) for row in arr]
        else:
            wfe_waves = [round(float(v), 4) for v in np.atleast_1d(arr)]
    except Exception as e:  # noqa: BLE001
        wfe_waves = [f"unavailable: {e.__class__.__name__}: {e}"]

    efls = _efl_per_wavelength(lens)
    chromatic = round(max(efls.values()) - min(efls.values()), 4) if len(efls) > 1 else 0.0

    return {
        "efl_mm": round(efl, 4),
        "f_number": round(efl / float(np.ravel(lens.paraxial.EPD())[0]), 3),
        "rms_spot_um_per_field": spot_um,
        "rms_wavefront_waves_per_field": wfe_waves,
        "chromatic_focal_shift_mm": chromatic,
        "efl_per_wavelength_mm": {k: round(v, 3) for k, v in efls.items()},
        "back_focal_distance_mm": _back_focal_distance(lens),
        "total_track_mm": round(float(lens.total_track), 3),
        "fields_deg": [float(f.y) for f in lens.fields.fields],
        "wavelengths_um": _wavelengths_um(lens),
        "grader_version": VERSION,
    }


# ---- public tools ---------------------------------------------------------


def build_lens(spec: dict) -> dict:
    lens = _build_optic(spec)
    lens_id = _new_id()
    STATE[lens_id] = lens
    ITERATIONS[lens_id] = 0
    report = check_system(lens)
    out = {
        "lens_id": lens_id,
        "system_ok": bool(report.ok),
        "system_findings": [str(f) for f in getattr(report, "findings", [])] if not report.ok else [],
        "prescription": _prescription(lens),
    }
    if report.ok:
        try:
            out["efl_mm"] = round(float(lens.paraxial.f2()), 4)
        except Exception as e:  # noqa: BLE001
            out["efl_mm"] = f"unavailable: {e}"
        out["manufacturability_violations"] = _manufacturability(lens)
    return out


def evaluate(lens_id: str) -> dict:
    lens = STATE[lens_id]
    out = _metrics(lens)
    out["manufacturability_violations"] = _manufacturability(lens)
    out["lens_id"] = lens_id
    return out


def optimize(
    lens_id: str,
    variables: list[dict],
    operands: list[dict],
    solver: str = "least_squares",
    maxiter: int = 200,
) -> dict:
    """variables: [{type:'radius'|'thickness'|'conic', surface: int, min: float, max: float}]
    operands: [{type:'f2'|'rms_spot_size'|'total_track'|'edge_thickness', target: float, weight: float,
                min: float, max: float, field_y: float, surface: int}]
    """
    lens = STATE[lens_id]
    before = _metrics(lens)
    problem = optimization.OptimizationProblem()
    for v in variables:
        kwargs = {}
        if v.get("min") is not None:
            kwargs["min_val"] = v["min"]
        if v.get("max") is not None:
            kwargs["max_val"] = v["max"]
        problem.add_variable(lens, v["type"], surface_number=v["surface"], **kwargs)
    primary = lens.primary_wavelength
    for op in operands:
        t = op["type"]
        input_data = {"optic": lens}
        if t == "rms_spot_size":
            input_data.update(
                {
                    "surface_number": -1,
                    "Hx": 0,
                    "Hy": float(op.get("field_y", 1.0)),
                    "num_rays": 5,
                    "wavelength": primary,
                    "distribution": "hexapolar",
                }
            )
        elif t == "edge_thickness":
            input_data["surface_number"] = op["surface"]
        kwargs = {"operand_type": t, "input_data": input_data, "weight": float(op.get("weight", 1.0))}
        if op.get("target") is not None:
            kwargs["target"] = float(op["target"])
        if op.get("min") is not None:
            kwargs["min_val"] = float(op["min"])
        if op.get("max") is not None:
            kwargs["max_val"] = float(op["max"])
        problem.add_operand(**kwargs)
    cls = SOLVERS[solver]
    opt = cls(problem)
    if solver != "least_squares":
        # Global solvers scale badly with variable count. Cap them so one call can't eat an hour.
        maxiter = min(maxiter, GLOBAL_MAXITER)
    def _timeout(signum, frame):  # noqa: ARG001
        raise TimeoutError(f"optimize exceeded {OPTIMIZE_TIMEOUT_S}s and was stopped")

    armed = False
    try:
        try:
            signal.signal(signal.SIGALRM, _timeout)
            signal.setitimer(signal.ITIMER_REAL, OPTIMIZE_TIMEOUT_S)
            armed = True
        except (ValueError, AttributeError):
            pass  # not the main thread, or no SIGALRM; run without the guard
        if solver == "least_squares":
            bounded = any(v.get("min") is not None or v.get("max") is not None for v in variables)
            opt.optimize(maxiter=maxiter, tol=1e-6, method_choice="trf" if bounded else "lm")
        else:
            opt.optimize(maxiter=maxiter)
    except TimeoutError as e:
        return {
            "lens_id": lens_id,
            "error": f"{e}. Reduce the variable count, tighten the bounds, or use least_squares.",
            "before": before,
        }
    except Exception as e:  # noqa: BLE001
        return {"lens_id": lens_id, "error": f"{e.__class__.__name__}: {e}", "before": before}
    finally:
        if armed:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
            except Exception:
                pass
    ITERATIONS[lens_id] += 1
    after = _metrics(lens)
    after["manufacturability_violations"] = _manufacturability(lens)
    return {
        "lens_id": lens_id,
        "iteration": ITERATIONS[lens_id],
        "solver": solver,
        "before": {k: before[k] for k in ("efl_mm", "rms_spot_um_per_field", "total_track_mm")},
        "after": after,
        "prescription": _prescription(lens),
    }


def export(lens_id: str, out_dir: str = "out") -> dict:
    lens = STATE[lens_id]
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    zmx = d / f"{lens_id}.zmx"
    js = d / f"{lens_id}.json"
    save_zemax_file(lens, str(zmx))
    save_optiland_file(lens, str(js))
    return {"lens_id": lens_id, "zmx": str(zmx), "json": str(js), "prescription": _prescription(lens)}


def find_starting_point(elements: int, f_number: float | None = None, field_deg: float | None = None) -> dict:
    """Read-only index of Optiland's sample prescriptions by element count."""
    from optiland.samples import objectives, simple  # noqa: PLC0415

    candidates = []
    for mod in (simple, objectives):
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and issubclass(obj, Optic) and obj is not Optic:
                try:
                    lens = obj()
                    n_glass = sum(1 for s in lens.surfaces.surfaces if _is_glass(s))
                    lens.updater.update_paraxial()
                    efl = float(lens.paraxial.f2())
                    fno = efl / lens.paraxial.EPD()
                    max_field = max(float(f.y) for f in lens.fields.fields)
                    candidates.append(
                        {
                            "name": name,
                            "elements": n_glass,
                            "efl_mm": round(efl, 2),
                            "f_number": round(fno, 2),
                            "max_field_deg": round(max_field, 2),
                            "spec": _spec_from_optic(lens),
                        }
                    )
                except Exception:  # noqa: BLE001
                    continue

    def score(c):
        s = abs(c["elements"] - elements) * 10
        if f_number is not None:
            s += abs(c["f_number"] - f_number)
        if field_deg is not None:
            s += abs(c["max_field_deg"] - field_deg) / 5
        return s

    candidates.sort(key=score)
    return {"candidates": candidates[:3]}


def _spec_from_optic(lens: Optic) -> dict:
    surfaces = []
    for row in _prescription(lens):
        surfaces.append(
            {
                "radius": row["radius"],
                "thickness": row["thickness"],
                "material": None if row["material"] in ("Air", "IdealMaterial", None) else row["material"],
                "is_stop": row["is_stop"],
            }
        )
    return {
        "surfaces": surfaces,
        "epd": float(lens.paraxial.EPD()),
        "fields_deg": [float(f.y) for f in lens.fields.fields],
        "wavelengths_um": _wavelengths_um(lens),
    }


if __name__ == "__main__":
    # Smoke test: the README singlet.
    spec = {
        "surfaces": [
            {"thickness": None},
            {"radius": 25.0, "thickness": 6.0, "material": "N-BK7", "is_stop": True},
            {"radius": -75.0, "thickness": 34.0},
            {},
        ],
        "epd": 20,
        "fields_deg": [0, 5],
        "wavelengths_um": [0.587],
    }
    b = build_lens(spec)
    print(json.dumps(b, indent=1))
    print(json.dumps(evaluate(b["lens_id"]), indent=1))
    o = optimize(
        b["lens_id"],
        variables=[{"type": "radius", "surface": 1, "min": 10, "max": 100}, {"type": "radius", "surface": 2, "min": -300, "max": -10}, {"type": "thickness", "surface": 2, "min": 20, "max": 60}],
        operands=[{"type": "f2", "target": 50}, {"type": "rms_spot_size", "target": 0, "weight": 5, "field_y": 0}, {"type": "rms_spot_size", "target": 0, "weight": 5, "field_y": 1}],
    )
    print(json.dumps(o, indent=1, default=str))
    print(json.dumps(find_starting_point(3, 4.5, 20), indent=1, default=str)[:1500])
