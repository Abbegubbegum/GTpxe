#!/usr/bin/env python3
from flask import Flask, request, Response, send_from_directory, abort
import shelve
import os
import pathlib
import logging
from datetime import date

ROOT = pathlib.Path("/srv")
STATIC_DIR = ROOT / "http"         # all your static boot files
DB_PATH = ROOT / "bootstage.db"    # tiny state per MAC
LOG_FILE = ROOT / "pxe_http.log"   # log file path

app = Flask(__name__, static_url_path="", static_folder=str(STATIC_DIR))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add file handler for logging to file
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(file_handler)


@app.before_request
def log_request():
    logger.info(
        f"Request: {request.method} {request.path} from {request.remote_addr}")


def ipxe(text: str) -> Response:
    return Response("#!ipxe\n" + text + "\n", mimetype="text/plain")

# -------- Dynamic endpoints --------


@app.get("/bootstage")
def bootstage():
    mac = (request.args.get("mac") or "").lower()
    logger.info(f"bootstage endpoint hit with MAC: {mac or 'NONE'}")

    if not mac:
        logger.warning(
            "No MAC address provided, returning default alpine target")
        return ipxe("set def_target alpine")

    today = date.today().isoformat()

    with shelve.open(str(DB_PATH)) as db:
        entry = db.get(mac, {})
        last_test_date = entry.get("last_memtest_date")

        if last_test_date == today:
            logger.info(
                f"MAC {mac} already ran memtest today ({today}), returning alpine target")
            return ipxe("set def_target alpine")
        else:
            if last_test_date:
                logger.info(
                    f"MAC {mac} last tested on {last_test_date}, running memtest again for today ({today})")
            else:
                logger.info(
                    f"MAC {mac} hasn't run memtest yet, running memtest for today ({today})")
            entry["last_memtest_date"] = today
            db[mac] = entry
            return ipxe("set def_target memtest")

# Health check


@app.get("/healthz")
def health():
    return "ok", 200


if __name__ == "__main__":
    # Dev only; prod uses gunicorn (see systemd unit below)
    app.run(host="0.0.0.0", port=8080)
