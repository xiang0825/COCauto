# Ignore Impossible Historical Resource OCR Peaks

**Intent:** Honor the configured full-resource standby behavior when a past OCR sample contains an impossible resource count.

**Root cause:** The recent-resource peak guard trusts any successful OCR value. A historical elixir reading of 411,067,075 makes the current 31,000,000 full store look incomplete forever.

**Approaches:**
- Recommended: only let historical values that match a known storage-capacity range act as a lower-bound guard. This preserves reliable history and keeps the database read-only.
- Alternative: delete or rewrite contaminated historical rows. This mutates user data and the same OCR error could recur.

**Constraints:** Keep full detection conservative; preserve the guard for valid historical capacities; do not edit the live database; deploy only after pausing at a confirmed home screen.

**Success:** 31,000,000/31,000,000 with a 411,067,075 historical OCR outlier is treated as full, while a lower current value remains not-full when a valid higher capacity was observed.
