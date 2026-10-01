# Archived visual gate

`rope_track_v21b.py` preserves the final offline candidate from the 0.1.0
optimization trials. It is not imported by the application or bundled in the
EXE. Its four timing contracts live in `tests/test_archived_candidate.py`.

The final three complete seven-round candidates did not significantly improve
on v18b. The released `rope_track.py` therefore uses the verified v18b gate.
Raw measurement fixtures remain available to reproduce the archived findings;
offline candidate events are not game scores. See
[`docs/optimization-0.1.0.md`](../docs/optimization-0.1.0.md).
