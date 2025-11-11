#!/bin/sh

set -e

# Parse command-line arguments
SERVER_TYPE="rock"  # Default to rock

print_usage() {
    echo "Usage: $0 [--type <rock|ubuntu>]"
    echo "  --type rock    : Setup Armbian Rock 4 as DHCP+DNS+TFTP PXE server (default)"
    echo "  --type ubuntu  : Setup Ubuntu as TFTP-only PXE server (no DHCP/DNS)"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --type)
            SERVER_TYPE="$2"
            shift 2
        ;;
        -h|--help)
            print_usage
        ;;
        *)
            echo "Unknown option: $1"
            print_usage
        ;;
    esac
done

if [ "$SERVER_TYPE" != "rock" ] && [ "$SERVER_TYPE" != "ubuntu" ]; then
    echo "Error: Invalid server type '$SERVER_TYPE'. Must be 'rock' or 'ubuntu'."
    print_usage
fi

echo "Installing PXE server with type: $SERVER_TYPE"

# Update and install necessary packages
apt update

if [ "$SERVER_TYPE" = "rock" ]; then
    # Rock: Install dnsmasq for DHCP+DNS+TFTP and netplan for network configuration
    apt install -y dnsmasq netplan.io python3-venv python3-pip
else
    # Ubuntu: Install standalone TFTP server (no DHCP/DNS)
    apt install -y tftpd-hpa python3-venv python3-pip
fi

# Make the server directories
mkdir -p /srv/tftp/
mkdir -p /srv/http/alpine/boot/x86_64
mkdir -p /srv/http/alpine/boot/x86
mkdir -p /srv/http/alpine/apks/x86_64
mkdir -p /srv/http/alpine/apks/x86

# Copy over the server files
cp -r ./srv/* /srv/

# Set permissions for /srv directory to allow all users to write
chmod -R 777 /srv

# Setup python http server
python3 -m venv /srv/python/.venv
/srv/python/.venv/bin/pip install --upgrade pip
/srv/python/.venv/bin/pip install flask gunicorn

cp ./conf/pxe-http.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now pxe-http

# Download alpine images
# We get these files from the netboot since they have NiC drivers included
#64-bit
wget -P /srv/http/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/vmlinuz-lts
wget -P /srv/http/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/initramfs-lts
wget -P /srv/http/alpine/boot/x86_64 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/netboot/modloop-lts
#32-bit
wget -P /srv/http/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/vmlinuz-lts
wget -P /srv/http/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/initramfs-lts
wget -P /srv/http/alpine/boot/x86 http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/netboot/modloop-lts

# Download and extract necessary alpine apks from the .iso images
# This we have to get from the regular .iso install
#64-bit
wget http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/alpine-standard-3.22.0-x86_64.iso
mkdir -p /mnt/alpine-x64
mount -o loop alpine-standard-3.22.0-x86_64.iso /mnt/alpine-x64
cp -a /mnt/alpine-x64/apks/x86_64/* /srv/http/alpine/apks/x86_64/
umount /mnt/alpine-x64
rm alpine-standard-3.22.0-x86_64.iso

#32-bit
wget http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86/alpine-standard-3.22.0-x86.iso
mkdir -p /mnt/alpine-x86
mount -o loop alpine-standard-3.22.0-x86.iso /mnt/alpine-x86
cp -a /mnt/alpine-x86/apks/x86/* /srv/http/alpine/apks/x86/
umount /mnt/alpine-x86
rm alpine-standard-3.22.0-x86.iso

# Configure network and start services based on server type
if [ "$SERVER_TYPE" = "rock" ]; then
    # Rock: Configure network interfaces to switch from setup network (192.168.150.x) to PXE server network (192.168.200.x)
    # Armbian uses netplan for network configuration
    # Remove the old network configs
    rm -rf /etc/netplan/*.yaml 2>/dev/null || true
    
    # Create new netplan configuration for PXE server network (192.168.200.1)
    cp ./conf/armbian/01-netcfg.yaml /etc/netplan/
    
    # Set correct permissions for netplan (must be 600 or 644 with no world-readable secrets)
    chmod 600 /etc/netplan/01-netcfg.yaml
    
    # Apply netplan configuration
    netplan apply
    
    cp ./conf/armbian/dnsmasq.conf /etc/dnsmasq.conf
    
    # Disable systemd-resolved to avoid port 53 conflict with dnsmasq
    # This is done last, after all downloads and installations are complete
    systemctl disable systemd-resolved 2>/dev/null || true
    systemctl stop systemd-resolved 2>/dev/null || true
    
    # Start dnsmasq (DHCP+DNS+TFTP)
    systemctl restart dnsmasq
    systemctl enable dnsmasq
    
    
    echo ""
    echo "==================================================================="
    echo "Rock 4 PXE Server setup complete!"
    echo "The server will now operate on network 192.168.200.0/24"
    echo "Server IP: 192.168.200.1"
    echo "Services running: DHCP, DNS, TFTP, HTTP"
    echo "==================================================================="
else
    
    cp ./conf/ubuntu/tftpd-hpa /etc/default/
    # Ubuntu: No network configuration changes needed
    # Start standalone TFTP server
    systemctl restart tftpd-hpa
    systemctl enable tftpd-hpa
    
    echo ""
    echo "==================================================================="
    echo "Ubuntu PXE Server setup complete!"
    echo "Network configuration unchanged (using existing LAN settings)"
    echo "Services running: TFTP, HTTP"
    echo "Note: Configure your DHCP server to point to this server as"
    echo "      the PXE boot server (next-server option)"
    echo "==================================================================="
fi