# Batch v5: geometry investigation and offline checks

Status: candidate release for a new three-round user-run test. No verified 100-point bot game and no GitHub push.

## Actual v4 results

Recordings: `dist/debug/batch-test-20260927-213635-200228-round-{01,02,03}.mp4` and matching `.events.json`.
The result screens show **32, 43, 33**. The JSON logs contain **36, 46, 40** jump inputs respectively; these are not scores.
All three logs end with `round_finished`, contain zero jumps after the first `result` frame, and contain zero menu inputs after that round started. The batch runner separately authorizes navigation between completed rounds.

## Nine inspected life losses

Times below are actual elapsed seconds from JSON, not fixed-rate MP4 playback seconds. Each MP4 frame N corresponds to `frames[N]` in JSON. Life-loss timing is measured from three stable lower-heart observations and visually checked in the generated contact sheets.

| Round / score | Life loss t | Last actual input before loss | Observed failure | v5 replay candidate t |
| --- | ---: | ---: | --- | ---: |
| 1 / 17 | 42.475 | 40.799 | No jump for this pass; far-arc confirmation remained blocked after obscured measurements | 42.079 |
| 1 / 26 | 59.060 | 57.384 | No jump; visible approaching rope had reported coverage as low as 0.09 | 58.726 |
| 1 / 32 | 70.476 | 70.315 | Late; an overhead rope labelled gold selected the later floor threshold | 70.190 |
| 2 / 15 | 39.748 | 39.071 | Early; bowls pulled the fitted arc toward the approach threshold while the actual rope was still high | 39.281 |
| 2 / 34 | 67.794 | 67.586 | Late; inaccurate arc fit delayed the approach crossing | 67.460 |
| 2 / 43 | 82.864 | 81.454 | No jump for this pass after occlusion disrupted the fitted arc | 82.531 |
| 3 / 23 | 49.635 | 49.425 | Late despite no large obstacle at the decisive moment; raised rope hands broke the fixed-endpoint model | 49.232 |
| 3 / 31 | 65.065 | 64.341 | Early during a prop-induced fit jump, followed by no input on the actual approach | 64.731 |
| 3 / 33 | 76.087 | 75.877 | Late; the fitted curve lagged behind the visible rope as the props cleared | 75.753 |

The replay column is an offline visual candidate, **not an actual new input or a rescued jump**. A real input also incurs a fresh-frame safety check and input latency. Different actions would change the game and subsequent recordings. This table cannot establish a new game score.

## Changed detection points and decisions

- The old curve fixed the left hand near normalized y=0.648 and the right near y=0.410, with only ±0.035 global adjustment. In round 3 frame 713, the actual left rope hand is near y=0.53. This produced low coverage even though the rope was plainly visible.
- v5 fits three separated visible pieces from five horizontal bands spanning x=0.29–0.79. Curvature and both endpoint heights move with the observed rope. The control measurement is the fitted rope height at the central player's x≈0.565, independent of costume.
- Candidate pixels must look like a thin line, be brighter in at least one channel than both nearby vertical neighbors, and show current image motion. Large blue/white prop surfaces no longer count as whole rope sections simply because they share its colors. The confidence score rewards support in at least three bands; weak or partial fits remain possible and are separately gated by the detector.
- A single gold color label no longer chooses floor timing. A shallow gold trajectory establishes floor mode; a confidently observed overhead arc ends it regardless of color. The floor path retains its observed peak/descent/rebound logic for the opposite approach direction.
- Fragment-triggered jumps now enter the same visible-retreat requirement as full-arc jumps, closing an early-return path that could permit duplicate candidates.
- Per-frame JSON now includes five-band support, estimated endpoints, screen-space movement direction, mode and decision reason.

## Checks and remaining limitations

- 72 tests passed, including four pairs of actual failure frames, a synthetic moving-hand/central-occlusion scene, gold-tinted overhead arcs, duplicate-event gating, and F9/focus-loss interruption during result recording. Those interruptions cancel batch continuation as well as input. The eight JPEG fixtures are small extracts, not videos.
- Replayed all frames on the original capture timestamps in all three v4 rounds and three older v3 rounds. v4 produced 37/46/41 candidates; the older rounds produced 39/35/40. Counts do not measure success or recall.
- The tracker took about 6 ms median in one replay process and about 9 ms with three concurrent replay jobs on this machine. These are offline timings, not a live end-to-end latency benchmark.
- Complete occlusion, poor lighting and ambiguity among several thin moving edges remain possible. Real three-round testing is still required, particularly for direction changes and floor swings. The packaged executable has not yet played a new game.

Reproduce:

```powershell
.\.venv\Scripts\python.exe tools\analyze_round_failures.py dist\debug\batch-test-20260927-213635-200228-round-03.events.json
.\.venv\Scripts\python.exe tools\replay_recorded_geometry.py dist\debug\batch-test-20260927-213635-200228-round-03.events.json --output dist\debug\geometry-v5-check.json
.\.venv\Scripts\python.exe -m pytest -q
```
