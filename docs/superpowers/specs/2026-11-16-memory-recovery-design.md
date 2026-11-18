# Host Memory Recovery Design

## Intent

Keep a CoC task from permanently ending after the robot's host-memory guard blocks ADB screenshots. The observed run had 828 MB of free commit, so the guard correctly prevented more screenshots; the missing behavior is a safe path to resume after resources return.

## Goals

- Keep the existing screenshot thresholds and preserve the emulator/game processes.
- For the explicit host-budget guard only, wait without screenshots or game input until the memory budget is healthy for three consecutive checks.
- After recovery, require the existing two-frame page confirmation before restarting the task plan.
- Honor an explicit user stop immediately. Unclassified allocation failures remain fail-closed.

## Non-goals

- Do not launch CoC, change login state, or send input while the page is unknown.
- Do not lower the 900 MB physical / 1536 MB commit thresholds.
- Do not change battle strategy, clean local build artifacts, or publish a release in this change.

## Approaches

- Lower the memory threshold: rejected because the observed free commit was below the existing safety reserve and could make ADB/emulator failure more likely.
- Retry screenshots at a longer interval: rejected because screenshots remain forbidden while the budget is low and repeated failures do not recover task state.
- Add a resource-wait state that polls Windows memory without screenshots, then returns to the existing page-confirmation state: selected because it preserves the current safety boundary and resumes only after the original guard condition has recovered.

## Behavior

Only an exception containing `主机内存保护已触发` is automatically recoverable. Poll the existing memory thresholds every ten seconds. Three consecutive healthy samples clear the host-memory guard and allow read-only page recognition to resume. Any low sample resets the consecutive count. Explicit stop wins over recovery. Other memory exceptions terminate the task safely and ask for manual review.

## Verification

Test threshold reporting, no-screenshot waiting while memory is low, recovery after three healthy samples, explicit-stop interruption, and fail-closed behavior for non-host allocation errors. Run the complete unittest suite, syntax/package checks, and build an isolated candidate. Real battle verification remains a separate gate and must use a confirmed CoC screen.
