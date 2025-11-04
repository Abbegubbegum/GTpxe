#!/bin/sh

set -e

# Disable systemd-resolved (if it exists - Armbian may not have it)
systemctl disable systemd-resolved 2>/dev/null || true
systemctl stop systemd-resolved 2>/dev/null || true

# Add DNS server (Armbian uses systemd-resolved less often, but this is still safe)
rm -f /etc/resolv.conf
echo "nameserver 1.1.1.1" > /etc/resolv.conf

# Update and install necessary packages
apt update
apt install -y dnsmasq python3-venv python3-pip

# Make the server directories
mkdir -p /srv/tftp/
mkdir -p /srv/www/alpine/boot/x86_64
mkdir -p /srv/www/alpine/boot/x86
mkdir -p /srv/www/alpine/apks/x86_64
mkdir -p /srv/www/alpine/apks/x86

# Configure dnsmasq
cp ./conf/dnsmasq.conf /etc/dnsmasq.conf

# Setup python http server
cp -r ./python /srv/
python3 -m venv /srv/python/.venv
/srv/python/.venv/bin/pip install --upgrade pip
/srv/python/.venv/bin/pip install flask gunicorn

cp ./conf/pxe-http.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now pxe-http

# Download alpine images
# We get these files from the netboot since they have NiC drivers included
#64-bit
wget -P /srv/www/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/vmlinuz-lts
wget -P /srv/www/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/initramfs-lts
wget -P /srv/www/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/modloop-lts
#32-bit
wget -P /srv/www/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/vmlinuz-lts
wget -P /srv/www/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/initramfs-lts
wget -P /srv/www/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/modloop-lts

# Download and extract necessary alpine apks from the .iso images
# This we have to get from the regular .iso install
#64-bit
wget http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/alpine-standard-3.22.0-x86_64.iso
mkdir -p /mnt/alpine-x64
mount -o loop alpine-standard-3.22.0-x86_64.iso /mnt/alpine-x64
cp -a /mnt/alpine-x64/apks/x86_64/* /srv/www/alpine/apks/x86_64/
umount /mnt/alpine-x64
rm alpine-standard-3.22.0-x86_64.iso

#32-bit
wget http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/alpine-standard-3.22.0-x86.iso
mkdir -p /mnt/alpine-x86
mount -o loop alpine-standard-3.22.0-x86.iso /mnt/alpine-x86
cp -a /mnt/alpine-x86/apks/x86/* /srv/www/alpine/apks/x86/
umount /mnt/alpine-x86
rm alpine-standard-3.22.0-x86.iso

# Copy over overlay files
cp -r ./boot/* /srv/

# Configure network interfaces to switch from setup network (192.168.150.x) to PXE server network (192.168.200.x)
# Armbian uses netplan for network configuration
# Backup the current netplan configuration
mv /etc/netplan/*.yaml /etc/netplan/01-netcfg.yaml.bak 2>/dev/null || true

# Create new netplan configuration for PXE server network (192.168.200.1)
cp ./conf/armbian/01-netcfg.yaml /etc/netplan/

# Set correct permissions for netplan (must be 600 or 644 with no world-readable secrets)
chmod 600 /etc/netplan/01-netcfg.yaml

# Start dnsmasq
systemctl restart dnsmasq
systemctl enable dnsmasq

# Apply netplan configuration
netplan apply