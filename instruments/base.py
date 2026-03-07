"""
Base class for frequency counter instruments.
All instrument implementations must inherit from CounterInstrument and
implement the init(), read(), and close() methods.
"""

import abc


class CounterReading:
    """
    Standardised data contract for a single measurement sample.
    """
    def __init__(self, frequency):
        self.frequency = frequency   # Hz


class CounterInstrument(abc.ABC):
    """
    Abstract base class for frequency counter instruments.

    Subclasses must implement:
        init(resource_address, gate_time_seconds)
        read() -> list of CounterReading
        close()
    """

    @abc.abstractmethod
    def init(self, resource_address, gate_time_seconds):
        """
        Open the connection to the instrument and apply initial settings.

        Parameters:
            resource_address   (str)   VISA resource string, e.g. "USB0::0x1AB1::..."
            gate_time_seconds  (float) Gate time in seconds
        """
        pass

    @abc.abstractmethod
    def read(self):
        """
        Query the instrument for all measurements accumulated since the last call.

        Returns:
            list of CounterReading

        Instruments that do not support continuous buffering will always return
        a list containing a single CounterReading.
        """
        pass

    @abc.abstractmethod
    def close(self):
        """
        Release the instrument connection and any associated resources.
        """
        pass