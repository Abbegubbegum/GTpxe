#!/bin/sh

set -e

# Disable systemd-resolved
systemctl disable systemd-resolved
systemctl stop systemd-resolved
rm -f /etc/resolv.conf
echo "nameserver 1.1.1.1" > /etc/resolv.conf

# Update and install necessary packages
apt update
apt install -y dnsmasq apache2

# Make the server directories
mkdir -p /srv/tftp/
mkdir -p /srv/www/alpine/boot/x86_64
mkdir -p /srv/www/alpine/boot/x86
mkdir -p /srv/www/alpine/apks/x86_64
mkdir -p /srv/www/alpine/apks/x86

# Configure dnsmasq
cp ./conf/dnsmasq.conf /etc/dnsmasq.conf

# Configure apache
rm -rf /var/www/html
ln -s /srv/www /var/www/html
systemctl restart apache2
systemctl enable apache2

# Download alpine images
#64-bit
wget -P /srv/www/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/vmlinuz-lts
wget -P /srv/www/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/initramfs-lts
wget -P /srv/www/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/modloop-lts
#32-bit
wget -P /srv/www/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/vmlinuz-lts
wget -P /srv/www/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/initramfs-lts
wget -P /srv/www/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/modloop-lts

# Download and extract necessary alpine apks from the .iso images
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
cp -r ./boot/* /srv/www/alpine/boot/

# Copy over ipxe file
cp ./ipxe/boot.ipxe /srv/tftp/boot.ipxe

# Configure network interfaces
mv /etc/network/interfaces.d/eth0 /etc/network/interfaces.d/eth0.bak
cp ./conf/interfaces/* /etc/network/interfaces.d/

# Start dnsmasq
systemctl restart dnsmasq
systemctl enable dnsmasq

# Restart networking to apply changes, which will drop the current ssh connection
systemctl restart networking