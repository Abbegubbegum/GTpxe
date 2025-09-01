#!/bin/sh
# This script creates a "client" package that can then be sent to a client to setup the apkovl.
# This will contatin the diagnostic scripts and a script to setup everything for the overlay.

set -eu

cd client

rm -rf packages/x86_64
rm -rf packages/x86

mkdir -p packages/x86_64
mkdir -p packages/x86

cp -r startup packages/x86_64/
cp -r startup packages/x86/

cp keyboard_test/build/keyboard_test_x86_64 packages/x86_64/keyboard_test
cp keyboard_test/build/keyboard_test_i686 packages/x86/keyboard_test

cp setup_client.sh packages/x86_64/
cp setup_client.sh packages/x86/

cp -r scripts packages/x86_64/
cp -r scripts packages/x86/