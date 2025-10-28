#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
disk_health.py — offline drive inventory + health + self-test (Alpine/BusyBox friendly)

Notes:
- Safe against smartctl/nvme non-zero exit codes: we capture output and continue.
- Requires: lsblk, dmesg, smartctl (smartmontools), nvme-cli (for NVMe).
"""

import os
import re
import sys
import time
import math
import shutil
import subprocess
from typing import Tuple, Dict, Optional, List

# --------------------------- helpers ---------------------------


def print_line():
    print("-" * 80)


def run_cmd(cmd: List[str], input_text: Optional[bytes] = None, timeout: Optional[int] = None) -> Tuple[int, str, str]:
    """Run a command, returning (rc, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(cmd, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, check=False, text=True)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return 127, "", str(e)


def which_or(name: str) -> Optional[str]:
    return shutil.which(name)


def indent(text: str, spaces: int = 6) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())


def to_int(s: str, default: int = 0) -> int:
    try:
        return int(s, 0)
    except Exception:
        return default


def years_from_hours(poh: int) -> float:
    return poh / 24.0 / 365.0 if poh else 0.0

# ------------------- SMART (ATA/SATA) parsing -------------------


SMART_SECTION_START = re.compile(r"Vendor Specific SMART Attributes", re.I)
SMART_SECTION_END = re.compile(
    r"^SMART|^General SMART Values|^SMART overall-health", re.I)


def parse_smart_attrs(table_text: str) -> Dict[str, int]:
    """
    Parse SMART attribute table to a dict mapping attribute NAME -> raw numeric value.
    Compatible with formats like:
      ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
    Also copes with RAW like '497h+18m+30s' or '44 (Min/Max ...)' by extracting first number or converting h+m+s.
    """
    attrs: Dict[str, int] = {}
    in_section = False
    for line in table_text.splitlines():
        if SMART_SECTION_START.search(line):
            in_section = True
            continue
        if in_section and SMART_SECTION_END.search(line):
            in_section = False
        if not in_section:
            continue

        # Tokenize carefully; columns are space-separated but RAW_VALUE may contain spaces.
        parts = line.split()
        if len(parts) < 10:
            continue
        # Cols (common smartctl output):
        # 0:ID, 1:NAME, 9+: RAW_VALUE (10th col onwards)
        attr_id = parts[0]
        name = parts[1]
        raw = " ".join(parts[9:]).strip()

        # Normalize raw to int
        val = 0
        # h+m+s format e.g. 497h+18m+30s
        if re.search(r"[0-9]+h\+[0-9]+m\+[0-9]+s", raw):
            tmp = re.sub(r"(h\+|m\+|s)", " ", raw)
            a = tmp.split()
            if len(a) >= 3:
                val = to_int(a[0]) * 3600 + to_int(a[1]) * 60 + to_int(a[2])
        else:
            # First integer substring (handles '44 (Min/Max 10/65)' or '0 (2000 0)')
            m = re.search(r"(\d+)", raw)
            if m:
                val = to_int(m.group(1), 0)

        attrs[name] = val
        attrs[attr_id] = val  # allow lookup by ID string too
    return attrs


def get_attr(attrs: Dict[str, int], key_regex: str) -> int:
    """Return numeric attribute value by ID or NAME regex (like bash function get_attr)."""
    rx = re.compile(key_regex)
    for k, v in attrs.items():
        if rx.match(str(k)):
            return int(v)
    return 0


def smart_severity(smart_o_text: str) -> Tuple[str, str, Dict[str, int]]:
    """
    Compute severity from key ATA attributes and overall health lines inside smartctl output.
    Returns (sev: PASS/WARN/FAIL, why, extras dict).
    """
    sev = "PASS"
    why_parts: List[str] = []

    # overall-health
    m = re.search(r"overall-health.*:\s*(.+)", smart_o_text, re.I)
    if m and "failed" in m.group(1).lower():
        sev = "FAIL"
        why_parts.append("overall-health-failed")

    attrs = parse_smart_attrs(smart_o_text)
    ralloc = get_attr(attrs, r"^(5|Reallocated_Sector_Ct)$")
    repunc = get_attr(attrs, r"^(187|Reported_Uncorrect)$")
    pend = get_attr(attrs, r"^(197|Current_Pending_Sector)$")
    offunc = get_attr(attrs, r"^(198|Offline_Uncorrectable)$")
    crc = get_attr(attrs, r"^(199|UDMA_CRC_Error_Count)$")

    if any(x > 0 for x in (ralloc, repunc, pend, offunc)):
        sev = "FAIL"
        why_parts.append("media-errors")
    if crc > 0 and sev == "PASS":
        sev = "WARN"
        why_parts.append("crc-link-errors")

    extras = {
        "ralloc": ralloc,
        "repunc": repunc,
        "pend":   pend,
        "offunc": offunc,
        "crc":    crc,
    }
    return sev, " ".join(why_parts), extras

