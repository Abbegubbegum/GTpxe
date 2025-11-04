#!/usr/bin/env python3
from flask import Flask, request, Response, send_from_directory, abort
import shelve
import os
import pathlib
import logging

ROOT = pathlib.Path("/srv")
STATIC_DIR = ROOT / "http"         # all your static boot files
DB_PATH = ROOT / "bootstage.db"    # tiny state per MAC

app = Flask(__name__, static_url_path="", static_folder=str(STATIC_DIR))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@app.before_request
def log_request():
    logger.info(
        f"Request: {request.method} {request.path} from {request.remote_addr} | Query: {dict(request.args)}")


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

    with shelve.open(str(DB_PATH)) as db:
        entry = db.get(mac, {"ran_memtest": False})
        if entry.get("ran_memtest"):
            logger.info(
                f"MAC {mac} has already run memtest, returning alpine target")
            return ipxe("set def_target alpine")
        else:
            logger.info(
                f"MAC {mac} hasn't run memtest yet, marking as run and returning memtest target")
            entry["ran_memtest"] = True
            db[mac] = entry
            return ipxe("set def_target memtest")

# Health check


@app.get("/healthz")
def health():
    return "ok", 200


if __name__ == "__main__":
    # Dev only; prod uses gunicorn (see systemd unit below)
    app.run(host="0.0.0.0", port=8080)
