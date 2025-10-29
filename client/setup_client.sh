#!/bin/ash
# shellcheck shell=dash

# Run this script to set up the client environment ready for the overlay.
# Run this after running setup-alpine and following the instructions in README.md

echo "Uncommenting APK community repositories..."
# This will remove the comment on the apk community repository, so that we can fetch community packages.
sed -i 's/^\s*#//' /etc/apk/repositories

echo "Creating local repository with necessary packages..."

ARCH=$(apk --print-arch)
echo "Detected Alpine architecture: $ARCH"

REPO_PATH="/var/custom-repo/main/$ARCH"

mkdir -p "$REPO_PATH"

cd "$REPO_PATH" || exit

apk update
apk fetch --recursive memtester stress-ng smartmontools nvme-cli util-linux python3 acpi py3-usb
apk index -o APKINDEX.tar.gz -- *.apk

lbu add /var/custom-repo/

# Because for some reason, pyusb fails to install
mkdir -p /var/py3-usb
cd /var/py3-usb || exit
apk fetch py3-usb

lbu add /var/py3-usb

echo "Moving diagnostic startup scripts to /etc/local.d/..."
# Add the diagnostic scripts
mv /home/ssh/startup/* /etc/local.d/
chmod +x /etc/local.d/*.start

echo "Adding /etc/local.d to overlay..."
lbu add /etc/local.d/

echo "Enabling local startup service..."
rc-update add local default

echo "Making binaries and script files executable..."
# Make the scripts executable
chmod +x /home/ssh/binaries/*
chmod +x /home/ssh/scripts/*

mv /home/ssh/scripts/restart_test.sh /root
lbu add /root

echo "Disabling online APK repositories..."
sed -i '/^http:\/\/dl-cdn/s|^|#|' /etc/apk/repositories

echo "Adding our own reposity..."
echo 'file:///var/custom-repo/main' >> /etc/apk/repositories

echo "Removing 'gateway' entries from /etc/network/interfaces..."
sed -i '/^\s*gateway\s\+/d' /etc/network/interfaces

echo "Creating overlay backup package..."
lbu pkg /home/ssh

echo "Setup complete. The client environment is now ready."
