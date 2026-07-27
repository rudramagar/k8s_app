"""
CLI runner for the ME session manager backend.

Run directly against the matching engine to test each protocol step
before any frontend exists:

    export MERCURY_PASSWORD='...'
    python -m app.main --host 10.0.0.1 --port 11005 --user a01

Password comes from the env var (not a flag) so it never shows up in
`ps` or `kubectl describe pod`.
"""
import argparse
import os
import sys

from client import MercuryClient


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="ME session manager backend")
    p.add_argument("-H", "--host", required=True, help="ME API host / IP")
    p.add_argument("-s", "--port", type=int, default=11005, help="ME API port")
    p.add_argument("-u", "--user", required=True, help="admin user, e.g. a01")
    p.add_argument("-p", "--password", default=os.environ.get("MERCURY_PASSWORD"),
                   help="admin password (or set MERCURY_PASSWORD env var)")
    p.add_argument("-a", "--action", default="login",
                   choices=["login", "list-users", "list-entry-points"],
                   help="what to do after login")
    p.add_argument("--sequence", default="1",
                   help="login requested sequence number (try 0 if login drops)")
    p.add_argument("--session", default="",
                   help="login requested session (blank = server default)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.password:
        print("ERROR: no password (set MERCURY_PASSWORD or pass --password)")
        return 2

    client = MercuryClient(host=args.host, port=args.port,
                           user=args.user, password=args.password,
                           session=args.session, sequence=args.sequence)
    try:
        client.connect()
        print(f"[main] connected to {args.host}:{args.port}")
        if not client.login():
            print("[main] LOGIN FAILED")
            return 1
        print("[main] LOGIN OK")

        if args.action == "list-users":
            rows = client.list_users()
            _print_rows("users", rows)
        elif args.action == "list-entry-points":
            rows = client.list_entry_points()
            _print_rows("entry points", rows)
        return 0
    finally:
        client.close()


def _print_rows(label, rows):
    print(f"\n[main] {len(rows)} {label}:")
    for r in rows:
        print(f"  {r}")


if __name__ == "__main__":
    sys.exit(main())
