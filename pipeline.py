import queue
import threading
import time


def read_instrument_loop(
    instrument,
    readings_queue,
    polling_interval_seconds,
    num_samples,
    stop_event,
    reader_done_event,
    num_samples_reached_event,
    error_queue,
    reporter
):
    sample_number = 1
    next_poll_time = time.monotonic()
    exit_reason = "stop requested"

    try:
        while not stop_event.is_set():
            if num_samples is not None and sample_number > num_samples:
                num_samples_reached_event.set()
                exit_reason = "target sample count reached"
                break

            wait_seconds = next_poll_time - time.monotonic()
            if wait_seconds > 0 and stop_event.wait(wait_seconds):
                break

            readings = instrument.read()

            for reading in readings:
                if stop_event.is_set():
                    break

                if num_samples is not None and sample_number > num_samples:
                    num_samples_reached_event.set()
                    exit_reason = "target sample count reached"
                    break

                # Backpressure policy: block when queue is full so we do not
                # silently drop samples.
                enqueued = False
                while not stop_event.is_set():
                    try:
                        readings_queue.put((reading, sample_number), timeout=0.1)
                        enqueued = True
                        break
                    except queue.Full:
                        continue

                if not enqueued:
                    exit_reason = "stop requested"
                    break

                sample_number = sample_number + 1

            next_poll_time = next_poll_time + polling_interval_seconds
            if next_poll_time < time.monotonic():
                next_poll_time = time.monotonic()

    except Exception as error:
        error_queue.put(("reader", error))
        stop_event.set()
        exit_reason = "error"

    finally:
        reader_done_event.set()
        reporter.show_reader_finished(sample_number - 1, exit_reason)


def write_loop(
    writer,
    readings_queue,
    run_name,
    gate_time_seconds,
    num_samples,
    stop_event,
    reader_done_event,
    error_queue,
    reporter
):
    next_status_time = time.monotonic() + 1.0
    last_sample_number = 0
    latest_frequency_text = None

    try:
        while True:
            if reader_done_event.is_set() and readings_queue.empty():
                break

            try:
                reading, sample_number = readings_queue.get(timeout=0.1)
            except queue.Empty:
                writer.flush()
                current_time = time.monotonic()
                if last_sample_number > 0 and current_time >= next_status_time:
                    reporter.show_status(
                        last_sample_number,
                        num_samples,
                        readings_queue.qsize(),
                        readings_queue.maxsize,
                        latest_frequency_text=latest_frequency_text
                    )
                    next_status_time = current_time + 1.0
                continue

            try:
                writer.write(reading, sample_number, run_name, gate_time_seconds)
                last_sample_number = sample_number
                latest_frequency_text = reading.frequency_text

                current_time = time.monotonic()
                if current_time >= next_status_time:
                    reporter.show_status(
                        sample_number,
                        num_samples,
                        readings_queue.qsize(),
                        readings_queue.maxsize,
                        latest_frequency_text=latest_frequency_text
                    )
                    next_status_time = current_time + 1.0
            finally:
                readings_queue.task_done()

    except Exception as error:
        error_queue.put(("writer", error))
        stop_event.set()


def run_pipeline(config, instrument, writer, reporter, stop_event=None):
    readings_queue = queue.Queue(maxsize=config.queue_size)
    if stop_event is None:
        stop_event = threading.Event()
    reader_done_event = threading.Event()
    num_samples_reached_event = threading.Event()
    error_queue = queue.Queue()

    reader_thread = threading.Thread(
        target=read_instrument_loop,
        args=(
            instrument,
            readings_queue,
            config.polling_interval_seconds,
            config.num_samples,
            stop_event,
            reader_done_event,
            num_samples_reached_event,
            error_queue,
            reporter,
        ),
        name="instrument-reader"
    )

    writer_thread = threading.Thread(
        target=write_loop,
        args=(
            writer,
            readings_queue,
            config.run_name,
            config.gate_time_seconds,
            config.num_samples,
            stop_event,
            reader_done_event,
            error_queue,
            reporter,
        ),
        name="data-writer"
    )

    reader_thread.start()
    writer_thread.start()

    try:
        while reader_thread.is_alive() or writer_thread.is_alive():
            reader_thread.join(timeout=0.2)
            writer_thread.join(timeout=0.2)

            if not error_queue.empty():
                break

    except KeyboardInterrupt:
        reporter.show_polling_stopped_by_user()
        stop_event.set()

    finally:
        stop_event.set()
        reader_thread.join()
        writer_thread.join()

        if not error_queue.empty():
            component, error = error_queue.get()
            reporter.show_thread_error(component, error)

        if num_samples_reached_event.is_set():
            reporter.show_samples_collected(config.num_samples)
