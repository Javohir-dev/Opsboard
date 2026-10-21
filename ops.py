import argparse
import getpass
import json
import sys

import config as cfg
import detect

MARK = {True: "✓", False: "✗", None: "–"}
USER_ONLY = {"claude.live_usage", "telegram.chat_id", "telegram.claude_chat", "telegram.chat_permission"}


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
    args = p.parse_args()
    if args.cmd == "config" and args.action in ("set", "unset") and not args.key:
        p.error("config set/unset needs a key")
    if args.cmd == "config" and args.action == "set" and args.value is None:
        p.error("config set needs a value")
    return {"detect": cmd_detect, "config": cmd_config, "secret": cmd_secret, "doctor": cmd_doctor}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
