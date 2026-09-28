# Rope geometry regression images

The first eight small JPEG frames come from the user's bot recordings
`batch-test-20260927-213635-200228-round-NN.mp4` in ignored `dist/debug/`.
Those older videos were reviewed and removed under the retention policy;
these compact regression images remain. Large videos are not included in Git.

| Pair | Round | Before/current frame | Visually inspected height at central player |
| --- | --- | --- | --- |
| raised-hand | 03 | 712 / 713 | about -0.33 |
| bowls-at-apex | 02 | 568 / 569 | about -0.45 |
| occluded-approach | 03 | 933 / 934 | about -0.19 |
| warm-rope | 03 | 1095 / 1096 | about -0.14 |

The night-violet before/current pair comes from frames 1427/1428 of
`batch-test-20260927-230050-006614-round-03.mp4` (full video removed after
review under the retention policy; this compact image pair remains).
Its central rope height is about -0.32; the old bright-color mask rejected
the visible dark violet line. There are ten JPEG images in total.

Heights are relative to the same normalized reference line as `RopePosition`;
the rope is measured at x=0.565 of the game client. Labels were checked against
the visible rope, with a ±0.045 test tolerance for perspective, fitting and JPEG
compression. These tests assess pixel tracking, not successful game jumps.

`occluded-floor-v9/` contains nine lossless 960×540 frames (2225–2233) from
`batch-test-20260928-211007-100694-round-01.mp4`, with capture timestamps in
`sequence.json`. At frame 2232 the center is covered by a bowl but the two
visible side portions remain on the shallow high arc, around height .13.
Unregularized fitting on this short sequence snaps to ~.047. The v10 bounded
near-floor continuity ranking retains the current-pixel-supported .123 fit.
This label is an approximate spatial check, not evidence of a successful jump.

`occluded-retreat-v10/` contains seven lossless 960x540 frames (2746-2752)
from `batch-test-20260928-214809-043529-round-04.mp4` with real timestamps.
At frame 2752 the visible rope retreats above the player (height about -.28),
with bowls obscuring the center. The v10 short replay chose a near-ground
curve above -.1; v11 current-pixel local refinement retains the visible arc.
The short sequence is a spatial regression, not a recreated full game state.
