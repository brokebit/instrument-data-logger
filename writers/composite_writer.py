"""
Composite writer.

Holds a list of DataWriter instances and fans every write() and close()
call out to all of them. This allows main.py to remain unaware of how
many backends are active.

Usage:
    writer = CompositeWriter([CSVWriter("out.csv"), SQLiteWriter("out.db")])
    writer.write(reading, sample_number, run_name, gate_time_seconds)
    writer.close()
"""

from writers.base import DataWriter


class CompositeWriter(DataWriter):

    def __init__(self, writers):
        self._writers = writers

    def write(self, reading, sample_number, run_name, gate_time_seconds):
        for writer in self._writers:
            writer.write(reading, sample_number, run_name, gate_time_seconds)

    def flush(self):
        for writer in self._writers:
            writer.flush()

    def close(self):
        for writer in self._writers:
            writer.close()
