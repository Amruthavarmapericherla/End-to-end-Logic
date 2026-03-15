from __future__ import annotations
import argparse
import logging
import time

from runner import Runner
from datetime import datetime, timedelta
from pymongo.errors import PyMongoError
from utils import sleep_with_jitter

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Telekom scraper - direct selector mode")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip numbers that already have a 200 + content")
    p.add_argument("--limit", type=int, default=None,
                   help="Max numbers to process this run (default: env BATCH_LIMIT=200)")
    p.add_argument("--delay-sec", type=float, default=None,
                   help="Delay between processing numbers (default: env PROCESS_DELAY_SEC=0)")
    p.add_argument("--min-cycle-sec", type=float, default=3600,
                   help="Minimum length of each cycle before next DB query (default: 3600 seconds)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    runner = Runner(
        skip_existing=args.skip_existing,
        limit=args.limit,
        delay_sec=args.delay_sec,
    )
    log.info(
        "startup_config",
        extra={
            "extra_mode": runner.mode,
            "extra_min_cycle_sec": args.min_cycle_sec,
            "extra_per_item_delay_min_sec": 20.0,
            "extra_per_item_delay_max_sec": 40.0,
        },
    )
    _run_continuous(runner, min_cycle_sec=args.min_cycle_sec)


def _run_continuous(runner: Runner, min_cycle_sec: float) -> None:
    """Run batches forever, waiting out the remainder of each cycle to avoid hammering the DB."""
    while True:
        start = time.monotonic()
        try:
            selected_count = runner.run_once()
        except PyMongoError:
            log.exception(
                "mongo_unavailable",
                extra={
                    "extra_min_cycle_sec": min_cycle_sec,
                    "extra_retry_sleep_sec": 60,
                },
            )
            # Avoid exiting the process on temporary Mongo outages.
            sleep_with_jitter(60.0, jitter_range=10.0)
            continue
        elapsed = time.monotonic() - start
        sleep_for = max(0.0, min_cycle_sec - elapsed)
        if selected_count == 0:
            log.info(
                "selection_empty",
                extra={
                    "extra_limit": runner.limit,
                    "extra_delay_sec": runner.delay_sec,
                    "extra_mode": runner.mode,
                    "extra_elapsed_sec": round(elapsed, 2),
                    "extra_sleep_sec": round(sleep_for, 2),
                    "extra_min_cycle_sec": min_cycle_sec,
                },
            )
        if sleep_for > 0:
            log.info(
                "cycle_sleep",
                extra={
                    "extra_elapsed_sec": round(elapsed, 2),
                    "extra_sleep_sec": round(sleep_for, 2),
                    "extra_min_cycle_sec": min_cycle_sec,
                },
            )
            time.sleep(sleep_for)


if __name__ == "__main__":
    main()
