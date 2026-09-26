"""Operator-only CLI for test accounts and demo access."""

import argparse
from getpass import getpass
from pathlib import Path

from .auth import CredentialExists
from .operator import provision_user, revoke_demo_member, seed_demo


def _password():
    first = getpass("Password (12+ characters): ")
    second = getpass("Repeat password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    return first


def main(argv=None):
    parser = argparse.ArgumentParser(description="selecont closed-demo operator commands")
    parser.add_argument("--db", type=Path, required=True, help="SQLite database path")
    commands = parser.add_subparsers(dest="command", required=True)
    provision = commands.add_parser("provision", help="create one test account")
    provision.add_argument("handle")
    provision.add_argument("--reset-password", action="store_true")
    seed = commands.add_parser("seed-demo", help="create grigory/friend/family/stranger")
    seed.add_argument("--reset-passwords", action="store_true")
    revoke = commands.add_parser("revoke", help="remove a follower from the author's circle")
    revoke.add_argument("author")
    revoke.add_argument("follower")
    args = parser.parse_args(argv)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "provision":
            provision_user(args.db, args.handle, _password(), replace_password=args.reset_password)
            print(f"Provisioned @{args.handle}")
        elif args.command == "seed-demo":
            seed_demo(args.db, _password(), replace_password=args.reset_passwords)
            print("Provisioned demo handles: " + ", ".join(("grigory", "friend", "family", "stranger")))
        else:
            revoke_demo_member(args.db, args.author, args.follower)
            print(f"Revoked @{args.follower} from @{args.author}'s private circle")
    except CredentialExists:
        raise SystemExit("Account already has a password; use the explicit reset flag to replace it")
    except ValueError as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main()
