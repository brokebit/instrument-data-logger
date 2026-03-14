"""
InfluxDB 1.x writer implementation.

Buffers data points and writes them to an InfluxDB 1.x instance using the
influxdb-python client library (pip install influxdb).

Authentication is not required. The client is configured with empty
credentials and SSL verification is disabled to match a typical local
self-hosted deployment.

The measurement name written to InfluxDB is "frequency_counter".

Tags written with every point:
    run_name          Name of the sample run

Fields written with every point:
    frequency_hz      Measured frequency in Hz
    gate_time_ms      Gate time in milliseconds
    sample_number     Incrementing sample index within the run
"""

import time
import urllib3
from influxdb import InfluxDBClient
from writers.base import DataWriter

_MEASUREMENT = "frequency_counter"


class InfluxWriter(DataWriter):

    def __init__(self, host, port, database, batch_size=500, flush_interval_seconds=1.0):
        self._host                   = host
        self._port                   = port
        self._database               = database
        self._batch_size             = batch_size
        self._flush_interval_seconds = flush_interval_seconds
        self._client                 = None
        self._pending_points         = []
        self._last_flush_time        = 0.0
        self._last_point_time_ns     = 0

    def open(self):
        # Suppress the InsecureRequestWarning that urllib3 emits when
        # verify_ssl=False. Scoped to just this warning class so other
        # urllib3 warnings remain visible.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # username and password are set to empty strings because
        # authentication is disabled on this instance.
        self._client = InfluxDBClient(
            host=self._host,
            port=self._port,
            username="",
            password="",
            database=self._database,
            ssl=True,
            verify_ssl=False
        )

        # Verify the target database exists before collection starts.
        # get_list_database() returns a list of dicts, e.g. [{"name": "samples_db"}, ...]
        existing_databases = self._client.get_list_database()
        existing_names     = [entry["name"] for entry in existing_databases]

        if self._database not in existing_names:
            self._client.close()
            self._client = None
            raise RuntimeError(
                "InfluxDB database \"" + self._database + "\" does not exist on "
                + self._host + ":" + str(self._port) + ". "
                "Create it first with: CREATE DATABASE " + self._database
            )

        self._last_flush_time = time.monotonic()

    def write(self, reading, sample_number, run_name, gate_time_seconds):
        gate_time_ms = gate_time_seconds * 1000.0
        point_time_ns = time.time_ns()
        if point_time_ns <= self._last_point_time_ns:
            point_time_ns = self._last_point_time_ns + 1
        self._last_point_time_ns = point_time_ns

        point = {
            "measurement": _MEASUREMENT,
            "time": point_time_ns,
            "tags": {
                "run_name": run_name
            },
            "fields": {
                "frequency_hz":  float(reading.frequency),
                "gate_time_ms":  gate_time_ms,
                "sample_number": sample_number
            }
        }

        self._pending_points.append(point)

        if len(self._pending_points) >= self._batch_size:
            self._flush_pending()
            return

        current_time = time.monotonic()
        if current_time - self._last_flush_time >= self._flush_interval_seconds:
            self._flush_pending(current_time)

    def flush(self):
        if not self._pending_points:
            return

        current_time = time.monotonic()
        if current_time - self._last_flush_time >= self._flush_interval_seconds:
            self._flush_pending(current_time)

    def _flush_pending(self, flush_time=None):
        if not self._pending_points:
            return

        self._client.write_points(self._pending_points, time_precision="n")
        self._pending_points = []
        if flush_time is None:
            flush_time = time.monotonic()
        self._last_flush_time = flush_time

    def close(self):
        self._flush_pending()
        if self._client is not None:
            self._client.close()
