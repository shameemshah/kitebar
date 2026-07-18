# KiteBar macOS App Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the rumps menu bar app as a self-contained `KiteBar.app` (Apple Silicon only), released as a dmg on `shameemshah/kitebar` and installable via `brew install --cask shameemshah/tap/kitebar`.

**Architecture:** Rename ZerodhaBar→KiteBar inside the single-file app with silent data migration; add a py2app build (`setup.py` + shell scripts) that produces an ad-hoc-signed .app in a dmg; a tag-triggered GitHub Actions workflow on an M-series runner creates the release and bumps the cask in a new `shameemshah/homebrew-tap` repo.

**Tech Stack:** Python 3.12 (build), py2app, rumps/PyObjC, `sips`+`iconutil` (icns), `hdiutil` (dmg), GitHub Actions `macos-14`, Homebrew cask, `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-07-17-kitebar-mac-app-packaging-design.md`

## Global Constraints

- App name: `KiteBar`; source file: `kitebar.py`; bundle ID / LaunchAgent label: `com.shameemshah.kitebar`.
- New Keychain service: `kitebar`; old (migrate from, never delete): `zerodha-menubar`.
- New data dir: `~/Library/Application Support/KiteBar`; old: `~/Library/Application Support/ZerodhaBar`.
- arm64 only; `LSMinimumSystemVersion` 11.0; `LSUIElement` true (no Dock icon).
- Unsigned: ad-hoc `codesign -s -` unless `$CODESIGN_IDENTITY` is set.
- Single version source: `VERSION = "1.0.0"` constant in `kitebar.py`; tags are `v<VERSION>`.
- GitHub repos: app `shameemshah/kitebar` (exists, empty), tap `shameemshah/homebrew-tap` (to create).
- Migration must be silent, idempotent, and never crash the app (every stage wrapped, failures ignored).
- This is a GUI/packaging project with no pytest suite; each task's test cycle is the concrete verification commands given in its steps.

---

### Task 1: Rename ZerodhaBar → KiteBar with data migration and bundle awareness

**Files:**
- Rename: `zerodha_bar.py` → `kitebar.py` (`git mv`)
- Modify: `kitebar.py` (constants block ~lines 30–65, `_notify` ~line 1453, `on_toggle_launch` ~line 1411, `__main__` ~line 1480, login HTML strings ~lines 238/315/322)

**Interfaces:**
- Produces: `VERSION = "1.0.0"` module constant (regex-read by Task 2's `setup.py` and Task 3's `build.sh` as `^VERSION = "([^"]+)"`), `migrate_from_zerodhabar()` called from `__main__`, bundle-aware `RESOURCEPATH` handling.

- [ ] **Step 1: git mv the file**

```bash
git mv zerodha_bar.py kitebar.py
```

- [ ] **Step 2: Update the constants block**

In `kitebar.py`, replace the constants (currently lines 34–62) so they read:

```python
APP_NAME = "KiteBar"
VERSION = "1.0.0"
BUNDLE_ID = "com.shameemshah.kitebar"
KEYRING_SERVICE = "kitebar"                  # Keychain service name
IST = ZoneInfo("Asia/Kolkata")

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8000
CALLBACK_PATH = "/callback"
LOGIN_WAIT_SECONDS = 300                     # how long the local server waits

POLL_SECONDS = 5                             # market-hours refresh cadence
WAKE_GAP_SECONDS = 120                       # tick gap that means "slept"
MF_REFRESH_SECONDS = 1800                    # MF NAVs move once a day
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
TOKEN_EXPIRY_HOUR = 6                        # tokens die ~6 AM IST daily


def _resources_dir():
    """py2app sets RESOURCEPATH to KiteBar.app/Contents/Resources."""
    rp = os.environ.get("RESOURCEPATH")
    if rp:
        return os.path.join(rp, "assets")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _bundle_path():
    """Path to KiteBar.app when running frozen (py2app), else None."""
    rp = os.environ.get("RESOURCEPATH")
    if not rp:
        return None
    return os.path.dirname(os.path.dirname(rp))


ASSETS_DIR = _resources_dir()
MENUBAR_ICON = os.path.join(ASSETS_DIR, "menubar.png")
APP_ICON = os.path.join(ASSETS_DIR, "appicon-256.png")

APP_SUPPORT = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
TOKEN_FILE = os.path.join(APP_SUPPORT, "access_token.json")
SETTINGS_FILE = os.path.join(APP_SUPPORT, "settings.json")

AUTO_LOGIN_COOLDOWN = 600     # never auto-open the browser more than 1/10 min

LAUNCH_AGENT_LABEL = BUNDLE_ID
LAUNCH_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist"
)

# Pre-rename (ZerodhaBar) names — read once at startup for migration.
OLD_KEYRING_SERVICE = "zerodha-menubar"
OLD_APP_SUPPORT = os.path.expanduser("~/Library/Application Support/ZerodhaBar")
OLD_LAUNCH_AGENT_LABEL = "com.zerodha.menubar"
OLD_LAUNCH_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{OLD_LAUNCH_AGENT_LABEL}.plist"
)
```

