import abc
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
import time


_EVENT_HISTORY_LIMIT = 200


def _current_event_timestamp():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _format_event_message(message):
    return "[" + _current_event_timestamp() + "] " + message


def _build_run_label(instrument_name, run_name):
    if instrument_name and run_name:
        return instrument_name + " (" + run_name + ")"

    if run_name:
        return run_name

    if instrument_name:
        return instrument_name

    return "run"


class _EventLogFile:

    def __init__(self, path):
        self._handle = None
        self._lock = threading.Lock()

        if path is None:
            return

        try:
            self._handle = Path(path).expanduser().open("a", encoding="utf-8")
        except OSError as error:
            raise RuntimeError(
                "Unable to open event log file: " + str(path) + ". " + str(error)
            ) from error

    def write(self, message):
        if self._handle is None:
            return

        with self._lock:
            self._handle.write(message + "\n")
            self._handle.flush()

    def close(self):
        with self._lock:
            if self._handle is None:
                return

            self._handle.close()
            self._handle = None


@dataclass(frozen=True)
class DashboardSnapshot:
    run_state: str
    connection_closed: bool
    resource_address: str
    instrument_name: str
    run_name: str
    gate_time_seconds: float
    polling_interval_seconds: float
    num_samples: int | None
    output_csv: str | None
    output_influx: str | None
    influx_batch_size: int | None
    influx_flush_interval_seconds: float | None
    queue_size: int
    current_sample: int
    queue_depth: int
    queue_capacity: int
    latest_frequency_text: str | None
    error_count: int
    last_error: str | None
    reader_finished_reason: str | None
    start_time_monotonic: float | None
    end_time_monotonic: float | None
    events: tuple[str, ...]


class Reporter(abc.ABC):

    @abc.abstractmethod
    def show_connecting(self, resource_address):
        pass

    @abc.abstractmethod
    def show_run_summary(self, config):
        pass

    @abc.abstractmethod
    def show_status(
        self,
        sample_number,
        num_samples,
        queue_depth,
        queue_capacity,
        latest_frequency_text=None
    ):
        pass

    @abc.abstractmethod
    def show_reader_finished(self, samples_queued, reason):
        pass

    @abc.abstractmethod
    def show_polling_stopped_by_user(self):
        pass

    @abc.abstractmethod
    def show_thread_error(self, component, error):
        pass

    @abc.abstractmethod
    def show_samples_collected(self, num_samples):
        pass

    @abc.abstractmethod
    def show_error(self, message):
        pass

    @abc.abstractmethod
    def show_connection_closed(self):
        pass

    def close(self):
        pass


