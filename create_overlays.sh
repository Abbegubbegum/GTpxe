#!/bin/sh
# This script creates the overlay files using the existing overlay files in clients/overlays/x/etc
# This is because what changes in the overlay files is only the scripts and home directory, the rest
# of the files stay the same.

set -eu

./build_client_packages.sh

cd client

rm -rf overlays/x86_64
rm -rf overlays/x86

mkdir -p overlays/x86_64
mkdir -p overlays/x86

tar -xzf overlays/x86_64.apkovl.tar.gz -C overlays/x86_64
tar -xzf overlays/x86.apkovl.tar.gz -C overlays/x86

# Remove the existing home directory. (everything within will be replaced)
rm -rf overlays/x86_64/home/*
rm -rf overlays/x86/home/*

# Remove the existing local.d scripts.
rm -rf overlays/x86_64/etc/local.d/*
rm -rf overlays/x86/etc/local.d/*

# Copy the new local.d scripts.
cp -r startup/* overlays/x86_64/etc/local.d/
cp -r startup/* overlays/x86/etc/local.d/

# Copy over the packages to the home directory.
cp -r packages/x86_64/* overlays/x86_64/home
cp -r packages/x86/* overlays/x86/home

# Remove the startup scripts and shell script from the home directory since its not used when not installing.
rm -rf overlays/x86_64/home/startup
rm -rf overlays/x86/home/startup

rm -rf overlays/x86_64/home/setup_client.sh
rm -rf overlays/x86/home/setup_client.sh


# Compress the overlays into tar.gz files.
cd overlays/x86_64
tar -czf ../x86_64.apkovl.tar.gz .
cd ../x86
tar -czf ../x86.apkovl.tar.gz .
cd ../../..
cp client/overlays/x86_64.apkovl.tar.gz server/package/boot/x86_64/localhost.apkovl.tar.gz
cp client/overlays/x86.apkovl.tar.gz server/package/boot/x86/localhost.apkovl.tar.gz