Keep `FAILURES_BEFORE_WARNING` and `PRIVATE_MASK` as they are.

- [ ] **Step 3: Add `import shutil` and the migration function**

Add `shutil` to the stdlib import block (alphabetical: after `plistlib`). Then add after the constants block:

```python
def migrate_from_zerodhabar():
    """One-time silent migration from the old ZerodhaBar names.

    Each stage is independent and idempotent; failures never block startup —
    the app just behaves like a fresh install.
    """
    try:  # Keychain: copy forward, never delete the old entries
        for key in ("api_key", "api_secret"):
            if not keyring.get_password(KEYRING_SERVICE, key):
                old = keyring.get_password(OLD_KEYRING_SERVICE, key)
                if old:
                    keyring.set_password(KEYRING_SERVICE, key, old)
    except Exception:  # noqa: BLE001
        pass
    try:  # token + settings files
        if not os.path.isdir(APP_SUPPORT) and os.path.isdir(OLD_APP_SUPPORT):
            os.makedirs(APP_SUPPORT, exist_ok=True)
            for name in ("access_token.json", "settings.json"):
                src = os.path.join(OLD_APP_SUPPORT, name)
                dst = os.path.join(APP_SUPPORT, name)
                if os.path.exists(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
            if os.path.exists(TOKEN_FILE):
                os.chmod(TOKEN_FILE, 0o600)
    except Exception:  # noqa: BLE001
        pass
    try:  # old LaunchAgent: remove so two copies never autostart
        if os.path.exists(OLD_LAUNCH_AGENT_PLIST):
            subprocess.run(
                ["launchctl", "bootout",
                 f"gui/{os.getuid()}/{OLD_LAUNCH_AGENT_LABEL}"],
                capture_output=True, check=False)
            os.remove(OLD_LAUNCH_AGENT_PLIST)
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 4: Call migration from `__main__`**

```python
if __name__ == "__main__":
    if "--set-credentials" in sys.argv:
        set_credentials_cli()
    else:
        migrate_from_zerodhabar()
        KiteBarApp().run()
```

- [ ] **Step 5: Rename the class and user-visible strings**

- `class ZerodhaBarApp(rumps.App):` → `class KiteBarApp(rumps.App):`
- In the login-page HTML/messages (lines ~238, ~315, ~322): `ZerodhaBar` → `KiteBar`.
- In `_notify` (~line 1453): `rumps.notification("Zerodha", ...)` → `rumps.notification("KiteBar", ...)`.
- Module docstring: retitle to `KiteBar — Zerodha holdings in the macOS menu bar.` keeping the free-plan explanation; update `Run:  python3 kitebar.py`.
- Grep to confirm nothing is left: `grep -n "ZerodhaBar\|zerodha_bar\|com.zerodha.menubar" kitebar.py` must return nothing (`zerodha-menubar` remains only as `OLD_KEYRING_SERVICE`).

- [ ] **Step 6: Make Launch at login bundle-aware**

In `on_toggle_launch`, replace the `ProgramArguments` line:

```python
                bundle = _bundle_path()
                program = (["/usr/bin/open", "-a", bundle] if bundle
                           else [sys.executable, os.path.abspath(__file__)])
                payload = {
                    "Label": LAUNCH_AGENT_LABEL,
                    "ProgramArguments": program,
                    "RunAtLoad": True,
                    "KeepAlive": False,
                    "StandardOutPath": os.path.join(APP_SUPPORT, "agent.log"),
                    "StandardErrorPath": os.path.join(APP_SUPPORT, "agent.log"),
                }
