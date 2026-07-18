"""Launch-at-login via a per-user LaunchAgent."""

import os
import plistlib
import subprocess
import sys

from .constants import (
    APP_SUPPORT,
    LAUNCH_AGENT_LABEL,
    LAUNCH_AGENT_PLIST,
    _bundle_path,
)


def is_installed():
    return os.path.exists(LAUNCH_AGENT_PLIST)


def uninstall():
    """Unload and delete the LaunchAgent."""
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
        capture_output=True, check=False)
    os.remove(LAUNCH_AGENT_PLIST)


def install():
    """Write and load the LaunchAgent.

    Inside the .app the agent opens the bundle; from a plain checkout it
    runs `python -m kitebar` with the package's parent as the working dir.
    """
    bundle = _bundle_path()
    if bundle:
        program = ["/usr/bin/open", "-a", bundle]
        workdir = None
    else:
        program = [sys.executable, "-m", "kitebar"]
        workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": program,
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": os.path.join(APP_SUPPORT, "agent.log"),
        "StandardErrorPath": os.path.join(APP_SUPPORT, "agent.log"),
    }
    if workdir:
        payload["WorkingDirectory"] = workdir
    os.makedirs(os.path.dirname(LAUNCH_AGENT_PLIST), exist_ok=True)
    with open(LAUNCH_AGENT_PLIST, "wb") as fh:
        plistlib.dump(payload, fh)
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", LAUNCH_AGENT_PLIST],
        capture_output=True, check=False)
