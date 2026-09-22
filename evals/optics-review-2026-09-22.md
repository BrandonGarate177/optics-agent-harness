# Optical design review: harness arm vs baseline arm

Reviewer: outside optical design engineer. Date: 2026-09-22.
Scope: all 24 exported lenses (4 buildable cases x 3 runs x 2 arms), traced independently from the exported Optiland files found via the logs, plus a read of the optimize reasoning in six runs.

## Verdict (five lines)

1. These are the same lenses. Both arms start from the same Optiland sample, vary the same radii, pin `f2`, minimize spot, and land within a few percent of each other. The between-arm gap is smaller than the run-to-run spread inside each arm.
2. Where the two arms differ as hardware, the baseline wins one and loses one. The baseline's achromat is the part you would actually order (4.0/2.5mm centers, 2.9mm edges); the harness's is the sample scaled 5x with 2.17/1.60mm centers and a 1.13mm crown edge. The baseline's edge_rule run 2 is an 11.93mm-thick puck in a 12mm blank, which is worse.
3. The single biggest number in the whole set, the harness's 20.3um on edge_rule run 0, is an undeclared conic on the front surface. The spec said single-element N-BK7. That is a different part with a different process, and nothing in the harness or the grader looks at conic.
4. The `_manufacturability` edge-thickness check is dead code under numpy 2.x. `float()` on the operand's `(1,)` array raises, the bare `except` swallows it, and every lens in this set was graded with that rule silently off. Five of the six triplets violate the project's own 1.0mm edge minimum (0.62 to 0.97mm) and all six were logged as "viol 0".
5. Three of the four buildable specs are first-year exercises, and the fourth is a Cooke triplet whose answer ships inside `optiland.samples`. The eval measures whether the agent can drive an optimizer, not whether it can design a lens.

## Per-case results

Spot is RMS radius in microns, per field, mean over wavelengths, as the harness computes it. Wavefront is RMS in waves at 0.5876um, per field. Min edge is the thinnest element edge at the traced clear aperture, computed by sag, not by the broken operand. Track in mm.

