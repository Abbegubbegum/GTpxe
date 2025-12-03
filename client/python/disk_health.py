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

# ANSI color codes


class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    RED = '\033[0;31m'
    CYAN = '\033[0;36m'
    GRAY = '\033[0;90m'
    DIM = '\033[2m'  # Dimmed text (more visible than gray)


def print_line():
    print(Colors.GRAY + "-" * 80 + Colors.RESET)


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

    # Thresholds (balanced for practical use - filter out noise, catch real problems)
    RALLOC_FAIL = 50    # 50+ reallocated sectors indicates drive degradation
    RALLOC_WARN = 10    # 10+ reallocated sectors warrants monitoring
    CRC_FAIL = 100      # 100+ CRC errors indicates serious cable/controller issue
    CRC_WARN = 10       # 10+ CRC errors means cable should be checked

    # Critical current errors - these are active problems (should always be 0)
    if pend > 0 or offunc > 0:
        sev = "FAIL"
        if pend > 0:
            why_parts.append(f"pending_sectors={pend}")
        if offunc > 0:
            why_parts.append(f"offline_uncorrectable={offunc}")

    # Reported uncorrectable - warn if present, but not immediate fail
    # (these are historical, not active bad sectors)
    if repunc > 0 and sev == "PASS":
        sev = "WARN"
        why_parts.append(f"reported_uncorrect={repunc}")

    # Reallocated sectors - graduated response
    if ralloc >= RALLOC_FAIL:
        sev = "FAIL"
        why_parts.append(f"reallocated_sectors={ralloc}(≥{RALLOC_FAIL})")
    elif ralloc >= RALLOC_WARN and sev == "PASS":
        sev = "WARN"
        why_parts.append(f"reallocated_sectors={ralloc}(≥{RALLOC_WARN})")

    # CRC errors - cable/connection issue (not drive failure)
    if crc >= CRC_FAIL:
        if sev == "PASS":
            sev = "FAIL"
        why_parts.append(f"crc_errors={crc}(≥{CRC_FAIL},CHECK_CABLE)")
    elif crc >= CRC_WARN and sev == "PASS":
        sev = "WARN"
        why_parts.append(f"crc_errors={crc}(≥{CRC_WARN},CHECK_CABLE)")

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
    print(f"{Colors.BOLD}{Colors.CYAN}Disk Inventory:{Colors.RESET}")
    inv = lsblk_filtered()
    if inv:
        print(inv)
    print_line()

    disks = list_disks()
    if not disks:
        print(f"{Colors.YELLOW}No disks detected.{Colors.RESET}")
        return 0

    overall_rc = 0

    for n in disks:
        dev = f"/dev/{n}"
        print(f"\n{Colors.BOLD}{Colors.CYAN}Device: {dev}{Colors.RESET}")
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

                # NVMe health thresholds
                sev = "PASS"
                why = []

                # Critical warning - always fail (indicates hardware problem)
                if cw != 0:
                    sev = "FAIL"
                    why.append("critical_warning")

                # Media errors - always fail (indicates bad NAND cells)
                if me > 0 and sev == "PASS":
                    sev = "FAIL"
                    why.append("media_errors")

                # Wear level thresholds
                if pu >= 100 and sev == "PASS":
                    sev = "FAIL"
                    why.append("worn_out")
                elif pu >= 90 and sev == "PASS":
                    sev = "WARN"
                    why.append("high_wear(≥90%)")

                # Error log entries - only warn if significant
                if ne >= 10 and sev == "PASS":
                    sev = "WARN"
                    why.append(f"controller_errors(≥10)")

                # Colorize health status
                if sev == "PASS":
                    health_str = f"{Colors.GREEN}{Colors.BOLD}PASS{Colors.RESET}"
                elif sev == "WARN":
                    health_str = f"{Colors.YELLOW}{Colors.BOLD}WARN{Colors.RESET}"
                else:
                    health_str = f"{Colors.RED}{Colors.BOLD}FAIL{Colors.RESET}"

                print(f"  Health: {health_str}")
                if sev == "FAIL":
                    overall_rc = 1
                print(
                    f"    Power-on hours: {poh or 0}  (~{years_from_hours(poh):.2f} years)")
                print(f"    Wear level: {pu or 0}%")

                # Only show concerning attributes
                nvme_concerns = []
                if cw != 0:
                    nvme_concerns.append(f"Critical_Warning={cw} (FAIL if >0)")
                if me > 0:
                    nvme_concerns.append(f"Media_Errors={me} (FAIL if >0)")
                if pu >= 90:
                    nvme_concerns.append(
                        f"Percentage_Used={pu}% (WARN≥90%, FAIL≥100%)")
                if ne >= 10:
                    nvme_concerns.append(f"Error_Log_Entries={ne} (WARN≥10)")

                if nvme_concerns:
                    print(
                        f"    {Colors.YELLOW}{Colors.BOLD}CONCERNS:{Colors.RESET}")
                    for concern in nvme_concerns:
                        print(
                            f"      {Colors.YELLOW}•{Colors.RESET} {concern}")

                # Self-test log (optional)
                rcS, stlog, _ = run_cmd(["nvme", "self-test-log", ctrl])
                if rcS == 0 and stlog.strip():
                    decoded = nvme_decode_selftest_result_block(stlog)
                    # Only show if there's useful info
                    if decoded and not all("No test recorded" in line for line in decoded):
                        print(
                            f"    {Colors.CYAN}Self-test result (most recent):{Colors.RESET}")
                        for l in decoded:
                            print(f"    {l}")
            else:
                print(
                    f"  Health: {Colors.RED}{Colors.BOLD}ERROR{Colors.RESET}")
                overall_rc = 1
                if nvme_e.strip():
                    print(
                        f"    {Colors.RED}" + indent("\n".join(nvme_e.splitlines()[:6]), 4) + Colors.RESET)

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

                # ATA error count - only warn if significant
                m = re.search(r"ATA Error Count\s*:\s*(\d+)", smart_o, re.I)
                ata_err = to_int(m.group(1), 0) if m else 0
                if ata_err >= 5 and sev == "PASS":
                    sev = "WARN"
                    why = (why + " " if why else "") + f"ata_error_log(≥5)"

                # Colorize health status
                if sev == "PASS":
                    health_str = f"{Colors.GREEN}{Colors.BOLD}PASS{Colors.RESET}"
                elif sev == "WARN":
                    health_str = f"{Colors.YELLOW}{Colors.BOLD}WARN{Colors.RESET}"
                else:
                    health_str = f"{Colors.RED}{Colors.BOLD}FAIL{Colors.RESET}"

                print(f"  Health: {health_str}")
                if sev == "FAIL":
                    overall_rc = 1
                print(
                    f"    Power-on hours: {poh or 0}  (~{years_from_hours(poh):.2f} years)")

                # Only show concerning attributes
                concerns = []
                if extras['repunc'] > 0:
                    concerns.append(
                        f"Reported_Uncorrect={extras['repunc']} (WARN if >0)")
                if extras['pend'] > 0:
                    concerns.append(
                        f"Pending_Sectors={extras['pend']} (FAIL if >0)")
                if extras['offunc'] > 0:
                    concerns.append(
                        f"Offline_Uncorrectable={extras['offunc']} (FAIL if >0)")
                if extras['ralloc'] >= 10:
                    concerns.append(
                        f"Reallocated_Sectors={extras['ralloc']} (WARN≥10, FAIL≥50)")
                if extras['crc'] >= 10:
                    concerns.append(
                        f"CRC_Errors={extras['crc']} (WARN≥10, FAIL≥100) {Colors.YELLOW}- CHECK CABLE{Colors.RESET}")

                if concerns:
                    print(
                        f"    {Colors.YELLOW}{Colors.BOLD}CONCERNS:{Colors.RESET}")
                    for concern in concerns:
                        print(
                            f"      {Colors.YELLOW}•{Colors.RESET} {concern}")

                if ata_err >= 5:
                    print(
                        f"    {Colors.YELLOW}ATA Error Log: {ata_err} errors found (WARN≥5){Colors.RESET}")
                    # Show recent errors (first ~20 lines that match key markers)
                    print(f"    {Colors.RED}Recent ATA errors:{Colors.RESET}")
                    shown = 0
                    for ln in smart_o.splitlines():
                        if re.match(r"^(Error \d+ occurred|Error: )", ln):
                            print(f"      {ln}")
                            shown += 1
                            if shown >= 20:
                                break

                # Show self-test results only if there's something interesting
                selftest_lines = [ln for ln in smart_o.splitlines()
                                  if re.search(r"Self-test execution status|#\s*1\s+", ln)]
                if selftest_lines and not all("Completed without error" in ln or "of test" in ln for ln in selftest_lines):
                    print(f"    {Colors.CYAN}Self-test results:{Colors.RESET}")
                    for ln in selftest_lines[:3]:  # Only show first 3 lines
                        print(f"      {ln}")

            else:
                print(
                    f"  Health: {Colors.RED}{Colors.BOLD}ERROR{Colors.RESET}")
                overall_rc = 1
                err_head = "\n".join(smart_e.splitlines()[
                                     :8]) if smart_e else ""
                if err_head:
                    print(f"    {Colors.RED}" +
                          indent(err_head, 4) + Colors.RESET)

        print_line()

    return overall_rc


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
