from instruments.registry import build_instrument
from pipeline import run_pipeline
from writers.factory import build_writer


def run_session(config, reporter, stop_event=None):
    instrument = None
    writer = None
    connection_started = False

    try:
        instrument = build_instrument(config.instrument_name)
        writer = build_writer(config)

        reporter.show_connecting(config.resource_address)
        connection_started = True

        instrument.init(
            config.resource_address,
            config.gate_time_seconds,
            config.num_samples
        )
        reporter.show_run_summary(config)

        run_pipeline(
            config,
            instrument,
            writer,
            reporter,
            stop_event=stop_event,
        )
    except Exception as error:
        reporter.show_error(str(error))
    finally:
        close_errors = []

        if instrument is not None:
            try:
                instrument.close()
            except Exception as error:
                close_errors.append("Error while closing instrument: " + str(error))

        if writer is not None:
            try:
                writer.close()
            except Exception as error:
                close_errors.append("Error while closing writer: " + str(error))

        for message in close_errors:
            reporter.show_error(message)

        if connection_started:
            reporter.show_connection_closed()
