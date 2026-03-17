import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from instruments.keysight_53230a import MAX_SAMPLE_COUNT
from instruments.registry import KEYSIGHT_53230A_NAME, SUPPORTED_INSTRUMENTS

DEFAULT_UI_MODE = "plain"
DEFAULT_INSTRUMENT_NAME = "dg912-pro"
DEFAULT_GATE_TIME_SECONDS = 0.001
DEFAULT_INFLUX_BATCH_SIZE = 500
DEFAULT_INFLUX_FLUSH_INTERVAL_SECONDS = 1.0
DEFAULT_QUEUE_SIZE = 10000
SUPPORTED_UI_MODES = ("plain", "textual")
CONFIG_HELP_TEXT = (
    "Path to a YAML config file. When provided, no other run arguments may be used."
)

DEFAULT_ARGUMENT_VALUES = {
    "ui": DEFAULT_UI_MODE,
    "instrument": DEFAULT_INSTRUMENT_NAME,
    "resource": None,
    "run_name": None,
    "gate_time": DEFAULT_GATE_TIME_SECONDS,
    "polling_interval": None,
    "num_samples": None,
    "output_csv": None,
    "event_log": None,
    "output_influx": None,
    "influx_batch_size": DEFAULT_INFLUX_BATCH_SIZE,
    "influx_flush_interval": DEFAULT_INFLUX_FLUSH_INTERVAL_SECONDS,
    "queue_size": DEFAULT_QUEUE_SIZE,
}


@dataclass(frozen=True)
class RunConfig:
    ui_mode: str
    instrument_name: str
    resource_address: str
    run_name: str
    gate_time_seconds: float
    polling_interval_seconds: float
    num_samples: Optional[int]
    output_csv: Optional[str]
    event_log: Optional[str]
    output_influx: Optional[str]
    influx_batch_size: int
    influx_flush_interval_seconds: float
    queue_size: int


def parse_run_config(argv=None):
    config_path, remaining_args = _parse_bootstrap_args(argv)

    if config_path is not None:
        if remaining_args:
            raise RuntimeError(
                "--config cannot be combined with other CLI arguments: "
                + " ".join(remaining_args)
            )
        args = _build_config_args(config_path)
    else:
        args = _parse_args(argv)

    _validate_args(args)
    return _build_run_config(args)


def _parse_bootstrap_args(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=str, default=None)
    args, remaining_args = parser.parse_known_args(argv)
    return args.config, remaining_args


def _parse_args(argv=None):
    return _build_parser().parse_args(argv)


def _build_parser():
    parser = argparse.ArgumentParser(description="Frequency counter polling script.")

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=CONFIG_HELP_TEXT
    )
    parser.add_argument(
        "--ui",
        type=str,
        default=DEFAULT_UI_MODE,
        choices=SUPPORTED_UI_MODES,
        help="User interface mode to use (default: plain)."
    )
    parser.add_argument(
        "--instrument",
        type=str,
        default=DEFAULT_INSTRUMENT_NAME,
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
        default=DEFAULT_GATE_TIME_SECONDS,
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
        "--event-log",
        type=str,
        default=None,
        help="Path to a log file that mirrors the Textual event stream."
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
        default=DEFAULT_QUEUE_SIZE,
        help=(
            "Max in-memory samples to buffer between reader and writer threads "
            + "(default: " + str(DEFAULT_QUEUE_SIZE) + ")."
        )
    )

    return parser


def _build_config_args(config_path):
    values = DEFAULT_ARGUMENT_VALUES.copy()
    values.update(_load_config_values(config_path))
    return argparse.Namespace(**values)


def _load_config_values(config_path):
    config_file = Path(config_path).expanduser().resolve()
    yaml = _import_yaml_module()

    try:
        with config_file.open("r", encoding="utf-8") as handle:
            loaded_values = yaml.safe_load(handle)
    except FileNotFoundError as error:
        raise RuntimeError("Config file not found: " + str(config_file) + ".") from error
    except OSError as error:
        raise RuntimeError("Unable to read config file: " + str(config_file) + ".") from error
    except Exception as error:
        raise RuntimeError(
            "Unable to parse config file " + str(config_file) + ": " + str(error)
        ) from error

    if loaded_values is None:
        loaded_values = {}

    if not isinstance(loaded_values, dict):
        raise RuntimeError("Config file must contain a top-level mapping.")

    normalized_values = {}
    normalized_sources = {}

    for raw_key, raw_value in loaded_values.items():
        if not isinstance(raw_key, str):
            raise RuntimeError("Config file keys must be strings.")

        normalized_key = raw_key.replace("-", "_")
        if normalized_key not in DEFAULT_ARGUMENT_VALUES:
            raise RuntimeError("Unknown config key: " + raw_key + ".")

        if normalized_key in normalized_values:
            raise RuntimeError(
                "Duplicate config key after normalization: "
                + raw_key
                + " conflicts with "
                + normalized_sources[normalized_key]
                + "."
            )

        normalized_sources[normalized_key] = raw_key
        normalized_values[normalized_key] = _coerce_config_value(
            normalized_key,
            raw_value
        )

    if normalized_values.get("output_csv") is not None:
        normalized_values["output_csv"] = _resolve_config_relative_path(
            config_file.parent,
            normalized_values["output_csv"]
        )

    if normalized_values.get("event_log") is not None:
        normalized_values["event_log"] = _resolve_config_relative_path(
            config_file.parent,
            normalized_values["event_log"]
        )

    return normalized_values


