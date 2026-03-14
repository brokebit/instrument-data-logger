import argparse
from dataclasses import dataclass
from typing import Optional

from instruments.keysight_53230a import MAX_SAMPLE_COUNT
from instruments.registry import KEYSIGHT_53230A_NAME, SUPPORTED_INSTRUMENTS

DEFAULT_INFLUX_BATCH_SIZE = 500
DEFAULT_INFLUX_FLUSH_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class RunConfig:
    instrument_name: str
    resource_address: str
    run_name: str
    gate_time_seconds: float
    polling_interval_seconds: float
    num_samples: Optional[int]
    output_csv: Optional[str]
    output_influx: Optional[str]
    influx_batch_size: int
    influx_flush_interval_seconds: float
    queue_size: int


def parse_run_config():
    args = _parse_args()
    _validate_args(args)

    polling_interval_seconds = args.gate_time
    if args.polling_interval is not None:
        polling_interval_seconds = args.polling_interval

    return RunConfig(
        instrument_name=args.instrument,
        resource_address=args.resource,
        run_name=args.run_name,
        gate_time_seconds=args.gate_time,
        polling_interval_seconds=polling_interval_seconds,
        num_samples=args.num_samples,
        output_csv=args.output_csv,
        output_influx=args.output_influx,
        influx_batch_size=args.influx_batch_size,
        influx_flush_interval_seconds=args.influx_flush_interval,
        queue_size=args.queue_size,
    )


def _parse_args():
    parser = argparse.ArgumentParser(description="Frequency counter polling script.")

    parser.add_argument(
        "--instrument",
        type=str,
        default="dg912-pro",
        choices=sorted(SUPPORTED_INSTRUMENTS.keys()),
        help="Instrument type to use (default: dg912-pro)."
    )
    parser.add_argument(
        "--resource",
        type=str,
        required=True,
        help="VISA resource address of the instrument."
    )
    parser.add_argument(
        "--run-name",
        type=str,
        required=True,
        help="Name for this sample run."
    )
    parser.add_argument(
        "--gate-time",
        type=float,
        default=0.001,
        help="Gate time in seconds (default: 0.001)."
    )
    parser.add_argument(
        "--polling-interval",
        type=float,
        default=None,
        help="Polling interval in seconds (default: same as gate time)."
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=None,
        help=(
            "Number of samples to collect. Omit to run indefinitely, "
            + "except for keysight-53230a."
        )
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        help="Path to a CSV file to write results to."
    )
    parser.add_argument(
        "--output-influx",
        type=str,
        default=None,
        help="InfluxDB target as host:port:database (e.g. influx_host:8086:samples_db)."
    )
    parser.add_argument(
        "--influx-batch-size",
        type=int,
        default=DEFAULT_INFLUX_BATCH_SIZE,
        help=(
            "Number of points to buffer before writing to InfluxDB "
            + "(default: " + str(DEFAULT_INFLUX_BATCH_SIZE) + ")."
        )
    )
    parser.add_argument(
        "--influx-flush-interval",
        type=float,
        default=DEFAULT_INFLUX_FLUSH_INTERVAL_SECONDS,
        help=(
            "Maximum seconds to hold buffered InfluxDB points before flushing "
            + "(default: " + str(DEFAULT_INFLUX_FLUSH_INTERVAL_SECONDS) + ")."
        )
    )
    parser.add_argument(
        "--queue-size",
        type=int,
        default=10000,
        help="Max in-memory samples to buffer between reader and writer threads (default: 10000)."
    )

    return parser.parse_args()


def _validate_args(args):
    if args.influx_batch_size <= 0:
        raise RuntimeError("--influx-batch-size must be greater than 0.")

    if args.influx_flush_interval <= 0:
        raise RuntimeError("--influx-flush-interval must be greater than 0.")

    if args.instrument != KEYSIGHT_53230A_NAME:
        return

    if args.num_samples is None:
        raise RuntimeError("The keysight-53230a instrument requires --num-samples.")

    if args.num_samples > MAX_SAMPLE_COUNT:
        raise RuntimeError(
            "The keysight-53230a instrument does not support --num-samples "
            + "greater than " + str(MAX_SAMPLE_COUNT) + "."
        )
