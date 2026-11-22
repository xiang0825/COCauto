# CoC Reliability and Mobile Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Stabilize and publish the Windows controller, then add a paired Android client that launches CoC on the phone and controls the Windows agent.

**Architecture:** Reconcile the current local work with GitHub `main`, preserve the live robot until a safe release handoff, and validate the Python desktop agent through tests, package verification, and real MuMu runs. Add a Flutter Android client and a minimal authenticated LAN API only after the desktop task/state contract is stable.

**Tech Stack:** Python 3.11, Tkinter, SQLite, ADB, PyInstaller, PowerShell; Flutter/Dart with a Kotlin Android platform bridge; GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-11-19-desktop-mobile-product-design.md`

## Global constraints

- No scheduled tasks or silent post-reboot starts.
- Preserve the live DB, selected-task semantics, and the running healthy process until a verified safe handoff.
- Never click an uncertain game page or report a test as real-game proof.
- Every published package must match source tag and displayed version and include a SHA-256 checksum.
- Remove generated build outputs only after identifying exact paths and confirming they are not live or required.
- LAN control must use explicit pairing and authenticated commands; no public listener or router forwarding.

## Review focus

- A stale or transient page must not be mistaken for a battle result or return-home screen; exercise multi-frame transitions and manual recovery.
- An unselected task must never run; exercise all task-plan variants and startup defaults.
- A dropped ADB session must not allow stale commands after reconnect; exercise device replacement, delayed responses, and recovery state.
- An OCR spike must not mark resources full or keep the bot farming after confirmed capacity; exercise valid capacity and outlier histories.
- An upload must not leave a broken home download link or mismatch source/runtime versions; inspect GitHub metadata and re-hash the uploaded ZIP.

---

### Task 1: Reconcile the local work with the repository's current main

**Files:** Git history and existing tracked/untracked worktree files.

- [x] Create a named `codex/` branch without discarding the current worktree.
- [x] Classify every changed/deleted test, fixture, source file, design doc, and build directory; restore coverage if a deletion is not replaced by an equivalent test.
- [x] Integrate `origin/main` commits `e0d5f35` and `3c615bf` while preserving local changes.
- [x] Record the current real EXE hash, version, Python runtime, and root-package layout before any release mutation.
- [x] Confirm only the intended source/docs/tests remain in the branch diff; keep local databases and build outputs out of Git.

### Task 2: Verify the Windows reliability work against current behavior

**Files:** Existing task flow, ADB/device classes, page recognizer, resource state, test suite, and runtime maintenance report.

- [ ] Run the full supported unit suite and record failures without weakening assertions to obtain a pass.
- [ ] Add or restore focused regression tests for selected-task-only scheduling, new-home recognition, search-entry confirmation, settlement/return, disconnect recovery, heartbeat timeouts, memory cleanup, and full-resource standby.
- [ ] Re-run tests after each root-cause fix and run the package module verifier on the staged executable.
- [ ] Use actual MuMu screen and DB logs to verify five consecutive attack/settlement/return cycles; record each actual result, resource delta, recovery event, and whether the learned tactic was executed.
- [ ] Keep monitoring the live process without terminating it while healthy; only report finite observed duration and outcomes.

### Task 3: Make release packaging and cleanup repeatable

**Files:** `发布EXE.ps1`, `自动脚本.spec`, `工具包/版本管理.py`, `README.md`, and release helper scripts.

- [ ] Ensure one version value propagates to executable UI, package metadata, release tag, README, and update API.
- [x] The package verifier rejects candidates whose `_internal/版本号.txt` is missing, empty, or differs from the source `版本号.txt`.
- [ ] Add a short-timeout GitHub Releases check that runs off the Tk thread at startup, supports a manual check, quietly tolerates offline use, and opens the release page only after a newer version is confirmed.
- [ ] Build into a unique staging directory, verify Python ABI, required modules, runtime file count, and EXE hash before publication.
- [ ] Produce a ZIP containing the EXE, `_internal`, required licenses/model files, a concise quick-start, and a SHA-256 manifest; exclude DBs, logs, account settings, caches, and source-only files.
- [ ] Publish source/tag, release notes, ZIP, and SHA-256 to GitHub; update the repository home download link and verify the uploaded asset against the staged archive.
- [ ] At a safe game-home/standby handoff, deploy the verified package and remove only superseded generated versions, retaining one root EXE and matching `_internal`.

### Task 4: Stabilize the desktop control boundary for mobile clients

**Files:** New local agent API module, robot manager/task scheduler integration, UI pairing/settings, tests, and security documentation.

- [ ] Define a small API for pairing, robot status, selected tasks, start, pause, stop, and recent logs; do not expose arbitrary shell or coordinate commands.
- [ ] Bind only to an explicitly selected LAN interface; pair with a five-minute one-time code and QR-pinned TLS fingerprint, then issue a revocable random token stored via DPAPI/Android Keystore.
- [ ] Bind each phone token to exactly one desktop robot and its saved task plan; require a new explicit pairing to change either binding.
- [ ] Serialize all controls through the robot state machine; reject stale revision commands and make pause/stop outrank queued starts.
- [ ] Treat phone-network loss as stale remote status while desktop remains authoritative; treat ADB loss as a safe recovery event that waits for confirmed screen state before further inputs.
- [ ] Add tests for authentication, invalid robot IDs, disconnected devices, reconnect, and graceful API shutdown.
- [ ] Verify LAN API calls update the desktop UI and actual robot state consistently.

### Task 5: Build the Android app

**Files:** New `mobile/` Flutter project, Kotlin bridge, assets, and mobile documentation.

- [ ] Add a short Android onboarding flow that pairs to the Windows agent and reports missing ADB/game prerequisites.
- [ ] Add game launch intent, device/robot state, selected-task summary, recent logs, and explicit start/pause/stop controls.
- [ ] Check GitHub Releases on foreground entry and show version/release notes plus a user-confirmed download/install path; use a system/in-app notification, no scheduled background polling, and no silent install.
- [ ] Build an APK and test lifecycle, LAN loss/reconnect, denied notifications, unavailable game, and unavailable agent in an Android emulator.
- [ ] Verify launch and game-control behavior through five consecutive real attack/settlement/return cycles on an Android phone before claiming device compatibility or publishing a stable mobile release.

### Task 6: Publish, clean, and audit the complete deliverables

**Files:** GitHub source/release, root Windows package, release notes, `README.md`, and mobile package.

- [ ] Publish the verified desktop release and Android APK or clearly staged Android preview to GitHub with matching versions and checksums.
- [ ] Verify downloads, source tag, UI version, package hashes, and startup instructions from the published artifacts.
- [ ] Remove stale local build dirs and superseded packages only after remote artifact verification; preserve source, current root runtime, DB, and user data.
- [ ] Audit each acceptance item in the design doc against tests, release files, and actual runtime evidence; keep the goal active until all required evidence exists.
