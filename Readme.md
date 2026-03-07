# Frequency Counter Polling Tool

A Python command-line tool for polling a frequency counter over VISA, with support for multiple instruments and configurable output destinations.

## Features

- Polls a frequency counter at a configurable gate time
- Supports multiple instruments via a common abstraction layer
- Writes results to CSV, InfluxDB 1.x, or both simultaneously
- Prints live readings to the console during collection
- Stops cleanly on Ctrl+C or after a fixed number of samples


For instruments connected via a National Instruments GPIB adapter (e.g. NI GPIB-USB-HS), install NI-488.2 and NI-VISA from the [NI website](https://www.ni.com/en/support/downloads/drivers/download.ni-488-2.html) instead of `pyvisa-py`. PyVISA will detect and use the NI VISA backend automatically.

## Project Structure

```
main.py                      Entry point and polling loop
instruments/
    base.py                  CounterReading and CounterInstrument abstract base class
    dg912_pro.py             Rigol DG912 Pro implementation (USB)
    cnt90.py                 Pendulum CNT-90 implementation (USB or GPIB)
writers/
    base.py                  DataWriter abstract base class
    csv_writer.py            Writes readings to a CSV file
    influx_writer.py         Writes readings to InfluxDB 1.x
    composite_writer.py      Fans out writes to multiple writers simultaneously
```

## Supported Instruments

### Rigol DG912 Pro

Connected via Ethernet. Uses a single blocking `:COUNter:MEASure?` query per sample. Returns exactly one reading per call.

VISA resource address format:
```
TCPIP0::192.168.100.217::inst0::INSTR
```

### Pendulum CNT-90

Connected via USB or GPIB (e.g. via NI GPIB-USB-HS adapter). Uses continuous buffered measurement mode — the instrument measures autonomously and accumulates results in an internal buffer. Each `read()` call drains everything that has accumulated since the last call, which may be zero or more readings depending on timing relative to the gate time.

VISA resource address formats:
```
USB0::0x14EB::0x0090::<serial>::INSTR   (direct USB)
GPIB0::12::INSTR                         (via GPIB adapter, address set on instrument)
```

To confirm PyVISA can see your instrument before running the tool:
```python
import pyvisa
rm = pyvisa.ResourceManager()
print(rm.list_resources())
```

## Usage

```
python main.py --resource <VISA address> --run-name <name> [options]
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--resource` | Yes | — | VISA resource address of the instrument |
| `--run-name` | Yes | — | Name for this collection run |
| `--gate-time` | No | `0.001` | Gate time in seconds |
| `--num-samples` | No | — | Number of samples to collect. Omit to run indefinitely |
| `--output-csv` | No | — | Path to a CSV file to write results to |
| `--output-influx` | No | — | InfluxDB target as `host:port:database` |

### Examples

Collect 100 samples from a DG912 Pro at 100 ms gate time, writing to CSV:
```bash
python main.py \
    --resource "USB0::0x1AB1::0x0641::DG9A1234::INSTR" \
    --run-name "bench_test_01" \
    --gate-time 0.1 \
    --num-samples 100 \
    --output-csv results.csv
```

Collect indefinitely from a CNT-90 via GPIB, writing to InfluxDB:
```bash
python main.py \
    --resource "GPIB0::12::INSTR" \
    --run-name "stability_run_01" \
    --gate-time 1.0 \
    --output-influx influx_host:8086:samples_db
```

Write to both CSV and InfluxDB simultaneously:
```bash
python main.py \
    --resource "GPIB0::12::INSTR" \
    --run-name "stability_run_01" \
    --gate-time 1.0 \
    --output-csv results.csv \
    --output-influx influx_host:8086:samples_db
```

## Output Formats

### CSV

Columns written to the CSV file:

| Column | Description |
|---|---|
| `timestamp` | ISO 8601 UTC timestamp of the reading |
| `sample_number` | Incrementing index within the run, starting at 1 |
| `run_name` | Value of `--run-name` |
| `gate_time_ms` | Gate time in milliseconds |
| `frequency_hz` | Measured frequency in Hz |

The file is opened in append mode. Multiple runs can share the same file and are distinguished by `run_name`.

### InfluxDB

Measurement name: `frequency_counter`

| Type | Key | Description |
|---|---|---|
| Tag | `run_name` | Value of `--run-name` |
| Field | `frequency_hz` | Measured frequency in Hz |
| Field | `gate_time_ms` | Gate time in milliseconds |
| Field | `sample_number` | Incrementing index within the run |

The target database must already exist on the server. The tool checks for this at startup and exits with an error if it is missing. To create the database:
```
CREATE DATABASE samples_db
```

SSL is enabled with certificate verification disabled, matching a typical local self-hosted deployment with a self-signed certificate. Authentication is not required.

#### Querying a run

All results from a single run:
```sql
SELECT * FROM frequency_counter WHERE run_name = 'bench_test_01'
```

Via the `influx` CLI:
```bash
influx -host influx_host -port 8086 -database samples_db \
    -execute "SELECT * FROM frequency_counter WHERE run_name = 'bench_test_01'"
```

Via HTTP:
```bash
curl -G "https://influx_host:8086/query" \
     --data-urlencode "db=samples_db" \
     --data-urlencode "q=SELECT * FROM frequency_counter WHERE run_name = 'bench_test_01'" \
     -k
```

## Adding an Instrument

Create a new file in `instruments/` that subclasses `CounterInstrument` from `instruments/base.py` and implements three methods:

- `init(resource_address, gate_time_seconds)` — open the VISA connection and configure the instrument
- `read()` — return a `list` of `CounterReading` objects (one per measurement in the current poll)
- `close()` — stop the instrument and close the VISA connection

Then update the import and instantiation in `main.py`.

## Adding a Writer

Create a new file in `writers/` that subclasses `DataWriter` from `writers/base.py` and implements:

- `open()` — establish any connections or open files
- `write(reading, sample_number, run_name, gate_time_seconds)` — persist one reading
- `close()` — flush and close

Add instantiation of the new writer inside `build_writer()` in `main.py`. `CompositeWriter` will fan out to it automatically alongside any other active writers.

## Allan Deviation Analysis

Results stored in InfluxDB can be loaded into a Jupyter notebook for Allan deviation analysis using `allantools` and the `influxdb` `DataFrameClient`:

```python
from influxdb import DataFrameClient
import allantools
import numpy as np

client = DataFrameClient(host='influx_host', port=8086, database='samples_db', ssl=True, verify_ssl=False)
df = client.query("SELECT * FROM frequency_counter WHERE run_name = 'bench_test_01'")['frequency_counter']

# Check for missing samples using sample_number before computing ADEV
expected = np.arange(df['sample_number'].min(), df['sample_number'].max() + 1)
missing  = np.setdiff1d(expected, df['sample_number'].to_numpy())
if len(missing) > 0:
    print("Missing samples: " + str(missing))

gate_time_seconds = df['gate_time_ms'].iloc[0] / 1000.0

taus, adev, errors, ns = allantools.oadev(
    df['frequency_hz'].to_numpy(),
    rate=1.0 / gate_time_seconds,
    data_type='freq',
    taus='all'
)
```