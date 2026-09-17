#!/usr/bin/python3
"""Print the last N log lines as a table: python3 overmind/tail.py [N]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from overmind import log  # noqa: E402


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    for line in log.read(limit=n):
        answers = line.get("answers") or {}
        detail = " ".join("%s=%.2f" % kv for kv in answers.items())
        if line.get("interrupted"):  # the free label: he stopped that turn n messages in
            detail = ("escape@%s %s" % (line.get("depth", "?"), detail)).strip()
        if line.get("error") or line.get("tail_error"):
            detail = ("%s error=%s" % (detail, line.get("error") or line["tail_error"])).strip()
        print("%s  %-16s %-8s %-14s %5s ms  %s" % (line.get("ts", "")[11:19], line.get("event", ""),
                                                    line.get("session_id", "")[:8], line.get("cwd", "")[:14],
                                                    line.get("ms", "-"), detail))


if __name__ == "__main__":
    main()