| Case | Run | Arm | EFL | f/# | Spot per field | WFE per field | Min edge | Track | Grade | Note |
|---|---|---|---|---|---|---|---|---|---|---|
| singlet_50 | 0 | harness | 50.000 | 5.00 | 12.6/14.0 | 1.54/0.73 | 4.47 | 51.7 | B+ | Bending q=0.686, short of best form; 5.0mm center buys nothing |
| singlet_50 | 0 | baseline | 50.000 | 5.00 | 12.6/13.1 | 1.54/0.70 | 3.51 | 51.2 | A- | q=0.713, textbook best form, round 4mm center |
| singlet_50 | 1 | harness | 50.000 | 5.00 | 12.6/13.7 | 1.55/0.72 | 4.48 | 51.7 | B+ | Same as run 0 |
| singlet_50 | 1 | baseline | 50.000 | 5.00 | 12.6/13.1 | 1.55/0.70 | 3.51 | 51.3 | A- | Repeatable to 0.07um across three runs |
| singlet_50 | 2 | harness | 50.000 | 5.00 | 12.8/14.2 | 1.56/0.75 | 4.01 | 51.5 | B | Worst singlet in the set, still passes by 4x |
| singlet_50 | 2 | baseline | 50.000 | 5.00 | 12.6/13.0 | 1.54/0.70 | 3.51 | 51.2 | A- | Identical to runs 0 and 1 |
| achromat_100 | 0 | harness | 100.000 | 8.00 | 4.6/4.5 | 0.19/0.19 | 1.37 | 101.8 | B | Optiland's CementedAchromat scaled exactly 5x; thicknesses never revisited |
| achromat_100 | 0 | baseline | 100.000 | 8.00 | 4.5/4.5 | 0.19/0.19 | 2.90 | 103.0 | A- | Same optics, sane 4.0/2.5mm centers |
| achromat_100 | 1 | harness | 100.000 | 8.00 | 4.5/4.4 | 0.19/0.19 | 1.13 | 101.9 | B- | 1.13mm crown edge on a 12.5mm element, no mount margin left |
| achromat_100 | 1 | baseline | 100.000 | 8.00 | 4.4/4.6 | 0.19/0.19 | 2.90 | 103.0 | A- | Unchanged from run 0 |
| achromat_100 | 2 | harness | 100.000 | 8.00 | 4.6/4.4 | 0.19/0.19 | 1.37 | 101.8 | B | Same scaled-sample thicknesses as run 0 |
| achromat_100 | 2 | baseline | 100.000 | 8.00 | 4.5/4.5 | 0.19/0.19 | 2.90 | 103.0 | A- | Unchanged |
| triplet_50 | 0 | harness | 50.000 | 4.50 | 15.3/15.2/19.0 | 2.09/1.44/1.24 | 0.85 | 60.2 | C+ | Axial 15.3um from a triplet that should give 7 to 9; element thicknesses left at sample values |
| triplet_50 | 0 | baseline | 50.000 | 4.50 | 8.7/14.4/17.4 | 1.12/0.98/1.23 | 0.62 | 59.6 | B | Best axial of the six, but 0.62mm crown edge is the thinnest in the set |
| triplet_50 | 1 | harness | 50.000 | 4.50 | 6.2/12.9/18.4 | 0.84/0.72/1.60 | 0.84 | 60.3 | B- | 3:1 center-to-corner ratio; unbalanced merit function, not a balanced design |
| triplet_50 | 1 | baseline | 50.000 | 4.50 | 14.5/19.1/15.0 | 1.74/1.34/1.23 | 0.82 | 60.7 | B- | Mid-field is the worst point, which means astigmatism is left unbalanced |
| triplet_50 | 2 | harness | 50.000 | 4.50 | 23.0/18.7/19.7 | 3.04/2.04/1.03 | 0.97 | 60.4 | C | Worst lens in the review. 3.0 waves RMS on axis, 1.56% barrel, passes by 2um |
| triplet_50 | 2 | baseline | 50.000 | 4.50 | 10.1/14.4/16.4 | 1.36/1.00/1.33 | 0.83 | 60.3 | B+ | Best-balanced of the twelve triplet fields |
| edge_rule | 0 | harness | 30.000 | 2.50 | 20.3 | 4.23 | 4.29 | 32.1 | C | Conic -0.537 on the front surface. Undeclared asphere, spec said single-element N-BK7 |
| edge_rule | 0 | baseline | 30.000 | 2.50 | 52.0 | 11.20 | 2.80 | 30.8 | A- | Minimal, clean, exactly what an f/2.5 BK7 singlet gives |
| edge_rule | 1 | harness | 30.000 | 2.50 | 50.4 | 10.89 | 6.31 | 32.2 | B | 7.53mm center for a 1.5um spot gain over 4mm |
| edge_rule | 1 | baseline | 30.000 | 2.50 | 51.8 | 11.19 | 3.00 | 30.9 | A- | Repeat of run 0 |
| edge_rule | 2 | harness | 30.000 | 2.50 | 50.3 | 10.83 | 5.78 | 32.2 | B | 7.0mm center, arbitrary but harmless |
| edge_rule | 2 | baseline | 30.000 | 2.50 | 48.1 | 10.38 | 10.69 | 34.1 | D | 11.93mm center in a 12mm blank, diameter over thickness of 1.01. A glass puck for 3.8um |
| impossible | 0-2 | harness | - | - | - | - | - | - | C | Correct refusal, zero tool calls. The system prompt names this exact spec as its impossible example |
| impossible | 0-2 | baseline | - | - | - | - | - | - | A | Built it, optimized it, got EFL 99.99 at 5.04mm track, saw it was not in focus, refused |

### Notes a designer would write in the margin

