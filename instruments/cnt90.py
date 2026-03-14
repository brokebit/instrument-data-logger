"""
Instrument implementation for the Pendulum CNT-90 Timer/Counter/Analyzer.

SCPI command reference: Pendulum CNT-90 Series Programmer's Handbook (May 2017)

This implementation uses continuous buffered measurement mode:
    - :INITiate:CONTinuous ON causes the instrument to measure continuously,
      storing results in an internal buffer.
    - Each call to read() drains all accumulated results from the buffer using
      :FETCh:ARRay? MAX, returning however many measurements have completed
      since the last call.
    - If read() is called faster than the gate time, the buffer may be empty
      and an empty list is returned. If read() is called slower than the gate
      time, multiple readings will be returned per call.

This is different from the DG912 Pro, which makes a fresh single measurement
on each query and always returns exactly one result.

Key differences from the DG912 Pro:
    - Gate time is set via :ACQuisition:APERture, not :COUNter:GATetime
    - Each measurement parameter must be fetched with a separate query.
      There is no combined measurement command.
    - Continuous mode requires :INITiate:CONTinuous ON and uses :FETCh:ARRay?
      rather than :MEASure:<function>?
    - USB Vendor ID is 0x14EB (Pendulum Instruments), Model ID is 0x0090.
      Resource address format: "USB0::0x14EB::0x0090::<serial>::INSTR"

Relevant SCPI commands used here:
    :ACQuisition:APERture <time>    Set gate (measurement) time in seconds
    :INITiate:CONTinuous ON         Start continuous measurement into buffer
    :FUNCtion "FREQuency"           Set the active measurement function
    :FETCh:ARRay? MAX               Drain all buffered frequency results
"""

from decimal import Decimal
import pyvisa
from instruments.base import CounterInstrument, CounterReading


class CNT90(CounterInstrument):

    def __init__(self):
        self._resource_manager = None
        self._instrument = None

    def init(self, resource_address, gate_time_seconds, num_samples=None):
        self._resource_manager = pyvisa.ResourceManager()

        self._instrument = self._resource_manager.open_resource(resource_address)
        self._instrument.timeout = 5000

        # Set the measurement gate (aperture) time in seconds.
        # Default after *RST is 10 ms (0.01 s).
        self._instrument.write(":ACQuisition:APERture " + str(gate_time_seconds))

        # Start continuous measurement mode.
        # The instrument will now measure continuously and buffer results.
        # Each call to read() will drain whatever has accumulated.
        self._instrument.write(":INITiate:CONTinuous ON")

    def read(self):
        readings = []

        # Set the active measurement function to frequency and fetch all
        # buffered values accumulated since the last call.
        # MAX tells the instrument to return everything currently in the buffer.
        self._instrument.write(":FUNCtion 'FREQuency'")
        raw_frequencies = self._instrument.query(":FETCh:ARRay? MAX").strip()

        frequency_values = raw_frequencies.split(",")

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

    def close(self):
        if self._instrument is not None:
            # Stop continuous measurement mode before closing.
            self._instrument.write(":INITiate:CONTinuous OFF")
            self._instrument.close()
        if self._resource_manager is not None:
            self._resource_manager.close()
