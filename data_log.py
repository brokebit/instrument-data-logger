"""
Frequency counter polling script.

Select the active instrument with --instrument.

Requirements:
    pip install pyvisa pyvisa-py

For USB connections you may also need:
    pip install pyusb

Usage:
    python data_log.py --resource <VISA address> --run-name <name> [options]

    --instrument    Instrument type (default: dg912-pro)
    --resource      VISA resource address of the instrument (required)
    --run-name      Name for this sample run (required)
    --gate-time     Gate time in seconds (default: 0.001)
    --polling-interval
                    Polling interval in seconds (default: same as gate time)
    --num-samples   Number of samples to collect. Omit to run indefinitely.
    --output-csv    Path to a CSV file to write results to (optional)
    --output-influx InfluxDB target as host:port:database (optional)

Example:
    python data_log.py --instrument keysight-53230a \
                       --resource "TCPIP0::192.168.100.217::inst0::INSTR" \
                       --run-name "bench_test_01" \
                       --gate-time 0.1 \
                       --polling-interval 0.25 \
                       --num-samples 50 \
                       --output-csv results.csv \
                       --output-influx influx_host:8086:samples_db
"""

import argparse
import queue
import threading
import time
from instruments.cnt90 import CNT90
from instruments.dg912_pro import DG912Pro
from instruments.keysight_53230a import Keysight53230A
from writers.csv_writer import CSVWriter
from writers.composite_writer import CompositeWriter
from writers.influx_writer import InfluxWriter


SUPPORTED_INSTRUMENTS = {
    "cnt90": CNT90,
    "dg912-pro": DG912Pro,
    "keysight-53230a": Keysight53230A,
}

KEYSIGHT_53230A_MAX_SAMPLES = 1000000


def display_status(sample_number, num_samples, queue_depth, queue_capacity):
    if num_samples is None:
        sample_status = str(sample_number)
    else:
        sample_percent = (sample_number / num_samples) * 100.0
        sample_status = (
            str(sample_number)
            + "/" + str(num_samples)
            + " (" + f"{sample_percent:.1f}" + "%)"
        )

    queue_percent = (queue_depth / queue_capacity) * 100.0

    print(
        "\rSample: " + sample_status
        + " | Queue: " + str(queue_depth) + "/" + str(queue_capacity)
        + " (" + f"{queue_percent:.1f}" + "%)",
        end="",
        flush=True
    )


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


def build_instrument(instrument_name):
    instrument_class = SUPPORTED_INSTRUMENTS[instrument_name]
    return instrument_class()


def validate_args(args):
    if args.instrument != "keysight-53230a":
        return

    if args.num_samples is None:
        raise RuntimeError("The keysight-53230a instrument requires --num-samples.")

    if args.num_samples > KEYSIGHT_53230A_MAX_SAMPLES:
        raise RuntimeError(
            "The keysight-53230a instrument does not support --num-samples "
            + "greater than " + str(KEYSIGHT_53230A_MAX_SAMPLES) + "."
        )


def read_instrument_loop(
    instrument,
    readings_queue,
    polling_interval_seconds,
    num_samples,
    stop_event,
    reader_done_event,
    num_samples_reached_event,
    error_queue
):
    sample_number = 1
    next_poll_time = time.monotonic()
    exit_reason = "stop requested"

    try:
        while not stop_event.is_set():
            if num_samples is not None and sample_number > num_samples:
                num_samples_reached_event.set()
                exit_reason = "target sample count reached"
                break

            wait_seconds = next_poll_time - time.monotonic()
            if wait_seconds > 0 and stop_event.wait(wait_seconds):
                break

            readings = instrument.read()

            for reading in readings:
                if stop_event.is_set():
                    break

                if num_samples is not None and sample_number > num_samples:
                    num_samples_reached_event.set()
                    exit_reason = "target sample count reached"
                    break

                # Backpressure policy: block when queue is full so we do not
                # silently drop samples.
                enqueued = False
                while not stop_event.is_set():
                    try:
                        readings_queue.put((reading, sample_number), timeout=0.1)
                        enqueued = True
                        break
                    except queue.Full:
                        continue

                if not enqueued:
                    exit_reason = "stop requested"
                    break

                sample_number = sample_number + 1

            next_poll_time = next_poll_time + polling_interval_seconds
            if next_poll_time < time.monotonic():
                next_poll_time = time.monotonic()

    except Exception as error:
        error_queue.put(("reader", error))
        stop_event.set()
        exit_reason = "error"

    finally:
        reader_done_event.set()
        print(
            "\nInstrument read loop finished. "
            + "Samples queued: " + str(sample_number - 1)
            + ". Reason: " + exit_reason + "."
        )


