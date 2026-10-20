"""
Cross-platform active window and application detection module.
Supports Windows, macOS, Linux (X11 & Wayland), and Android (Termux/Root).
"""

import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ActiveAppDetector:
    """Detects the foreground active application and window title across various OS environments."""

    def __init__(self):
        self.os_type = sys.platform

    def get_active_app(self) -> Dict[str, str]:
        """
        Returns a dictionary with:
            - 'app_name': Name of the active application (e.g., 'Google Chrome', 'Code')
            - 'window_title': Title of the active window
        """
        try:
            if self.os_type == "win32":
                return self._detect_windows()
            elif self.os_type == "darwin":
                return self._detect_macos()
            elif self.os_type.startswith("linux"):
                # Detect whether running inside Android / Termux or desktop Linux
                if "ANDROID_ROOT" in os.environ or os.path.exists("/data/data/com.termux"):
                    return self._detect_android()
                return self._detect_linux()
            else:
                return {"app_name": "Unknown", "window_title": "Unknown"}
        except Exception as e:
            logger.debug("Failed to detect active window: %s", e)
            return {"app_name": "Unknown", "window_title": "Unknown"}

    def _detect_windows(self) -> Dict[str, str]:
        """Windows detection using ctypes (built-in, no external wheels required)."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"app_name": "Desktop / None", "window_title": "None"}

        # Get window title
        length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        window_title = title_buffer.value or "Untitled"

        # Get process ID and process executable name
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        app_name = "Unknown"
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h_process:
            try:
                exe_buffer = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h_process, 0, exe_buffer, ctypes.byref(size)):
                    full_path = exe_buffer.value
                    app_name = os.path.splitext(os.path.basename(full_path))[0]
            finally:
                kernel32.CloseHandle(h_process)

        return {"app_name": app_name, "window_title": window_title}

    def _detect_macos(self) -> Dict[str, str]:
        """macOS detection using AppleScript osascript."""
        app_script = 'tell application "System Events" to get name of first application process whose frontmost is true'
        title_script = (
            'tell application "System Events" to tell (first application process whose frontmost is true) '
            'to get name of front window'
        )

        app_name = self._run_cmd(["osascript", "-e", app_script]) or "macOS App"
        window_title = self._run_cmd(["osascript", "-e", title_script]) or app_name

        return {"app_name": app_name.strip(), "window_title": window_title.strip()}

    def _detect_linux(self) -> Dict[str, str]:
        """Linux desktop detection (X11 / Wayland)."""
        # 1. Try X11 xdotool / xprop
        if shutil.which("xdotool"):
            win_id = self._run_cmd(["xdotool", "getactivewindow"])
            if win_id and win_id.isdigit():
                win_name = self._run_cmd(["xdotool", "getwindowname", win_id]) or ""
                # Get WM_CLASS
                wm_class = self._run_cmd(["xprop", "-id", win_id, "WM_CLASS"]) or ""
                app_name = "Linux App"
                if "=" in wm_class:
                    parts = wm_class.split("=")[-1].replace('"', "").split(",")
                    app_name = parts[-1].strip() if parts else "Linux App"
                return {
                    "app_name": app_name or "Linux App",
                    "window_title": win_name.strip() or "Untitled",
                }

        # 2. Try xprop directly
        if shutil.which("xprop"):
            root_win = self._run_cmd(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
            if root_win and "window id #" in root_win:
                win_id = root_win.split("window id #")[-1].strip().split()[0]
                win_name = self._run_cmd(["xprop", "-id", win_id, "WM_NAME"]) or ""
                if "=" in win_name:
                    win_name = win_name.split("=")[-1].strip().strip('"')
                wm_class = self._run_cmd(["xprop", "-id", win_id, "WM_CLASS"]) or ""
                app_name = "Linux App"
                if "=" in wm_class:
                    app_name = wm_class.split("=")[-1].replace('"', "").split(",")[-1].strip()
                return {"app_name": app_name, "window_title": win_name}

        # 3. Wayland (Hyprland / Sway)
        if shutil.which("hyprctl"):
            hypr_out = self._run_cmd(["hyprctl", "activewindow", "-j"])
            if hypr_out and '"class":' in hypr_out:
                import json
                try:
                    data = json.loads(hypr_out)
                    return {
                        "app_name": data.get("class", "Hyprland App"),
                        "window_title": data.get("title", ""),
                    }
                except Exception:
                    pass

        return {"app_name": "Linux Desktop", "window_title": "Active Desktop"}

    def _detect_android(self) -> Dict[str, str]:
        """Android / Termux detection via dumpsys if root or termux-api."""
        # Try root dumpsys for current focus
        su_cmd = shutil.which("su")
        if su_cmd:
            res = self._run_cmd([su_cmd, "-c", "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"])
            if res:
                # e.g. mCurrentFocus=Window{... u0 com.android.chrome/com.google.android.apps.chrome.Main}
                match = re.search(r"([a-zA-Z0-9_\.]+)/([a-zA-Z0-9_\.]+)", res)
                if match:
                    pkg_name = match.group(1)
                    activity_name = match.group(2)
                    app_friendly = pkg_name.split(".")[-1].capitalize()
                    return {
                        "app_name": f"{app_friendly} ({pkg_name})",
                        "window_title": activity_name,
                    }

        # Non-root fallback: check if termux-api is available or return Termux / Foreground
        return {
            "app_name": "Android Application",
            "window_title": os.environ.get("TERM", "Termux Shell"),
        }

    def _run_cmd(self, cmd: list) -> Optional[str]:
        """Execute a sub-process command and return trimmed stdout."""
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            return None
        return None
