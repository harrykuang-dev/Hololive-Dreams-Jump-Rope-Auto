# Measured v5, v6 and v7 sequences

These compact JSON fixtures were extracted with `tools/extract_gate_fixture.py`
from the three `batch-test-20260927-224247-583982` recordings. Each row contains
real capture time, central rope height, confidence, color and line contrast.
All eligible observations are kept so the detector's state is not reset just
before a selected failure. Full v5 source videos were later removed under the
retention policy; compact measurements and reviewed failure summaries remain.

Nine life losses were visually reviewed against their input logs. The tests
require one visual candidate in a reviewed approach window and reject the
extra plateau event near 59.746 seconds in round 2. These are decision timing
regressions, not proof that an earlier input succeeds in the game. Compressed
MP4 pixel replays can also differ from the original uncompressed measurements.

Seven v6 sequences come from `batch-test-20260927-230050-006614`.
The v7 tests cover selected late approaches, a false first plateau dip, and a
weak outlier that must not invent a trough. All eligible observations remain
in each fixture. These selected timing contracts are not a jump-success metric.

Seven v7 sequences come from `batch-test-20260928-104917-045059`.
They expose a rebound rejected because it returned too close to the original
peak, plus discarded far-side arming evidence on entry to blue floor mode.
The v8 regression requires the reviewed earlier candidate without duplicating
the later event. Full-sequence candidate counts are regression assertions only,
not desired jump counts or scores. Latest v9/v10 videos remain local; older full
videos were removed after analysis, retaining compact measurements and summaries.

`native60-v9-raw.json` contains native 60 FPS measurements from the original
`Desktop 2026.09.27 - 03.00.28.01.mp4`, seconds 16–100, crop 448 144 1773 889.
It was extracted from `debug/v9-native-stride1.json` before the final v9
single-frame-snap filter. No frames were interpolated. Reviewed windows reject
gold-tint duplicate passes near 35.984/36.300 and prop jumps at 79.084/81.567,
while retaining the subsequent visible approach. This is a human reference
recording, not a bot score. Its MP4 remains in the ignored recordings folder.

`v9-round-1.json` preserves raw live measurements from
`batch-test-20260928-211007-100694-round-01.events.json`. The bowl-rim dips at
72.9075/83.9617 must not cause early floor triggers at 72.979/83.989; the
subsequent observed return remains eligible. This is distinct from compressed
MP4 replay: compression can change the geometric candidate even without a
code change. Both forms of evidence are retained; neither proves a saved life.

`v10-round-3.json` and `v10-round-4.json` preserve all eligible raw measurements
from `batch-test-20260928-214809-043529`. Weak fits immediately after a short
retreat created extra inputs at 85.770/94.938/101.793 in round 3 and 71.871
in round 4. Tests reject those while keeping reviewed subsequent approaches.
These are input-timing contracts, not proof of avoiding the recorded life loss.