```

- [ ] **Step 7: Verify as a plain script**

```bash
python3 -c "import ast; ast.parse(open('kitebar.py').read())" && echo SYNTAX-OK
.venv/bin/python kitebar.py &   # launch, watch the menu bar
```

Expected: menu bar item appears; because migration copied the old Keychain entries and token, holdings load **without** any login prompt. Check migration results:

```bash
ls ~/Library/Application\ Support/KiteBar/          # access_token.json settings.json
security find-generic-password -s kitebar -a api_key >/dev/null && echo KEYCHAIN-OK
test ! -f ~/Library/LaunchAgents/com.zerodha.menubar.plist && echo OLD-AGENT-GONE
```

Then quit the app from its menu.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "Rename ZerodhaBar to KiteBar with silent data migration"
```

---

### Task 2: Icon pipeline and py2app setup

**Files:**
- Create: `scripts/make-icns.sh`
- Create: `setup.py`
- Modify: `.gitignore` (add `build/`, `dist/`)

**Interfaces:**
- Consumes: `VERSION` constant in `kitebar.py` (Task 1).
- Produces: `scripts/make-icns.sh` → `build/KiteBar.icns`; `setup.py` py2app config used by Task 3's `scripts/build.sh` (`python3 setup.py py2app` → `dist/KiteBar.app`).

- [ ] **Step 1: Write `scripts/make-icns.sh`**

```bash
#!/usr/bin/env bash
# Generate build/KiteBar.icns from assets/appicon-512.png (sips + iconutil).
set -euo pipefail
cd "$(dirname "$0")/.."

SRC=assets/appicon-512.png
SET=build/KiteBar.iconset
mkdir -p "$SET"

for sz in 16 32 128 256 512; do
  sips -z "$sz" "$sz" "$SRC" --out "$SET/icon_${sz}x${sz}.png" >/dev/null
done
for sz in 16 32 128 256; do
  dbl=$((sz * 2))
  sips -z "$dbl" "$dbl" "$SRC" --out "$SET/icon_${sz}x${sz}@2x.png" >/dev/null
done

iconutil -c icns "$SET" -o build/KiteBar.icns
rm -rf "$SET"
echo "Wrote build/KiteBar.icns"
```

```bash
chmod +x scripts/make-icns.sh
```

- [ ] **Step 2: Run it and verify**

```bash
scripts/make-icns.sh && file build/KiteBar.icns
```

Expected: `build/KiteBar.icns: Mac OS X icon, ...`

- [ ] **Step 3: Write `setup.py`**

```python
"""py2app build config: python3 setup.py py2app  ->  dist/KiteBar.app"""
import re

from setuptools import setup

with open("kitebar.py") as fh:
    VERSION = re.search(r'^VERSION = "([^"]+)"', fh.read(), re.M).group(1)

OPTIONS = {
    "iconfile": "build/KiteBar.icns",
    "resources": ["assets"],
    "packages": ["rumps", "kiteconnect", "keyring"],
    "plist": {
        "CFBundleName": "KiteBar",
        "CFBundleDisplayName": "KiteBar",
        "CFBundleIdentifier": "com.shameemshah.kitebar",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,
        "LSMinimumSystemVersion": "11.0",
        "LSArchitecturePriority": ["arm64"],
        "NSHumanReadableCopyright": "MIT License — not affiliated with Zerodha",
    },
}

setup(
    name="KiteBar",
    version=VERSION,
    app=["kitebar.py"],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
```

- [ ] **Step 4: Ignore build outputs**

Append to `.gitignore`:

```
build/
dist/
```

- [ ] **Step 5: Commit**

```bash
git add scripts/make-icns.sh setup.py .gitignore
git commit -m "Add icns pipeline and py2app setup"
```

---

### Task 3: Build script — .app, ad-hoc signature, dmg

**Files:**
- Create: `scripts/build.sh`

**Interfaces:**
- Consumes: `scripts/make-icns.sh`, `setup.py` (Task 2), `VERSION` regex (Task 1).
- Produces: `dist/KiteBar.app` and `dist/KiteBar-<VERSION>.dmg` — exact names Task 4's workflow and Task 5's cask depend on. Honors `$CODESIGN_IDENTITY` (default ad-hoc `-`).

- [ ] **Step 1: Write `scripts/build.sh`**

