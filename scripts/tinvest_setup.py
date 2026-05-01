"""List or open T-Invest sandbox accounts.

Usage:
    set -a && . .env && set +a   # load TINVEST_SANDBOX_TOKEN into env
    python scripts/tinvest_setup.py            # list existing accounts
    python scripts/tinvest_setup.py --open     # create a new sandbox account

Prints account ids only. Token is read from env, never logged.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from src.execution.tinvest import TInvestSandboxAdapter


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--open", action="store_true", help="create a new sandbox account before listing"
    )
    args = parser.parse_args()

    token = os.environ.get("TINVEST_SANDBOX_TOKEN", "").strip()
    if not token:
        print("error: TINVEST_SANDBOX_TOKEN is empty (`set -a; . .env; set +a` first)")
        return 1

    async with TInvestSandboxAdapter(token, account_id="probe", figi_resolver={}) as ad:
        if args.open:
            new_id = await ad.open_sandbox_account()
            print(f"opened: {new_id}")

        accounts = await ad.list_accounts()
        if not accounts:
            print("no sandbox accounts (run with --open to create one)")
            return 0

        print(f"{len(accounts)} sandbox account(s):")
        for a in accounts:
            acc_id = str(a.get("id", ""))
            status = a.get("status", "?")
            opened_at = a.get("openedDate", "?")
            print(f"  {acc_id}  status={status}  opened={opened_at}")
        print()
        print("Add to .env:")
        print(f"TINVEST_SANDBOX_ACCOUNT_ID={accounts[0].get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
