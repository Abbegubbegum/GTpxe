#/bin/sh
# This script creates a "client" package that can then be sent to a client to setup the apkovl.
# This will contatin the diagnostic scripts and a script to setup everything for the overlay.

set -eu

cd client

mkdir -p packages/x86_64
mkdir -p packages/i686

cp -r startup packages/x86_64/startup
cp -r startup packages/i686/startup

cp keyboard_test/build/keyboard_test_x86_64 packages/x86_64/keyboard_test
cp keyboard_test/build/keyboard_test_i686 packages/i686/keyboard_test

cp setup_client.sh packages/x86_64/setup_client.sh
cp setup_client.sh packages/i686/setup_client.sh