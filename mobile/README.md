# CoCauto Android

CoCauto Android is the phone companion for the Windows CoC controller. It can
launch the CoC app installed on the phone and control the Windows robot's
already-selected task plan over the same private LAN. The Windows controller
remains responsible for task selection, battle recognition, and game input.

## Pair a phone with Windows

1. On Windows, open **手机控制**, select the computer's private LAN address,
   and press **启动手机控制**.
2. Generate the one-time pairing QR code. It expires within five minutes and
   can be used once.
3. On the phone, install and open CoCauto, then scan the QR code. Camera access
   is requested only after tapping the scan button; the manual paste option is
   also available.
4. The phone verifies the HTTPS certificate fingerprint in the QR code and
   stores the revocable access token in Android Keystore-backed storage.
5. Install CoC on the phone if needed. Use **启动部落冲突** to open it. The
   Windows agent still needs its selected Android device connected through ADB
   (including Wireless Debugging when controlling a phone).

The Windows service binds only to the chosen private interface. It does not
open a public listener or configure router forwarding. If Windows shows a
firewall prompt, inspect the app path and allow private-network access only
when it is the expected CoCauto controller; do not grant public-network access.

## Mobile controls

The dashboard shows the selected task plan, robot and ADB state, recent logs,
and the desktop version. Start, pause, and stop are sent to the bound robot with
the current state revision. A stale revision is rejected and never retried
automatically. If the phone loses LAN connectivity, the app marks the desktop
state stale and disables controls until a successful refresh.

Release checks run when the app opens or returns to the foreground. Update
notices link to the GitHub release page; downloading and installing remain
user-initiated. No scheduled background polling or silent installation is
used.

## Development

Requires the Flutter 3.50.0 stable SDK and Android SDK 36. From this directory:

```powershell
flutter pub get
flutter analyze
flutter test
flutter build apk --build-name=2026.11.23 --build-number=118
```

The Android bridge reports the app version as `<build-name>-rc<build-number>`;
for example, the command above reports `2026.11.23-rc118`, matching the
`v2026.11.23-rc118` GitHub tag convention. Use the release script from the
repository root when one is provided for the current release.
