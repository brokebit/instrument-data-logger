"""
Base class for data writers.
All writer implementations must inherit from DataWriter and
implement the write() and close() methods.
"""

import abc


class DataWriter(abc.ABC):

    @abc.abstractmethod
    def write(self, reading, sample_number, run_name, gate_time_seconds):
        """
        Persist a single counter reading.

        Parameters:
            reading            (CounterReading) The measurement result
            sample_number      (int)            Incrementing sample index
            run_name           (str)            Name of this sample run
            gate_time_seconds  (float)          Gate time used for this run
        """
        pass

    def flush(self):
        """
        Flush any buffered writes.

        Unbuffered writers can inherit this no-op implementation.
        """
        pass

    @abc.abstractmethod
    def close(self):
        """
        Flush and release any resources held by the writer.
        """
        pass
