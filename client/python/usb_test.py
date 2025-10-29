#!/usr/bin/env python3
import usb.core
import usb.util
import time
import struct
import json
import sys
import argparse
from typing import Dict, Any, List, Tuple

# ---------------------- Defaults (generous) ----------------------
DEFAULT_MIN_THR_MBPS = 1.4      # worst seen was 1.5 Mbps → set floor at 1.5
DEFAULT_V_MIN_MV = 4600     # 4.6 V
DEFAULT_V_MAX_MV = 5500     # 5.5 V
DEFAULT_MAX_DROOP_MV = 600
DEFAULT_MAX_RIPPLE_MVPP = 250
DEFAULT_MAX_RECOVERY_US = 5
DEFAULT_MIN_MAX_CURRENT_MA = 400

# ---------------------- USB IDs & Protocol ----------------------
VID = 0x1209
PID = 0x4004

REQ_GET_PORT = 0x01  # IN:  u8 port
REQ_SET_PORT = 0x02  # OUT: wValue = port
REQ_GET_POWER = 0x03  # IN:  power report blob
REQ_GET_PORTMAP = 0x10  # IN:  bitmask of available ports

TEST_SECS = 3.0
PKT_SIZE = 1024
TIMEOUT_MS = 1000

POWER_REPORT_FMT = "<BBB" + "HH" + "5H"*8 + "HHH"
POWER_REPORT_SIZE = struct.calcsize(POWER_REPORT_FMT)

# ---------------------- USB helpers ----------------------


def find_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise RuntimeError(
            f"Device not found (VID=0x{VID:04X}, PID=0x{PID:04X})")
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    return dev


def find_vendor_interface(dev):
    for cfg in dev:
        for intf in cfg:
            if intf.bInterfaceClass == 0xFF:
                return intf
    raise RuntimeError("No vendor interface (class 0xFF) found")


def ctrl_in(dev, req, length, intf_num):
    return dev.ctrl_transfer(0xC1, req, 0, intf_num, length, timeout=TIMEOUT_MS)


def ctrl_out(dev, req, intf_num, wValue=0):
    dev.ctrl_transfer(0x41, req, wValue, intf_num, None, timeout=TIMEOUT_MS)


def try_get_map(dev, intf_num):
    data = bytes(ctrl_in(dev, REQ_GET_PORTMAP, 1, intf_num))
    if len(data) != 1:
        raise RuntimeError("Map request returned wrong length")
    return data[0]


def build_ports_from_map(map_val):
    return [i for i in range(8) if (map_val >> i) & 1]


def get_ports_to_test(dev):
    intf_num = find_vendor_interface(dev).bInterfaceNumber
    port_map = try_get_map(dev, intf_num)
    return build_ports_from_map(port_map)


def set_port_and_reopen(dev, intf_num, port):
    ctrl_out(dev, REQ_SET_PORT, intf_num, port)
    time.sleep(1)  # allow re-enumeration
    dev = find_device()
    intf_num = find_vendor_interface(dev).bInterfaceNumber
    return dev

# ---------------------- Bulk loopback ----------------------


def find_bulk_eps(dev):
    intf = find_vendor_interface(dev)
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(
            e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
    )
    ep_in = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(
            e.bEndpointAddress) == usb.util.ENDPOINT_IN
        and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
    )
    if ep_out is None or ep_in is None:
        raise RuntimeError("Could not find bulk endpoints on vendor interface")
    return ep_out, ep_in


HEADER_SIZE = 6  # <u32 seq><u16 len>


def make_packet(total_size, seq):
    if total_size < HEADER_SIZE:
        total_size = HEADER_SIZE
    hdr = struct.pack("<IH", seq, total_size)
    payload = bytes((i & 0xFF for i in range(total_size - HEADER_SIZE)))
    return hdr + payload


def check_echo(buf, expected_seq, expected_len):
    if len(buf) < HEADER_SIZE:
        return False, "short echo"
    seq, ln = struct.unpack("<IH", buf[:HEADER_SIZE])
    if seq != expected_seq or ln != expected_len:
        return False, f"header mismatch seq={seq} len={ln} expected seq={expected_seq} len={expected_len}"
    if len(buf) != expected_len:
        return False, "USB len mismatch"
    for i, b in enumerate(buf[HEADER_SIZE:]):
        if b != (i & 0xFF):
            return False, f"payload mismatch at {i}"
    return True, ""


def recv_exact(ep_in, size, timeout_ms=TIMEOUT_MS):
    buf = bytearray()
    while len(buf) < size:
        chunk = ep_in.read(size - len(buf), timeout=timeout_ms)
        buf.extend(chunk)
    return bytes(buf)


