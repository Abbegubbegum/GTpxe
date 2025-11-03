#!/usr/bin/env python3
from flask import Flask, request, Response, send_from_directory, abort
import shelve
import os
import pathlib

ROOT = pathlib.Path("/srv")
STATIC_DIR = ROOT / "www"         # all your static boot files
DB_PATH = ROOT / "bootstage.db"    # tiny state per MAC

app = Flask(__name__, static_url_path="", static_folder=str(STATIC_DIR))


def ipxe(text: str) -> Response:
    return Response("#!ipxe\n" + text + "\n", mimetype="text/plain")

# -------- Dynamic endpoints --------


@app.get("/bootstage")
def bootstage():
    mac = (request.args.get("mac") or "").lower()

    if not mac:
        return ipxe("set def_target alpine")

    with shelve.open(str(DB_PATH)) as db:
        entry = db.get(mac, {"ran_memtest": False})
        if entry.get("ran_memtest"):
            return ipxe("set def_target alpine")
        else:
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
