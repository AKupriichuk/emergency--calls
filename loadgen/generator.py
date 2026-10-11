"""Open-loop and closed-loop HTTP load generator.

Open loop: every request's send time is computed in advance from the start
of the run, independent of when earlier responses arrive. Scheduling is
split across worker processes (one per CPU core) because computing send
times and parsing responses is CPU-bound in Python and the GIL would
otherwise serialize it onto one core; each worker process also keeps its
own thread pool so its scheduling loop never blocks waiting for a response.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests


@dataclass
class RequestResult:
    worker_id: int
    seq: int
    sent_ts: float
    done_ts: float
    status_code: int
    error: str
    instance_id: str


def _do_request(
    session: requests.Session, url: str, worker_id: int, seq: int, sent_ts: float
) -> RequestResult:
    try:
        response = session.get(url, timeout=10)
        return RequestResult(
            worker_id,
            seq,
            sent_ts,
            time.time(),
            response.status_code,
            "",
            response.headers.get("X-Instance-Id", ""),
        )
    except requests.RequestException as exc:
        return RequestResult(worker_id, seq, sent_ts, time.time(), 0, str(exc), "")


def _write_part(path: str, results: list[RequestResult]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["worker_id", "seq", "sent_ts", "done_ts", "status_code", "error", "instance_id"])
        for r in results:
            writer.writerow([r.worker_id, r.seq, r.sent_ts, r.done_ts, r.status_code, r.error, r.instance_id])


def _open_loop_worker(
    worker_id: int, url: str, worker_rate: float, total_seconds: float, start_time: float, out_path: str
) -> None:
    session = requests.Session()
    count = max(1, int(worker_rate * total_seconds))
    results: list[RequestResult] = []

    with ThreadPoolExecutor(max_workers=max(4, int(worker_rate / 5) + 1)) as pool:
        futures = []
        for seq in range(count):
            target_time = start_time + seq / worker_rate
            sleep_for = target_time - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            futures.append(pool.submit(_do_request, session, url, worker_id, seq, time.time()))
        for future in futures:
            results.append(future.result())

    _write_part(out_path, results)


def _merge_parts(part_paths: list[str], out_path: str, warmup_s: float, start_time: float) -> None:
    with open(out_path, "w", newline="") as out_fh:
        writer = csv.writer(out_fh)
        writer.writerow(
            ["worker_id", "seq", "sent_ts", "done_ts", "status_code", "error", "instance_id", "warmup"]
        )
        for part_path in part_paths:
            with open(part_path, newline="") as in_fh:
                for row in csv.DictReader(in_fh):
                    is_warmup = float(row["sent_ts"]) - start_time < warmup_s
                    writer.writerow(
                        [
                            row["worker_id"],
                            row["seq"],
                            row["sent_ts"],
                            row["done_ts"],
                            row["status_code"],
                            row["error"],
                            row["instance_id"],
                            int(is_warmup),
                        ]
                    )
            os.remove(part_path)


def run_open_loop(url: str, rate: float, warmup_s: float, duration_s: float, out_path: str) -> None:
    num_workers = os.cpu_count() or 1
    worker_rate = rate / num_workers
    total_seconds = warmup_s + duration_s
    start_time = time.time() + 1.0

    part_paths = [f"{out_path}.part{i}" for i in range(num_workers)]
    processes = [
        mp.Process(
            target=_open_loop_worker,
            args=(i, url, worker_rate, total_seconds, start_time, part_paths[i]),
        )
        for i in range(num_workers)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()

    _merge_parts(part_paths, out_path, warmup_s, start_time)


def _closed_loop_worker(worker_id: int, url: str, end_time: float, out_path: str) -> None:
    session = requests.Session()
    results: list[RequestResult] = []
    seq = 0
    while time.time() < end_time:
        sent_ts = time.time()
        results.append(_do_request(session, url, worker_id, seq, sent_ts))
        seq += 1
    _write_part(out_path, results)


def run_closed_loop(url: str, concurrency: int, warmup_s: float, duration_s: float, out_path: str) -> None:
    start_time = time.time() + 1.0
    end_time = start_time + warmup_s + duration_s

    part_paths = [f"{out_path}.part{i}" for i in range(concurrency)]
    processes = [
        mp.Process(target=_closed_loop_worker, args=(i, url, end_time, part_paths[i]))
        for i in range(concurrency)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()

    _merge_parts(part_paths, out_path, warmup_s, start_time)


def run_selfcheck(url: str, rate: float, duration_s: float) -> None:
    out_path = "/tmp/selfcheck.csv"
    run_open_loop(url, rate, warmup_s=0, duration_s=duration_s, out_path=out_path)
    with open(out_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    achieved = len(rows) / duration_s
    print(f"target rate: {rate} req/s, achieved rate: {achieved:.1f} req/s, sent: {len(rows)}")
    os.remove(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Open/closed loop HTTP load generator")
    sub = parser.add_subparsers(dest="mode", required=True)

    open_p = sub.add_parser("open")
    open_p.add_argument("--url", required=True)
    open_p.add_argument("--rate", type=float, required=True)
    open_p.add_argument("--warmup", type=float, default=10)
    open_p.add_argument("--duration", type=float, default=30)
    open_p.add_argument("--out", required=True)

    closed_p = sub.add_parser("closed")
    closed_p.add_argument("--url", required=True)
    closed_p.add_argument("--concurrency", type=int, required=True)
    closed_p.add_argument("--warmup", type=float, default=10)
    closed_p.add_argument("--duration", type=float, default=30)
    closed_p.add_argument("--out", required=True)

    selfcheck_p = sub.add_parser("selfcheck")
    selfcheck_p.add_argument("--url", required=True)
    selfcheck_p.add_argument("--rate", type=float, required=True)
    selfcheck_p.add_argument("--duration", type=float, default=10)

    args = parser.parse_args()
    if args.mode == "open":
        run_open_loop(args.url, args.rate, args.warmup, args.duration, args.out)
    elif args.mode == "closed":
        run_closed_loop(args.url, args.concurrency, args.warmup, args.duration, args.out)
    elif args.mode == "selfcheck":
        run_selfcheck(args.url, args.rate, args.duration)


if __name__ == "__main__":
    main()