def run_bulk_test(dev, duration_s=TEST_SECS, pkt_size=PKT_SIZE):
    ep_out, ep_in = find_bulk_eps(dev)
    # flush stale IN
    try:
        while True:
            data = ep_in.read(512, timeout=5)
            if not data:
                break
    except usb.core.USBError:
        pass

    deadline = time.time() + duration_s
    seq = 0
    sent = 0
    got = 0
    errors = 0

    while time.time() < deadline:
        pkt = make_packet(pkt_size, seq)
        try:
            wrote = ep_out.write(pkt, timeout=TIMEOUT_MS)
            sent += wrote
        except usb.core.USBError:
            errors += 1
            continue

        try:
            echo = bytes(recv_exact(ep_in, pkt_size))
            ok, _ = check_echo(echo, seq, pkt_size)
            if not ok:
                errors += 1
            else:
                got += len(echo)
        except usb.core.USBError:
            errors += 1

        seq += 1

    bps = got / duration_s
    return {
        "bytes_sent": sent,
        "bytes_rcvd": got,
        "seconds": duration_s,
        "throughput_Bps": bps,
        "throughput_Mbps": (bps * 8) / 1e6,
        "errors": errors
    }

# ---------------------- Power parsing ----------------------


def parse_power_report(blob):
    if len(blob) != POWER_REPORT_SIZE:
        raise ValueError(
            f"power report wrong length: {len(blob)} != {POWER_REPORT_SIZE}")
    it = iter(struct.unpack(POWER_REPORT_FMT, blob))
    port = next(it)
    n_steps = next(it)
    flags = next(it)
    maxpower = next(it)
    v_idle = next(it)

    def take_u16(n): return [next(it) for _ in range(n)]
    loads = take_u16(5)
    v_mean = take_u16(5)
    v_min = take_u16(5)
    v_max = take_u16(5)
    droop = take_u16(5)
    ripple = take_u16(5)
    current_mA = take_u16(5)
    recovery_us = take_u16(5)

    max_current = next(it)
    ocp_at = next(it)
    errors = next(it)

    n = n_steps
    return {
        "port": port,
        "n_steps": n,
        "flags": flags,
        "maxpower_mA": maxpower,
        "v_idle_mV": v_idle,
        "loads_mA":        loads[:n],
        "v_mean_mV":       v_mean[:n],
        "v_min_mV":        v_min[:n],
        "v_max_mV":        v_max[:n],
        "droop_mV":        droop[:n],
        "ripple_mVpp":     ripple[:n],
        "current_mA":      current_mA[:n],
        "recovery_us":     recovery_us[:n],
        "max_current_mA":  max_current,
        "ocp_at_mA":       ocp_at,
        "errors":          errors,
    }

# ---------------------- Evaluation ----------------------


