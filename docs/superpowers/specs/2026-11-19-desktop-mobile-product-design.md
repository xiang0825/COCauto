# CoC Desktop Reliability and Mobile Control Design

> **历史方案，已被主线取代。** 手机控制已在 `8f5276a` 中移除；本文中的 Tkinter、手机配对和远程控制计划不是当前功能或支持路线。普通使用者请使用 Windows 发布 exe。

## Intent

Make the existing Windows CoC controller dependable during real matches, publish every verified release with matching source and a clear download, and then provide an Android app that can launch CoC on the phone and control the Windows agent without exposing the agent to the public internet.

## Why

The current implementation is a Python/Tkinter Windows application that controls Android devices through ADB. The real game is already an Android application. Replacing the working automation engine with a new Android implementation would duplicate battle recognition, task scheduling, and recovery logic before the desktop path is stable. A phone companion can run CoC on the phone while retaining the tested Windows engine and extending its device support to Android wireless debugging.

## Goals

- Keep task selection explicit: only selected tasks run; battle, settlement, return-home, disconnect, and recovery states remain distinct and observable.
- Recover from transient game and ADB interruptions without blind clicks, false battle results, or silently abandoning a selected task.
- Bound screenshot/log/model memory use and keep long-running process memory observable.
- Make the version displayed in the UI, executable, source tag, release notes, and downloaded package agree.
- Check the public GitHub Releases feed at desktop startup without blocking the Tk event loop, expose a manual check, and show an update notice with the release page when a newer build exists.
- Publish each verified Windows release to `xiang0825/COCauto` with source, package, and SHA-256; refresh the repository home page; after upload verification, remove obsolete local build/release copies while retaining the single runnable root package and user database.
- Build an Android phone app that launches the installed CoC app, pairs with the local Windows agent, shows robot/game state and recent logs, and offers explicit start/pause/stop controls.
- Check GitHub Releases when the Android app is opened or brought to the foreground and present a clear update notice; do not rely on scheduled tasks or silent installation.
- Validate battle outcomes from real logs and screenshots. Store strategy feedback only when supported by observed deployment and results; never fabricate results or present a short run as a long-term guarantee.

## Non-goals

- Copying source code, graphics, or branding from MaaAssistantArknights or Kazumi.
- Moving the automation into a public cloud service or opening a router port.
- Claiming that tests alone prove real-game reliability.
- Silently installing updates or starting automation after a reboot.

## Approaches considered

1. **Recommended: staged Windows agent plus Android companion.** Keep the current Python battle engine and expose a small authenticated local-network control API. A Flutter Android app launches CoC on the phone and controls a paired Windows agent; the agent uses ADB over Wi-Fi. This keeps one battle engine and makes real-game phone testing possible without porting the full image-recognition stack.
2. **Port all automation to Android.** Reimplement the scheduler, OpenCV/OCR pipeline, game-state guards, and battle recovery in a native Android service. This removes the Windows dependency but duplicates a large, currently changing system and creates accessibility, foreground-service, and device-compatibility risks before the existing engine is stable.
3. **Remote desktop only.** Reuse screen mirroring and remote-control software. This is quickest but does not provide a focused CoC app, release-aware updates, or reliable task-state controls.

The user delegated implementation choices and asked for the whole program to be completed. Approach 1 is selected for the first mobile deliverable; the Android UI will use Flutter, with a small Kotlin bridge for launching CoC and Android-specific integration. The Windows agent remains the source of truth for battle execution and task state.

## Constraints

- Do not use scheduled tasks.
- Do not stop a healthy active robot merely to run a build; stage builds separately and change the installed release only at a safe, verified handoff.
- Do not click uncertain game screens.
- The LAN API must require a paired secret, bind only to the selected local interface, and reject unauthenticated control requests.
- Phone-to-agent pairing and Android Wireless Debugging authorization are separate steps. Pairing uses a short-lived one-time code, a QR-provided TLS certificate fingerprint, a random revocable token stored with Windows DPAPI/Android Keystore, and one explicit Windows robot/device binding.
- The desktop's selected robot and saved task plan are authoritative. The phone may start, pause, or stop that plan but may not silently change tasks or target another device.
- A phone-to-agent network loss leaves an already-running desktop task under desktop control and marks phone status stale; an ADB/device loss causes the agent's safe recovery path to wait for a confirmed screen before further game input.
- Commands share one serialized state machine; stale state revisions are rejected and pause/stop take priority over queued starts.
- The Android app may launch CoC only when the game is installed; it must explain when the Windows agent or ADB pairing is unavailable.
- Release ZIPs include the EXE and adjacent `_internal` runtime; the standalone EXE is not portable by itself.
- Update checks use short network timeouts and fail quietly offline; downloading/installing remains user-confirmed and occurs after the running app closes.
- Keep the current project license and third-party notices; use the references for architecture and UX patterns only.

## Reference patterns

- MaaAssistantArknights uses image recognition and task-oriented modules and offers explicit documentation, releases, and multiple integration interfaces. Apply the modular task boundaries, state visibility, and release discipline to CoC without importing its game-specific implementation.
- Kazumi uses Flutter with separate platform directories and publishes through releases across mobile and desktop. Apply its app/release structure and foreground update-notice pattern; do not copy its code or assets.

## Acceptance criteria

### Windows reliability and release

- The branch includes the current remote `main` history and the retained local work; no user changes are discarded.
- All selected-task, battle-entry, result, return-home, disconnect, timeout, and resource-full regressions are covered and pass in the supported test suite.
- The packaged-module verifier confirms required deferred imports and runtime files; the packaged app opens and displays the same version as its package metadata.
- Online startup check detects a newer published release and offline startup keeps the UI responsive without an error dialog.
- The actual MuMu screen and database logs agree through at least five consecutive attack/return cycles on the current game UI, with no unreviewed page clicks, false results, or unexplained task stop. Any transient disconnect must be visible and recovered or explicitly reported.
- A release has a matching Git commit/tag, README download link, ZIP, SHA-256, and release notes. The package is downloaded or hashed back from GitHub to verify the uploaded artifact.
- After release verification, generated build directories and superseded local package copies are removed; the user's DB and one current root executable/runtime remain intact.

### Android app

- The Android project builds an installable APK and launches an installed CoC package.
- Pairing with the Windows agent is explicit and authenticated; pairing loss and offline states are visible.
- Start, pause, stop, and recent task status/log messages operate on the selected robot and are reflected in both clients.
- The first mobile public release must complete five consecutive real attack/settlement/return cycles on an Android handset using Wireless Debugging; emulator-only smoke testing is a preview, not device-compatibility proof.
- The phone app checks GitHub Releases when opened or resumed, then displays a system/in-app update notice with version, notes, and a user-confirmed download/install path. It does not use periodic background jobs or silently install APKs.
- Android smoke checks cover install/start/stop, reconnection, denied notification permission, and an unavailable Windows agent. A real phone run remains necessary before claiming device compatibility.

## Open implementation decisions

The current Windows package and Python engine are kept as the first milestone. Exact LAN API shape, Android minimum SDK, and update package format may be chosen during implementation after checking the available Android toolchain; choices must preserve the acceptance criteria and avoid new infrastructure credentials.
