#!/bin/sh

set -eu

PORTS="$(ls /dev/ttyS* 2>/dev/null)" || true

[ -z "$PORTS" ] && {
    echo "No serial ports found."
    exit 1
}

rc=0

for port in $PORTS; do
    echo "Testing $port..."

    # Set up the serial port
    # Explanation of flags are in the readme
    stty -F "$port" 9600 raw -echo -ixon -ixoff -crtscts clocal min 0 time 10
    
    if ! exec 3<>"$port"; then
        echo "Failed to open $port"
        rc=1
        continue
    fi
    
    # Flush any existing data
    dd of=/dev/null bs=256 count=1 2>/dev/null <&3 || true

    test_str="PROVA-$(date +%s)"

    # Write test data
    printf "%s\n" "$test_str" > "$port"

    # Read back the data
    got="$(dd if="$port" bs=1 count=$((${#test_str} + 1)) 2>/dev/null | tr -d '\r\n')"

    if [ "$got" = "$test_str" ]; then
        echo "Serial port $port is functioning correctly."
    else
        echo "Serial port $port failed the test."
        rc=1
    fi
done