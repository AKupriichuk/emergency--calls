"""Insert 100 emergency-call records before a load-test series and save one
id to reuse as the GET-by-id target for the whole series."""

import argparse
import random
from datetime import datetime, timedelta, timezone

import requests


def build_payload(i: int) -> dict:
    received = datetime.now(timezone.utc) - timedelta(minutes=i)
    arrived = received + timedelta(minutes=random.randint(5, 30))
    return {
        "call_number": f"SEED-{i:04d}",
        "urgency_category": random.randint(1, 4),
        "address": f"Test street {i}",
        "received_at": received.isoformat(),
        "arrived_at": arrived.isoformat(),
        "outcome": "transported",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out", default="results/seed_id.txt")
    args = parser.parse_args()

    first_id = None
    for i in range(args.count):
        response = requests.post(f"{args.base_url}/emergency-calls", json=build_payload(i), timeout=10)
        response.raise_for_status()
        if first_id is None:
            first_id = response.json()["id"]

    with open(args.out, "w") as fh:
        fh.write(first_id)
    print(f"seeded {args.count} records, sample id: {first_id}")


if __name__ == "__main__":
    main()
