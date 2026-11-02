"""KiteBarApp — the rumps status-bar application."""

import json
import os
import threading
import time
import webbrowser
from datetime import datetime
from http.server import HTTPServer

import keyring
import rumps
from kiteconnect import KiteConnect
from kiteconnect import exceptions as kex

from .. import launch_agent
from ..auth import _CallbackHandler, token_expiry
from ..constants import (
    APP_ICON,
    APP_SUPPORT,
    AUTO_LOGIN_COOLDOWN,
    CALLBACK_HOST,
    CALLBACK_PORT,
    FAILURES_BEFORE_WARNING,
    KEYRING_SERVICE,
    LOGIN_WAIT_SECONDS,
    MENUBAR_ICON,
    MF_REFRESH_SECONDS,
    POLL_SECONDS,
    PRIVATE_MASK,
    SETTINGS_FILE,
    TOKEN_FILE,
    WAKE_GAP_SECONDS,
)
from ..formatting import fmt_inr
from ..market import is_market_open, last_market_close, now_ist
from ..portfolio import eff_qty, position_state
from .cocoa import _MenuStateDelegate, activate_app, run_on_main_thread
from .theme import soft_red

class KiteBarApp(rumps.App):

    def __init__(self):
        super().__init__("₹ …", quit_button=None)
        if os.path.exists(MENUBAR_ICON):
            self.icon = MENUBAR_ICON
        os.makedirs(APP_SUPPORT, exist_ok=True)

        self.kite = None
        self.access_token_ok = False
        self.holdings = []
        self.positions = []
        self.mf_holdings = []
        self._last_mf_fetch = None
        self.last_fetch = None          # datetime of last successful fetch
        self.last_tick = now_ist()
        self.fail_count = 0
        self._fetching = False
        self._logging_in = False
        self._menu_open = False
        self._menu_dirty = False        # data arrived while menu was open
        self._row_refs = {}             # live labels for in-place ticks
        self.settings = self._load_settings()
        self._last_auto_login = None    # monotonic ts of last auto attempt

        # static action items (re-added on every menu rebuild)
        self.item_refresh = rumps.MenuItem("Refresh now", callback=self.on_refresh)
        self.item_login = rumps.MenuItem("Login", callback=self.on_login)
        self.item_launch = rumps.MenuItem("Launch at login",
                                          callback=self.on_toggle_launch)
        self.item_launch.state = launch_agent.is_installed()
        self.item_autologin = rumps.MenuItem("Auto-login on expiry",
                                             callback=self.on_toggle_autologin)
        self.item_autologin.state = bool(self.settings.get("auto_login", True))
        self.item_private = rumps.MenuItem("Private mode",
                                           callback=self.on_toggle_private)
        self.item_private.state = bool(self.settings.get("private_mode", False))
        self.item_filter = rumps.MenuItem("Show")
        self._filter_items = {}
        for key, title in (("all", "All"), ("equity", "Equity"),
                           ("mf", "Mutual funds")):
            child = rumps.MenuItem(title, callback=self.on_filter)
            self._filter_items[key] = child
            self.item_filter.add(child)
        self._sync_filter_checks()
        self.item_quit = rumps.MenuItem("Quit", callback=rumps.quit_application)
        self.item_status = rumps.MenuItem("Starting…")

        try:
            # NSMenu auto-disables items without an action, which renders all
            # info rows dimmed gray; manage enabled state ourselves instead.
            self.menu._menu.setAutoenablesItems_(False)
        except Exception:
            pass

        self._menu_delegate = None
        if _MenuStateDelegate is not None:
            try:
                self._menu_delegate = _MenuStateDelegate.alloc().initWithApp_(self)
                self.menu._menu.setDelegate_(self._menu_delegate)
            except Exception:
                self._menu_delegate = None

        self._rebuild_menu()

        rumps.Timer(self.on_tick, POLL_SECONDS).start()
        rumps.Timer(self.on_startup, 1).start()  # one-shot, stops itself

    # ------------------------------------------------------------ startup

    def on_startup(self, timer):
        timer.stop()
        self._set_app_icon()
        if not self._get_credentials(prompt_if_missing=False):
            self._set_title("⚠️ Setup", color="orange")
            self._set_status("No API credentials — click Login to set them up")
            self._prompt_credentials()
        self._restore_session()
        threading.Thread(target=self._fetch, daemon=True).start()

    def _set_app_icon(self):
        """Kite logo on dialogs and notifications instead of the Python
        rocket (the script runs bare, without an .app bundle icon)."""
        try:
            from AppKit import NSApplication, NSImage
            img = NSImage.alloc().initWithContentsOfFile_(APP_ICON)
            if img and img.isValid():
                NSApplication.sharedApplication().setApplicationIconImage_(img)
        except Exception:
            pass

    # ------------------------------------------------------- keychain creds

    def _get_credentials(self, prompt_if_missing=True):
        api_key = keyring.get_password(KEYRING_SERVICE, "api_key")
        api_secret = keyring.get_password(KEYRING_SERVICE, "api_secret")
        if (not api_key or not api_secret) and prompt_if_missing:
            return self._prompt_credentials()
        if api_key and api_secret:
            return {"api_key": api_key, "api_secret": api_secret}
        return None

    def _prompt_credentials(self):
        intro = ("Enter your Kite Connect credentials from "
                 "developers.kite.trade.\nThey are stored only in the macOS "
                 "Keychain.")
        activate_app()
        win = rumps.Window(message=intro, title="Zerodha — API Key",
                           default_text="", ok="Save", cancel="Cancel",
                           dimensions=(320, 24))
        resp = win.run()
        if not resp.clicked or not resp.text.strip():
            return None
        api_key = resp.text.strip()

        activate_app()
        win = rumps.Window(message="API Secret:", title="Zerodha — API Secret",
                           default_text="", ok="Save", cancel="Cancel",
                           dimensions=(320, 24))
        resp = win.run()
        if not resp.clicked or not resp.text.strip():
            return None
        api_secret = resp.text.strip()

        if len(api_key) != 16 or len(api_secret) != 32:
            self._notify(
                "Check your credentials",
                f"Expected 16-char key / 32-char secret, got "
                f"{len(api_key)}/{len(api_secret)} — saved anyway.")
        keyring.set_password(KEYRING_SERVICE, "api_key", api_key)
        keyring.set_password(KEYRING_SERVICE, "api_secret", api_secret)
        self._notify("Credentials saved",
                           "Stored in the macOS Keychain.")
        return {"api_key": api_key, "api_secret": api_secret}

    # ----------------------------------------------------------- settings

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE) as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as fh:
                json.dump(self.settings, fh)
        except OSError as err:
            self._set_status(f"Could not save settings: {err}"[:120])

    def _filter(self):
        value = self.settings.get("filter", "all")
        return value if value in ("all", "equity", "mf") else "all"

    def _private(self):
        return bool(self.settings.get("private_mode", False))

    def _sync_filter_checks(self):
        current = self._filter()
        for key, item in self._filter_items.items():
            item.state = (key == current)

    def on_filter(self, item):
        for key, child in self._filter_items.items():
            if child is item:
                self.settings["filter"] = key
                break
        self._save_settings()
        self._sync_filter_checks()
        self._rebuild_menu()

    def on_toggle_private(self, item):
        enabled = not item.state
        item.state = enabled
        self.settings["private_mode"] = enabled
        self._save_settings()
        self._render_title()
        self._rebuild_menu()

    def on_toggle_autologin(self, item):
        enabled = not item.state
        item.state = enabled
        self.settings["auto_login"] = enabled
        self._save_settings()
        if enabled and not self.access_token_ok:
            # already sitting at ⚠️ Login — act on the new setting right away
            self._maybe_auto_login()

    # ----------------------------------------------------- token persistence

    def _save_token(self, api_key, access_token):
        payload = {"api_key": api_key, "access_token": access_token,
                   "issued_at": now_ist().isoformat()}
        with open(TOKEN_FILE, "w") as fh:
            json.dump(payload, fh)
        os.chmod(TOKEN_FILE, 0o600)

    def _load_token(self, api_key):
        try:
            with open(TOKEN_FILE) as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            return None
        if payload.get("api_key") != api_key:
            return None
        try:
            issued = datetime.fromisoformat(payload["issued_at"])
        except (KeyError, ValueError):
            return None
        if now_ist() >= token_expiry(issued):
            return None
        return payload.get("access_token")

    def _clear_token(self):
        try:
            os.remove(TOKEN_FILE)
        except OSError:
            pass

    def _restore_session(self):
        creds = self._get_credentials(prompt_if_missing=False)
        if not creds:
            return
        self.kite = KiteConnect(api_key=creds["api_key"])
        token = self._load_token(creds["api_key"])
        if token:
            self.kite.set_access_token(token)
            self.access_token_ok = True
        else:
            self._enter_login_state()

    # -------------------------------------------------------------- login

    def on_login(self, _):
        creds = self._get_credentials(prompt_if_missing=True)
        if not creds:
            self._notify("Login cancelled",
                               "API credentials are required.")
            return
        if self._logging_in:
            self._notify("Login already in progress",
                               "Finish the login in your browser.")
            return
        self._logging_in = True
        self._set_status("Waiting for browser login…")
        threading.Thread(target=self._do_login, args=(creds,),
                         daemon=True).start()

    def _do_login(self, creds):
        try:
            self.kite = KiteConnect(api_key=creds["api_key"])
            _CallbackHandler.result = None
            try:
                server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT),
                                    _CallbackHandler)
            except OSError as err:
                self._notify_main("Login failed",
                                  f"Port {CALLBACK_PORT} unavailable: {err}")
                return

            server.timeout = 1
            webbrowser.open(self.kite.login_url())

            deadline = time.monotonic() + LOGIN_WAIT_SECONDS
            while time.monotonic() < deadline and _CallbackHandler.result is None:
                server.handle_request()
            server.server_close()

            result = _CallbackHandler.result
            if not result or "request_token" not in result:
                reason = (result or {}).get("error", "timed out")
                self._notify_main("Login failed", f"Kite login {reason}.")
                run_on_main_thread(
                    lambda: self._enter_login_state(allow_auto=False))
                return

            session = self.kite.generate_session(
                result["request_token"], api_secret=creds["api_secret"])
            self.kite.set_access_token(session["access_token"])
            self._save_token(creds["api_key"], session["access_token"])
            self.access_token_ok = True
            self.fail_count = 0
            self._notify_main("Logged in",
                              f"Hi {session.get('user_name', '')}! "
                              "Fetching holdings…")
            self._fetch()
        except Exception as err:  # noqa: BLE001 — surface anything, never crash
            msg = str(err)

            def show_failure():
                self._enter_login_state(allow_auto=False)
                self._set_status(f"Login failed: {msg}"[:120])
                if "checksum" in msg.lower():
                    self._set_status(
                        "Login failed: Invalid checksum — the API Secret in "
                        "the Keychain is wrong. Re-run with --set-credentials")

            self._notify_main("Login failed", msg)
            run_on_main_thread(show_failure)
        finally:
            self._logging_in = False

    def _enter_login_state(self, allow_auto=True):
        self.access_token_ok = False
        self._clear_token()
        self._set_title("⚠️ Login", color="orange")
        self._set_status("Session expired — click Login to re-authenticate")
        if allow_auto:
            self._maybe_auto_login()

    def _maybe_auto_login(self):
        """Open the browser login unprompted when the session expires.

        Only fires on a genuine expiry (never after a failed login, to
        avoid browser-tab loops), needs stored credentials, and is
        rate-limited by AUTO_LOGIN_COOLDOWN. With an active
        kite.zerodha.com session in the browser the redirect completes
        with zero typing.
        """
        if not self.settings.get("auto_login", True) or self._logging_in:
            return
        if (self._last_auto_login is not None
                and time.monotonic() - self._last_auto_login
                < AUTO_LOGIN_COOLDOWN):
            return
        creds = self._get_credentials(prompt_if_missing=False)
        if not creds:
            return
        self._last_auto_login = time.monotonic()
        self._logging_in = True
        self._set_status("Auto-login: finish in the browser if asked…")
        threading.Thread(target=self._do_login, args=(creds,),
                         daemon=True).start()

    # ------------------------------------------------------------- polling

    def on_tick(self, _):
        now = now_ist()
        woke = (now - self.last_tick).total_seconds() > WAKE_GAP_SECONDS
        self.last_tick = now

        if not self.access_token_ok or self._fetching:
            return

        should_fetch = (
            is_market_open(now)
            or woke
            or self.last_fetch is None
            or self.last_fetch < last_market_close(now)
        )
        if should_fetch:
            threading.Thread(target=self._fetch, daemon=True).start()

    def on_refresh(self, _):
        if self.access_token_ok and not self._fetching:
            threading.Thread(target=self._fetch, daemon=True).start()
        elif not self.access_token_ok:
            self._notify("Not logged in",
                               "Click Login first.")

    def _fetch(self):
        """Background thread: call kite.holdings() and hand off to the UI."""
        if not self.kite or not self.access_token_ok or self._fetching:
            return
        self._fetching = True
        try:
            holdings = self.kite.holdings()
            try:
                # positions is a portfolio endpoint too (works on the free
                # plan); a failure here shouldn't sink the whole refresh
                positions = (self.kite.positions() or {}).get("net", [])
            except Exception:
                positions = self.positions
            mf = self.mf_holdings
            stale = (self._last_mf_fetch is None
                     or (now_ist() - self._last_mf_fetch).total_seconds()
                     > MF_REFRESH_SECONDS)
            if stale:
                try:
                    # MF NAVs update once a day — refresh sparingly, and a
                    # failure never sinks the equity refresh
                    mf = self.kite.mf_holdings() or []
                    self._last_mf_fetch = now_ist()
                except Exception:
                    mf = self.mf_holdings
        except kex.TokenException:
            run_on_main_thread(self._enter_login_state)
            return
        except kex.PermissionException as err:
            msg = f"Permission error: {err}"
            run_on_main_thread(lambda: self._on_fetch_error(msg))
            return
        except Exception as err:  # network, throttle, 5xx — retry next tick
            msg = str(err)
            run_on_main_thread(lambda: self._on_fetch_error(msg))
            return
        finally:
            self._fetching = False
        run_on_main_thread(lambda: self._apply_data(holdings, positions, mf))

    def _on_fetch_error(self, message):
        self.fail_count += 1
        self._set_status(f"Fetch failed ({message[:80]}) — retrying")
        if self.fail_count >= FAILURES_BEFORE_WARNING and self.holdings:
            # keep showing last good data, add a subtle staleness marker
            self._render_title(stale=True)

    def _apply_data(self, holdings, positions, mf=None):
        self.fail_count = 0
        # alphabetical, matching the Kite app's holdings screen
        self.holdings = sorted(
            holdings,
            key=lambda h: str(h.get("tradingsymbol") or ""),
        )
        if mf is not None:
            self.mf_holdings = sorted(
                mf, key=lambda f: str(f.get("fund") or ""))
        # bright rows first (by P&L desc), then sold holdings, then
        # closed round-trips — matching Kite's positions screen
        rank = {"open": 0, "holding": 0, "sold": 1, "closed": 2}
        self.positions = sorted(
            positions,
            key=lambda p: (rank[position_state(p)], -(p.get("pnl") or 0)),
        )
        self.last_fetch = now_ist()
        self._render_title()
        if self._menu_open:
            self._update_menu_in_place()
        else:
            self._rebuild_menu()

    # ------------------------------------------------------------ rendering

    def _totals(self):
        invested = sum((h.get("average_price") or 0) * eff_qty(h)
                       for h in self.holdings)
        current = sum((h.get("last_price") or 0) * eff_qty(h)
                      for h in self.holdings)
        total_pnl = current - invested
        day_pnl = sum((h.get("day_change") or 0) * eff_qty(h)
                      for h in self.holdings)
        prev_close = sum((h.get("close_price") or 0) * eff_qty(h)
                         for h in self.holdings)
        day_pct = (day_pnl / prev_close * 100) if prev_close else 0.0
        return invested, current, total_pnl, day_pnl, day_pct

    def _mf_totals(self):
        invested = sum((f.get("average_price") or 0) * (f.get("quantity") or 0)
                       for f in self.mf_holdings)
        current = sum((f.get("last_price") or 0) * (f.get("quantity") or 0)
                      for f in self.mf_holdings)
        return invested, current, current - invested

    def _positions_totals(self):
        total = sum(p.get("pnl") or 0 for p in self.positions)
        m2m = sum((p.get("m2m") if p.get("m2m") is not None
                   else (p.get("pnl") or 0)) for p in self.positions)
        return total, m2m

    def _day_totals(self):
        """Today's combined move: holdings day change + positions M2M."""
        _, _, _, hold_day, _ = self._totals()
        _, pos_m2m = self._positions_totals()
        day_total = hold_day + pos_m2m
        prev_close = sum((h.get("close_price") or 0) * eff_qty(h)
                         for h in self.holdings)
        pct = (day_total / prev_close * 100) if prev_close else None
        return day_total, pct

    def _render_title(self, stale=False):
        if not self.holdings and not self.positions:
            self._set_title("₹ no holdings")
            return
        day_total, pct = self._day_totals()
        arrow = "▲" if day_total >= 0 else "▼"
        color = "green" if day_total >= 0 else "red"
        if self._private():
            text = f"{arrow} {pct:+.1f}%" if pct is not None else arrow
        else:
            text = f"{arrow} {fmt_inr(day_total, explicit_sign=True)}"
            if pct is not None:
                text += f" ({pct:+.1f}%)"
        if stale:
            text += " ⚠"
        self._set_title(text, color=color)

    def _set_title(self, text, color=None):
        self.title = text
        if color is None:
            return
        try:  # colour needs the underlying NSStatusItem — best-effort only
            from AppKit import (NSAttributedString, NSColor, NSFont,
                                NSFontAttributeName,
                                NSForegroundColorAttributeName)
            ns_color = {
                "green": NSColor.systemGreenColor(),
                "red": soft_red(),
                "orange": NSColor.systemOrangeColor(),
            }.get(color)
            if ns_color is None:
                return
            font = NSFont.monospacedDigitSystemFontOfSize_weight_(0, 0)
            attrs = {NSForegroundColorAttributeName: ns_color,
                     NSFontAttributeName: font}
            attributed = NSAttributedString.alloc().initWithString_attributes_(
                text, attrs)
            self._nsapp.nsstatusitem.button().setAttributedTitle_(attributed)
        except Exception:
            pass  # plain title already set

    def _set_status(self, text):
        self.item_status.title = text
        try:
            self.item_status._menuitem.setAttributedTitle_(
                self._styled([(text, "dim", False)], size=12))
        except Exception:
            pass

    def _styled(self, segments, size=12.5, font="mono"):
        """NSAttributedString from [(text, color_key, bold), ...] segments.

        font="mono" is fully monospaced (status row); font="digits" keeps
        proportional text with tabular figures (Kite-style data rows).
        """
        from AppKit import (NSAttributedString, NSColor, NSFont,
                            NSFontAttributeName, NSForegroundColorAttributeName,
                            NSMutableAttributedString)
        colors = {
            "label": NSColor.labelColor(),
            "dim": NSColor.secondaryLabelColor(),
            "faint": NSColor.tertiaryLabelColor(),
            "green": NSColor.systemGreenColor(),
            "red": soft_red(),
            "orange": NSColor.systemOrangeColor(),
            "blue": NSColor.systemBlueColor(),
        }
        font_fn = (NSFont.monospacedDigitSystemFontOfSize_weight_
                   if font == "digits"
                   else NSFont.monospacedSystemFontOfSize_weight_)
        result = NSMutableAttributedString.alloc().init()
        for text, color_key, bold in segments:
            fnt = font_fn(size, 0.3 if bold else 0.0)  # 0.3 == semibold
            attrs = {NSFontAttributeName: fnt,
                     NSForegroundColorAttributeName: colors.get(
                         color_key, colors["label"])}
            result.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(
                    text, attrs))
        return result

    def _mk_attr_label(self, segments, size):
        from AppKit import NSTextField
        lbl = NSTextField.labelWithAttributedString_(
            self._styled(segments, size=size, font="digits"))
        lbl.sizeToFit()
        return lbl

    # ------------------------------------------------- custom view rows
    # NSMenuItem.setView_ replaces the item's text with an arbitrary NSView:
    # full control over fonts, colors, and layout, and no
    # hover highlight on informational rows.

    MENU_W = 340

    def _view_row(self, key, height, build):
        item = rumps.MenuItem(key)  # key doubles as plain-text fallback
        try:
            from AppKit import NSView
            from Foundation import NSMakeRect
            view = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, self.MENU_W, height))
            build(view)
            item._menuitem.setView_(view)
        except Exception:
            import traceback
            traceback.print_exc()
        self.menu.add(item)

    def _mk_label(self, text, size, weight, color, mono=True):
        from AppKit import NSFont, NSTextField
        lbl = NSTextField.labelWithString_(text)
        font = (NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)
                if mono else NSFont.systemFontOfSize_weight_(size, weight))
        lbl.setFont_(font)
        lbl.setTextColor_(color)
        lbl.sizeToFit()
        return lbl

    @staticmethod
    def _place_left(view, lbl, x, y):
        lbl.setFrameOrigin_((x, y))
        view.addSubview_(lbl)

    def _place_right(self, view, lbl, y, right_inset=14):
        x = self.MENU_W - right_inset - lbl.frame().size.width
        lbl.setFrameOrigin_((x, y))
        view.addSubview_(lbl)
        return x

    SUMMARY_H = 96

    def _summary_content(self):
        """Text and color for the summary card — shared by build/update.

        Follows the Show filter: combined equity+MF on All, one side only
        otherwise.
        """
        from AppKit import NSColor
        flt = self._filter()
        inv_e, cur_e, _, _, _ = self._totals()
        inv_m, cur_m, _ = self._mf_totals()
        if flt == "equity":
            invested, current = inv_e, cur_e
        elif flt == "mf":
            invested, current = inv_m, cur_m
        else:
            invested, current = inv_e + inv_m, cur_e + cur_m
        total_pnl = current - invested
        total_pct = (total_pnl / invested * 100) if invested else 0.0
        pnl_c = (NSColor.systemGreenColor() if total_pnl >= 0
                 else soft_red())
        private = self._private()
        return {
            "invested": (PRIVATE_MASK if private
                         else fmt_inr(invested, 2, rupee=False)),
            "current": (PRIVATE_MASK if private
                        else fmt_inr(current, 2, rupee=False)),
            "pnl": ("" if private
                    else fmt_inr(total_pnl, 2, explicit_sign=True,
                                 rupee=False)),
            "pct": f"{total_pct:+.2f}%",
            "color": pnl_c,
        }

    def _pct_pill(self, text, ns_color):
        """Rounded translucent percentage badge, Kite-style."""
        from AppKit import NSBox, NSBoxCustom, NSNoTitle
        from Foundation import NSMakeRect
        inner = self._mk_label(text, 11, 0.3, ns_color)
        tw = inner.frame().size.width
        th = inner.frame().size.height
        w, h = tw + 16, th + 6
        box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        box.setBoxType_(NSBoxCustom)
        box.setTitlePosition_(NSNoTitle)
        box.setBorderWidth_(0)
        box.setCornerRadius_(h / 2.0)
        box.setFillColor_(ns_color.colorWithAlphaComponent_(0.16))
        box.setContentViewMargins_((0, 0))
        inner.setFrameOrigin_(((w - tw) / 2.0, (h - th) / 2.0))
        box.contentView().addSubview_(inner)
        return box

    def _place_summary_pnl(self, refs, content):
        """Position the pct pill at the far right, the P&L amount beside it."""
        pill = self._pct_pill(content["pct"], content["color"])
        px = self.MENU_W - 14 - pill.frame().size.width
        pill.setFrameOrigin_((px, 9))
        refs["view"].addSubview_(pill)
        refs["pill"] = pill
        self._relabel(refs["pnl"], content["pnl"], color=content["color"],
                      right_edge=px - 8)

    def _build_summary(self, view):
        """Kite-style summary card:

        Invested                                   Current
        8,71,986.27                          10,24,441.67
        ──────────────────────────────────────────────────
        P&L                          +1,52,455.40 (+17.48%)
        """
        from AppKit import NSBox, NSBoxCustom, NSColor, NSNoTitle
        from Foundation import NSMakeRect
        content = self._summary_content()
        dim = NSColor.secondaryLabelColor()
        label = NSColor.labelColor()

        self._place_left(view, self._mk_label(
            "Invested", 11, 0.0, dim, mono=False), 14, 74)
        self._place_right(view, self._mk_label(
            "Current", 11, 0.0, dim, mono=False), 74)
        inv_lbl = self._mk_label(content["invested"], 17, 0.4, label)
        self._place_left(view, inv_lbl, 14, 48)
        cur_lbl = self._mk_label(content["current"], 17, 0.4, label)
        self._place_right(view, cur_lbl, 48)

        hairline = NSBox.alloc().initWithFrame_(
            NSMakeRect(14, 38, self.MENU_W - 28, 1))
        hairline.setBoxType_(NSBoxCustom)
        hairline.setTitlePosition_(NSNoTitle)
        hairline.setBorderWidth_(0)
        hairline.setFillColor_(NSColor.separatorColor())
        view.addSubview_(hairline)

        self._place_left(view, self._mk_label(
            "P&L", 11, 0.0, dim, mono=False), 14, 12)
        pnl_lbl = self._mk_label(content["pnl"], 14, 0.4, content["color"])
        view.addSubview_(pnl_lbl)
        pnl_lbl.setFrameOrigin_((0, 12))  # placed by _place_summary_pnl
        refs = {"view": view, "invested": inv_lbl, "current": cur_lbl,
                "pnl": pnl_lbl, "pill": None}
        self._place_summary_pnl(refs, content)
        self._row_refs["summary"] = refs

    DAY_H = 34

    def _day_content(self):
        """Day's P&L row: the same figure as the menu-bar title."""
        from AppKit import NSColor
        day_total, pct = self._day_totals()
        return {
            "amount": ("" if self._private()
                       else fmt_inr(day_total, 2, explicit_sign=True,
                                    rupee=False)),
            "pct": f"{pct:+.2f}%" if pct is not None else None,
            "color": (NSColor.systemGreenColor() if day_total >= 0
                      else soft_red()),
        }

    def _place_day_pnl(self, refs):
        """Pct pill at the far right, the day amount beside it."""
        content = self._day_content()
        if refs.get("pill") is not None:
            refs["pill"].removeFromSuperview()
        right_edge = self.MENU_W - 14
        refs["pill"] = None
        if content["pct"] is not None:
            pill = self._pct_pill(content["pct"], content["color"])
            right_edge -= pill.frame().size.width
            pill.setFrameOrigin_((right_edge, 6))
            refs["view"].addSubview_(pill)
            refs["pill"] = pill
            right_edge -= 8
        self._relabel(refs["amount"], content["amount"],
                      color=content["color"], right_edge=right_edge)

    def _build_day_pnl(self, view):
        """Day's P&L                      +54,714.46 (+4.69%)"""
        from AppKit import NSColor
        self._place_left(view, self._mk_label(
            "Day's P&L", 11, 0.0, NSColor.secondaryLabelColor(),
            mono=False), 14, 9)
        amount = self._mk_label("", 14, 0.4, NSColor.labelColor())
        amount.setFrameOrigin_((0, 9))  # placed by _place_day_pnl
        view.addSubview_(amount)
        refs = {"view": view, "amount": amount, "pill": None}
        self._place_day_pnl(refs)
        self._row_refs["day"] = refs

    ROW_H = 64  # three-line Kite-style rows

    def _holding_segments(self, h):
        """Kite-style row content — shared by first build and live update."""
        qty = eff_qty(h)
        ltp = h.get("last_price") or 0
        avg = h.get("average_price") or 0
        invested = avg * qty
        pnl = (ltp - avg) * qty
        pnl_pct = ((ltp - avg) / avg * 100) if avg else 0.0
        day_pct = h.get("day_change_percentage") or 0
        pnl_key = "green" if pnl >= 0 else "red"
        day_key = "green" if day_pct >= 0 else "red"
        private = self._private()
        return {
            "qty_avg": [("Qty. ", "dim", False),
                        ("••" if private else f"{qty}", "label", False),
                        ("  •  ", "faint", False), ("Avg. ", "dim", False),
                        (fmt_inr(avg, 2, rupee=False), "label", False)],
            "pnl_pct": ([] if private
                        else [(f"{pnl_pct:+.2f}%", pnl_key, False)]),
            "pnl": [(f"{pnl_pct:+.2f}%" if private
                     else fmt_inr(pnl, 2, explicit_sign=True, rupee=False),
                     pnl_key, True)],
            "invested": [("Invested ", "dim", False),
                         (PRIVATE_MASK if private
                          else fmt_inr(invested, 2, rupee=False),
                          "label", False)],
            "ltp": [("LTP ", "dim", False),
                    (fmt_inr(ltp, 2, rupee=False), "label", False),
                    (f" ({day_pct:.2f}%)", day_key, False)],
        }

    POSITION_TAGS = {"holding": ("HOLDING", "blue"),
                     "sold": ("SOLD HOLDING", "faint"),
                     "closed": ("CLOSED", "faint")}

    def _position_segments(self, p):
        qty = p.get("quantity") or 0
        avg = p.get("average_price") or 0
        ltp = p.get("last_price") or 0
        pnl = p.get("pnl") or 0
        m2m = p.get("m2m") if p.get("m2m") is not None else pnl
        state = position_state(p)
        # sold holdings and closed round-trips render fully dimmed, like
        # Kite's positions screen
        dim = state in ("sold", "closed")
        pnl_key = "dim" if dim else ("green" if pnl >= 0 else "red")
        m2m_key = "dim" if dim else ("green" if m2m >= 0 else "red")
        lbl_key = "faint" if dim else "dim"
        val_key = "dim" if dim else "label"
        product = [(str(p.get("product", "")), lbl_key, False)]
        tag = self.POSITION_TAGS.get(state)
        if tag:
            product += [("  •  ", "faint", False), (tag[0], tag[1], False)]
        private = self._private()
        return {
            "qty_avg": [("Qty. ", lbl_key, False),
                        ("••" if private else f"{qty:+d}", val_key, False),
                        ("  •  ", "faint", False), ("Avg. ", lbl_key, False),
                        (fmt_inr(avg, 2, rupee=False), val_key, False)],
            "pnl_pct": ([] if private
                        else [(fmt_inr(m2m, 2, explicit_sign=True,
                                       rupee=False) + " today",
                               m2m_key, False)]),
            "pnl": [(PRIVATE_MASK if private
                     else fmt_inr(pnl, 2, explicit_sign=True, rupee=False),
                     pnl_key, True)],
            "invested": product,
            "ltp": [("LTP ", lbl_key, False),
                    (fmt_inr(ltp, 2, rupee=False), val_key, False)],
        }

    @staticmethod
    def _fund_display_name(f):
        """Coin fund names are long — drop the plan suffix, keep the fund."""
        name = str(f.get("fund") or f.get("tradingsymbol") or "?")
        for suffix in (" - DIRECT PLAN", " - REGULAR PLAN",
                       "  - DIRECT PLAN", " DIRECT PLAN", " REGULAR PLAN"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name.strip()

    def _mf_segments(self, f):
        qty = f.get("quantity") or 0
        nav = f.get("last_price") or 0
        avg = f.get("average_price") or 0
        invested = avg * qty
        pnl = (nav - avg) * qty
        pnl_pct = ((nav - avg) / avg * 100) if avg else 0.0
        pnl_key = "green" if pnl >= 0 else "red"
        private = self._private()
        qty_txt = "••" if private else f"{qty:.3f}".rstrip("0").rstrip(".")
        return {
            "qty_avg": [("Qty. ", "dim", False), (qty_txt, "label", False),
                        ("  •  ", "faint", False), ("Avg. ", "dim", False),
                        (fmt_inr(avg, 2, rupee=False), "label", False)],
            "pnl_pct": ([] if private
                        else [(f"{pnl_pct:+.2f}%", pnl_key, False)]),
            "pnl": [(f"{pnl_pct:+.2f}%" if private
                     else fmt_inr(pnl, 2, explicit_sign=True, rupee=False),
                     pnl_key, True)],
            "invested": [("Invested ", "dim", False),
                         (PRIVATE_MASK if private
                          else fmt_inr(invested, 2, rupee=False),
                          "label", False)],
            "ltp": [("NAV ", "dim", False),
                    (fmt_inr(nav, 2, rupee=False), "label", False)],
        }

    def _build_row(self, view, key, symbol, seg, refs_bucket, name_len=16,
                   dim=False):
        """Three-line Kite layout:

        Qty. 595  •  Avg. 301.67 ………………………………………… +34.85%
        BEL ……………………………………………………………………………… +62,548.35
        Invested 1,79,497.65 ………………………… LTP 406.80 (-0.21%)
        """
        from AppKit import NSColor
        qty_avg = self._mk_attr_label(seg["qty_avg"], 11)
        self._place_left(view, qty_avg, 14, 46)
        pnl_pct = self._mk_attr_label(seg["pnl_pct"], 11)
        self._place_right(view, pnl_pct, 46)
        self._place_left(view, self._mk_label(
            symbol[:name_len], 13, 0.3,
            NSColor.secondaryLabelColor() if dim else NSColor.labelColor(),
            mono=False), 14, 25)
        pnl = self._mk_attr_label(seg["pnl"], 14)
        self._place_right(view, pnl, 24)
        invested = self._mk_attr_label(seg["invested"], 11)
        self._place_left(view, invested, 14, 6)
        ltp = self._mk_attr_label(seg["ltp"], 11)
        self._place_right(view, ltp, 6)
        refs_bucket[key] = {"qty_avg": qty_avg, "pnl_pct": pnl_pct,
                            "pnl": pnl, "invested": invested, "ltp": ltp}

    def _build_holding(self, view, h):
        self._build_row(view, str(h.get("tradingsymbol", "?")),
                        str(h.get("tradingsymbol", "?")),
                        self._holding_segments(h),
                        self._row_refs["holdings"])

    def _build_position(self, view, p):
        self._build_row(view, self._position_key(p),
                        str(p.get("tradingsymbol", "?")),
                        self._position_segments(p),
                        self._row_refs["positions"],
                        dim=position_state(p) in ("sold", "closed"))

    def _build_mf(self, view, f):
        self._build_row(view, str(f.get("tradingsymbol", "?")),
                        self._fund_display_name(f),
                        self._mf_segments(f),
                        self._row_refs["mf"], name_len=26)

    SECTION_H = 30

    def _section_row(self, text, right_text=None, right_value=0.0):
        """Full-width tinted band so HOLDINGS/POSITIONS read as sections."""
        def build(view):
            from AppKit import NSBox, NSBoxCustom, NSColor, NSNoTitle
            from Foundation import NSMakeRect
            band_h = self.SECTION_H - 6
            box = NSBox.alloc().initWithFrame_(
                NSMakeRect(8, 3, self.MENU_W - 16, band_h))
            box.setBoxType_(NSBoxCustom)
            box.setTitlePosition_(NSNoTitle)
            box.setBorderWidth_(0)
            box.setCornerRadius_(6)
            box.setFillColor_(
                NSColor.labelColor().colorWithAlphaComponent_(0.07))
            box.setContentViewMargins_((0, 0))
            view.addSubview_(box)

            lbl = self._mk_label(text, 11, 0.4,
                                 NSColor.secondaryLabelColor(), mono=False)
            lbl_y = 3 + (band_h - lbl.frame().size.height) / 2.0
            self._place_left(view, lbl, 16, lbl_y)
            if right_text:
                color = (NSColor.systemGreenColor() if right_value >= 0
                         else soft_red())
                rlbl = self._mk_label(right_text, 11, 0.4, color)
                self._place_right(view, rlbl, lbl_y, right_inset=16)
        self._view_row("§ " + text, self.SECTION_H, build)

    # -------------------------------------------------- in-place live ticks
    # Clearing and re-adding items while the dropdown is showing glitches
    # NSMenu, so fresh data updates the existing labels directly;
    # re-sorting and row add/remove wait until the menu closes.

    @staticmethod
    def _position_key(p):
        return f"{p.get('tradingsymbol', '?')} · {p.get('product', '')}"

    def _relabel(self, lbl, text, color=None, right_edge=None):
        """Update a label's text (and color), keeping its alignment."""
        lbl.setStringValue_(text)
        if color is not None:
            lbl.setTextColor_(color)
        lbl.sizeToFit()
        if right_edge is not None:
            lbl.setFrameOrigin_((right_edge - lbl.frame().size.width,
                                 lbl.frame().origin.y))

    def _relabel_attr(self, lbl, segments, size, right_edge=None):
        lbl.setAttributedStringValue_(
            self._styled(segments, size=size, font="digits"))
        lbl.sizeToFit()
        if right_edge is not None:
            lbl.setFrameOrigin_((right_edge - lbl.frame().size.width,
                                 lbl.frame().origin.y))

    def _update_summary(self, refs):
        content = self._summary_content()
        self._relabel(refs["invested"], content["invested"])
        self._relabel(refs["current"], content["current"],
                      right_edge=self.MENU_W - 14)
        if refs.get("pill") is not None:
            refs["pill"].removeFromSuperview()
        self._place_summary_pnl(refs, content)

    def _update_row(self, refs, seg):
        right = self.MENU_W - 14
        self._relabel_attr(refs["qty_avg"], seg["qty_avg"], 11)
        self._relabel_attr(refs["pnl_pct"], seg["pnl_pct"], 11,
                           right_edge=right)
        self._relabel_attr(refs["pnl"], seg["pnl"], 14, right_edge=right)
        self._relabel_attr(refs["invested"], seg["invested"], 11)
        self._relabel_attr(refs["ltp"], seg["ltp"], 11, right_edge=right)

    def _update_menu_in_place(self):
        self._menu_dirty = True  # re-sort/re-layout once the menu closes
        try:
            if self._row_refs.get("summary"):
                self._update_summary(self._row_refs["summary"])
            if self._row_refs.get("day"):
                self._place_day_pnl(self._row_refs["day"])
            by_symbol = {str(h.get("tradingsymbol", "?")): h
                         for h in self.holdings}
            for key, refs in self._row_refs.get("holdings", {}).items():
                if key in by_symbol:
                    self._update_row(refs,
                                     self._holding_segments(by_symbol[key]))
            by_key = {self._position_key(p): p for p in self.positions}
            for key, refs in self._row_refs.get("positions", {}).items():
                if key in by_key:
                    self._update_row(refs,
                                     self._position_segments(by_key[key]))
            by_isin = {str(f.get("tradingsymbol", "?")): f
                       for f in self.mf_holdings}
            for key, refs in self._row_refs.get("mf", {}).items():
                if key in by_isin:
                    self._update_row(refs, self._mf_segments(by_isin[key]))
        except Exception:
            import traceback
            traceback.print_exc()
        self._update_status_row()

    def _rebuild_after_close(self):
        if self._menu_dirty:
            self._menu_dirty = False
            self._rebuild_menu()

    def _update_status_row(self):
        if self.last_fetch:
            self._set_status(
                f"Updated {self.last_fetch.strftime('%H:%M:%S')} IST"
                + ("" if is_market_open(now_ist()) else " · market closed"))

    def _rebuild_menu(self):
        self.menu.clear()
        self._row_refs = {"summary": None, "day": None, "holdings": {},
                          "positions": {}, "mf": {}}
        flt = self._filter()
        show_equity = flt in ("all", "equity")
        show_mf = flt in ("all", "mf")

        if ((show_equity and (self.holdings or self.positions))
                or (show_mf and self.mf_holdings)):
            self._view_row("Portfolio summary", self.SUMMARY_H,
                           self._build_summary)
            self.menu.add(rumps.separator)

        if show_equity and self.holdings:
            inv_e, _, hold_pnl, _, _ = self._totals()
            if self._private():
                pct = (hold_pnl / inv_e * 100) if inv_e else 0.0
                right = f"P&L {pct:+.2f}%"
            else:
                right = f"P&L {fmt_inr(hold_pnl, explicit_sign=True)}"
            self._section_row(
                f"HOLDINGS · {len(self.holdings)}", right, hold_pnl)
            for i, h in enumerate(self.holdings):
                if i:
                    self.menu.add(rumps.separator)
                key = str(h.get("tradingsymbol", "?"))
                self._view_row(
                    key, self.ROW_H,
                    lambda view, h=h: self._build_holding(view, h))
            self.menu.add(rumps.separator)
        if show_equity and self.positions:
            pos_total, _ = self._positions_totals()
            self._section_row(
                f"POSITIONS · {len(self.positions)}",
                None if self._private()
                else f"P&L {fmt_inr(pos_total, explicit_sign=True)}",
                pos_total)
            for i, p in enumerate(self.positions):
                if i:
                    self.menu.add(rumps.separator)
                key = self._position_key(p)
                self._view_row(
                    key, self.ROW_H,
                    lambda view, p=p: self._build_position(view, p))
            self.menu.add(rumps.separator)
        if show_mf and self.mf_holdings:
            inv_m, _, mf_pnl = self._mf_totals()
            if self._private():
                pct = (mf_pnl / inv_m * 100) if inv_m else 0.0
                right = f"P&L {pct:+.2f}%"
            else:
                right = f"P&L {fmt_inr(mf_pnl, explicit_sign=True)}"
            self._section_row(
                f"MUTUAL FUNDS · {len(self.mf_holdings)}", right, mf_pnl)
            for i, f in enumerate(self.mf_holdings):
                if i:
                    self.menu.add(rumps.separator)
                key = str(f.get("tradingsymbol", "?"))
                self._view_row(
                    key, self.ROW_H,
                    lambda view, f=f: self._build_mf(view, f))
            self.menu.add(rumps.separator)

        if show_equity and (self.holdings or self.positions):
            self._view_row("Day's P&L", self.DAY_H, self._build_day_pnl)
            self.menu.add(rumps.separator)

        self._update_status_row()
        self.menu.add(self.item_status)
        self.menu.add(rumps.separator)
        self.menu.add(self.item_filter)
        self.menu.add(self.item_private)
        self.menu.add(self.item_refresh)
        self.menu.add(self.item_login)
        self.menu.add(self.item_launch)
        self.menu.add(self.item_autologin)
        self.menu.add(rumps.separator)
        self.menu.add(self.item_quit)

    # ------------------------------------------------------ launch at login

    def on_toggle_launch(self, item):
        try:
            if launch_agent.is_installed():
                launch_agent.uninstall()
                item.state = False
                self._notify("Launch at login disabled", "")
            else:
                launch_agent.install()
                item.state = True
                self._notify("Launch at login enabled",
                                   "Runs via a LaunchAgent.")
        except Exception as err:  # noqa: BLE001
            self._notify("Launch-at-login failed", str(err))

    # ------------------------------------------------------------- helpers

    def _notify(self, title, message):
        """Notification Center if available, else the status menu row.

        rumps notifications require an Info.plist with CFBundleIdentifier
        next to the interpreter; without it they raise — never fatal here.
        """
        try:
            rumps.notification("KiteBar", title, message)
        except Exception:
            self._set_status(f"{title} — {message}"[:120])

    def _notify_main(self, title, message):
        run_on_main_thread(lambda: self._notify(title, message))
