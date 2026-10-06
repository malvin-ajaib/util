#!/usr/bin/env python3
"""
Two modes, toggled by FETCH_ENABLED:

  FETCH_ENABLED = True   -> FETCH mode: query active customer ajaib_ids and
                            dump them to JSON. Inject is NOT run.
  FETCH_ENABLED = False  -> INJECT mode: skip the DB fetch, read the JSON,
                            and inject stock portfolios for each customer.

Each JSON record:
  {
    "ajaib_id": <int>,
    "injected": <bool>,          # true once inject has been attempted
    "inject_status": null | {    # per-stock result, null until injected
        "<stock_code>": "success" | "failed"
    }
  }

All configuration lives in the global vars below.
"""

import json
import random
import sys
import uuid

import pymysql
import requests

# --- Mode switch -------------------------------------------------------------
# True  = fetch mode (write JSON, no inject).
# False = inject mode (read JSON, run inject).
FETCH_ENABLED = False

# --- DB config (fetch mode) --------------------------------------------------
DB_HOST = "127.0.0.1"
DB_USER = "cloudsql-rw"
DB_NAME = "ajaib_stock_sandbox"
DB_PORT = 62201
DB_PASSWORD = ""  # <-- fill in

# Retrieve exactly LIMIT rows starting at OFFSET (single query, no loop).
LIMIT = 4500
OFFSET = 500

# --- Inject config (inject mode) ---------------------------------------------
# How many customers (from the JSON) to inject portfolios for.
NUMBER_TO_INJECT = 3500
# Stocks to inject per customer; each customer gets one credit per code.
STOCK_CODES = ["BBCA", "BBRI", "BBTN", "TLKM", "ASII"]
# Random lot per stock, inclusive bounds. shares = lot * 100.
MIN_LOT = 1
MAX_LOT = 5

INJECT_URL = ("http://stock-asset-ledger-http.stg.ajaib.int"
              "/api/v1/internal/stock-asset-ledger/asset/REG/credit")
SOURCE = "TRADING_SERVICE"
PRICE = 100

# --- Output ------------------------------------------------------------------
OUT = "inject_portfolio_out.json"

QUERY = """
    select c.ajaib_id
    from ajaib_stock_sandbox.customer c
    where c.status_fgs = 'ACTIVE'
      and (c.status_s21 = 'ACTIVE' or c.status_s21 = 'READY')
    order by c.created_at asc
    limit %s offset %s
"""


# --- Fetch mode --------------------------------------------------------------
def fetch_customers():
    """Run the query once for LIMIT/OFFSET and return the list of records."""
    conn = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        database=DB_NAME,
        port=DB_PORT,
        password=DB_PASSWORD,
    )
    records = []
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY, (LIMIT, OFFSET))
            rows = cur.fetchall()
            for (ajaib_id,) in rows:
                records.append({
                    "ajaib_id": ajaib_id,
                    "injected": False,
                    "inject_status": None,
                })
            print(f"[limit {LIMIT} offset {OFFSET}] {len(rows)} rows")
    finally:
        conn.close()
    return records


def load_records():
    """Load existing records from OUT, or [] if it doesn't exist yet."""
    try:
        with open(OUT, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def run_fetch():
    try:
        fetched = fetch_customers()
    except pymysql.MySQLError as e:
        sys.exit(f"ERROR: database error: {e}")

    records = load_records()
    existing_ids = {r["ajaib_id"] for r in records}

    added = 0
    skipped = 0
    for rec in fetched:
        if rec["ajaib_id"] in existing_ids:
            skipped += 1
            continue
        records.append(rec)
        existing_ids.add(rec["ajaib_id"])
        added += 1

    save_records(records)

    print(f"\nSummary: {added} added, {skipped} skipped (duplicate). "
          f"{len(records)} total records in {OUT}.")


# --- Inject mode -------------------------------------------------------------
def credit_stock(ajaib_id, stock_code, lot):
    """POST one credit for (customer, stock). Returns True on success."""
    payload = {
        "stock_code": stock_code,
        "source": SOURCE,
        "source_id": str(uuid.uuid4()),   # unique per request
        "shares": lot * 100,
        "price": PRICE,
    }
    headers = {
        "accept": "*/*",
        "User-Id": str(ajaib_id),
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(INJECT_URL, headers=headers, json=payload,
                             timeout=30)
        return 200 <= resp.status_code < 300
    except requests.RequestException:
        return False


def save_records(records):
    """Persist the full records list back to OUT."""
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def inject_portfolio(records):
    """Inject stocks for up to NUMBER_TO_INJECT not-yet-injected customers."""
    targets = [r for r in records if not r.get("injected")][:NUMBER_TO_INJECT]
    if not targets:
        print("No customers left to inject.")
        return targets

    for i, rec in enumerate(targets, 1):
        ajaib_id = rec["ajaib_id"]
        status = {}
        for stock_code in STOCK_CODES:
            lot = random.randint(MIN_LOT, MAX_LOT)
            ok = credit_stock(ajaib_id, stock_code, lot)
            status[stock_code] = "success" if ok else "failed"
            print(f"[{i}/{len(targets)}] ajaib_id={ajaib_id} "
                  f"{stock_code} lot={lot} -> {status[stock_code]}")
        rec["inject_status"] = status
        rec["injected"] = True  # attempted, regardless of per-stock outcome
        save_records(records)   # persist progress after each customer

    return targets


def run_inject():
    try:
        with open(OUT, "r", encoding="utf-8") as f:
            records = json.load(f)
    except FileNotFoundError:
        sys.exit(f"ERROR: {OUT} not found. Run fetch mode first "
                 f"(FETCH_ENABLED = True).")

    injected = inject_portfolio(records)
    save_records(records)  # final save (also covers the no-targets case)

    n = len(injected) if injected else 0
    print(f"\nDone. Injected {n} customer(s); {OUT} updated.")


def main():
    if FETCH_ENABLED:
        run_fetch()
    else:
        run_inject()


if __name__ == "__main__":
    main()
