import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://oid.ajaib.co.id/api/v1/coin-payment/service/history"

ENV_PATH = Path(__file__).resolve().parent / ".env"

BASE_HEADERS = {
    "x-device-signature": "qa-test-automation-1",
    "x-device-name": "SAMSUNG-S27",
    "x-app-mode": "PRO",
    "X-Android-Ver-Id": "ed1b83a6-2fc0-4b1f-a0e9-e17e1afca906",
    "X-Android-Ver-Name": "2.99.0 (333)",
    "X-Show-Mutual-Fund": "1",
    "X-Platform": "ANDROID",
    "User-Agent": "Android-333",
    "Accept-Language": "id",
    "X-Product": "stock-mf",
    "X-Android-Ver-Code": "333",
    "X-Quick-Buy": "0",
    "Host": "oid.ajaib.co.id",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
    "User-Id": "1",
}


def load_env(path: Path):
    """Minimal .env loader: KEY=VALUE per line, # comments, optional quotes."""
    if not path.exists():
        sys.exit(f"ERROR: no .env file found at {path}. "
                 f"Copy .env.example to .env and fill it in.")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Don't clobber a value already set in the real environment.
        os.environ.setdefault(key, value)


class Config:
    """Runtime config sourced entirely from environment / .env."""

    def __init__(self):
        self.token = os.environ.get("TOKEN", "").strip()
        self.cutoff_raw = os.environ.get("CUTOFF", "").strip()
        self.out = os.environ.get("OUT", "coin_out.json").strip() or "coin_out.json"
        self.delay = float(os.environ.get("DELAY", "0.2") or "0.2")
        self.max_pages = int(os.environ.get("MAX_PAGES", "1000") or "1000")
        # Keep only objects with timestamp >= cutoff in the final dump.
        self.strict = os.environ.get("STRICT", "1").strip().lower() not in (
            "0", "false", "no", "")

        if not self.token:
            sys.exit("ERROR: TOKEN is missing in .env")
        if not self.cutoff_raw:
            sys.exit("ERROR: CUTOFF is missing in .env")
        try:
            self.cutoff = datetime.strptime(self.cutoff_raw, "%Y-%m-%d")
        except ValueError:
            sys.exit("ERROR: CUTOFF must be in YYYY-MM-DD format")


def normalize_token(raw: str) -> str:
    raw = raw.strip()
    if raw.lower().startswith("jwt "):
        return raw  # already "jwt <token>"
    return f"jwt {raw}"


def main():
    load_env(ENV_PATH)
    cfg = Config()
    cutoff = cfg.cutoff

    headers = dict(BASE_HEADERS)
    headers["Authorization"] = normalize_token(cfg.token)

    session = requests.Session()
    ref = ""            # first request: empty ref
    dump = []           # accumulator
    page = 0

    while page < cfg.max_pages:
        page += 1
        try:
            resp = session.get(BASE_URL, headers=headers,
                               params={"ref": ref}, timeout=30)
        except requests.RequestException as e:
            sys.exit(f"ERROR: request failed on page {page}: {e}")

        if resp.status_code == 401:
            sys.exit("ERROR: 401 Unauthorized - token likely expired.")
        if resp.status_code != 200:
            sys.exit(f"ERROR: HTTP {resp.status_code} on page {page}: "
                     f"{resp.text[:300]}")

        try:
            body = resp.json()
        except ValueError:
            sys.exit(f"ERROR: non-JSON response on page {page}: "
                     f"{resp.text[:300]}")

        results = body.get("results") or []

        # Break point 1: empty page
        if not results:
            print(f"[page {page}] empty results - stopping.")
            break

        dump.extend(results)

        # Oldest object on page (array is newest-first)
        oldest = results[-1]
        oldest_ts_raw = oldest.get("timestamp", "")
        try:
            oldest_ts = datetime.fromisoformat(oldest_ts_raw)
        except ValueError:
            sys.exit(f"ERROR: cannot parse timestamp '{oldest_ts_raw}' "
                     f"on page {page}")

        print(f"[page {page}] +{len(results)} objs "
              f"(total {len(dump)}), oldest={oldest_ts_raw}")

        # Break point 2: passed the cutoff date
        if oldest_ts < cutoff:
            print(f"[page {page}] oldest {oldest_ts_raw} < cutoff "
                  f"{cfg.cutoff_raw} - stopping.")
            break

        # Next ref = oldest object's payment_id
        next_ref = oldest.get("payment_id")
        if not next_ref:
            print(f"[page {page}] no payment_id on oldest object - stopping.")
            break
        ref = next_ref

        time.sleep(cfg.delay)
    else:
        print(f"Reached max-pages ceiling ({cfg.max_pages}) - stopping.")

    # Post-filter: drop objects older than the cutoff (the final page can
    # contain some), unless STRICT is disabled.
    if cfg.strict:
        before = len(dump)
        dump = [
            o for o in dump
            if _ts_ok(o.get("timestamp", ""), cutoff)
        ]
        dropped = before - len(dump)
        if dropped:
            print(f"Filtered out {dropped} object(s) older than "
                  f"{cfg.cutoff_raw}.")

    with open(cfg.out, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(dump)} objects written to {cfg.out}")


def _ts_ok(ts_raw: str, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(ts_raw) >= cutoff
    except ValueError:
        return True  # keep anything we can't parse rather than silently drop


if __name__ == "__main__":
    main()