def write_loop(
    writer,
    readings_queue,
    run_name,
    gate_time_seconds,
    num_samples,
    stop_event,
    reader_done_event,
    error_queue
):
    next_status_time = time.monotonic() + 1.0
    last_sample_number = 0
    status_line_active = False

    try:
        while True:
            if reader_done_event.is_set() and readings_queue.empty():
                break

            try:
                reading, sample_number = readings_queue.get(timeout=0.1)
            except queue.Empty:
                current_time = time.monotonic()
                if last_sample_number > 0 and current_time >= next_status_time:
                    display_status(
                        last_sample_number,
                        num_samples,
                        readings_queue.qsize(),
                        readings_queue.maxsize
                    )
                    status_line_active = True
                    next_status_time = current_time + 1.0
                continue

            try:
                writer.write(reading, sample_number, run_name, gate_time_seconds)
                last_sample_number = sample_number

                current_time = time.monotonic()
                if current_time >= next_status_time:
                    display_status(
                        sample_number,
                        num_samples,
                        readings_queue.qsize(),
                        readings_queue.maxsize
                    )
                    status_line_active = True
                    next_status_time = current_time + 1.0
            finally:
                readings_queue.task_done()

    except Exception as error:
        error_queue.put(("writer", error))
        stop_event.set()

    finally:
        if status_line_active:
            print("")


def parse_args():
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
        "--queue-size",
        type=int,
        default=10000,
        help="Max in-memory samples to buffer between reader and writer threads (default: 10000)."
    )

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        validate_args(args)
    except RuntimeError as error:
        print("Error: " + str(error))
        return

    instrument_name    = args.instrument
    resource_address  = args.resource
    run_name          = args.run_name
    gate_time_seconds = args.gate_time
    if args.polling_interval is None:
        polling_interval_seconds = gate_time_seconds
    else:
        polling_interval_seconds = args.polling_interval
    num_samples       = args.num_samples
    queue_size        = args.queue_size

    instrument = build_instrument(instrument_name)

    try:
        writer = build_writer(args)
    except RuntimeError as error:
        print("Error: " + str(error))
        return

    print("Connecting to  : " + resource_address)
    try:
        instrument.init(resource_address, gate_time_seconds, num_samples)
    except Exception as error:
        writer.close()
        print("Error: " + str(error))
        return
    print("Instrument     : " + instrument_name)
    print("Run name       : " + run_name)
    print("Gate time      : " + str(gate_time_seconds * 1000) + " ms")
    print("Polling interval: " + str(polling_interval_seconds * 1000) + " ms")
    if num_samples is not None:
        print("Collecting     : " + str(num_samples) + " samples")
    else:
        print("Collecting     : indefinitely (Ctrl+C to stop)")
    if args.output_csv is not None:
        print("CSV output     : " + args.output_csv)
    if args.output_influx is not None:
        print("InfluxDB output: " + args.output_influx)
    print("Queue size     : " + str(queue_size))
    print()

    readings_queue = queue.Queue(maxsize=queue_size)
    stop_event = threading.Event()
    reader_done_event = threading.Event()
    num_samples_reached_event = threading.Event()
    error_queue = queue.Queue()

    reader_thread = threading.Thread(
        target=read_instrument_loop,
        args=(
            instrument,
            readings_queue,
            polling_interval_seconds,
            num_samples,
            stop_event,
            reader_done_event,
            num_samples_reached_event,
            error_queue,
        ),
        name="instrument-reader"
    )

    writer_thread = threading.Thread(
        target=write_loop,
        args=(
            writer,
            readings_queue,
            run_name,
            gate_time_seconds,
            num_samples,
            stop_event,
            reader_done_event,
            error_queue,
        ),
        name="data-writer"
    )

    reader_thread.start()
    writer_thread.start()

    try:
        while reader_thread.is_alive() or writer_thread.is_alive():
            reader_thread.join(timeout=0.2)
            writer_thread.join(timeout=0.2)

            if not error_queue.empty():
                break

    except KeyboardInterrupt:
        print("")
        print("Polling stopped by user.")
        stop_event.set()

    finally:
        stop_event.set()
        reader_thread.join()
        writer_thread.join()

        if not error_queue.empty():
            component, error = error_queue.get()
            print("Error in " + component + " thread: " + str(error))

        if num_samples_reached_event.is_set():
            print("Collected " + str(num_samples) + " samples. Done.")

        instrument.close()
        writer.close()
        print("Connection closed.")


if __name__ == "__main__":
    main()
