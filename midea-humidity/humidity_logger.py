#!/usr/bin/env python3
"""Hourly humidity logger for a Midea dehumidifier via Midea's MSmartHome cloud.

Reads the LIVE humidity from the cloud and appends one timestamped row to
humidity_log.csv. Runs from anywhere with internet -- the machine does NOT need
to be on the home Wi-Fi.

Notes on why this looks the way it does:
  * The midea-beautiful-air library (0.10.5) is out of date with Midea's current
    MSmartHome API in two ways, both patched below:
      1. It logs in with a hardcoded device id shared by every user worldwide,
         which trips Midea's "too many devices" cap (error 65027). We override it
         with our own stable, unique id so we get our own login slot.
      2. Its cloud status request sends envelope fields the current API rejects
         (appVNum, applianceId, ...). We rebuild the request with only the fields
         the API now accepts (applianceCode, order, funId, ...).
"""

import csv
import datetime
import pathlib
import sys
from secrets import token_hex

import midea_beautiful.cloud as cloudmod
from midea_beautiful import appliance_state, connect_to_cloud
from midea_beautiful.cloud import MideaCloud, _decode_from_csv, _encode_as_csv
import time

from midea_beautiful.exceptions import ProtocolError
from midea_beautiful.midea import SUPPORTED_APPS

# ---- your settings -------------------------------------------------------
ACCOUNT = "dianaandgabriel@gmail.com"
PASSWORD = "Beehive2026"
APP = "MSmartHome"
MIDEA_ID = "150633095692899"        # your dehumidifier's device id (stable)
# A stable, unique device id for THIS logger -- keeps a single login slot and
# avoids the shared-id cap (65027). Any random 16-hex value works; keep it fixed.
UNIQUE_DEVICE_ID = "3dc2b915e31c7b99"
# -------------------------------------------------------------------------

LOG = pathlib.Path(__file__).resolve().parent / "humidity_log.csv"
DEBUG_PRINT_STATE = False

# --- patch 1: use our own device id so we don't hit the shared-id cap -----
cloudmod.CLOUD_API_DEVICE_ID = UNIQUE_DEVICE_ID


# --- patch 2: send a request envelope the current MSmartHome API accepts ---
def _patched_transparent_send(self, appliance_id, data):
    encoded = _encode_as_csv(data)
    order = self._security.aes_encrypt_string(encoded)
    body = {
        "appId": self._appid,
        "src": self._appid,
        "format": 2,
        "clientType": 1,
        "language": "en_US",
        "stamp": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
        "deviceId": UNIQUE_DEVICE_ID,
        "reqId": token_hex(16),
        "uid": self._uid or "",
        "order": order,
        "funId": "0000",
        "applianceCode": appliance_id,
    }
    response = self.api_request("/v1/appliance/transparent/send", args={}, data=body)
    decrypted = self._security.aes_decrypt_string(response["reply"])
    reply = _decode_from_csv(decrypted)
    if len(reply) < 50:
        raise ProtocolError(f"Invalid payload size {len(reply)}")
    return [reply[40:]]


MideaCloud.appliance_transparent_send = _patched_transparent_send


def read_humidity() -> float:
    app = SUPPORTED_APPS[APP]
    cloud = connect_to_cloud(
        ACCOUNT,
        PASSWORD,
        appkey=app["appkey"],
        appid=app["appid"],
        appname=APP,
        hmackey=app["hmackey"],
        iotkey=app["iotkey"],
        api_url=app["apiurl"],
        sign_key=app["signkey"],
        proxied=app["proxied"],
    )
    dev = appliance_state(
        cloud=cloud,
        use_cloud=True,
        appliance_id=MIDEA_ID,
        appliance_type="0xa1",
    )
    if DEBUG_PRINT_STATE:
        print(dev.state)
    return dev.state.current_humidity


def log() -> None:
    rh = read_humidity()
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "humidity_pct"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), rh])
    print(f"logged {rh}% at {datetime.datetime.now():%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    last_exc = None
    for attempt in range(3):
        try:
            log()
            sys.exit(0)
        except Exception as exc:
            last_exc = exc
            print(f"ERROR {type(exc).__name__}: {exc} (attempt {attempt + 1}/3)", file=sys.stderr)
            if attempt < 2:
                time.sleep(10)
    sys.exit(1)
