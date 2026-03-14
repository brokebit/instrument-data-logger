"""
Instrument implementation for the Rigol DG912 Pro frequency counter.

SCPI command reference: DG800 Pro / DG900 Pro Series Programming Guide
    :COUNter:GATetime  <time>   Set gate time in seconds (range: 0.001 to 10000)
    :COUNter:MEASure?           Query frequency, period, duty cycle, +width, -width
"""

from decimal import Decimal
import pyvisa
from instruments.base import CounterInstrument, CounterReading


class DG912Pro(CounterInstrument):

    def __init__(self):
        self._resource_manager = None
        self._instrument = None

    def init(self, resource_address, gate_time_seconds, num_samples=None):
        self._resource_manager = pyvisa.ResourceManager()

        self._instrument = self._resource_manager.open_resource(resource_address)
        self._instrument.timeout = 5000

        # Set the gate time on the instrument.
        # Sending this command automatically disables the auto gate function.
        # Range: 0.001 s (1 ms) to 10000 s.
        self._instrument.write(":COUNter:GATetime " + str(gate_time_seconds))

    def read(self):
        # The DG912 Pro returns a comma-separated response with five fields:
        # frequency, period, duty cycle, positive width, negative width.
        # We parse only the frequency (first field).
        # The result is wrapped in a list to satisfy the interface contract.
        result = self._instrument.query(":COUNter:MEASure?").strip()

        raw_values = result.split(",")

        frequency_string = raw_values[0].strip()
        frequency = Decimal(frequency_string)

        return [CounterReading(frequency=frequency, frequency_text=frequency_string)]

    def close(self):
        if self._instrument is not None:
            self._instrument.close()
        if self._resource_manager is not None:
            self._resource_manager.close()
