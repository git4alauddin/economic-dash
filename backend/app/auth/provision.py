"""Private account administration: python -m app.auth.provision --username NAME.

Create/repeat safely, or explicitly --reset-password, --disable, --enable.
Passwords are accepted only from a non-echoing interactive prompt, never argv.
"""

import argparse
from getpass import GetPassWarning, getpass
import json
import sqlite3
import sys
import warnings

from argon2.exceptions import HashingError
from pydantic import ValidationError

from app.config import get_database_settings, get_settings
from app.database import Database
from .passwords import PasswordWorkBusy, normalize_username
from .users import UserStore


class AccountParser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo unrecognized argv: someone may have pasted a password.
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid account command; use --help. Passwords are prompted privately.\n")


def main(argv=None) -> int:
    parser = AccountParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--username", required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--reset-password", action="store_true")
    actions.add_argument("--disable", action="store_true")
    actions.add_argument("--enable", action="store_true")
    args = parser.parse_args(argv)
    password = confirmation = None
    try:
        name = normalize_username(args.username)
        if not (args.disable or args.enable):
            if not sys.stdin.isatty():
                raise ValueError("Run provisioning in an interactive terminal with password echo disabled.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                password = getpass("Password (15-128 characters): ")
                confirmation = getpass("Confirm password: ")
            if password != confirmation:
                raise ValueError("Passwords do not match.")
        database = Database(get_database_settings(get_settings().app_env))
        database.bootstrap()
        store = UserStore(database)
        if args.disable or args.enable:
            account = store.set_active(name, not args.disable)
            action = "enabled" if account.is_active else "disabled"
        else:
            result = store.provision(name, password, reset_password=args.reset_password)
            account, action = result.identity, result.action
        print(json.dumps({"result": "ok", "action": action, "is_active": account.is_active}))
        return 0
    except ValidationError:
        print("Account configuration is invalid.", file=sys.stderr)
        return 1
    except (ValueError, GetPassWarning) as error:
        print(str(error), file=sys.stderr)  # Only controlled validation/conflict messages.
        return 1
    except (OSError, sqlite3.Error, RuntimeError, HashingError, PasswordWorkBusy):
        print("Account operation could not be completed.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Account operation canceled.", file=sys.stderr)
        return 1
    finally:
        # Drop local references; Python strings cannot promise secure erasure.
        password = confirmation = None


if __name__ == "__main__":
    raise SystemExit(main())
