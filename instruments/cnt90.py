"""
Instrument implementation for the Pendulum CNT-90 Timer/Counter/Analyzer.

SCPI command reference: Pendulum CNT-90 Series Programmer's Handbook (May 2017)

This implementation supports two transports:
    - PyVISA resources (USB/GPIB/LAN via VISA backend)
    - Prologix Ethernet GPIB adapter (native TCP socket transport)

Prologix resource address formats accepted by init():
    - prologix://<host>[:<port>]/<gpib_address>
      Example: prologix://192.168.1.50:1234/12
    - PROLOGIX::<host>::<gpib_address>
      Example: PROLOGIX::192.168.1.50::12
    - PROLOGIX::<host>::<port>::<gpib_address>
      Example: PROLOGIX::192.168.1.50::1234::12

Continuous buffered measurement mode is used:
    - :INITiate:CONTinuous ON makes the instrument measure continuously.
    - read() drains buffered values using :FETCh:ARRay? MAX.
    - read() may return zero, one, or many readings depending on timing.

Relevant SCPI commands used here:
    :ACQuisition:APERture <time>    Set gate (measurement) time in seconds
    :INITiate:CONTinuous ON         Start continuous measurement into buffer
    :FUNCtion "FREQuency"           Set the active measurement function
    :FETCh:ARRay? MAX               Drain all buffered frequency results
"""

import socket
from urllib.parse import urlparse

try:
    import pyvisa
except ImportError:
    pyvisa = None
from instruments.base import CounterInstrument, CounterReading


