#!/usr/bin/env python3
"""
Read the inject-portfolio JSON and dump all ajaib_id values to CSV.

Config lives in the global vars below.
"""

import csv
import json
import sys

IN = "inject_portfolio_out.json"
OUT = "injected_users_out.csv"


def main():
    try:
        with open(IN, "r", encoding="utf-8") as f:
            records = json.load(f)
    except FileNotFoundError:
        sys.exit(f"ERROR: {IN} not found.")

    ajaib_ids = [r["ajaib_id"] for r in records if r.get("injected") is True]

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ajaib_id"])
        for ajaib_id in ajaib_ids:
            writer.writerow([ajaib_id])

    print(f"Done. {len(ajaib_ids)} ajaib_id(s) written to {OUT}")


if __name__ == "__main__":
    main()
