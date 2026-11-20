import os
import shutil
import subprocess
import sys

import safety

SERVICE = os.environ.get("OPS_SECRET_SERVICE", "opsboard")
LEGACY_SERVICE = "claude-ops"
NAMES = {"keychain": "macOS Keychain", "libsecret": "Secret Service (libsecret)"}


def backend():
    mode = os.environ.get("OPS_SECRET_STORE", "")
    if mode == "file":
        return None
    if mode in NAMES:
        return mode
    if os.environ.get("OPS_CONFIG") or os.environ.get("OPS_DATA_DIR"):
        return None
    if sys.platform == "darwin" and shutil.which("security"):
        return "keychain"
    if shutil.which("secret-tool") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return "libsecret"
    return None


def _run(cmd, stdin=None):
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


def _read(service, key):
    kind = backend()
    if kind == "keychain":
        r = _run(["security", "find-generic-password", "-s", service, "-a", key, "-w"])
    elif kind == "libsecret":
        r = _run(["secret-tool", "lookup", "service", service, "key", key])
    else:
        return None
    return r.stdout.rstrip("\n") if r and r.returncode == 0 else None


def read(key):
    value = _read(SERVICE, key)
    if value is None and SERVICE != LEGACY_SERVICE and not os.environ.get("OPS_SECRET_SERVICE"):
        old = _read(LEGACY_SERVICE, key)
        if old is not None and write(key, old):
            _delete(LEGACY_SERVICE, key)
            return old
    return value


def write(key, value):
    kind = backend()
    if kind == "keychain":
        safety.allow_keychain()
        r = _run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", key, "-l", f"{SERVICE} {key}", "-w", value])
    elif kind == "libsecret":
        r = _run(["secret-tool", "store", "--label", f"{SERVICE} {key}", "service", SERVICE, "key", key], stdin=value)
    else:
        return False
    return bool(r and r.returncode == 0) and _read(SERVICE, key) == value


def _delete(service, key):
    kind = backend()
    if kind == "keychain":
        safety.allow_keychain()
        _run(["security", "delete-generic-password", "-s", service, "-a", key])
    elif kind == "libsecret":
        _run(["secret-tool", "clear", "service", service, "key", key])


def delete(key):
    _delete(SERVICE, key)


def name():
    return NAMES.get(backend(), "config.json")