Every design in the set is at its own best focus already. I scanned through focus on all 24 and the largest available gain was 0.7um. Nobody left focus on the table, which is the one thing these merit functions got uniformly right.

The achromat case is not a design problem. Both arms produce a 4.5um RMS spot against a 5.73um Airy radius, so the geometric spot is already below the diffraction limit and the 15um threshold is decoration. The interesting number is the one nobody graded: 0.19 waves RMS wavefront, Strehl around 0.24. That is a soft objective. It comes from 0.138mm of F-to-C focal spread, roughly three times the secondary spectrum an N-BAK1/SF2 pair should give at 100mm. Both arms have it. Neither noticed, because color is only visible in the wavefront and the wavefront is never graded.

The harness achromat is literally `CementedAchromat` scaled by five. Sample centers 0.434 and 0.321mm become 2.169 and 1.604mm, to the micron, in two of three runs, with a back focus of 97.99 against the scaled 98.04. The agent re-optimized the three radii and left the thicknesses where `scale_system` dropped them. The baseline threw the scaled thicknesses away and picked 4.0/2.5mm, which is what a doublet of that diameter actually gets built at. That is a real judgment difference and the baseline is on the right side of it.

The triplets are the same story with less disguise. All six keep the sample's 3.259mm front crown and 2.9521mm rear crown; the harness keeps 6.0076 and 4.7504mm air gaps as well, unchanged to four decimals, in run 1. The agent varied six radii and called it a design. The Cooke triplet is the most tabulated design in the literature and `find_starting_point` hands over the finished article. There is no evidence in this set that either arm can design a triplet; there is evidence both can nudge one.

Edge thickness on the triplets is the manufacturability story. Crown edges run 0.62 to 0.97mm at the traced clear aperture in five of six runs, under the project's own 1.0mm floor, before you add the 0.5 to 1.0mm of radius a mount needs. A 20.7mm front crown with a 0.62mm edge (baseline run 0) is fragile to bevel and awkward to center. Every one of these was logged as zero violations.

## The specs and the grader

**EFL within 1% is a formality.** Optiland's `f2` operand hits it every time; all 24 lenses came back at 50.000, 100.000 or 30.000. It never discriminated between anything.

**Max spot is the only performance metric, and it binds in one case out of four.** Achieved against limit: singlet 13 of 60, achromat 4.5 of 15, edge_rule 48 to 52 of 120, triplet 16 to 23 of 25. Only the triplet is close, and harness run 2 passed it by 2um with 3.0 waves of on-axis wavefront error, which tells you the metric is not measuring what you want it to measure.

**Max track never binds.** Achieved over limit: 51.7/70, 102/130, 60.4/70, 32/45. Track for a singlet or a doublet is roughly EFL plus the center thickness, and every limit was set at 1.3x EFL or looser, so the constraint is satisfied by construction.

**What is missing, in the order I would add it:**

1. **RMS wavefront.** `evaluate` already computes it, shows it to the agent, and then the grader throws it away. It is the number that decides whether a lens is any good. Adding `max_wfe_waves` would have failed harness triplet run 2 (3.04 waves) and would have forced both arms to fix the achromat's residual color.
2. **Chromatic focal shift.** The achromat case specifies three wavelengths and then grades a single polychromatic spot. Nothing requires F and C to cross. A `max_focal_shift_F_C` of EFL/2000 is one line and would have caught the 0.138mm both arms left in.
3. **Edge thickness, actually working.** Stated as a rule, checked by dead code. See below.
4. **Distortion.** The triplet is a 50mm covering 20 degrees, a 36mm image circle, a photographic lens. Measured barrel runs -0.45% to -1.56% across the six runs. On a photographic lens the difference between 0.5% and 1.5% is the difference between shipping and not, and it is not in the spec at all.
5. **Back focal distance.** Nothing requires clearance behind the last vertex. Both arms landed 41 to 42mm on the triplet only because they inherited the sample's air space. A spec with a BFD floor is the single cheapest way to make these cases non-trivial.
6. **Clear aperture margin.** `_semi_diameters` returns the traced beam. Real parts need 0.5 to 1.0mm of radius past it for a mount. Every edge thickness in this review is therefore optimistic by 0.1 to 0.4mm, which pushes more triplet elements under the floor.
7. **Architecture conformance.** Nothing checks that the achromat is cemented, that the triplet is three air-spaced elements, or that a "single-element" lens is spherical. That last gap is how harness edge_rule run 0 exported an asphere.
8. **Vignetting.** Rays are traced unvignetted, so the 20-degree triplet spot is computed with rays a real barrel would clip. Relative illumination at 20 degrees is not reported anywhere.

