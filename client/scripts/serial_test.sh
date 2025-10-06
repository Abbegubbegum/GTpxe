#!/bin/sh
# serial_loopback_test.sh — robust loopback test for each serial port
set -eu

BAUDS="115200 9600"
TIMEOUT_SECONDS=1

# --- enumerate ports (skip non-existent) ---
ports() {
    for port in /dev/ttyS*; do
        # If the port exists, print it (return value basically)
        if ! stty -F "$port" -a >/dev/null 2>&1; then
            continue
        fi
        
        printf '%s\n' "$port"
    done
}

drain_port() {
    # clear a little pending input without blocking long
    timeout 0.2 dd if="$1" of=/dev/null bs=256 count=1 2>/dev/null || true
}

rc=0

found_ports=$(ports)

[ -n "$found_ports" ] || { echo "No serial ports found." >&2; exit 0; }

for port in $found_ports; do
    echo "Testing $port ..."
    success=0
    
    for baud in $BAUDS; do
        # raw, no echo/flow, ignore carrier, don't drop DTR on close
        if ! stty -F "$port" raw -echo -ixon -ixoff -crtscts clocal -hupcl ispeed "$baud" ospeed "$baud" 2>/dev/null; then
            echo "  stty failed at ${baud} baud"
            continue
        fi
        
        drain_port "$port"
        
        TEST="PROVA-$$-$(date +%s)"
        readlen=$(( ${#TEST} + 2 )) # token + CRLF
        tmp_file="$(mktemp)"
        
        # start the reader FIRST, bounded by timeout, into a temp file
        ( timeout "$TIMEOUT_SECONDS" head -c "$readlen" < "$port" > "$tmp_file" ) & rd=$!
        
        # small delay so the reader is definitely ready
        sleep 0.1
        
        # send the token with CRLF (widest compatibility)
        printf '%s\r\n' "$TEST" > "$port"
        
        # wait up to TIMEOUT_SECONDS+0.3s for reader, then stop it
        waited_ms=0
        limit_ms=$(( TIMEOUT_SECONDS * 1000 + 300 ))
        
        # While the reader is still running and we haven't waited too long
        while kill -0 "$rd" 2>/dev/null && [ "$waited_ms" -lt "$limit_ms" ]; do
            sleep 0.01
            waited_ms=$((waited_ms + 10))
        done
        
        # Kill the reader if it's still running
        kill "$rd" 2>/dev/null || true
        
        # Get what was read, stripping CRLF, and clean up
        got="$(tr -d '\r\n' < "$tmp_file")"
        rm -f "$tmp_file"
        
        if [ "$got" = "$TEST" ]; then
            echo "  OK: loopback matched at ${baud} baud."
            success=1
            break
        else
            echo "  No loop at ${baud} (got: ${got:-<nothing>})"
        fi
    done
    
    [ "$success" -eq 1 ] || rc=1
done

exit "$rc"
