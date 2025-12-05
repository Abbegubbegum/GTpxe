#!/bin/sh
# This script creates a "client" package that can then be sent to a client to setup the apkovl.
# This will contatin the diagnostic scripts and a script to setup everything for the overlay.

set -eu

cd client

cd input_device_test
./build.sh

cd ../screen_test
./build.sh

cd ..

rm -rf packages/x86_64
rm -rf packages/x86

mkdir -p packages/x86_64/binaries
mkdir -p packages/x86/binaries

cp -r startup packages/x86_64/
cp -r startup packages/x86/

cp input_device_test/build/input_device_test_x86_64 packages/x86_64/binaries/input_device_test
cp input_device_test/build/input_device_test_i686 packages/x86/binaries/input_device_test

cp screen_test/build/screen_test_x86_64 packages/x86_64/binaries/screen_test
cp screen_test/build/screen_test_i686 packages/x86/binaries/screen_test

cp setup_client.sh packages/x86_64/
cp setup_client.sh packages/x86/

cp -r scripts packages/x86_64/
cp -r scripts packages/x86/

cp -r python packages/x86_64/
cp -r python packages/x86/

cp -r instructions.txt packages/x86_64/
cp -r instructions.txt packages/x86/