class ConsoleReporter(Reporter):

    def __init__(self, event_log_path=None):
        self._lock = threading.Lock()
        self._status_line_active = False
        self._status_line_width = 0
        self._event_log = _EventLogFile(event_log_path)
        self._instrument_name = ""
        self._run_name = ""
        self._run_started = False
        self._run_finished_logged = False

    def show_connecting(self, resource_address):
        with self._lock:
            self._write_event("Connecting to " + resource_address)
            print("Connecting to  : " + resource_address)

    def show_run_summary(self, config):
        with self._lock:
            self._instrument_name = config.instrument_name
            self._run_name = config.run_name
            self._run_started = True
            self._run_finished_logged = False
            self._write_event("Run started: " + self._format_run_label())

            print("Instrument     : " + config.instrument_name)
            print("Run name       : " + config.run_name)
            print("Gate time      : " + str(config.gate_time_seconds * 1000) + " ms")
            print("Polling interval: " + str(config.polling_interval_seconds * 1000) + " ms")
            if config.num_samples is not None:
                print("Collecting     : " + str(config.num_samples) + " samples")
            else:
                print("Collecting     : indefinitely (Ctrl+C to stop)")
            if config.output_csv is not None:
                print("CSV output     : " + config.output_csv)
            if config.output_influx is not None:
                print("InfluxDB output: " + config.output_influx)
                print(
                    "Influx batching: "
                    + str(config.influx_batch_size)
                    + " points / "
                    + str(config.influx_flush_interval_seconds)
                    + " s"
                )
            print("Queue size     : " + str(config.queue_size))
            print("")

    def show_status(
        self,
        sample_number,
        num_samples,
        queue_depth,
        queue_capacity,
        latest_frequency_text=None
    ):
        with self._lock:
            if num_samples is None:
                sample_status = str(sample_number)
            else:
                sample_percent = (sample_number / num_samples) * 100.0
                sample_status = (
                    str(sample_number)
                    + "/" + str(num_samples)
                    + " (" + f"{sample_percent:.1f}" + "%)"
                )

            queue_percent = (queue_depth / queue_capacity) * 100.0
            status_text = (
                "Sample: " + sample_status
                + " | Queue: " + str(queue_depth) + "/" + str(queue_capacity)
                + " (" + f"{queue_percent:.1f}" + "%)"
            )
            padding = ""
            if len(status_text) < self._status_line_width:
                padding = " " * (self._status_line_width - len(status_text))

            print(
                "\r" + status_text + padding,
                end="",
                flush=True
            )
            self._status_line_active = True
            self._status_line_width = len(status_text)

    def show_reader_finished(self, samples_queued, reason):
        with self._lock:
            self._end_status_line()
            message = (
                "Instrument read loop finished. "
                + "Samples queued: " + str(samples_queued)
                + ". Reason: " + reason + "."
            )
            self._write_event(message)
            print(message)

    def show_polling_stopped_by_user(self):
        with self._lock:
            self._end_status_line()
            message = "Polling stopped by user."
            self._write_event(message)
            print(message)

    def show_thread_error(self, component, error):
        with self._lock:
            self._end_status_line()
            message = "Error in " + component + " thread: " + str(error)
            self._write_event(message)
            print(message)

    def show_samples_collected(self, num_samples):
        with self._lock:
            self._end_status_line()
            message = "Collected " + str(num_samples) + " samples. Done."
            self._write_event(message)
            print(message)

    def show_error(self, message):
        with self._lock:
            self._end_status_line()
            rendered_message = "Error: " + message
            self._write_event(rendered_message)
            print(rendered_message)

    def show_connection_closed(self):
        with self._lock:
            self._end_status_line()
            self._log_run_finished()
            self._write_event("Connection closed.")
            print("Connection closed.")

    def close(self):
        with self._lock:
            self._event_log.close()

    def _end_status_line(self):
        if self._status_line_active:
            print("")
            self._status_line_active = False
            self._status_line_width = 0

    def _log_run_finished(self):
        if not self._run_started or self._run_finished_logged:
            return

        self._write_event("Run finished: " + self._format_run_label())
        self._run_finished_logged = True

    def _format_run_label(self):
        return _build_run_label(self._instrument_name, self._run_name)

    def _write_event(self, message):
        self._event_log.write(_format_event_message(message))


