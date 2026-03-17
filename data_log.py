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

        try:
            launch_textual_dashboard(config)
        except RuntimeError as error:
            reporter.show_error(str(error))
        return

    try:
        reporter = ConsoleReporter(config.event_log)
    except RuntimeError as error:
        ConsoleReporter().show_error(str(error))
        return

    try:
        run_session(config, reporter)
    finally:
        reporter.close()


if __name__ == "__main__":
    main()