**Dead configuration.** `RULES["allowed_catalogs"]` is declared and never read; glass is never checked against a catalog, and both arms happily used SK16 and F2, which are legacy Schott names (the current parts are N-SK16 and N-F2). `RULES["max_diameter_to_thickness"] = 15.0` never fires either; the worst ratio observed in 24 lenses is 7.76, and the real limit for a polished element is closer to 8 or 10.

**The edge-thickness bug, precisely.** In `_manufacturability`, `float(problem.operands[0].value)` is called on a numpy array of shape `(1,)`. Under numpy 2.x that raises `TypeError: only 0-dimensional arrays can be converted to Python scalars`, and the surrounding `except Exception: pass` eats it. I confirmed it directly: a 24mm-diameter biconvex with R = plus and minus 20 and a 1.6mm center, whose surfaces physically cross with about -6.4mm of edge, returns an empty violation list. Fix is `float(np.ravel(value)[0])`. Note that the `edge_thickness` operand also appears in the agents' merit functions, where the same array shape is at best inert.

**Difficulty, honestly.** The singlet and edge_rule cases are closed-form best-form bendings, ten minutes each in any code, and their spot thresholds sit at two to four times the achievable value. The achromat is a catalog part you buy rather than design (this is a Thorlabs AC254-100-A). The triplet is the only case with content, and Optiland ships the solution in its sample library and the harness hands it to the agent on the first tool call. None of these are medium. To get to medium you need a spec whose starting point is not in the box: a 25mm f/2 over 30 degrees half-field with a 2% distortion cap, a double Gauss with a mandated back focus, an athermalized IR doublet, or anything telecentric.

**One leak worth fixing today.** `system_prompt.md` says "If the spec is physically impossible or self-contradictory (for example an f/0.5 singlet, or a 5mm track with a 100mm focal length)". `cases.json` then asks for "a 100mm focal length and a total track of 5mm". The harness arm refused all three runs in one turn with zero tool calls because the answer was in its prompt. That row is not evidence of reasoning and should not be counted as a pass for the harness arm.

## The reasoning in the logs

I read harness `achromat_100-0`, `triplet_50-1` and `edge_rule-0` end to end, plus the matching baseline runs.

**Sound.** The harness achromat reason is the best writing in the set: "the current radii ratios were inherited unchanged from a design scaled for a different field/aperture combination". That is a correct and specific diagnosis of exactly what was wrong. The follow-up, dropping 5:8 weighting to 6:6 because the axial field was already excellent and did not need the pressure, is real merit-function judgment, and the numbers moved the way it predicted (6.32/3.54 to 4.58/4.45). The triplet diagnosis, that a uniform 90um blur across all three fields including axis means defocus rather than a field aberration, is the right read.

**Cargo-culted.** In harness `triplet_50-1`, round 3 opens with "The previous round left every radius untouched, so I'm dropping the edge operands". The observation is honest and the action was right, but the causal story is invented. The agent had no way to know the `edge_thickness` operand was the problem, and in `edge_rule-0` the same operand was present in a round that optimized fine. It guessed and got lucky. Worth noting that the harness gave it an operand that sometimes poisons the solve and gave it no way to see why, so an empirical guess was the only move available.

