"""
paths.py — figure out where the app's files live and where it may write.

This lets the same code run three ways without changes:
  * normally  (python server.py)          -> files next to this script
  * packaged  (a PyInstaller .exe)         -> files unpacked in a temp folder,
                                              cache written next to the .exe
  * overridden (ACARS_CACHE_DIR env var)   -> cache written wherever you point it
"""

import os
import sys
import tempfile


def _frozen():
    # True for a PyInstaller .exe (sys.frozen) or a Nuitka-compiled build
    # (Nuitka injects __compiled__ into every module's globals).
    return getattr(sys, "frozen", False) or ("__compiled__" in globals())


def app_dir():
    """Directory that contains the app's data files (static/, etc.)."""
    if _frozen():
        # PyInstaller unpacks bundled data into _MEIPASS at runtime; Nuitka (and
        # a PyInstaller one-folder build) place data next to the executable.
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, ".write_test")
        with open(t, "w"):
            pass
        os.remove(t)
        return True
    except Exception:
        return False


def cache_root():
    """A writable folder for downloaded data files and rendered images."""
    env = os.environ.get("ACARS_CACHE_DIR")
    if env and _writable(env):
        return env
    if _frozen():
        # prefer a folder right next to the .exe so it's easy to find / clear;
        # if that location is read-only (e.g. Program Files), use the temp dir
        beside_exe = os.path.join(os.path.dirname(sys.executable), "acars_cache")
        if _writable(beside_exe):
            return beside_exe
        return os.path.join(tempfile.gettempdir(), "acars_tracks_cache")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