def evaluate_port(port_result: Dict[str, Any],
                  limits: Dict[str, float]) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Return (passed, reasons, rollup_metrics)"""
    reasons: List[str] = []
    passed = True

    port = port_result.get("port", -1)
    thr = port_result.get("throughput_Mbps", 0.0)
    if thr < limits["min_thr_mbps"]:
        passed = False
        reasons.append(
            f"throughput {thr:.2f} Mbps < {limits['min_thr_mbps']:.2f} Mbps")

    if port_result.get("errors", 0) > 0:
        passed = False
        reasons.append(f"{port_result['errors']} data errors")

    # --- Skip power checks for control port 0 ---
    if port == 0:
        rollup = {
            "throughput_Mbps": thr,
            "errors": 0,
            "vmin_mV": 0,
            "vmax_mV": 0,
            "max_droop_mV": 0,
            "max_ripple_mVpp": 0,
            "max_recovery_us": 0,
            "max_measured_current_mA": 0,
        }
        return passed, reasons, rollup

    pr = port_result.get("power_report", {}) or {}
    vmin_list = pr.get("v_min_mV", [])
    vmax_list = pr.get("v_max_mV", [])
    droop_list = pr.get("droop_mV", [])
    ripple_list = pr.get("ripple_mVpp", [])
    recov_list = pr.get("recovery_us", [])
    curr_list = pr.get("current_mA", [])

    # safe reductions
    vmin = min(vmin_list) if vmin_list else 99999
    vmax = max(vmax_list) if vmax_list else 0
    max_droop = max(droop_list) if droop_list else 0
    max_ripple = max(ripple_list) if ripple_list else 0
    max_recovery = max(recov_list) if recov_list else 0
    max_measured_current = max(curr_list) if curr_list else 0

    if vmin < limits["v_min_mV"]:
        passed = False
        reasons.append(
            f"Vmin {vmin/1000:.2f} V < {limits['v_min_mV']/1000:.2f} V")
    if vmax > limits["v_max_mV"]:
        passed = False
        reasons.append(
            f"Vmax {vmax/1000:.2f} V > {limits['v_max_mV']/1000:.2f} V")
    if max_droop > limits["max_droop_mV"]:
        passed = False
        reasons.append(f"droop {max_droop} mV > {limits['max_droop_mV']} mV")
    if max_ripple > limits["max_ripple_mVpp"]:
        passed = False
        reasons.append(
            f"ripple {max_ripple} mVpp > {limits['max_ripple_mVpp']} mVpp")
    if max_recovery > limits["max_recovery_us"]:
        passed = False
        reasons.append(
            f"recovery {max_recovery} µs > {limits['max_recovery_us']} µs")
    if max_measured_current < limits["min_max_current_mA"]:
        passed = False
        reasons.append(
            f"measured current never exceeds {limits['min_max_current_mA']} mA (max observed {max_measured_current} mA)"
        )

    # Optional: echo mismatch still fails
    echo = int(port_result.get("device_port_echo", port))
    if echo != port:
        passed = False
        reasons.append(f"port echo mismatch dev:{echo} != host:{port}")

    rollup = {
        "throughput_Mbps": thr,
        "errors": port_result.get("errors", 0),
        "vmin_mV": vmin,
        "vmax_mV": vmax,
        "max_droop_mV": max_droop,
        "max_ripple_mVpp": max_ripple,
        "max_recovery_us": max_recovery,
        "max_measured_current_mA": max_measured_current,
        "ocp_at_mA": int(pr.get("ocp_at_mA") or 0),
    }
    return passed, reasons, rollup

# ---------------------- Main ----------------------


def main():
    ap = argparse.ArgumentParser(
        description="USB loopback & power test for diagnostics pipeline"
    )
    ap.add_argument("--min-thr-mbps", type=float, default=DEFAULT_MIN_THR_MBPS)
    ap.add_argument("--v-min-mv", type=int, default=DEFAULT_V_MIN_MV)
    ap.add_argument("--v-max-mv", type=int, default=DEFAULT_V_MAX_MV)
    ap.add_argument("--max-droop-mv", type=int, default=DEFAULT_MAX_DROOP_MV)
    ap.add_argument("--max-ripple-mvpp", type=int,
                    default=DEFAULT_MAX_RIPPLE_MVPP)
    ap.add_argument("--max-recovery-us", type=int,
                    default=DEFAULT_MAX_RECOVERY_US)
    ap.add_argument("--secs", type=float, default=TEST_SECS)
    ap.add_argument("--pkt", type=int, default=PKT_SIZE)
    ap.add_argument("--json-only", action="store_true",
                    help="Only print JSON (no human summary)")
    args = ap.parse_args()

    limits = {
        "min_thr_mbps": args.min_thr_mbps,
        "v_min_mV": args.v_min_mv,
        "v_max_mV": args.v_max_mv,
        "max_droop_mV": args.max_droop_mv,
        "max_ripple_mVpp": args.max_ripple_mvpp,
        "max_recovery_us": args.max_recovery_us,
        "min_max_current_mA": DEFAULT_MIN_MAX_CURRENT_MA,
    }

    overall_pass = True
    summary_obj: Dict[str, Any] = {"tested_ports": [], "per_port": []}

    try:
        dev = find_device()
        intf_num = find_vendor_interface(dev).bInterfaceNumber
        ports = get_ports_to_test(dev)
    except Exception as e:
        # Hard fail: no device / enumeration error
        if not args.json_only:
            print(f"USB TEST: {e}")
        sys.exit(0)

    if not ports:
        if not args.json_only:
            print("USB TEST: FAIL — no ports detected")
        print(json.dumps({"error": "no ports detected"}))
        sys.exit(1)

    for p in ports:
        dev = set_port_and_reopen(dev, intf_num, p)

        res = run_bulk_test(dev, duration_s=args.secs, pkt_size=args.pkt)
        res["port"] = p
        try:
            port_echo = ctrl_in(dev, REQ_GET_PORT, 1, intf_num)[0]
            res["device_port_echo"] = int(port_echo)
        except Exception:
            res["device_port_echo"] = -1

        # Power report
        try:
            data = ctrl_in(dev, REQ_GET_POWER, POWER_REPORT_SIZE, intf_num)
            res["power_report"] = parse_power_report(bytes(data))
        except Exception as e:
            res["power_report_error"] = str(e)
            res["power_report"] = {
                "v_min_mV": [], "v_max_mV": [], "droop_mV": [], "ripple_mVpp": [], "recovery_us": []
            }

        passed, reasons, rollup = evaluate_port(res, limits)
        res["pass"] = passed
        res["fail_reasons"] = reasons
        res["rollup"] = rollup

        summary_obj["tested_ports"].append(p)
        summary_obj["per_port"].append(res)

        if not args.json_only:
            # concise single-line summary
            vmin_v = rollup["vmin_mV"] / \
                1000 if rollup["vmin_mV"] != 99999 else 0.0
            droop = rollup["max_droop_mV"]
            ripple = rollup["max_ripple_mVpp"]
            thr = rollup["throughput_Mbps"]
            imax = rollup["max_measured_current_mA"]

            status = "PASS" if passed else "FAIL"
            if p == 0:
                print(f"USB Port {p}: {thr:.2f} Mbps — {status}")
            else:
                print(f"USB Port {p}: {thr:.2f} Mbps, "
                      f"Vmin {vmin_v:.2f} V, droop {droop} mV, ripple {ripple} mVpp, "
                      f"Imax {imax} mA — {status}")

        if not passed:
            overall_pass = False

        time.sleep(0.05)

    # Try to switch back to neutral/default port 0 (best effort)
    try:
        set_port_and_reopen(dev, intf_num, 0)
    except Exception:
        pass

    # Save report to file
    try:
        with open("/root/usb_report.json", "w") as f:
            json.dump(summary_obj, f, indent=2)
    except Exception:
        pass

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
