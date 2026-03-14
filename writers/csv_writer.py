"""
CSV writer implementation.

Writes one row per reading to a CSV file. The file is created if it does
not exist. If it already exists, new rows are appended so that multiple
runs can share a single file and be distinguished by their run_name.

Columns:
    timestamp         ISO 8601 UTC timestamp of when the reading was taken
    sample_number     Incrementing sample index within the run
    run_name          Name of the sample run
    gate_time_ms      Gate time in milliseconds
    frequency_hz      Measured frequency in Hz
"""

import csv
import datetime
import os
from writers.base import DataWriter


class CSVWriter(DataWriter):

    def __init__(self, file_path):
        self._file_path = file_path
        self._file = None
        self._csv_writer = None

    def open(self):
        file_exists = os.path.isfile(self._file_path)

        # Open in append mode so existing data is preserved across runs.
        self._file = open(self._file_path, "a", newline="")
        self._csv_writer = csv.writer(self._file)

        # Only write the header row if the file is new.
        if not file_exists:
            self._csv_writer.writerow([
                "timestamp",
                "sample_number",
                "run_name",
                "gate_time_ms",
                "frequency_hz"
            ])

    def write(self, reading, sample_number, run_name, gate_time_seconds):
        timestamp     = datetime.datetime.utcnow().isoformat() + "Z"
        gate_time_ms  = gate_time_seconds * 1000.0

        self._csv_writer.writerow([
            timestamp,
            sample_number,
            run_name,
            gate_time_ms,
            reading.frequency_text
        ])

        # Flush after every row so data is not lost if the script is
        # interrupted before close() is called.
        self._file.flush()

    def close(self):
        if self._file is not None:
            self._file.close()