def _import_yaml_module():
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError(
            "YAML config files require the 'PyYAML' package. "
            + "Install the updated requirements first."
        ) from error

    return yaml


def _resolve_config_relative_path(base_directory, path_value):
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = base_directory / path
    return str(path)


def _coerce_config_value(key, value):
    if key in {"ui", "instrument", "resource", "run_name"}:
        return _coerce_string_value(key, value, allow_none=False)

    if key in {"output_csv", "event_log", "output_influx"}:
        return _coerce_string_value(key, value, allow_none=True)

    if key in {"gate_time", "influx_flush_interval"}:
        return _coerce_float_value(key, value, allow_none=False)

    if key == "polling_interval":
        return _coerce_float_value(key, value, allow_none=True)

    if key in {"influx_batch_size", "queue_size"}:
        return _coerce_int_value(key, value, allow_none=False)

    if key == "num_samples":
        return _coerce_int_value(key, value, allow_none=True)

    raise RuntimeError("Unsupported config key: " + key + ".")


def _coerce_string_value(key, value, allow_none):
    if value is None:
        if allow_none:
            return None
        raise RuntimeError("Config value for '" + key + "' cannot be null.")

    if not isinstance(value, str):
        raise RuntimeError("Config value for '" + key + "' must be a string.")

    return value


def _coerce_float_value(key, value, allow_none):
    if value is None:
        if allow_none:
            return None
        raise RuntimeError("Config value for '" + key + "' cannot be null.")

    if isinstance(value, bool):
        raise RuntimeError("Config value for '" + key + "' must be a number.")

    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError("Config value for '" + key + "' must be a number.") from error


def _coerce_int_value(key, value, allow_none):
    if value is None:
        if allow_none:
            return None
        raise RuntimeError("Config value for '" + key + "' cannot be null.")

    if isinstance(value, bool):
        raise RuntimeError("Config value for '" + key + "' must be an integer.")

    if isinstance(value, float):
        if not value.is_integer():
            raise RuntimeError("Config value for '" + key + "' must be an integer.")
        return int(value)

    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError("Config value for '" + key + "' must be an integer.") from error


def _build_run_config(args):
    polling_interval_seconds = args.gate_time
    if args.polling_interval is not None:
        polling_interval_seconds = args.polling_interval

    return RunConfig(
        ui_mode=args.ui,
        instrument_name=args.instrument,
        resource_address=args.resource,
        run_name=args.run_name,
        gate_time_seconds=args.gate_time,
        polling_interval_seconds=polling_interval_seconds,
        num_samples=args.num_samples,
        output_csv=args.output_csv,
        event_log=args.event_log,
        output_influx=args.output_influx,
        influx_batch_size=args.influx_batch_size,
        influx_flush_interval_seconds=args.influx_flush_interval,
        queue_size=args.queue_size,
    )


def _validate_args(args):
    if args.ui not in SUPPORTED_UI_MODES:
        raise RuntimeError(
            "Unsupported --ui value: "
            + str(args.ui)
            + ". Expected one of: "
            + ", ".join(SUPPORTED_UI_MODES)
            + "."
        )

    if args.instrument not in SUPPORTED_INSTRUMENTS:
        raise RuntimeError(
            "Unsupported --instrument value: "
            + str(args.instrument)
            + ". Expected one of: "
            + ", ".join(sorted(SUPPORTED_INSTRUMENTS.keys()))
            + "."
        )

    if _is_missing_text(args.resource):
        raise RuntimeError("Missing required value for --resource.")

    if _is_missing_text(args.run_name):
        raise RuntimeError("Missing required value for --run-name.")

    if args.event_log is not None and _is_missing_text(args.event_log):
        raise RuntimeError("--event-log must not be empty.")

    if args.gate_time <= 0:
        raise RuntimeError("--gate-time must be greater than 0.")

    if args.polling_interval is not None and args.polling_interval <= 0:
        raise RuntimeError("--polling-interval must be greater than 0.")

    if args.num_samples is not None and args.num_samples <= 0:
        raise RuntimeError("--num-samples must be greater than 0.")

    if args.influx_batch_size <= 0:
        raise RuntimeError("--influx-batch-size must be greater than 0.")

    if args.influx_flush_interval <= 0:
        raise RuntimeError("--influx-flush-interval must be greater than 0.")

    if args.queue_size <= 0:
        raise RuntimeError("--queue-size must be greater than 0.")

    if args.instrument != KEYSIGHT_53230A_NAME:
        return

    if args.num_samples is None:
        raise RuntimeError("The keysight-53230a instrument requires --num-samples.")

    if args.num_samples > MAX_SAMPLE_COUNT:
        raise RuntimeError(
            "The keysight-53230a instrument does not support --num-samples "
            + "greater than " + str(MAX_SAMPLE_COUNT) + "."
        )


def _is_missing_text(value):
    return value is None or value.strip() == ""
