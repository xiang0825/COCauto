# ADB Server Isolation Implementation Plan

> **For agentic workers:** Use the systematic debugging and test-driven development workflows. Preserve all unrelated existing worktree changes.

**Goal:** Prevent CoC recovery from restarting the shared default ADB server used by MuMu and other tools.

**Architecture:** Give every CoC ADB subprocess a private `ANDROID_ADB_SERVER_PORT=5038` environment, so ADB starts and controls only its dedicated server. Keep device selection and existing bounded recovery behavior, and make the connection panel reconnect its saved localhost device before scanning when necessary.

**Tech Stack:** Python, Tkinter, unittest, Android Debug Bridge CLI.

## Tasks

1. Add focused tests that every ADB subprocess receives the isolated server port and that scanning reconnects the saved localhost device first.
2. Add one shared ADB environment builder and route device, scan, connect, reconnect, and server-control commands through it.
3. Update connection-panel scanning to reconnect only the already-saved localhost address before listing devices.
4. Run targeted ADB/UI tests and the full suite only after host memory is safely above the application's guard. Do not access, restart, or send input to the live emulator during this work.

## Acceptance

- Every ADB client invocation from the CoC adapter uses port `5038`, regardless of the user's global ADB environment.
- `kill-server` and `start-server` cannot target the default `5037` server.
- Device scanning can restore the saved localhost MuMu endpoint without selecting a device automatically.
- Existing serial validation, entity-device refusal, and bounded retry behavior remain intact.
- Tests and a later real-runtime check are reported separately; source tests alone do not establish live battle stability.