class CNT90(CounterInstrument):

    def __init__(self):
        self._transport = None

        self._resource_manager = None
        self._instrument = None

        self._socket = None
        self._socket_recv_buffer = b""
        self._prologix_gpib_address = None

        self._timeout_seconds = 5.0

    def init(self, resource_address, gate_time_seconds):
        if self._is_prologix_resource(resource_address):
            host, port, gpib_address = self._parse_prologix_resource(resource_address)
            self._init_prologix(host, port, gpib_address, gate_time_seconds)
            return

        self._init_pyvisa(resource_address, gate_time_seconds)

    def _init_pyvisa(self, resource_address, gate_time_seconds):
        if pyvisa is None:
            raise RuntimeError(
                "pyvisa is required for VISA resources. Install with: pip install pyvisa pyvisa-py"
            )

        self._transport = "visa"
        self._resource_manager = pyvisa.ResourceManager()

        self._instrument = self._resource_manager.open_resource(resource_address)
        self._instrument.timeout = int(self._timeout_seconds * 1000.0)

        self._setup_cnt90(gate_time_seconds)

    def _init_prologix(self, host, port, gpib_address, gate_time_seconds):
        self._transport = "prologix"
        self._prologix_gpib_address = gpib_address

        self._socket = socket.create_connection((host, port), timeout=self._timeout_seconds)
        self._socket.settimeout(self._timeout_seconds)

        # Configure the Prologix adapter for controller mode and explicit reads.
        self._prologix_command("++mode 1")
        self._prologix_command("++auto 0")
        self._prologix_command("++eoi 1")
        self._prologix_command("++eos 3")
        self._prologix_command("++read_tmo_ms " + str(int(self._timeout_seconds * 1000.0)))
        self._prologix_command("++addr " + str(gpib_address))

        self._setup_cnt90(gate_time_seconds)

    def _setup_cnt90(self, gate_time_seconds):
        # Set the measurement gate (aperture) time in seconds.
        # Default after *RST is 10 ms (0.01 s).
        self._write_scpi(":ACQuisition:APERture " + str(gate_time_seconds))

        # Select frequency function and start continuous buffered mode.
        self._write_scpi(":FUNCtion 'FREQuency'")
        self._write_scpi(":INITiate:CONTinuous ON")

    def read(self):
        raw_frequencies = self._query_scpi(":FETCh:ARRay? MAX").strip()
        if raw_frequencies == "":
            return []

        readings = []
        frequency_values = raw_frequencies.split(",")

        for frequency_string in frequency_values:
            cleaned_value = frequency_string.strip()
            if cleaned_value == "":
                continue

            reading = CounterReading(frequency=float(cleaned_value))
            readings.append(reading)

        return readings

    def close(self):
        try:
            self._write_scpi(":INITiate:CONTinuous OFF")
        except Exception:
            pass

        if self._instrument is not None:
            self._instrument.close()
            self._instrument = None

        if self._resource_manager is not None:
            self._resource_manager.close()
            self._resource_manager = None

        if self._socket is not None:
            try:
                self._prologix_command("++loc")
            except Exception:
                pass
            self._socket.close()
            self._socket = None
            self._socket_recv_buffer = b""
            self._prologix_gpib_address = None

        self._transport = None

    def _write_scpi(self, command):
        if self._transport == "visa":
            self._instrument.write(command)
            return

        if self._transport == "prologix":
            self._prologix_command("++addr " + str(self._prologix_gpib_address))
            self._socket_send_line(command)
            return

        raise RuntimeError("CNT90 transport is not initialized.")

    def _query_scpi(self, command):
        if self._transport == "visa":
            return self._instrument.query(command)

        if self._transport == "prologix":
            self._prologix_command("++addr " + str(self._prologix_gpib_address))
            self._socket_send_line(command)
            self._prologix_command("++read eoi")
            return self._socket_read_line()

        raise RuntimeError("CNT90 transport is not initialized.")

    def _prologix_command(self, command):
        self._socket_send_line(command)

    def _socket_send_line(self, line):
        if self._socket is None:
            raise RuntimeError("Prologix socket is not connected.")

        payload = (line + "\n").encode("ascii")
        self._socket.sendall(payload)

    def _socket_read_line(self):
        if self._socket is None:
            raise RuntimeError("Prologix socket is not connected.")

        while True:
            newline_index = self._socket_recv_buffer.find(b"\n")
            if newline_index >= 0:
                line_bytes = self._socket_recv_buffer[:newline_index]
                self._socket_recv_buffer = self._socket_recv_buffer[newline_index + 1:]
                return line_bytes.decode("ascii", errors="replace").strip()

            chunk = self._socket.recv(4096)
            if chunk == b"":
                # If the connection closes after a final partial line, return it.
                if self._socket_recv_buffer != b"":
                    line_bytes = self._socket_recv_buffer
                    self._socket_recv_buffer = b""
                    return line_bytes.decode("ascii", errors="replace").strip()
                raise RuntimeError("Prologix socket connection was closed.")

            self._socket_recv_buffer = self._socket_recv_buffer + chunk

    def _is_prologix_resource(self, resource_address):
        upper_resource = resource_address.upper()
        return upper_resource.startswith("PROLOGIX::") or resource_address.lower().startswith("prologix://")

    def _parse_prologix_resource(self, resource_address):
        if resource_address.lower().startswith("prologix://"):
            parsed = urlparse(resource_address)

            host = parsed.hostname
            if host is None or host == "":
                raise ValueError(
                    "Invalid Prologix resource. Host is required, e.g. prologix://192.168.1.50:1234/12"
                )

            gpib_string = parsed.path.lstrip("/")
            if gpib_string == "":
                raise ValueError(
                    "Invalid Prologix resource. GPIB address is required, e.g. prologix://192.168.1.50:1234/12"
                )

            port = parsed.port if parsed.port is not None else 1234
            gpib_address = int(gpib_string)
            return host, port, gpib_address

        # PROLOGIX::<host>::<gpib_address>
        # PROLOGIX::<host>::<port>::<gpib_address>
        parts = resource_address.split("::")

        if len(parts) == 3:
            host = parts[1]
            port = 1234
            gpib_address = int(parts[2])
            return host, port, gpib_address

        if len(parts) == 4:
            host = parts[1]
            port = int(parts[2])
            gpib_address = int(parts[3])
            return host, port, gpib_address

        raise ValueError(
            "Invalid Prologix resource format. Use prologix://<host>[:<port>]/<gpib_address> "
            "or PROLOGIX::<host>::<gpib_address>."
        )
