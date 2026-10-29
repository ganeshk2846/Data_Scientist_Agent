"""Supervised process entry point for persisted BE-2 refresh schedules."""
from __future__ import annotations

import argparse
import logging
import signal
import threading

from .service import OnboardingService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="service state directory")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    service = OnboardingService(args.root)
    try:
        service.run_scheduler(stopped, poll_seconds=args.poll_seconds)
    finally:
        service.close()


if __name__ == "__main__":
    main()