**The one that should fail review.** Harness `edge_rule-0`, round 2: "Adding center thickness (bounded 2-12mm) and a conic on the front surface as variables should cancel the remaining third-order spherical aberration of the best-form singlet". The optics are correct. A conic on the front surface is exactly how you null spherical in a singlet. But it silently converts the deliverable from a ground and polished spherical singlet into a glass asphere, which for N-BK7 means diamond turning or MRF and a different price class, and the agent never said so. It also was not needed: the threshold was 120um and the spherical design was already at 52um. A lead engineer rejects this on sight, not because the physics is wrong but because the part changed and nobody was told.

**Weights are noise.** The harness follows the prompt's "weight 5 to 10" advice; the baseline uses weight 1 throughout. They converge to the same places. The prompt's numeric weight guidance is not doing any work.

**Process cost.** Harness averaged 3.33 optimize calls and 9.0 tool calls per buildable run at 0.86 dollars; baseline averaged 1.67 and 6.58 at 0.71 dollars. The harness spends twice the optimizer calls and about 20% more money to land in the same place, and on the triplet it lands slightly worse.

## Head to head, by the numbers

Worst-field RMS spot, mean over the three runs:

| Case | Harness | Baseline | Winner |
|---|---|---|---|
| singlet_50 | 13.96 | 13.07 | baseline by 7% |
| achromat_100 | 4.58 | 4.53 | tie |
| triplet_50 | 20.16 | 17.62 | baseline by 13%, and tighter spread (2.6 vs 4.7) |
| edge_rule | 40.33 | 50.63 | harness by 20%, entirely from the one asphere run. Drop it and it is 50.33 vs 49.98, a tie |

Buildability: baseline's achromat is better (2.90mm vs 1.13-1.37mm crown edge). Harness's edge_rule parts are better than the baseline's 11.93mm puck. Triplets are a wash and both are under the floor. One each.

The honest summary is "same lenses". Both arms pull the same starting point out of the same sample library, vary the same radii, pin the same `f2` operand, minimize the same spot, and stop at the same place. The harness's contribution is process (a stated reason per optimize, a gated export, a consistent refusal format) and none of it shows up in the glass. Worse, the gate is leaking: it passed six triplets that break the project's own edge rule and one lens that is not the part the spec asked for.

## What I would change

1. Fix `_manufacturability`'s edge-thickness call (`float(np.ravel(v)[0])`) and stop bare-excepting around a rule you claim to enforce. Then re-run. I expect five of six triplets to fail immediately, which is the correct outcome and the most useful thing this harness could tell you.
2. Add wavefront to the grader. `max_wfe_waves` per case, using the number `evaluate` already returns. Set it at 0.07 waves for the achromat (Maréchal) and something like 1.0 for the triplet. Nothing else you can add is this cheap or this diagnostic.
3. Add a back focal distance floor and a distortion cap to the triplet case, and a "no conics unless asked" check to the grader. Those three turn the triplet from a lookup into a design, and close the asphere hole.
4. Add clear-aperture margin: compute edge thickness at traced semi-aperture plus 0.75mm, not at the beam. Everything in this review gets 0.1 to 0.4mm harder and more honest.
5. Rewrite the `impossible` case so the system prompt does not contain it verbatim, or drop the example from the prompt. As it stands the harness arm's three passes measure recall.
6. Add one case whose starting point is not in `optiland.samples`. Until you do, the eval measures whether the agent can drive `scipy.optimize` from a known-good seed, which both arms can, equally.
7. Replace mean-over-wavelength with RMS-over-wavelength in `_metrics`. The current spot number runs 2 to 8% optimistic against the polychromatic value (baseline triplet run 0 field 3: 17.36 reported, 18.04 actual), which matters precisely where the threshold binds.
8. Either use `RULES["allowed_catalogs"]` or delete it, and tighten `max_diameter_to_thickness` from 15 to 8. Neither rule has ever fired.
