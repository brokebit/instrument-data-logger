"""
Frequency counter polling script entry point.

Select the active instrument with --instrument.
Run `python data_log.py --help` for full CLI usage.
"""

from cli import parse_run_config
from reporting import ConsoleReporter
from session import run_session


def main():
    reporter = ConsoleReporter()

    try:
        config = parse_run_config()
    except RuntimeError as error:
        reporter.show_error(str(error))
        return

    if config.ui_mode == "textual":
        try:
            from textual_ui import launch_textual_dashboard
        except ImportError:
            reporter.show_error(
                "The Textual UI requires the 'textual' package. "
                + "Install the updated requirements first."
            )
            return

        launch_textual_dashboard(config)
        return

    run_session(config, reporter)


if __name__ == "__main__":
    main()
