# KiteBar — macOS app packaging & distribution design

**Date**: 2026-07-17
**Status**: Approved by Shameem (conversation, 2026-07-17)

## Goal

Turn the single-file Python menu bar app (`zerodha_bar.py`) into a native,
self-contained `KiteBar.app` that Apple Silicon (M-series) Mac users can
install without Python, either by downloading a `.dmg` from GitHub Releases
on `shameemshah/kitebar` or via Homebrew:

```sh
brew install --cask shameemshah/tap/kitebar
```

## Decisions (settled with user)

| Decision | Choice |
|---|---|
| Code signing | **Unsigned** (ad-hoc signature only). No Apple Developer ID. Document the Gatekeeper bypass. Structure the build so real signing can be added later via env vars. |
| Homebrew path | **Personal tap** `shameemshah/homebrew-tap`. Official homebrew/cask submission deferred until the repo meets notability rules. |
| GitHub repo | Existing empty repo `shameemshah/kitebar` becomes `origin` for this project. |
| Build tool | **py2app** (standard for rumps/PyObjC menu bar apps). |
| Architecture | **arm64 only** (Apple Silicon). Built on free `macos-14` GitHub Actions runners. |
| Existing user data | **Automatic migration** from the old ZerodhaBar names — no re-entering credentials. |

## 1. Rename ZerodhaBar → KiteBar

File `zerodha_bar.py` is renamed `kitebar.py` (git mv). Inside it:

- `APP_NAME = "KiteBar"`.
- Bundle identifier / LaunchAgent label: `com.shameemshah.kitebar`
  (replaces `com.zerodha.menubar`).
- Keychain service: `kitebar` (replaces `zerodha-menubar`).
- Data dir: `~/Library/Application Support/KiteBar` (replaces `.../ZerodhaBar`).

### One-time migration (runs at startup, silent, idempotent)

- Keychain: for each of `api_key` / `api_secret`, if the `kitebar` service
  has no value but `zerodha-menubar` does, copy it to `kitebar`. Old entries
  are left in place (harmless; deleting other apps' keychain items is riskier
  than leaving them).
- Files: if `~/Library/Application Support/KiteBar` does not exist and
  `~/Library/Application Support/ZerodhaBar` does, copy
  `access_token.json` and `settings.json` across (preserving the 600 mode
  on the token file).
- Old LaunchAgent: if `~/Library/LaunchAgents/com.zerodha.menubar.plist`
  exists, unload and remove it so two copies never autostart.

### Bundle awareness

- **Assets**: when frozen by py2app the environment variable `RESOURCEPATH`
  points at `KiteBar.app/Contents/Resources`; load `menubar.png` /
  `appicon-256.png` from there. When run as a plain script, keep today's
  `assets/` next to the source file.
- **Launch at login**: when running inside the .app, the LaunchAgent's
  `ProgramArguments` is `["/usr/bin/open", "-a", <path to KiteBar.app>]`
  (resolved from the running bundle); as a plain script it keeps the current
  interpreter+script form.

## 2. Build setup (in `shameemshah/kitebar`)

- `setup.py` — py2app configuration:
  - `app=["kitebar.py"]`, `resources` = menubar/app icons.
  - plist: `CFBundleName=KiteBar`, `CFBundleIdentifier=com.shameemshah.kitebar`,
    `LSUIElement=True` (menu-bar only, no Dock icon),
    `CFBundleShortVersionString` from a single `VERSION` constant,
    `LSMinimumSystemVersion=11.0`, `LSArchitecturePriority=["arm64"]`.
  - `iconfile="build/KiteBar.icns"`.
- `scripts/make-icns.sh` — generates `KiteBar.icns` from
  `assets/appicon-512.png` using `sips` + `iconutil`.
