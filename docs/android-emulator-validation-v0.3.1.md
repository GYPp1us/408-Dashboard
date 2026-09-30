# Android emulator validation v0.3.1

Status: API 36 viewport, real-touch, notification, and signed install-r checks passed. API 35 results are recorded separately and its accelerated reminder acknowledgement chain is still being completed. The install-r smoke ran against production v0.3.0 before the v0.3.1 deployment; it does not claim that v0.3.1 is live on the public server.

## Build and package

- Version: `versionCode=4`, `versionName=0.3.1`; package `com.mutsumi.focus`.
- Debug build: `testDebugUnitTest` passed (14 tests, 0 failures); `lintDebug` and `assembleDebug` succeeded.
- Release build: `lintRelease` and `assembleRelease` succeeded using production defaults. Debug and release lint each reported 30 warnings and 0 errors.
- Signed artifact: [`artifacts/Mutsumi-Focus-v0.3.1.apk`](../artifacts/Mutsumi-Focus-v0.3.1.apk), SHA-256 `DA73FFEC7AFB27A957FF9E7C4EE4CEAEBE952447D81578F959533E52DF7D5453`.
- The release signer SHA-256 is `8fb58fd11708b42567aadfecc2c570f643d0f4fb9634d7a7e8a9059b27a42f52`, matching the repository's recorded release certificate fingerprint. The APK is non-debuggable and contains no localhost URL or emulator test CA material; generated production configuration uses `https://platform.arcol.site/`.
- Debug UI/notification regressions used the isolated HTTPS fixture at `https://localhost:43128/`. The signed Release APK was later installed in place on the API 36 emulator for a read-only pre-deployment bootstrap against the production-configured origin; it was not installed on a production/user device, and no credentials or mutating controls were used.

## Emulator setup

- API 36: AVD `MutsumiDashboardApi36`, serial `emulator-5560`. Landscape checks used `3168x1440` at physical density 420; the override has since been reset. Final state is the recorded original physical `1080x2400`, density 420, accelerometer rotation enabled, user rotation 0 (`.tmp/v031-api36-display-original.txt`).
- API 35: AVD `MutsumiAgentApi35Codex`, serial `emulator-5556`; that device is owned by the API 35 validation run. Its independent results are in [the API 35 note](android35-validation-v0.3.1.md).
- API 36 Debug QA used the isolated HTTPS fixture at `https://localhost:43128/` with `adb reverse tcp:43128 tcp:43128`; fixture data is `.tmp/v031-android-fixture.sqlite3`. The Debug app was left idle with no FocusService running. Its notification permission was restored to granted and `SYSTEM_ALERT_WINDOW` app-op to default. The Release app's pre-existing notification permission remained denied through install-r.

## API 36 landscape and route checks

All accepted checks below were repeated after the viewport correction with a fresh page load and physical emulator captures. Earlier cropped screenshots and half-scale touch attempts are diagnostic only and are discarded.

- At landscape `3168x1440`, WebView `innerWidth=1207` and `visualViewport=1207.238x462.095` CSS px at scale 1. The three dashboard panels fit within that viewport (`scrollWidth=1207`); accepted full-screen evidence is `.tmp/v031/android36-landscape-3168x1440-home-physical.png`.
- Native long-press on a focus row and on the index card opened right-anchored drawers. Each drawer occupied the right half of the visible viewport (`x=603.625..1207.238`, width `603.613` CSS px, bottom `462.095`). Android Back closed the drawer and retained the current route. The index drawer showed both daily and intraday charts, parameters, and visible `00:00`/`24:00` endpoint labels. Evidence: `.tmp/v031/android36-focus-drawer-physical.png` and `.tmp/v031/android36-index-drawer-final-physical.png`.
- The focus-kline route fit the visible width without horizontal overflow (`scrollWidth=1207`, chart bounds within `x=23.762..1183.476`); its longer content remains vertically scrollable (`scrollHeight=1302`). Returning to the home route worked. Evidence: `.tmp/v031/android36-focus-kline-final-physical.png`.
- The account settings route `?tab=account` survived rotation from landscape to portrait (`520x1125` CSS px) and back (`1207x462`), with scale 1 and no horizontal overflow. A synthetic local DOM layout with eight focus cards resolved to two columns and fit the compact controls panel; this checks responsive capacity, not an eight-item backend configuration. Evidence: `.tmp/v031/android36-settings-account-portrait-final-physical.png` and `.tmp/v031/android36-eight-quickfocus-final-physical.png`.
- Native photo-picker cancellation returned to the artwork drawer with no selected file and left its saved preview unchanged; Back then closed the drawer. A physical two-finger chart pinch did not zoom the WebView (`visualViewport.scale=1`) or change the full-day logical range (`-0.5..1440.5`).
- The chart displayed its full-day axis (`00:00` to `24:00`) and current-time marker. At `2026-09-30T12:28:49+08:00`, the fixture live API reported `market_active=false`, quote `10.78`, and `per_second=0`; the quote stayed `10.78` during observation. A separate controlled client-side live-tick probe advanced `100.000` to `100.034` in about 2.2 seconds. That probe checks client-side ticks only; server market behavior is covered by the API response. Axis evidence: `.tmp/v031/android36-final-chart-axis-physical.png`.

