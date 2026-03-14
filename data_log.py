"""
Frequency counter polling script entry point.

Select the active instrument with --instrument.
Run `python data_log.py --help` for full CLI usage.
"""

from cli import parse_run_config
from instruments.registry import build_instrument
from pipeline import run_pipeline
from writers.factory import build_writer


def print_run_summary(config):
    print("Instrument     : " + config.instrument_name)
    print("Run name       : " + config.run_name)
    print("Gate time      : " + str(config.gate_time_seconds * 1000) + " ms")
    print("Polling interval: " + str(config.polling_interval_seconds * 1000) + " ms")
    if config.num_samples is not None:
        print("Collecting     : " + str(config.num_samples) + " samples")
    else:
        print("Collecting     : indefinitely (Ctrl+C to stop)")
    if config.output_csv is not None:
        print("CSV output     : " + config.output_csv)
    if config.output_influx is not None:
        print("InfluxDB output: " + config.output_influx)
        print(
            "Influx batching: "
            + str(config.influx_batch_size)
            + " points / "
            + str(config.influx_flush_interval_seconds)
            + " s"
        )
    print("Queue size     : " + str(config.queue_size))
    print("")


def main():
    try:
        config = parse_run_config()
    except RuntimeError as error:
        print("Error: " + str(error))
        return

    instrument = build_instrument(config.instrument_name)

    try:
        writer = build_writer(config)
    except RuntimeError as error:
        print("Error: " + str(error))
        return

    print("Connecting to  : " + config.resource_address)
    try:
        instrument.init(
            config.resource_address,
            config.gate_time_seconds,
            config.num_samples
        )
    except Exception as error:
        writer.close()
        print("Error: " + str(error))
        return

    print_run_summary(config)

    try:
        run_pipeline(config, instrument, writer)
    finally:
        instrument.close()
        writer.close()
        print("Connection closed.")


if __name__ == "__main__":
    main()