- `scripts/build.sh` — end-to-end local/CI build:
  1. venv + `pip install -r requirements.txt py2app`
  2. make-icns
  3. `python setup.py py2app`
  4. ad-hoc sign: `codesign --force --deep -s - dist/KiteBar.app`
     (if `$CODESIGN_IDENTITY` is set, use it instead — future Developer ID hook)
  5. `hdiutil`-based dmg: `KiteBar-<version>.dmg` containing `KiteBar.app`
     and an `/Applications` symlink.
- `requirements.txt` unchanged; py2app is a build-only dependency.

## 3. Release automation — `.github/workflows/release.yml`

Trigger: push of tag `v*`.

Job on `macos-14` (arm64):
1. Checkout, set up Python 3.12 (pinned for py2app/PyObjC stability).
2. `scripts/build.sh` → `dist/KiteBar-<version>.dmg` (version parsed from tag).
3. Sanity checks: `.app` exists, binary is arm64, plist has LSUIElement.
4. `gh release create` with the dmg + generated notes.
5. Compute dmg sha256; check out `shameemshah/homebrew-tap` using secret
   `TAP_GITHUB_TOKEN`, rewrite `Casks/kitebar.rb` version+sha256, push.

`TAP_GITHUB_TOKEN`: fine-grained PAT, write access to `homebrew-tap` only.
Setup steps documented in the README's release section. If the secret is
missing, the tap-update step is skipped with a warning (release still works;
cask can be bumped by hand).

## 4. Tap repo — `shameemshah/homebrew-tap`

New public repo containing `Casks/kitebar.rb`:

```ruby
cask "kitebar" do
  version "X.Y.Z"
  sha256 "…"
  url "https://github.com/shameemshah/kitebar/releases/download/v#{version}/KiteBar-#{version}.dmg"
  name "KiteBar"
  desc "Live P&L of your Zerodha holdings in the macOS menu bar"
  homepage "https://github.com/shameemshah/kitebar"

  depends_on arch: :arm64
  depends_on macos: ">= :big_sur"

  app "KiteBar.app"

  zap trash: [
    "~/Library/Application Support/KiteBar",
    "~/Library/LaunchAgents/com.shameemshah.kitebar.plist",
  ]

  caveats <<~EOS
    KiteBar is not notarized (no Apple Developer subscription). On first
    launch macOS may refuse to open it. Either install with
      brew install --cask shameemshah/tap/kitebar --no-quarantine
    or right-click KiteBar.app → Open → Open.
  EOS
end
```

## 5. Repo wiring & docs

- `git remote add origin git@github.com:shameemshah/kitebar.git`, push `main`.
- README: rewritten install section — brew one-liner first, direct dmg
  download second, Gatekeeper note; current venv instructions move to a
  "Run from source / development" section. Keychain service and paths in the
  docs updated to the new names. Release-process section for maintainers
  (tag → workflow does the rest).
- CHANGELOG entry; first release tagged `v1.0.0`.

## Error handling

- Migration failures (Keychain denied, file copy error) are logged and
  skipped — the app then behaves like a fresh install rather than crashing.
- Build script fails fast (`set -euo pipefail`) with clear messages.
- CI verifies the built binary is arm64 Mach-O before releasing.

## Testing

- Local: run `kitebar.py` as a script (dev mode still works); build the .app
  locally, launch it, confirm menu bar item, login flow, icons, no Dock icon.
- Migration: verified on this Mac — existing `zerodha-menubar` Keychain
  entries and ZerodhaBar token are picked up without re-login.
- CI: workflow's sanity checks; then install the published cask end-to-end
  (`brew install --cask shameemshah/tap/kitebar --no-quarantine`).

## Out of scope

- Intel (x86_64) or universal builds.
- Notarization / Developer ID signing (hooks left in place).
- Submission to official homebrew/cask.
- Any feature/UI changes to the app itself.

## Open items for the user

- Create the `TAP_GITHUB_TOKEN` secret (instructions will be provided).
- Confirm the Kite Connect redirect URL note stays accurate (unchanged).
