from writers.composite_writer import CompositeWriter
from writers.csv_writer import CSVWriter
from writers.influx_writer import InfluxWriter


def build_writer(config):
    writers = []

    try:
        if config.output_csv is not None:
            csv_writer = CSVWriter(config.output_csv)
            csv_writer.open()
            writers.append(csv_writer)

        if config.output_influx is not None:
            host, port, database = _parse_influx_target(config.output_influx)

            influx_writer = InfluxWriter(
                host,
                port,
                database,
                batch_size=config.influx_batch_size,
                flush_interval_seconds=config.influx_flush_interval_seconds,
            )
            influx_writer.open()
            writers.append(influx_writer)
    except Exception:
        for writer in writers:
            writer.close()
        raise

    return CompositeWriter(writers)


def _parse_influx_target(output_influx):
    parts = output_influx.split(":")
    if len(parts) != 3:
        raise RuntimeError(
            "Invalid --output-influx value: expected host:port:database."
        )

    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError as error:
        raise RuntimeError(
            "Invalid --output-influx port: " + parts[1] + "."
        ) from error
    database = parts[2]

    return host, port, database