```bash
#!/usr/bin/env bash
# Build dist/KiteBar.app and dist/KiteBar-<version>.dmg.
# Run inside a venv (or CI python) that can take pip installs.
# Set CODESIGN_IDENTITY to a Developer ID to really sign; default is ad-hoc.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import re; print(re.search(r'^VERSION = \"([^\"]+)\"', open('kitebar.py').read(), re.M).group(1))")
echo "Building KiteBar ${VERSION}"

rm -rf build dist
scripts/make-icns.sh

python3 -m pip install --quiet -r requirements.txt py2app setuptools
python3 setup.py py2app

APP=dist/KiteBar.app
codesign --force --deep --sign "${CODESIGN_IDENTITY:--}" "$APP"
codesign --verify --deep "$APP" && echo "Signature OK"

STAGING=$(mktemp -d)
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
DMG="dist/KiteBar-${VERSION}.dmg"
hdiutil create -volname "KiteBar" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
rm -rf "$STAGING"

echo "Built $DMG"
```

```bash
chmod +x scripts/build.sh
```

- [ ] **Step 2: Run a full local build**

```bash
source .venv/bin/activate.fish 2>/dev/null || source .venv/bin/activate
scripts/build.sh
```

Expected: ends with `Built dist/KiteBar-1.0.0.dmg`. (If py2app fails on the local Python 3.14, note it and rely on the CI build with 3.12 — but attempt the fix first: py2app ≥0.28.9 supports recent Pythons.)

- [ ] **Step 3: Verify the bundle**

```bash
file dist/KiteBar.app/Contents/MacOS/KiteBar            # ... arm64
/usr/libexec/PlistBuddy -c 'Print :LSUIElement' dist/KiteBar.app/Contents/Info.plist   # true
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' dist/KiteBar.app/Contents/Info.plist  # com.shameemshah.kitebar
ls dist/KiteBar.app/Contents/Resources/assets/menubar.png
open dist/KiteBar.app
```

Expected: app launches from the bundle — menu bar icon appears, **no Dock icon**, dropdown shows holdings (token migrated in Task 1). Quit from the menu.

- [ ] **Step 4: Commit**

```bash
git add scripts/build.sh
git commit -m "Add build script: py2app bundle, ad-hoc sign, dmg"
```

---

