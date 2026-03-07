"""
Frequency counter polling script.

To use a different instrument, change the import and instantiation below.
Everything else stays the same.

Requirements:
    pip install pyvisa pyvisa-py

For USB connections you may also need:
    pip install pyusb

Usage:
    python main.py --resource <VISA address> --run-name <name> [options]

    --resource      VISA resource address of the instrument (required)
    --run-name      Name for this sample run (required)
    --gate-time     Gate time in seconds (default: 0.001)
    --num-samples   Number of samples to collect. Omit to run indefinitely.
    --output-csv    Path to a CSV file to write results to (optional)
    --output-influx InfluxDB target as host:port:database (optional)

Example:
    python main.py --resource "USB0::0x1AB1::0x0641::DG9A1234::INSTR" \
                   --run-name "bench_test_01" \
                   --gate-time 0.1 \
                   --num-samples 50 \
                   --output-csv results.csv \
                   --output-influx influx_host:8086:samples_db
"""

import argparse
import time
from instruments.dg912_pro import DG912Pro
from writers.csv_writer import CSVWriter
from writers.composite_writer import CompositeWriter
from writers.influx_writer import InfluxWriter


def format_frequency(hz):
    if hz >= 1000000.0:
        scaled = hz / 1000000.0
        return str(round(scaled, 6)) + " MHz"
    elif hz >= 1000.0:
        scaled = hz / 1000.0
        return str(round(scaled, 6)) + " kHz"
    else:
        return str(round(hz, 6)) + " Hz"


def display_reading(reading, sample_number, run_name, gate_time_seconds):
    print("Sample     : " + str(sample_number))
    print("Run        : " + run_name)
    print("Gate Time  : " + str(gate_time_seconds * 1000) + " ms")
    print("Frequency  : " + format_frequency(reading.frequency))
    print()


def build_writer(args):
    writers = []

    if args.output_csv is not None:
        csv_writer = CSVWriter(args.output_csv)
        csv_writer.open()
        writers.append(csv_writer)

    if args.output_influx is not None:
        # Expected format: host:port:database
        # Example: influx_host:8086:samples_db
        parts    = args.output_influx.split(":")
        host     = parts[0]
        port     = int(parts[1])
        database = parts[2]

        influx_writer = InfluxWriter(host, port, database)
        influx_writer.open()
        writers.append(influx_writer)

    return CompositeWriter(writers)


def parse_args():
    parser = argparse.ArgumentParser(description="Frequency counter polling script.")

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
        "--num-samples",
        type=int,
        default=None,
        help="Number of samples to collect. Omit to run indefinitely."
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

    return parser.parse_args()


def main():
    args = parse_args()

    resource_address  = args.resource
    run_name          = args.run_name
    gate_time_seconds = args.gate_time
    num_samples       = args.num_samples

    instrument = DG912Pro()

    try:
        writer = build_writer(args)
    except RuntimeError as error:
        print("Error: " + str(error))
        return

    print("Connecting to  : " + resource_address)
    instrument.init(resource_address, gate_time_seconds)
    print("Run name       : " + run_name)
    print("Gate time      : " + str(gate_time_seconds * 1000) + " ms")
    if num_samples is not None:
        print("Collecting     : " + str(num_samples) + " samples")
    else:
        print("Collecting     : indefinitely (Ctrl+C to stop)")
    if args.output_csv is not None:
        print("CSV output     : " + args.output_csv)
    if args.output_influx is not None:
        print("InfluxDB output: " + args.output_influx)
    print()

    sample_number = 1

    try:
        while True:
            readings = instrument.read()

            for reading in readings:
                display_reading(reading, sample_number, run_name, gate_time_seconds)
                writer.write(reading, sample_number, run_name, gate_time_seconds)
                sample_number = sample_number + 1

                if num_samples is not None and sample_number > num_samples:
                    print("Collected " + str(num_samples) + " samples. Done.")
                    return

            time.sleep(gate_time_seconds)

    except KeyboardInterrupt:
        print("")
        print("Polling stopped by user.")

    finally:
        instrument.close()
        writer.close()
        print("Connection closed.")


if __name__ == "__main__":
    main()