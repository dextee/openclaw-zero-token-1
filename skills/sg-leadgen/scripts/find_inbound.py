#!/usr/bin/env python3
"""
find_inbound.py — Locate the most recent Telegram-uploaded file.

OpenClaw's Telegram plugin saves incoming documents/photos to:
    /root/openclaw-zero-token/.openclaw-upstream-state/media/inbound/

Usage:
    python3 find_inbound.py                 # latest file of any type
    python3 find_inbound.py --ext xlsx      # latest xlsx
    python3 find_inbound.py --filename "Brdge*"   # glob match
    python3 find_inbound.py --copy /dest.xlsx     # also copy to dest
"""
import argparse
import fnmatch
import os
import shutil
import sys

INBOUND_DIR = "/root/openclaw-zero-token/.openclaw-upstream-state/media/inbound"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ext", default="", help="extension filter (xlsx/csv/pdf)")
    p.add_argument("--filename", default="", help="glob match on filename")
    p.add_argument("--copy", default="", help="copy selected file to this path")
    p.add_argument("--list", action="store_true", help="list all inbound files")
    p.add_argument("--count", type=int, default=1, help="show N most recent")
    args = p.parse_args()

    if not os.path.isdir(INBOUND_DIR):
        print(f"ERROR: inbound dir not found: {INBOUND_DIR}", file=sys.stderr)
        sys.exit(1)

    files = []
    for f in os.listdir(INBOUND_DIR):
        full = os.path.join(INBOUND_DIR, f)
        if not os.path.isfile(full):
            continue
        if args.ext and not f.lower().endswith("." + args.ext.lower().lstrip(".")):
            continue
        if args.filename and not fnmatch.fnmatch(f, args.filename):
            continue
        files.append((os.path.getmtime(full), full, f))

    if not files:
        print(f"NO_MATCH (filters: ext={args.ext!r} filename={args.filename!r})")
        sys.exit(2)

    files.sort(reverse=True)

    if args.list:
        for mtime, full, name in files[:args.count]:
            size = os.path.getsize(full)
            print(f"{full}  ({size} bytes)")
        return

    # default: print the most recent file path
    most_recent = files[0][1]
    print(most_recent)

    if args.copy:
        os.makedirs(os.path.dirname(args.copy) or ".", exist_ok=True)
        shutil.copy(most_recent, args.copy)
        print(f"COPIED_TO: {args.copy}", file=sys.stderr)


if __name__ == "__main__":
    main()
