#!/usr/bin/env python3
"""Collect Linux server metrics and save threshold events."""

import argparse
import csv
import json
import logging
import math
import platform
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


FIELDS = [
    "timestamp_utc",
    "elapsed_seconds",
    "cpu_percent",
    "memory_percent",
    "memory_available_mib",
    "swap_percent",
    "disk_percent",
    "disk_free_gib",
    "load_1m",
    "load_5m",
    "load_15m",
    "network_rx_mib_s",
    "network_tx_mib_s",
]


def counter_rate(current, previous, elapsed):
    """Return MiB/s; clamp negative deltas after counter resets."""
    if elapsed <= 0:
        raise ValueError("Elapsed time must be positive.")

    return max(0, current - previous) / elapsed / (1024 ** 2)


class AlertTracker:
    """Emit one alert on threshold entry and one recovery on exit."""

    def __init__(self, thresholds):
        self.thresholds = thresholds
        self.active = set()

    def update(self, metrics):
        events = []

        for metric, threshold in self.thresholds.items():
            value = metrics[metric]
            exceeded = value >= threshold

            if exceeded and metric not in self.active:
                self.active.add(metric)
                events.append((
                    "WARNING",
                    f"ALERT {metric}={value:.2f}; "
                    f"threshold={threshold:.2f}",
                ))

            elif not exceeded and metric in self.active:
                self.active.remove(metric)
                events.append((
                    "INFO",
                    f"RECOVERY {metric}={value:.2f}; "
                    f"threshold={threshold:.2f}",
                ))

        return events


def build_logger(output_folder):
    logger = logging.getLogger("server_monitor")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)sZ | %(levelname)s | %(message)s"
    )
    formatter.converter = time.gmtime

    file_handler = logging.FileHandler(
        output_folder / "alerts.log",
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()

    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def collect_metrics(interval, disk_path, previous_net, previous_time,
                    start_time):
    # Blocking CPU measurement covers the requested interval.
    cpu = psutil.cpu_percent(interval=interval)

    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(disk_path)
    load = psutil.getloadavg()

    current_net = psutil.net_io_counters(nowrap=True)
    if current_net is None:
        raise RuntimeError("Network counters are unavailable.")

    current_time = time.monotonic()
    delta_time = current_time - previous_time

    metrics = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": current_time - start_time,
        "cpu_percent": cpu,
        "memory_percent": memory.percent,
        "memory_available_mib": memory.available / (1024 ** 2),
        "swap_percent": swap.percent,
        "disk_percent": disk.percent,
        "disk_free_gib": disk.free / (1024 ** 3),
        "load_1m": load[0],
        "load_5m": load[1],
        "load_15m": load[2],
        "network_rx_mib_s": counter_rate(
            current_net.bytes_recv,
            previous_net.bytes_recv,
            delta_time,
        ),
        "network_tx_mib_s": counter_rate(
            current_net.bytes_sent,
            previous_net.bytes_sent,
            delta_time,
        ),
    }

    return metrics, current_net, current_time


def parse_args():
    root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Monitor Linux server performance."
    )
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument(
        "--duration",
        type=float,
        default=300,
        help="Collection duration in seconds; 0 runs until stopped.",
    )
    parser.add_argument("--disk-path", default="/")
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "results",
    )
    parser.add_argument("--cpu-threshold", type=float, default=85)
    parser.add_argument("--memory-threshold", type=float, default=85)
    parser.add_argument("--disk-threshold", type=float, default=90)

    args = parser.parse_args()

    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be finite and greater than zero.")

    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("--duration must be finite and nonnegative.")

    for name in (
        "cpu_threshold",
        "memory_threshold",
        "disk_threshold",
    ):
        value = getattr(args, name)
        if not math.isfinite(value) or not 0 <= value <= 100:
            parser.error(f"--{name.replace('_', '-')} must be 0–100.")

    if not Path(args.disk_path).exists():
        parser.error("--disk-path must exist.")

    return args


def main():
    args = parse_args()

    if not sys.platform.startswith("linux"):
        raise SystemExit("This project targets Linux systems.")

    # Validate access before creating the results directory.
    psutil.disk_usage(args.disk_path)

    args.output.mkdir(parents=True, exist_ok=True)

    run_name = datetime.now(timezone.utc).strftime(
        "run_%Y%m%d_%H%M%S_%f"
    )
    output_folder = args.output / run_name
    output_folder.mkdir()

    logger = build_logger(output_folder)

    thresholds = {
        "cpu_percent": args.cpu_threshold,
        "memory_percent": args.memory_threshold,
        "disk_percent": args.disk_threshold,
    }
    tracker = AlertTracker(thresholds)

    configuration = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "psutil_version": psutil.__version__,
        "logical_cpus": psutil.cpu_count(),
        "interval_seconds": args.interval,
        "duration_seconds": args.duration,
        "disk_path": str(Path(args.disk_path).resolve()),
        "thresholds": thresholds,
        "network_scope": "Aggregate counters across interfaces",
    }

    (output_folder / "configuration.json").write_text(
        json.dumps(configuration, indent=2),
        encoding="utf-8",
    )

    stopped = False

    def request_stop(signum, frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    sample_count = 0
    alert_count = 0
    start_time = time.monotonic()
    previous_time = start_time
    previous_net = psutil.net_io_counters(nowrap=True)

    if previous_net is None:
        raise RuntimeError("Network counters are unavailable.")

    logger.info("Monitoring started. Results: %s", output_folder)

    try:
        with (output_folder / "metrics.csv").open(
            "w", newline="", encoding="utf-8"
        ) as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
            writer.writeheader()
            csv_file.flush()

            while not stopped:
                elapsed = time.monotonic() - start_time

                if args.duration > 0:
                    remaining = args.duration - elapsed
                    if remaining <= 0:
                        break
                    interval = min(args.interval, remaining)
                else:
                    interval = args.interval

                metrics, previous_net, previous_time = collect_metrics(
                    interval,
                    args.disk_path,
                    previous_net,
                    previous_time,
                    start_time,
                )

                writer.writerow(metrics)
                csv_file.flush()
                sample_count += 1

                for level, message in tracker.update(metrics):
                    logger.log(getattr(logging, level), message)
                    if level == "WARNING":
                        alert_count += 1

                print(
                    f"CPU {metrics['cpu_percent']:5.1f}% | "
                    f"RAM {metrics['memory_percent']:5.1f}% | "
                    f"Disk {metrics['disk_percent']:5.1f}% | "
                    f"RX {metrics['network_rx_mib_s']:.3f} MiB/s | "
                    f"TX {metrics['network_tx_mib_s']:.3f} MiB/s",
                    flush=True,
                )

    finally:
        logger.info(
            "Monitoring stopped. Samples=%d, alerts=%d",
            sample_count,
            alert_count,
        )
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    print(f"\nGenerate a report with:\n"
          f'python src/report.py "{output_folder}"')


if __name__ == "__main__":
    main()