## API 36 notification checks

- All 17 scripted checks passed on a fresh run. With notification permission denied, the foreground timer survived; after granting it, the notification exposed a chronometer and API 36 `ProgressStyle` metadata. The app requests promoted ongoing status and declares `POST_PROMOTED_NOTIFICATIONS`, though this SystemUI run reported `promotedOngoing=false`.
- Real native notification Pause, Continue, and End actions matched the server and native preference state. Web pause/overlay resume also updated native state, and a 17-second background heartbeat kept the focus session active.
- The paused five-minute reminder appeared; tapping it opened the activity and set a five-minute snooze. Resuming cleared the due reminder. The isolated fixture backdated an ended session to the 60-minute threshold; actual taps on the resulting 15-, 30-, and 60-minute reminder sequence advanced acknowledgement counters to 1, 2, and 3. These were accelerated threshold checks, not 60 minutes of wall-clock waiting. After the final acknowledgement, the focus service and focus/reminder notifications stopped. Rest mode produced no reminder and returned to idle. No WebView runtime exceptions were recorded.
- The full fresh result list is `.tmp/v031/android-notifications-results.json`; raw notification captures are in `.tmp/v031/android36-live-notification.txt` and `.tmp/v031/android36-notification-final.txt`.

## Signed install-r smoke before deployment

- The emulator already had signed v0.3.0 installed (`versionCode=3`, `versionName=0.3.0`). Before updating, it had no active FocusService or focus/reminder notification. Its app data directory was `/data/user/0/com.mutsumi.focus`, and its original `firstInstallTime` was `2026-09-29 10:11:18`.
- `adb install -r artifacts/Mutsumi-Focus-v0.3.1.apk` succeeded without uninstalling or clearing data. Package Manager now reports `versionCode=4`, `versionName=0.3.1`, the same app data directory and unchanged first-install time; the pre-existing notification permission remained denied. Android accepted the in-place update over the existing package, confirming signer compatibility with the recorded release certificate.
- Cold launches before and after the update showed the guest-only `本日总结` / `今日有效学习` dashboard branch, with `休息时间` and `准备开始下一段专注`; the advancing value was the page clock, not an active focus session. `com.mutsumi.focus` had no FocusService and no focus/reminder notification before or after the update. No credentials were submitted and no focus/session/data-changing controls were used. Release WebView remote debugging is disabled, so the exact URL path could not be read; the rendered guest-only branch verifies the landing identity. The page was loaded from the production-configured APK while the public server was still v0.3.0 (`d08a559a`), so this is a pre-deployment bootstrap check, not post-deployment UI acceptance. Screenshots: `.tmp/v031/android36-release-v030-before-physical.png` and `.tmp/v031/android36-release-v031-after-physical.png`.

For browser and shared frontend results, see [frontend validation](frontend-validation-v0.3.1.md). The API 35 device has a separate record at [android35-validation-v0.3.1.md](android35-validation-v0.3.1.md); its reminder acknowledgement chain is still pending there.
