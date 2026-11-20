import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

import config as cfg
import detect
import safety

MARK = {True: "✓", False: "✗", None: "–"}
USER_ONLY = {"claude.live_usage", "telegram.chat_id", "telegram.claude_chat", "telegram.chat_permission", "telegram.webapp"}


def parse_value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def cmd_detect(args):
    results, notes = detect.detect_all()
    changed = detect.apply(results) if args.apply else []
    if args.json:
        print(json.dumps({"results": results, "notes": notes, "applied": args.apply, "changed": changed}, ensure_ascii=False, indent=2))
        return 0
    for key, item in results.items():
        print(f"{key:22} {str(item['value'])[:60]:62} {item['confidence']:.1f}  {item['from']}")
    for note in notes:
        print(f"note: {note}")
    print("applied as auto values" if args.apply else "dry run — add --apply to save as auto values")
    return 0


def cmd_config(args):
    if args.action == "get":
        data = cfg.public()
        if args.key:
            if args.key not in data:
                print(f"unknown setting {args.key}", file=sys.stderr)
                return 2
            data = {args.key: data[args.key]}
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if args.key in cfg.SECRETS:
        print(f"{args.key} is a secret — use `opsboard secret set {args.key}` or the Settings page", file=sys.stderr)
        return 2
    try:
        if args.key in USER_ONLY and args.source != "user":
            raise ValueError(f"{args.key} can only be changed by you, in Settings")
        if args.action == "set":
            cfg.set(args.key, parse_value(args.value), args.source, args.origin or f"set by {args.source}")
        else:
            cfg.set(args.key, None, args.source)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps({args.key: cfg.entry(args.key)}, ensure_ascii=False))
    return 0


def cmd_secret(args):
    value = "" if args.clear else getpass.getpass(f"{args.key} (input hidden): ").strip()
    try:
        cfg.set_secret(args.key, value)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"{args.key}: {'cleared' if not value else 'saved ' + cfg.masked(value)}")
    return 0


def cmd_doctor(args):
    checks = detect.doctor()
    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            hint = f"  → fix: {c['fix']}" if c["ok"] is False and c["fix"] else ""
            print(f"{MARK[c['ok']]} {c['id']:9} {c['detail']}{hint}")
    return 1 if any(c["ok"] is False for c in checks) else 0


def _target(item):
    kind, name = item.parent.name, item.name.split("-", 3)[-1]
    data = cfg.CONFIG_FILE.parent
    return {
        "config": cfg.CONFIG_FILE,
        "claude-settings": Path(os.environ.get("OPS_CLAUDE_SETTINGS", Path.home() / ".claude" / "settings.json")),
        "marks": data / "marks.json",
        "notes": data / "notes.json",
        "claude-logins": data / "claude-logins" / name,
    }.get(kind)


def cmd_backups(args):
    items = [i for i in safety.listing() if not args.kind or i.parent.name == args.kind]
    for i in items[-args.last:]:
        print(f"{i.parent.name:16} {i.name}")
    if not items:
        print("no backups yet")


def cmd_restore(args):
    item = next((i for i in safety.listing() if i.name == args.name), None)
    if not item:
        print(f"no backup named {args.name} — see: opsboard backups")
        return 1
    dest = _target(item)
    safety.backup(dest, item.parent.name)
    if item.is_dir():
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(item, dest)
    else:
        shutil.copy2(item, dest)
    print(f"restored {dest} from {item.name} (the version it replaced is backed up too)")


def main():
    p = argparse.ArgumentParser(prog="opsboard")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect", help="detect settings from the project folder and tokens")
    d.add_argument("--apply", action="store_true")
    d.add_argument("--json", action="store_true")
    c = sub.add_parser("config", help="read or change settings")
    c.add_argument("action", choices=["get", "set", "unset"])
    c.add_argument("key", nargs="?")
    c.add_argument("value", nargs="?")
    c.add_argument("--source", choices=cfg.SOURCES, default="user")
    c.add_argument("--from", dest="origin", default="")
    s = sub.add_parser("secret", help="store a token without echoing it")
    s.add_argument("action", choices=["set"])
    s.add_argument("key", choices=cfg.SECRETS)
    s.add_argument("--clear", action="store_true")
    dr = sub.add_parser("doctor", help="check every connection")
    dr.add_argument("--json", action="store_true")
    b = sub.add_parser("backups", help="list the copies kept before every change")
    b.add_argument("kind", nargs="?", choices=["config", "claude-settings", "claude-logins", "marks", "notes"])
    b.add_argument("--last", type=int, default=30)
    r = sub.add_parser("restore", help="put a backup back")
    r.add_argument("name")
    args = p.parse_args()
    if args.cmd == "config" and args.action in ("set", "unset") and not args.key:
        p.error("config set/unset needs a key")
    if args.cmd == "config" and args.action == "set" and args.value is None:
        p.error("config set needs a value")
    return {"detect": cmd_detect, "config": cmd_config, "secret": cmd_secret, "doctor": cmd_doctor, "backups": cmd_backups, "restore": cmd_restore}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
