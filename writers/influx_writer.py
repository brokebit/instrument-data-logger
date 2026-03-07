"""
InfluxDB 1.x writer implementation.

Writes one data point per reading to an InfluxDB 1.x instance using the
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

import urllib3
from influxdb import InfluxDBClient
from writers.base import DataWriter

_MEASUREMENT = "frequency_counter"


class InfluxWriter(DataWriter):

    def __init__(self, host, port, database):
        self._host     = host
        self._port     = port
        self._database = database
        self._client   = None

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

    def write(self, reading, sample_number, run_name, gate_time_seconds):
        gate_time_ms = gate_time_seconds * 1000.0

        point = {
            "measurement": _MEASUREMENT,
            "tags": {
                "run_name": run_name
            },
            "fields": {
                "frequency_hz":  reading.frequency,
                "gate_time_ms":  gate_time_ms,
                "sample_number": sample_number
            }
        }

        self._client.write_points([point])

    def close(self):
        if self._client is not None:
            self._client.close()