# ------------------------ NVMe parsing --------------------------


def parse_kv(text: str) -> Dict[str, int]:
    """
    Parse lines like 'critical_warning : 0' from nvme smart-log into dict of ints (missing -> 0).
    """
    out: Dict[str, int] = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower().replace(" ", "_")
            v = v.strip()
            # strip trailing percentage signs etc
            v = re.sub(r"[^\dxa-fA-F]", "", v)
            out[k] = to_int(v, 0)
    return out


def nvme_decode_selftest_result_block(text: str) -> List[str]:
    """
    Pull the 'Self Test Result[0]' block and decode the fields in a human-friendly way.
    """
    res_map = {
        0: "Completed without error",
        1: "Aborted by host",
        2: "Interrupted by reset",
        3: "Fatal error",
        4: "Unknown test error",
        5: "Self-test in progress",
        6: "Aborted for unknown reason",
        7: "Self-test not supported",
        15: "No test recorded"
    }

    lines = text.splitlines()
    out: List[str] = []
    in0 = False
    for i, line in enumerate(lines):
        if re.match(r"^Self Test Result\[0\]:", line):
            in0 = True
            continue
        if in0 and re.match(r"^Self Test Result\[\d+\]:", line):
            break
        if not in0:
            continue

        if "Operation Result" in line:
            code = to_int(line.split(":")[-1].strip(), 0)
            desc = res_map.get(code, "Unknown")
            out.append(f"      Operation Result : {desc} (code {code})")
        elif "Self Test Code" in line:
            code = to_int(line.split(":")[-1].strip(), 0)
            label = "Short" if code == 1 else "Extended" if code == 2 else f"Code {code}"
            out.append(f"      Self Test Code   : {label}")
        elif "Power on hours" in line:
            p = line.split(":", 1)[-1].strip()
            if p.lower().startswith("0x"):
                poh = int(p, 16)
            else:
                poh = to_int(p, 0)
            yrs = poh / 24.0 / 365.0 if poh else 0.0
            out.append(f"      Power-on hours   : {poh} (~{yrs:.2f} years)")
    return out

# ------------------------ inventory helpers ---------------------


def lsblk_filtered():
    # name type tran size model serial mountpoint
    rc, out, _ = run_cmd(
        ["lsblk", "-o", "NAME,TYPE,TRAN,SIZE,MODEL,SERIAL,MOUNTPOINT", "-e", "7"])
    if rc != 0:
        return ""
    lines = []
    for line in out.splitlines():
        if not line.strip():
            continue
        if re.match(r"^NAME\s+TYPE", line):
            lines.append(line)
            continue
        first = line.split()[0]
        # Exclude ram*, loop*, fd0, size==0B lines (size is col 4 typically; safer to keep everything but filter by first col)
        if first.startswith(("ram", "loop")) or first == "fd0":
            continue
        # We already asked lsblk to exclude 7 (rom), but keep a simple filter
        lines.append(line)
    return "\n".join(lines)


def list_disks() -> List[str]:
    rc, out, _ = run_cmd(["lsblk", "-ndo", "NAME,TYPE,SIZE"])
    disks = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                name, typ, size = parts[0], parts[1], parts[2]
                if typ == "disk" and not name.startswith(("ram", "loop")) and name != "fd0" and size != "0B":
                    disks.append(name)
    return disks


def block_rotational_flag(devname: str) -> str:
    # Reads /sys/block/<base>/queue/rotational
    base = re.sub(r"\d+$", "", devname)  # strip trailing digits (partitions)
    path = f"/sys/block/{base}/queue/rotational"
    try:
        with open(path, "r") as f:
            s = f.read().strip()
            if s == "1":
                return "HDD"
            elif s == "0":
                return "SSD/NVMe"
            else:
                return "Unknown"
    except Exception:
        return "Unknown"