### Task 4: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `scripts/build.sh` (Task 3); tag format `v<VERSION>`.
- Produces: GitHub Release with `KiteBar-<version>.dmg`; pushes version+sha256 bump to `shameemshah/homebrew-tap:Casks/kitebar.rb` (Task 6's file) when secret `TAP_GITHUB_TOKEN` exists, else warns and skips.

- [ ] **Step 1: Write `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  build-release:
    runs-on: macos-14   # Apple Silicon runner
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Check tag matches VERSION
        run: |
          VERSION=$(python3 -c "import re; print(re.search(r'^VERSION = \"([^\"]+)\"', open('kitebar.py').read(), re.M).group(1))")
          if [ "v${VERSION}" != "${GITHUB_REF_NAME}" ]; then
            echo "Tag ${GITHUB_REF_NAME} does not match VERSION ${VERSION} in kitebar.py"
            exit 1
          fi

      - name: Build app and dmg
        run: scripts/build.sh

      - name: Sanity-check bundle
        run: |
          test -d dist/KiteBar.app
          file dist/KiteBar.app/Contents/MacOS/KiteBar | grep -q arm64
          /usr/libexec/PlistBuddy -c 'Print :LSUIElement' dist/KiteBar.app/Contents/Info.plist | grep -q true
          ls dist/KiteBar-*.dmg

      - name: Create GitHub release
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release create "${GITHUB_REF_NAME}" dist/KiteBar-*.dmg --generate-notes

      - name: Update Homebrew tap
        env:
          TAP_TOKEN: ${{ secrets.TAP_GITHUB_TOKEN }}
        run: |
          if [ -z "${TAP_TOKEN}" ]; then
            echo "::warning::TAP_GITHUB_TOKEN not set — skipping tap update. Bump Casks/kitebar.rb manually."
            exit 0
          fi
          VERSION="${GITHUB_REF_NAME#v}"
          SHA=$(shasum -a 256 "dist/KiteBar-${VERSION}.dmg" | awk '{print $1}')
          git clone "https://x-access-token:${TAP_TOKEN}@github.com/shameemshah/homebrew-tap.git" tap
          cd tap
          sed -i '' \
            -e "s|^  version \".*\"|  version \"${VERSION}\"|" \
            -e "s|^  sha256 \".*\"|  sha256 \"${SHA}\"|" \
            Casks/kitebar.rb
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git commit -am "kitebar ${VERSION}"
          git push
```

- [ ] **Step 2: Lint the workflow locally**

```bash
python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/release.yml')); print('YAML-OK')"
```

Expected: `YAML-OK` (install pyyaml into the venv if missing). Real verification happens in Task 7 when the tag is pushed.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "Add tag-triggered release workflow (build, release, tap bump)"
```

---

### Task 5: README, CHANGELOG, and repo push

**Files:**
- Modify: `README.md` (install/first-run/troubleshooting/launch-at-login sections, badges, clone URL, script name)
- Modify: `CHANGELOG.md` (new 1.0.0 entry at top)
- Modify: `CONTRIBUTING.md` (script name `zerodha_bar.py` → `kitebar.py` if mentioned)

**Interfaces:**
- Consumes: install commands fixed by Tasks 3/4/6: `brew install --cask shameemshah/tap/kitebar`, dmg name `KiteBar-<version>.dmg`.

- [ ] **Step 1: Rewrite README install sections**

Rename the title to `# KiteBar` (keep the "Zerodha holdings in your menu bar" tagline). Replace the current **Install** section with:

````markdown
## Install

### Homebrew (recommended)

```sh
brew install --cask shameemshah/tap/kitebar --no-quarantine
```

`--no-quarantine` is needed because KiteBar isn't notarized (no Apple
Developer subscription — it's a free, open-source tool). Without it,
macOS will refuse to open the app until you right-click → Open → Open.

### Direct download

Grab `KiteBar-<version>.dmg` from the
[latest release](https://github.com/shameemshah/kitebar/releases/latest),
drag **KiteBar.app** to Applications, then on first launch
right-click the app → **Open** → **Open** (one-time Gatekeeper bypass), or:

```sh
xattr -d com.apple.quarantine /Applications/KiteBar.app
```

### Requirements

- Apple Silicon Mac (M1 or later), macOS 11+.
- A free Kite Connect app (see Prerequisites above) — takes 2 minutes.

### Run from source (development)

```sh
git clone https://github.com/shameemshah/kitebar.git
cd kitebar
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string "com.shameemshah.kitebar"' .venv/bin/Info.plist
.venv/bin/python kitebar.py
```
````

Also update throughout the README: `zerodha_bar.py` → `kitebar.py`, Keychain service `zerodha-menubar` → `kitebar`, paths `ZerodhaBar` → `KiteBar`, LaunchAgent `com.zerodha.menubar.plist` → `com.shameemshah.kitebar.plist`, platform badge → `macOS 11+ (Apple Silicon)`. Add a migration note: "Upgrading from the old ZerodhaBar script? KiteBar migrates your Keychain credentials and token automatically on first launch." Add a **Releasing (maintainers)** section:

````markdown
## Releasing (maintainers)

1. Bump `VERSION` in `kitebar.py`, update `CHANGELOG.md`, commit.
2. `git tag v<version> && git push origin main --tags`
3. The release workflow builds the dmg on an M-series runner, publishes the
   GitHub Release, and bumps the cask in `shameemshah/homebrew-tap`
   (requires the `TAP_GITHUB_TOKEN` repo secret — a fine-grained PAT with
   read/write **Contents** permission on `homebrew-tap` only).
````

- [ ] **Step 2: CHANGELOG entry**

Prepend to `CHANGELOG.md`:

```markdown
## 1.0.0 — 2026-07-17

- Renamed ZerodhaBar → **KiteBar**; existing Keychain credentials, token and
  settings migrate automatically on first launch.
- Native `KiteBar.app` (py2app, Apple Silicon only) — no Python needed.
- Distribution: dmg on GitHub Releases + Homebrew cask
  (`brew install --cask shameemshah/tap/kitebar`).
- Launch-at-login now points at the app bundle when running from KiteBar.app.
```

- [ ] **Step 3: Sweep remaining doc references**

```bash
grep -rn "zerodha_bar\|ZerodhaBar\|com.zerodha.menubar" README.md CONTRIBUTING.md CHANGELOG.md SECURITY.md
```

Fix every hit except historical CHANGELOG entries and the migration notes.

- [ ] **Step 4: Commit and push to the new origin**

```bash
git add -A && git commit -m "Rewrite docs for KiteBar: brew install, dmg, release process"
git remote add origin git@github.com:shameemshah/kitebar.git
git push -u origin main
```

Expected: push succeeds; https://github.com/shameemshah/kitebar shows the code.

---

### Task 6: Homebrew tap repo with the kitebar cask

**Files:**
- Create (new repo `shameemshah/homebrew-tap`): `Casks/kitebar.rb`, `README.md`

**Interfaces:**
- Consumes: dmg naming from Task 3 (`KiteBar-<version>.dmg`), release URL from Task 4.
- Produces: cask `kitebar` whose `version`/`sha256` lines match the exact `sed` patterns in Task 4's workflow (two-space indent, `version "..."` / `sha256 "..."`).

- [ ] **Step 1: Create the tap repo and cask**

Work in a scratch dir (not inside the kitebar repo):

```bash
gh repo create shameemshah/homebrew-tap --public --description "Homebrew tap for shameemshah's tools" --clone
cd homebrew-tap && mkdir Casks
```

`Casks/kitebar.rb` (sha256 placeholder `:no_check` is invalid with versions — use a zeroed literal; the release workflow or Task 7 replaces it before anyone installs):

```ruby
cask "kitebar" do
  version "1.0.0"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

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
    KiteBar is not notarized (no Apple Developer subscription). If you did
    not install with --no-quarantine, the first launch needs:
      right-click KiteBar.app -> Open -> Open
    or: xattr -d com.apple.quarantine /Applications/KiteBar.app
  EOS
end
```

`README.md`:

```markdown
# homebrew-tap

    brew install --cask shameemshah/tap/kitebar --no-quarantine
```

- [ ] **Step 2: Style-check the cask**

```bash
brew style Casks/kitebar.rb
```

Expected: no offenses (fix any it reports).

- [ ] **Step 3: Commit and push**

```bash
git add -A && git commit -m "Add kitebar cask" && git push -u origin main
```

---

### Task 7: First release — tag, CI run, cask sha, end-to-end brew install

**Files:**
- Modify (possibly): `homebrew-tap:Casks/kitebar.rb` (real sha256, if `TAP_GITHUB_TOKEN` isn't set up yet)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Ask the user to add TAP_GITHUB_TOKEN (or skip)**

Tell the user: create a fine-grained PAT at https://github.com/settings/personal-access-tokens/new — Resource owner `shameemshah`, Only select repositories → `homebrew-tap`, Repository permissions → Contents: Read and write. Then `gh secret set TAP_GITHUB_TOKEN --repo shameemshah/kitebar` (paste the token). If they defer, continue — Step 4 covers the manual bump.

- [ ] **Step 2: Tag and push**

```bash
git tag v1.0.0 && git push origin v1.0.0
```

- [ ] **Step 3: Watch the workflow**

```bash
gh run watch --repo shameemshah/kitebar --exit-status
```

Expected: job green; `gh release view v1.0.0 --repo shameemshah/kitebar` lists `KiteBar-1.0.0.dmg`. If the build fails, fix, delete the tag (`git tag -d v1.0.0; git push origin :v1.0.0`), re-tag.

- [ ] **Step 4: Ensure the cask has the real sha256**

If the tap-update step was skipped (no token):

```bash
cd ../homebrew-tap
curl -LO https://github.com/shameemshah/kitebar/releases/download/v1.0.0/KiteBar-1.0.0.dmg
shasum -a 256 KiteBar-1.0.0.dmg   # paste into Casks/kitebar.rb sha256
rm KiteBar-1.0.0.dmg
git commit -am "kitebar 1.0.0" && git push
```

- [ ] **Step 5: End-to-end install test**

```bash
brew install --cask shameemshah/tap/kitebar --no-quarantine
open /Applications/KiteBar.app
```

Expected: cask installs, app runs from /Applications with menu bar item and live holdings. Then clean up the duplicate (keep whichever copy the user prefers running):

```bash
brew uninstall --cask kitebar   # if the user prefers the source checkout
```

or keep it installed — user's call; ask at the end.

- [ ] **Step 6: Final commit of any fixes**

Any workflow/build fixes made during the release land on `main` with clear messages.
