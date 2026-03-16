"""
Instrument implementation for the Keysight 53230A frequency counter.

This implementation uses the instrument's continuous buffered frequency mode:
    - *RST resets the counter to a known state.
    - CONF:FREQ 1.0E7 configures a channel 1 frequency measurement with an
      expected input near 10 MHz.
    - FREQ:GATE:SOUR TIME and FREQ:GATE:TIME <seconds> enable fixed
      time-based gating.
    - FREQ:MODE CONT enables continuous gap-free acquisition.
    - SAMP:COUN uses the requested --num-samples value, capped at 1000000.
    - TRIG:SOUR IMM and INIT start acquisition immediately.
    - Each read() call drains the currently buffered results using R?.

Like the CNT-90, this counter may return zero, one, or many readings per poll
depending on how the polling interval relates to the configured gate time.
"""

from decimal import Decimal
import time
import pyvisa
from instruments.base import CounterInstrument, CounterReading

MAX_SAMPLE_COUNT = 1000000


class Keysight53230A(CounterInstrument):

    def __init__(self):
        self._resource_manager = None
        self._instrument = None
        self._command_delay_seconds = 0.1

    def init(self, resource_address, gate_time_seconds, num_samples=None):
        if num_samples is None:
            raise RuntimeError("Keysight 53230A requires --num-samples.")
        if num_samples > MAX_SAMPLE_COUNT:
            raise RuntimeError(
                "Keysight 53230A does not support --num-samples greater than "
                + str(MAX_SAMPLE_COUNT) + "."
            )

        self._resource_manager = pyvisa.ResourceManager()

        self._instrument = self._resource_manager.open_resource(resource_address)
        self._instrument.timeout = 5000
        self._instrument.chunk_size = 1024 * 1024

        setup_commands = [
            "*RST",
            "CONF:FREQ 1.0E7",
            "INP:IMP 50",
            "INP:LEV 0.0",
            "FREQ:GATE:SOUR TIME",
            "FREQ:GATE:TIME " + str(gate_time_seconds),
            "FREQ:MODE CONT",
            "SAMP:COUN " + str(num_samples),
            "TRIG:SOUR IMM",
            "INIT",
        ]

        for index, command in enumerate(setup_commands):
            self._instrument.write(command)

            if index < len(setup_commands) - 1:
                time.sleep(self._command_delay_seconds)

    def read(self):
        raw_response = self._instrument.query("R?")
        payload = self._extract_payload(raw_response)

        if payload == "":
            return []

        readings = []

        frequency_values = payload.replace("\r", "\n").replace("\n", ",").split(",")

        for frequency_string in frequency_values:
            frequency_string = frequency_string.strip()
            if frequency_string == "":
                continue

            reading = CounterReading(
                frequency=Decimal(frequency_string),
                frequency_text=frequency_string
            )
            readings.append(reading)

        return readings

    def _extract_payload(self, raw_response):
        response = raw_response.strip()

        if response == "":
            return ""

        # The 53230A can return array results as IEEE definite-length blocks.
        # An empty buffer appears as "#10", which means zero payload bytes.
        if not response.startswith("#"):
            return response

        if len(response) < 2 or not response[1].isdigit():
            raise RuntimeError("Unexpected block header from Keysight 53230A: " + response[:32])

        header_digits = int(response[1])

        if header_digits == 0:
            return response[2:]

        header_end = 2 + header_digits
        if len(response) < header_end:
            raise RuntimeError("Incomplete block header from Keysight 53230A: " + response[:32])

        payload_length = int(response[2:header_end])
        payload_end = header_end + payload_length
        if len(response) < payload_end:
            raise RuntimeError("Incomplete block payload from Keysight 53230A.")

        return response[header_end:payload_end]
    def close(self):
        if self._instrument is not None:
            try:
                self._instrument.write("ABORt")
            except Exception:
                pass
            self._instrument.close()
        if self._resource_manager is not None:
            self._resource_manager.close()
