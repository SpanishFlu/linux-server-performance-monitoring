# Linux Server Performance Monitoring

A Python-based Linux monitoring tool that records server metrics,
detects threshold violations, and generates performance reports.

## Features

- CPU, RAM, and swap utilization
- Disk-space monitoring for a selected filesystem
- Aggregate network receive/transmit rates
- System load averages
- Threshold alerts and recovery notifications
- CSV metrics and JSON configuration
- Separate results folder for each execution
- PNG charts and JSON summary statistics
- Unit tests for rate and alert logic

## Requirements

- Linux
- Python 3.10+
- Dependencies listed in requirements.txt

Tested environment: Not yet recorded.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```bash
python src/monitor.py --interval 5 --duration 300
```

A duration of 0 runs until stopped.

Results are saved under:

```text
results/run_<UTC timestamp>/
```

## Generate a Report

Use the run-folder path printed by the monitor:

```bash
python src/report.py results/run_YOUR_RUN_FOLDER
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Output Files

| File | Contents |
|---|---|
| configuration.json | Environment and monitoring settings |
| metrics.csv | Timestamped metric samples |
| alerts.log | Start/stop messages, alerts, and recoveries |
| summary.json | Sample minimum, mean, and maximum |
| performance.png | Performance charts |

The report files are created by report.py, not monitor.py.

## Default Alert Thresholds

- CPU: 85%
- RAM: 85%
- Disk space: 90%

An alert is generated when a metric meets or exceeds its threshold.
A recovery is generated when it drops below the threshold.

These are configurable demonstration settings.

## Limitations

- Monitors one server only
- Disk percentage describes capacity, not disk I/O performance
- Network counters aggregate interfaces and may include loopback
  and virtual-interface traffic
- Load averages are not percentages
- Sampling can miss brief resource spikes
- CPU and other metrics are not collected atomically
- Alerts have no persistence window or hysteresis
- No email, webhook, or remote dashboard
- No automatic retention or log rotation
- Containers may expose a mixture of host and namespace metrics
- Report means are unweighted sample means
- Monitor activity itself introduces overhead

## Security and Operations

Run as a normal user where permissions allow.

Do not publish raw results without reviewing hostname and
environment information.

For extended monitoring, configure external retention and
supervision rather than allowing results to grow indefinitely.

## Results Status

No measured results are claimed until the code has been executed.

Record the Linux distribution, Python version, package versions,
sampling interval, workload, and Git revision when publishing results.
