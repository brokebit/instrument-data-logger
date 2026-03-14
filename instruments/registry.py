from instruments.cnt90 import CNT90
from instruments.dg912_pro import DG912Pro
from instruments.keysight_53230a import Keysight53230A

KEYSIGHT_53230A_NAME = "keysight-53230a"

SUPPORTED_INSTRUMENTS = {
    "cnt90": CNT90,
    "dg912-pro": DG912Pro,
    KEYSIGHT_53230A_NAME: Keysight53230A,
}


def build_instrument(instrument_name):
    instrument_class = SUPPORTED_INSTRUMENTS[instrument_name]
    return instrument_class()