def lsblk_one(dev: str, field: str) -> str:
    rc, out, _ = run_cmd(["lsblk", "-ndo", field, dev])
    return out.strip() if rc == 0 else ""

# ---------------------------- main ------------------------------


def main() -> int:
    print()
    print_line()
    print("Disk inventory:")
    inv = lsblk_filtered()
    if inv:
        print(inv)
    print_line()

    print("Recent kernel disk messages:")
    rc, out, _ = run_cmd(["dmesg"])
    if rc == 0:
        # match sdX or nvmeN
        lines = [ln for ln in out.splitlines() if re.search(
            r"\bsd[a-z]\b|\bnvme\d", ln)]
        print("\n".join(lines[-20:]))
    print_line()

    disks = list_disks()
    if not disks:
        print("No disks detected.")
        return 0

    overall_rc = 0

    for n in disks:
        dev = f"/dev/{n}"
        print(f"Device: {dev}")
        model = lsblk_one(dev, "MODEL")
        serial = lsblk_one(dev, "SERIAL")
        size = lsblk_one(dev, "SIZE")
        tran = lsblk_one(dev, "TRAN")
        dtype = block_rotational_flag(n)
        print(
            f"  Model: {model} | Serial: {serial or 'N/A'} | Size: {size} | Bus: {tran or 'N/A'} | Type: {dtype}")

        is_nvme = n.startswith("nvme")
        if is_nvme and which_or("nvme"):
            ctrl = f"/dev/{re.split(r'n\d+', n)[0]}"
            print(f"    → Running short self-test on {ctrl}...")
            # Kick short self-test (code 1)
            run_cmd(["nvme", "device-self-test", "-s", "1", ctrl])
            rcH, nvme_h, nvme_e = run_cmd(["nvme", "smart-log", "-H", ctrl])

            if nvme_h.strip():
                # parse key fields
                rcJ, nvme_json, _ = run_cmd(["nvme", "smart-log", ctrl])
                kv = parse_kv(nvme_json)

                cw = kv.get("critical_warning", 0)
                me = kv.get("media_errors", 0)
                ne = kv.get("num_err_log_entries", 0)
                pu = kv.get("percentage_used", 0)
                poh = kv.get("power_on_hours", 0)

                sev = "PASS"
                why = []
                if cw != 0:
                    sev = "FAIL"
                    why.append("critical_warning")
                if me > 0 and sev == "PASS":
                    sev = "FAIL"
                    why.append("media_errors")
                if pu >= 100 and sev == "PASS":
                    sev = "FAIL"
                    why.append("worn_out")
                if pu >= 80 and sev == "PASS":
                    sev = "WARN"
                    why.append("high_wear")
                if ne > 0 and sev == "PASS":
                    sev = "WARN"
                    why.append("controller_errors")

                print(f"  Health: {sev}")
                if sev == "FAIL":
                    overall_rc = 1
                print(f"    reasons: {(' '.join(why)) or 'ok'}")
                print(
                    f"    Power-on hours: {poh or 0}  (~{years_from_hours(poh):.2f} years)")
                print(f"    critical_warning: {cw or 0}")
                print(f"    media_errors:     {me or 0}")
                print(f"    err_log_entries:  {ne or 0}")
                print(f"    percentage_used:  {pu or 0}")

                # Self-test log (optional)
                rcS, stlog, _ = run_cmd(["nvme", "self-test-log", ctrl])
                if rcS == 0 and stlog.strip():
                    print("    Self-test result (most recent):")
                    for l in nvme_decode_selftest_result_block(stlog):
                        print(l)
                else:
                    # If we failed to fetch, just note that we started the test
                    print(
                        "    Self-test: started (short). Recheck later with: nvme self-test-log", ctrl)
            else:
                print("  Health: ERROR")
                overall_rc = 1
                if nvme_e.strip():
                    print(
                        "    " + indent("\n".join(nvme_e.splitlines()[:6]), 4))

        else:
            # SATA/USB/SAS via smartctl
            print(f"    → Running short self-test on {dev}...")
            rcT, _, ste = run_cmd(["smartctl", "-t", "short", dev])
            if rcT != 0 and re.search(r"(Unknown USB bridge|please specify device type)", ste or "", re.I):
                # Retry with SAT bridge
                run_cmd(["smartctl", "-d", "sat", "-t", "short", dev])

            # Poll up to ~130s until not in-progress
            end = time.time() + 130
            while time.time() < end:
                rcC, cap, _ = run_cmd(["smartctl", "-c", dev])
                if rcC == 0 and re.search(r"Self-test routine in progress", cap or "", re.I):
                    time.sleep(5)
                    continue
                break

            # Fetch SMART data (H/A/error/selftest)
            rcO, smart_o, smart_e = run_cmd(
                ["smartctl", "-H", "-A", "-l", "error", "-l", "selftest", dev])
            if (not smart_o.strip()) or re.search(r"(Unknown USB bridge|please specify device type)", smart_e or "", re.I):
                rcO, smart_o, smart_e = run_cmd(
                    ["smartctl", "-d", "sat", "-H", "-A", "-l", "error", "-l", "selftest", dev])

            if smart_o.strip():
                attrs = parse_smart_attrs(smart_o)

                # Power on hours / seconds heuristic
                poh = get_attr(attrs, r"^(Power_On_Hours|Power_On_Seconds)$")
                if poh > 100000:   # looks like seconds
                    poh = poh // 3600

                sev, why, extras = smart_severity(smart_o)

                # ATA error count
                m = re.search(r"ATA Error Count\s*:\s*(\d+)", smart_o, re.I)
                ata_err = to_int(m.group(1), 0) if m else 0
                if ata_err > 0 and sev == "PASS":
                    sev = "WARN"
                    why = (why + " " if why else "") + "ata_error_log"

                print(f"  Health: {sev}")
                if sev == "FAIL":
                    overall_rc = 1
                print(f"    reasons: {why or 'ok'}")
                print(
                    f"    ralloc={extras['ralloc']} repunc={extras['repunc']} pend={extras['pend']} offunc={extras['offunc']} crc={extras['crc']}")
                print(
                    f"    Power-on hours: {poh or 0}  (~{years_from_hours(poh):.2f} years)")
                print(f"    ata_error_log: {ata_err}")

                if ata_err > 0:
                    # Show recent errors (first ~20 lines that match key markers)
                    print("    Recent ATA errors (drive shows last 5):")
                    shown = 0
                    for ln in smart_o.splitlines():
                        if re.match(r"^(Error \d+ occurred|Error: )", ln):
                            print("      " + ln)
                            shown += 1
                            if shown >= 20:
                                break

                print("    Self-test results:")
                for ln in smart_o.splitlines():
                    if re.search(r"Self-test execution status|#\s*1\s+", ln):
                        print("      " + ln)

                print("    Key SMART attributes:")
                # Print key attributes like original script
                wanted_ids = {"5", "187", "196", "197", "198", "199"}
                wanted_names = {
                    "Reallocated_Sector_Ct",
                    "Reported_Uncorrect",
                    "Uncorrect",
                    "Current_Pending_Sector",
                    "Offline_Uncorrectable",
                    "UDMA_CRC_Error_Count"
                }

                printed = set()
                # Prefer names
                for name in list(attrs.keys()):
                    if name.isdigit():  # skip numeric mirror keys in this loop
                        continue
                    name_ok = (name in wanted_names)
                    id_ok = False
                    # find the matching ID mirror if any
                    # (We stored both name and id with same value, but we don't have mapping name->id here;
                    #  instead, use heuristic: if numeric key exists and equals this value, and numeric in wanted_ids.)
                    # Simpler: also emit by numeric id:
                for id_ in wanted_ids:
                    val = attrs.get(id_, None)
                    if val is not None and ("ID"+id_) not in printed:
                        # Try to find the usual smartctl name for cosmetic print
                        label = {
                            "5": "Reallocated_Sector_Ct",
                            "187": "Reported_Uncorrect",
                            "196": "Reallocated_Event_Count",
                            "197": "Current_Pending_Sector",
                            "198": "Offline_Uncorrectable",
                            "199": "UDMA_CRC_Error_Count",
                        }.get(id_, f"ID_{id_}")
                        print(f"      {label:<26}={val}")
                        printed.add("ID"+id_)

                # Additionally, if names exist directly, print them (avoid duplicates)
                for nm in sorted(wanted_names):
                    if nm in attrs and ("NM"+nm) not in printed:
                        print(f"      {nm:<26}={attrs[nm]}")
                        printed.add("NM"+nm)

            else:
                print("  Health: ERROR")
                overall_rc = 1
                err_head = "\n".join(smart_e.splitlines()[
                                     :8]) if smart_e else ""
                if err_head:
                    print("    " + indent(err_head, 4))

        print_line()

    return overall_rc


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
