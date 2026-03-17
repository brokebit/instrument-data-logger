from collections import deque
import threading
import time

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, ProgressBar, RichLog, Static

from reporting import TextualReporter
from session import run_session

_REFRESH_INTERVAL_SECONDS = 0.25
_RATE_HISTORY_LIMIT = 12


class TextualDashboardApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #dashboard {
        height: 1fr;
        padding: 1 2;
    }

    #stats-row {
        height: 7;
        margin: 0 0 1 0;
    }

    .metric {
        width: 1fr;
        border: round $primary;
        background: $surface;
        padding: 1 2;
        margin: 0 1 0 0;
    }

    #main-row {
        height: 1fr;
        margin: 0 0 1 0;
    }

    .panel {
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    #live-panel {
        width: 1fr;
        margin: 0 1 0 0;
    }

    #config-panel {
        width: 1fr;
    }

    #events-panel {
        height: 12;
    }

    .panel-title {
        text-style: bold;
        margin: 0 0 1 0;
    }

    ProgressBar {
        margin: 0 0 1 0;
    }

    #events-log {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("s", "stop_run", "Stop"),
        ("q", "quit_app", "Quit"),
    ]

    def __init__(self, config, reporter):
        super().__init__()
        self._config = config
        self._reporter = reporter
        self._stop_event = threading.Event()
        self._session_thread = None
        self._exit_on_finish = False
        self._events_rendered = 0
        self._sample_history = deque(maxlen=_RATE_HISTORY_LIMIT)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="dashboard"):
            with Horizontal(id="stats-row"):
                yield Static(id="state-card", classes="metric")
                yield Static(id="elapsed-card", classes="metric")
                yield Static(id="rate-card", classes="metric")
            with Horizontal(id="main-row"):
                with Vertical(id="live-panel", classes="panel"):
                    yield Static("Run Progress", classes="panel-title")
                    yield Static(id="sample-summary")
                    yield ProgressBar(total=100, show_eta=False, id="sample-progress")
                    yield Static(id="queue-summary")
                    yield ProgressBar(total=100, show_eta=False, id="queue-progress")
                    yield Static(id="health-summary")
                with Vertical(id="config-panel", classes="panel"):
                    yield Static("Run Details", classes="panel-title")
                    yield Static(id="config-text")
            with Vertical(id="events-panel", classes="panel"):
                yield Static("Events", classes="panel-title")
                yield RichLog(id="events-log", wrap=True)
        yield Footer()

    def on_mount(self):
        self.title = "Instrument Data Logger"
        self.sub_title = self._config.run_name

        self._state_card = self.query_one("#state-card", Static)
        self._elapsed_card = self.query_one("#elapsed-card", Static)
        self._rate_card = self.query_one("#rate-card", Static)
        self._sample_summary = self.query_one("#sample-summary", Static)
        self._sample_progress = self.query_one("#sample-progress", ProgressBar)
        self._queue_summary = self.query_one("#queue-summary", Static)
        self._queue_progress = self.query_one("#queue-progress", ProgressBar)
        self._health_summary = self.query_one("#health-summary", Static)
        self._config_text = self.query_one("#config-text", Static)
        self._events_log = self.query_one("#events-log", RichLog)

        self.set_interval(_REFRESH_INTERVAL_SECONDS, self._refresh_dashboard)

        self._session_thread = threading.Thread(
            target=run_session,
            args=(self._config, self._reporter, self._stop_event),
            name="session-runner"
        )
        self._session_thread.start()

        self._refresh_dashboard()

    def action_stop_run(self):
        if self._stop_event.is_set():
            return

        if self._session_thread is not None and self._session_thread.is_alive():
            self._reporter.show_polling_stopped_by_user()
            self._stop_event.set()

    def action_quit_app(self):
        if self._session_thread is not None and self._session_thread.is_alive():
            self._exit_on_finish = True
            self.action_stop_run()
            return

        self.exit()

    def shutdown_session(self):
        self._stop_event.set()
        if self._session_thread is not None:
            self._session_thread.join()

    def _refresh_dashboard(self):
        snapshot = self._reporter.snapshot()
        self._append_new_events(snapshot.events)
        self._record_sample_rate(snapshot.current_sample)
        self._update_header_cards(snapshot)
        self._update_progress_panels(snapshot)
        self._update_config_panel(snapshot)

        if (
            self._exit_on_finish
            and self._session_thread is not None
            and not self._session_thread.is_alive()
        ):
            self.exit()

    def _append_new_events(self, events):
        if self._events_rendered >= len(events):
            return

        for event in events[self._events_rendered:]:
            self._events_log.write(event)

        self._events_rendered = len(events)

    def _record_sample_rate(self, current_sample):
        current_time = time.monotonic()

        if not self._sample_history:
            self._sample_history.append((current_time, current_sample))
            return

        last_time, last_sample = self._sample_history[-1]
        if current_sample != last_sample or current_time - last_time >= 1.0:
            self._sample_history.append((current_time, current_sample))

    def _update_header_cards(self, snapshot):
        self._state_card.update(
            "State\n" + self._format_state(snapshot.run_state, snapshot.connection_closed)
        )
        self._elapsed_card.update(
            "Elapsed\n" + self._format_elapsed(snapshot)
        )
        self._rate_card.update(
            "Sample Rate\n" + self._format_sample_rate()
        )

    def _update_progress_panels(self, snapshot):
        if snapshot.num_samples is None:
            self._sample_summary.update(
                "Sample progress: "
                + str(snapshot.current_sample)
                + " collected (no target configured)"
            )
            self._sample_progress.update(total=1, progress=0)
        else:
            sample_percent = 0.0
            if snapshot.num_samples > 0:
                sample_percent = (snapshot.current_sample / snapshot.num_samples) * 100.0
            self._sample_summary.update(
                "Sample progress: "
                + str(snapshot.current_sample)
                + "/" + str(snapshot.num_samples)
                + " (" + f"{sample_percent:.1f}" + "%)"
            )
            self._sample_progress.update(
                total=snapshot.num_samples,
                progress=min(snapshot.current_sample, snapshot.num_samples)
            )

        queue_percent = 0.0
        if snapshot.queue_capacity > 0:
            queue_percent = (snapshot.queue_depth / snapshot.queue_capacity) * 100.0

        self._queue_summary.update(
            "Queue fill: "
            + str(snapshot.queue_depth)
            + "/" + str(snapshot.queue_capacity)
            + " (" + f"{queue_percent:.1f}" + "%)"
        )
        self._queue_progress.update(
            total=max(snapshot.queue_capacity, 1),
            progress=min(snapshot.queue_depth, max(snapshot.queue_capacity, 1))
        )

        self._health_summary.update(
            "\n".join(
                [
                    "Reader status : " + self._format_reader_status(snapshot),
                    "Errors        : " + str(snapshot.error_count),
                    "Last error    : " + (snapshot.last_error or "--"),
                    "Latest freq   : " + self._format_latest_frequency(snapshot.latest_frequency_text),
                ]
            )
        )

    def _update_config_panel(self, snapshot):
        lines = [
            "Instrument      : " + (snapshot.instrument_name or self._config.instrument_name),
            "Resource        : " + (snapshot.resource_address or self._config.resource_address),
            "Run name        : " + (snapshot.run_name or self._config.run_name),
            "Gate time       : " + self._format_milliseconds(self._config.gate_time_seconds),
            "Polling interval: " + self._format_milliseconds(self._config.polling_interval_seconds),
            "Queue size      : " + str(self._config.queue_size),
        ]

        if self._config.num_samples is not None:
            lines.append("Target samples  : " + str(self._config.num_samples))
        else:
            lines.append("Target samples  : indefinite")

        if self._config.output_csv is not None:
            lines.append("CSV output      : " + self._config.output_csv)

        if self._config.event_log is not None:
            lines.append("Event log       : " + self._config.event_log)

        if self._config.output_influx is not None:
            lines.append("Influx target   : " + self._config.output_influx)
            lines.append(
                "Influx batching : "
                + str(self._config.influx_batch_size)
                + " / "
                + str(self._config.influx_flush_interval_seconds)
                + " s"
            )

        self._config_text.update("\n".join(lines))

    def _format_state(self, run_state, connection_closed):
        if run_state == "completed":
            return "COMPLETED"
        if run_state == "error":
            return "ERROR"
        if run_state == "stopped":
            return "STOPPED"
        if run_state == "finishing":
            return "FINISHING"
        if run_state == "connecting":
            return "CONNECTING"
        if connection_closed:
            return "CLOSED"
        if run_state == "running":
            return "RUNNING"
        return "IDLE"

    def _format_elapsed(self, snapshot):
        start_time = snapshot.start_time_monotonic
        if start_time is None:
            return "--"

        end_time = snapshot.end_time_monotonic
        if end_time is None:
            end_time = time.monotonic()

        return self._format_duration(end_time - start_time)

    def _format_sample_status(self, current_sample, num_samples):
        if num_samples is None:
            return str(current_sample)

        if num_samples <= 0:
            return str(current_sample) + "/0"

        sample_percent = (current_sample / num_samples) * 100.0
        return (
            str(current_sample)
            + "/" + str(num_samples)
            + " (" + f"{sample_percent:.1f}" + "%)"
        )

    def _format_queue_status(self, queue_depth, queue_capacity):
        if queue_capacity <= 0:
            return str(queue_depth)

        queue_percent = (queue_depth / queue_capacity) * 100.0
        return (
            str(queue_depth)
            + "/" + str(queue_capacity)
            + " (" + f"{queue_percent:.1f}" + "%)"
        )

    def _format_latest_frequency(self, latest_frequency_text):
        if latest_frequency_text is None:
            return "--"

        return latest_frequency_text + " Hz"

    def _format_sample_rate(self):
        if len(self._sample_history) < 2:
            return "--"

        start_time, start_sample = self._sample_history[0]
        end_time, end_sample = self._sample_history[-1]
        elapsed_seconds = end_time - start_time
        if elapsed_seconds <= 0:
            return "--"

        return f"{(end_sample - start_sample) / elapsed_seconds:.1f} samples/s"

    def _format_reader_status(self, snapshot):
        if snapshot.reader_finished_reason is not None:
            return snapshot.reader_finished_reason

        if snapshot.run_state == "running":
            return "running"

        if snapshot.run_state == "connecting":
            return "starting"

        return snapshot.run_state

    def _format_milliseconds(self, seconds):
        return str(seconds * 1000.0) + " ms"

    def _format_duration(self, total_seconds):
        total_seconds = max(int(total_seconds), 0)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"


def launch_textual_dashboard(config):
    reporter = TextualReporter(config.event_log)
    app = TextualDashboardApp(config, reporter)

    try:
        app.run()
    finally:
        app.shutdown_session()
        reporter.close()
