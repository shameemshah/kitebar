"""Cocoa plumbing: activation, main-thread dispatch, menu-state delegate."""

def activate_app():
    """Bring this menu-bar-only app to the foreground.

    rumps activates the app once at startup; any dialog shown later (while
    e.g. the terminal is active) renders but never gets keyboard focus,
    because key events keep routing to the active application. Re-activate
    right before showing input windows.
    """
    try:
        from AppKit import (NSApplication,
                            NSApplicationActivateIgnoringOtherApps,
                            NSRunningApplication)
        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def run_on_main_thread(fn):
    """Schedule `fn` on the Cocoa main thread (falls back to direct call).

    `fn` is shielded: an exception escaping into an Objective-C block is
    uncatchable and aborts the process (SIGABRT).
    """
    def shielded():
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()

    try:
        from Foundation import NSOperationQueue
        NSOperationQueue.mainQueue().addOperationWithBlock_(shielded)
    except Exception:
        shielded()


# ---------------------------------------------------- menu open/close state

try:
    import objc
    from Foundation import NSObject

    class _MenuStateDelegate(NSObject):
        """NSMenu delegate tracking whether the dropdown is showing.

        Updating existing labels is safe while the menu is open; a full
        clear-and-rebuild is not (NSMenu glitches), so the app must know
        which state it is in before applying fresh data.
        """

        def initWithApp_(self, app):
            self = objc.super(_MenuStateDelegate, self).init()
            if self is None:
                return None
            self._app = app
            return self

        def menuWillOpen_(self, menu):
            self._app._menu_open = True

        def menuDidClose_(self, menu):
            self._app._menu_open = False
            # Mutating the menu inside the close callback glitches AppKit;
            # queue the rebuild to run right after the close completes.
            run_on_main_thread(self._app._rebuild_after_close)

except Exception:  # pragma: no cover — pyobjc always ships with rumps
    _MenuStateDelegate = None
