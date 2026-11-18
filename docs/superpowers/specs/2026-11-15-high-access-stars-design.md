# High-access target strategy design

## Intent

Improve the chance of earning at least one star when the selected opponent has highly reachable resource buildings. The current detector recognizes resource buildings only, so resource reach is a useful but imperfect proxy for attack opportunity.

## Approaches

- Train a Town Hall and defense detector: potentially more direct star targeting, but requires labeled images and model validation that are not available in this task.
- Raise the resource score threshold: already rejects weak loot targets and does not distinguish attack formation.
- Keep two-direction exploration for high-access, high-score targets after repeated low results: recent outcome data favors it, and the existing selector can execute it without new vision or input logic. This is the selected approach.

## Behavior

When there are at least two low-performing results in the recent window and the current result has a resource score of at least 8.0 and conservative high-value reach of at least 70%, set the next suggestion to `提高目标可达评分`. Require score evidence from the current result so stale high-access data cannot trigger the rule. For the next attack, the search task temporarily requires a score of at least 6.5 and conservative reach of at least 70% for the first eight candidates; the existing attack selector uses up to two directions when enough safe targets exist. Other cases keep their current rules.

## Constraints and verification

- Do not add a new detector, template, dependency, or input action.
- Keep the live RC72 process and game state untouched; build the candidate package in isolation.
- Add a regression test for the high-access branch, run it red/green, run the full test suite, and verify the candidate version and package contents.
- The refreshed recent-200 sample had 14/22 wins for dispersed targets and 8/19 for concentrated targets among score-8-plus, 70%-plus reach targets (n=41). The live run also accepted a score-5.9, 46%-reach candidate while the stricter gate was inactive. This is directional evidence with selection bias, not a guarantee of causation.