class TextualReporter(Reporter):

    def __init__(self, event_log_path=None):
        self._lock = threading.Lock()
        self._events = deque(maxlen=_EVENT_HISTORY_LIMIT)
        self._event_log = _EventLogFile(event_log_path)
        self._run_state = "idle"
        self._connection_closed = False
        self._resource_address = ""
        self._instrument_name = ""
        self._run_name = ""
        self._gate_time_seconds = 0.0
        self._polling_interval_seconds = 0.0
        self._num_samples = None
        self._output_csv = None
        self._output_influx = None
        self._influx_batch_size = None
        self._influx_flush_interval_seconds = None
        self._queue_size = 0
        self._current_sample = 0
        self._queue_depth = 0
        self._queue_capacity = 0
        self._latest_frequency_text = None
        self._error_count = 0
        self._last_error = None
        self._reader_finished_reason = None
        self._start_time_monotonic = None
        self._end_time_monotonic = None
        self._run_finished_logged = False

    def snapshot(self):
        with self._lock:
            return DashboardSnapshot(
                run_state=self._run_state,
                connection_closed=self._connection_closed,
                resource_address=self._resource_address,
                instrument_name=self._instrument_name,
                run_name=self._run_name,
                gate_time_seconds=self._gate_time_seconds,
                polling_interval_seconds=self._polling_interval_seconds,
                num_samples=self._num_samples,
                output_csv=self._output_csv,
                output_influx=self._output_influx,
                influx_batch_size=self._influx_batch_size,
                influx_flush_interval_seconds=self._influx_flush_interval_seconds,
                queue_size=self._queue_size,
                current_sample=self._current_sample,
                queue_depth=self._queue_depth,
                queue_capacity=self._queue_capacity,
                latest_frequency_text=self._latest_frequency_text,
                error_count=self._error_count,
                last_error=self._last_error,
                reader_finished_reason=self._reader_finished_reason,
                start_time_monotonic=self._start_time_monotonic,
                end_time_monotonic=self._end_time_monotonic,
                events=tuple(self._events),
            )

    def show_connecting(self, resource_address):
        with self._lock:
            self._run_state = "connecting"
            self._connection_closed = False
            self._resource_address = resource_address
            self._append_event("Connecting to " + resource_address)

    def show_run_summary(self, config):
        with self._lock:
            self._instrument_name = config.instrument_name
            self._run_name = config.run_name
            self._gate_time_seconds = config.gate_time_seconds
            self._polling_interval_seconds = config.polling_interval_seconds
            self._num_samples = config.num_samples
            self._output_csv = config.output_csv
            self._output_influx = config.output_influx
            self._influx_batch_size = config.influx_batch_size
            self._influx_flush_interval_seconds = config.influx_flush_interval_seconds
            self._queue_size = config.queue_size
            self._queue_capacity = config.queue_size
            self._queue_depth = 0
            self._current_sample = 0
            self._run_state = "running"
            self._run_finished_logged = False
            if self._start_time_monotonic is None:
                self._start_time_monotonic = time.monotonic()
            self._append_event(
                "Run started: " + self._format_run_label()
            )

    def show_status(
        self,
        sample_number,
        num_samples,
        queue_depth,
        queue_capacity,
        latest_frequency_text=None
    ):
        with self._lock:
            self._current_sample = sample_number
            self._num_samples = num_samples
            self._queue_depth = queue_depth
            self._queue_capacity = queue_capacity
            self._latest_frequency_text = latest_frequency_text

    def show_reader_finished(self, samples_queued, reason):
        with self._lock:
            if self._current_sample < samples_queued:
                self._current_sample = samples_queued
            self._reader_finished_reason = reason
            if self._run_state == "running":
                self._run_state = "finishing"
            self._append_event(
                "Instrument read loop finished. Samples queued: "
                + str(samples_queued)
                + ". Reason: " + reason + "."
            )

    def show_polling_stopped_by_user(self):
        with self._lock:
            self._run_state = "stopped"
            self._append_event("Polling stopped by user.")

    def show_thread_error(self, component, error):
        with self._lock:
            self._run_state = "error"
            self._error_count = self._error_count + 1
            self._last_error = str(error)
            self._append_event("Error in " + component + " thread: " + str(error))

    def show_samples_collected(self, num_samples):
        with self._lock:
            self._run_state = "completed"
            self._current_sample = num_samples
            self._append_event("Collected " + str(num_samples) + " samples. Done.")

    def show_error(self, message):
        with self._lock:
            self._run_state = "error"
            self._error_count = self._error_count + 1
            self._last_error = message
            self._append_event("Error: " + message)

    def show_connection_closed(self):
        with self._lock:
            self._connection_closed = True
            if self._start_time_monotonic is not None and not self._run_finished_logged:
                self._end_time_monotonic = time.monotonic()
                self._append_event("Run finished: " + self._format_run_label())
                self._run_finished_logged = True
            elif self._end_time_monotonic is None:
                self._end_time_monotonic = time.monotonic()
            self._append_event("Connection closed.")

    def _append_event(self, message):
        rendered_message = _format_event_message(message)
        self._events.append(rendered_message)
        self._event_log.write(rendered_message)

    def close(self):
        with self._lock:
            self._event_log.close()

    def _format_run_label(self):
        return _build_run_label(self._instrument_name, self._run_name)
