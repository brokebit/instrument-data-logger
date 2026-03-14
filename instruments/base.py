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
    def __init__(self, frequency, frequency_text=None):
        self.frequency = frequency   # Hz
        self.frequency_text = str(frequency) if frequency_text is None else frequency_text


class CounterInstrument(abc.ABC):
    """
    Abstract base class for frequency counter instruments.

    Subclasses must implement:
        init(resource_address, gate_time_seconds, num_samples=None)
        read() -> list of CounterReading
        close()
    """

    @abc.abstractmethod
    def init(self, resource_address, gate_time_seconds, num_samples=None):
        """
        Open the connection to the instrument and apply initial settings.

        Parameters:
            resource_address   (str)   VISA resource string, e.g. "USB0::0x1AB1::..."
            gate_time_seconds  (float) Gate time in seconds
            num_samples        (int)   Optional requested run length
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
