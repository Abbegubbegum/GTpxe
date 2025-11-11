# Alpine PXE Diagnostic Tool

This project provides a lightweight, PXE-bootable diagnostic Linux environment based on Alpine Linux. It boots entirely into RAM and automatically runs hardware diagnostics to verify essential system components are working correctly.

---

## Features

-   **Memory & CPU Testing**

    -   30-second stress test using `stress-ng` with CPU and RAM load (75% memory utilization)
    -   Dedicated RAM sanity check with `memtester` (100 MB, single pass)
    -   Validates CPU core functionality and memory integrity

-   **Storage Health Testing**

    -   Full SMART diagnostics for NVMe drives using `nvme-cli` (self-test + health log parsing)
    -   SATA/SAS drive testing with `smartctl` (short self-test + attribute analysis)
    -   USB storage support with SAT protocol fallback
    -   Detects media errors, reallocated sectors, and wear indicators

-   **USB Port Testing (Custom Hardware Required)**

    -   Data throughput test via bulk loopback transfer (default minimum: 1.4 Mbps)
    -   VBUS power load testing across 8 current levels
    -   Voltage droop, ripple, and recovery time measurement
    -   Requires custom USB test fixture (VID: 0x1209, PID: 0x4004)
    -   JSON report generation for detailed analysis

-   **Serial Port Testing**

    -   Hardware loopback test for all `/dev/ttyS*` ports
    -   Tests both 115200 and 9600 baud rates
    -   Token-based echo validation

-   **Display Testing**

    -   Native DRM framebuffer rendering with double buffering
    -   Custom Rust application using direct kernel mode-setting
    -   Visual test patterns for screen validation
    -   No X11/GUI environment required

-   **Keyboard & Touchscreen Testing**

    -   Interactive Rust TUI application with Swedish keyboard layout support
    -   Raw input event capture via `/dev/input/event*`
    -   Full keyboard layout visualization with color-coded feedback
    -   4-point touchscreen calibration and validation
    -   Hardware-specific machine detection (e.g., DATOR_BB_FÄLT)

-   **Audio Testing**

    -   Speaker output test with 880 Hz sine wave tone
    -   ALSA test sound playback
    -   Automatic volume configuration and unmute

-   **System Monitoring**

    -   Battery status and health reporting via `acpi`
    -   Temperature sensor readout from all thermal zones
    -   Real-time thermal monitoring in degrees Celsius

-   **Early Exit Support**

    -   Background keypress monitoring allows graceful test termination
    -   Press 'q' at any time to abort diagnostics

---

## Included Packages

| Package         | Purpose                                                 |
| --------------- | ------------------------------------------------------- |
| `stress-ng`     | CPU and memory stress testing                           |
| `memtester`     | RAM integrity validation                                |
| `smartmontools` | SATA/SAS SMART diagnostics (`smartctl`)                 |
| `nvme-cli`      | NVMe health monitoring and self-test                    |
| `util-linux`    | Block device utilities (`lsblk`, etc.)                  |
| `python3`       | Diagnostic script runtime environment                   |
| `py3-usb`       | Python USB library for custom hardware testing          |
| `acpi`          | Battery and power status reporting                      |
| `alsa-utils`    | Audio testing tools (`amixer`, `speaker-test`, `aplay`) |

---

## How It Works

1. **PXE Boot**
   The system boots Alpine Linux entirely into RAM via PXE, loading the kernel, initramfs, and custom `.apkovl.tar.gz` overlay containing all diagnostic tools and scripts.

2. **Automated Diagnostic Sequence**
   The startup script (`run_diagnostic.start`) executes automatically on boot in the following order:

    1. CPU and memory stress test (30 seconds with `stress-ng`)
    2. RAM integrity test (100 MB with `memtester`)
    3. Storage health scan (NVMe/SATA SMART diagnostics)
    4. USB port testing (requires custom test fixture)
    5. Battery status display
    6. Temperature sensor monitoring
    7. Serial port loopback tests
    8. Keyboard test (interactive Rust TUI on separate VT)
    9. Display test (Rust DRM application on separate VT)
    10. Speaker/audio output test

3. **Results Reporting**
    - All output is displayed on `/dev/tty1` and logged to `/root/diagnostic_report.txt`
    - USB test generates detailed JSON report at `/root/usb_report.json`
    - Tests marked as mandatory will halt execution on failure
    - Non-critical tests (e.g., serial ports) continue on error

---

## Create Alpine Overlay File (.apkovl)

The `.apkovl.tar.gz` file is a compressed overlay containing all diagnostic scripts, packages, and system settings. During PXE boot, this overlay is applied to the Alpine filesystem running in RAM.

### Step 1: Prepare Alpine Virtual Machine

1. Start an Alpine Linux machine (VM or physical)
2. Run `setup-alpine` and configure the following settings:
    - **Keyboard layout**: `se` > `se`
    - **Network**: Configure with internet access (required for package downloads)
    - **Root password**: Leave empty (press Enter)
    - **User account**: Create `ssh` user for file transfers via SCP
    - **Other options**: Leave as default

### Step 2: Build and Transfer Client Package

On your **host computer**, build the client package:

```sh
./build_client_packages.sh
```

Transfer the appropriate architecture package to the Alpine machine (replace `192.168.150.105` with your Alpine VM's IP):

**For x86_64:**

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r client/packages/x86_64/* ssh@192.168.150.105:~
```

**For x86 (32-bit):**

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r client/packages/x86/* ssh@192.168.150.105:~
```

### Step 3: Run Setup Script on Alpine

On the **Alpine machine**, execute the setup script:

```sh
chmod +x /home/ssh/setup_client.sh
/home/ssh/setup_client.sh
```

This script installs all diagnostic tools and configures the system to generate the overlay file.

### Step 4: Copy Overlay Back to Host

On your **host computer**, copy the generated `.apkovl.tar.gz` file to the correct architecture folder:

**For x86_64:**

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ssh@192.168.150.105:~/localhost.apkovl.tar.gz ./client/overlays/x86_64.apkovl.tar.gz
```

**For x86 (32-bit):**

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ssh@192.168.150.105:~/localhost.apkovl.tar.gz ./client/overlays/x86.apkovl.tar.gz
```

> **Important**: Ensure you copy to the correct architecture folder matching your target hardware.

---

## Update Overlays on PXE Server

Use this procedure to update the overlay files on your production PXE server.

### Step 1: Create Overlays

On your **host computer**, run the overlay creation script:

```sh
./create_overlays.sh
```

This packages the boot files for both architectures into `server/package/boot/`.

### Step 2: Deploy to PXE Server

Copy the overlay files to your PXE server (replace `192.168.150.62` with your server's IP):

```sh
scp server/package/srv/http/alpine/boot/x86_64/* tele@192.168.150.62:/srv/http/alpine/boot/x86_64/
scp server/package/srv/http/alpine/boot/x86/* tele@192.168.150.62:/srv/http/alpine/boot/x86/
```

The overlays will be served via HTTP during PXE boot.

---

## Setup PXE Server on Rock 4SE

This setup configures a Rock 4SE single-board computer as a complete PXE server with DHCP, TFTP, and HTTP services.

### Step 1: Flash Armbian to SD Card

Download the Armbian community image for Rock 4SE:

```
https://github.com/armbian/community/releases/download/25.11.0-trunk.413/Armbian_community_25.11.0-trunk.413_Rock-4se_trixie_current_6.12.57_minimal.img.xz
```

**On Linux**, flash the image to an SD card:

```sh
# Identify your SD card device
lsblk

# Flash the image (replace /dev/sdX with your SD card device)
xzcat Armbian_community_25.11.0-trunk.413_Rock-4se_trixie_current_6.12.57_minimal.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

> **Warning**: Double-check the device path! Using the wrong device will destroy data.

### Step 2: Initial Boot and Configuration

1. Insert the SD card, connect ethernet cable, HDMI, and keyboard, then power on the Rock 4SE
2. On first boot, you'll be prompted to create accounts:

    - **Root password**: `opled`
    - **User**: `tele` with password `opled`

3. Configure network and keyboard layout:

```sh
armbian-config
```

Navigate to **Network** settings and configure:

-   **Static IP**: `192.168.150.30` (or your preferred IP)
-   After setting the IP, select **"Drop the fallback DHCP configuration"** to apply changes

Navigate to **Keyboard Layout** settings and configure:

-   **Keyboard Layout**: `Swedish > Swedish`, the rest default

### Step 3: Enable SSH

Start and enable the SSH service:

```sh
systemctl enable ssh
systemctl start ssh
```

You can now connect remotely to: `tele@192.168.150.30`

### Step 4: Deploy PXE Server Software

**On your host computer**, copy the server package to the Rock:

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r ./server/package tele@192.168.150.30:~/
```

**On the Rock 4SE** , run the setup script:

```sh
cd /home/tele/package
chmod +x setup_server.sh
./setup_server.sh
```

This script installs and configures:

-   **dnsmasq** (DHCP + TFTP server)
-   **lighttpd** (HTTP server for Alpine overlay files)
-   **iPXE** boot files and configuration

---

## Setup PXE Server on Ubuntu (TFTP + HTTP Only, No DHCP)

Use this setup if you already have an existing DHCP server and only need TFTP and HTTP services for PXE boot.

### Step 1: Prepare Ubuntu Server

1. Install Ubuntu Server on your target machine
2. Configure networking with internet access
3. Create user accounts as needed
4. Enable SSH if not already active:

```sh
sudo systemctl enable ssh
sudo systemctl start ssh
```

### Step 2: Deploy and Run Setup Script

**On your host computer**, copy the server package (replace `192.168.150.62` with your Ubuntu server's IP):

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r ./server/package tele@192.168.150.62:~/
```

**On the Ubuntu server** (via SSH), run the setup script with the `--type ubuntu` flag:

```sh
cd /home/tele/package
sudo chmod +x ./setup_server.sh
sudo ./setup_server.sh --type ubuntu
```

> **Note**: The `--type ubuntu` flag configures only TFTP and HTTP services. You must configure your existing DHCP server to point to this server's IP for PXE boot (DHCP option 66 for TFTP server, option 67 for boot filename).

---

## Usage

### Running Diagnostics on Target Hardware

1. **Enable Network Boot**

    - Enter BIOS/UEFI settings on the target computer
    - Enable PXE boot (also called Network Boot or LAN Boot)
    - Set network boot as the first boot device or use the boot menu

2. **Connect to Network**

    - Connect the target computer to the same network as your PXE server via ethernet cable
    - Power on or reboot the computer

3. **Automatic Boot Process**

    - The system will obtain an IP address via DHCP
    - Download and boot the Alpine Linux kernel and initramfs
    - Load the diagnostic overlay from the HTTP server
    - Automatically start the diagnostic sequence

4. **Observe Test Results**

    - All output is displayed on the primary console (`/dev/tty1`)
    - Tests run automatically in sequence
    - Interactive tests (keyboard/screen) will prompt for user input
    - Press **'q'** at any time to abort the diagnostics

5. **Review Reports**
    - Main diagnostic log: `/root/diagnostic_report.txt`
    - USB test JSON report: `/root/usb_report.json`
    - Reports are available in RAM until reboot

### Test Outcomes

-   **Pass**: All mandatory tests complete successfully
-   **Fail**: One or more mandatory tests fail (system halts)
-   **Warnings**: Non-critical tests (e.g., serial ports) may fail without stopping the sequence

---

## Customization

-   Add or modify diagnostic scripts in `client/startup/` and `client/scripts/`
-   Python diagnostic modules are located in `client/python/`
-   Rust TUI applications (keyboard/screen tests) can be rebuilt from source in `client/keyboard_test/` and `client/screen_test/`
-   Pre-built binaries for both x86_64 and i686 architectures are stored in `client/packages/{arch}/binaries/`
-   Machine-specific configurations (e.g., keyboard layouts) can be customized in the Rust source code
-   Rebuild the overlay with `./build_client_packages.sh` after making changes

---

## Requirements

### Server Requirements

-   PXE boot server with DHCP, TFTP, and HTTP services
-   Alpine Linux kernel (`vmlinuz-lts`) and initramfs (`initramfs-lts`)
-   Custom `.apkovl.tar.gz` overlay files for x86 and x86_64 architectures
-   Network connectivity for PXE boot infrastructure

### Target Hardware Requirements

-   PXE boot capability (network boot enabled in BIOS/UEFI)
-   Minimum 512 MB RAM (entire system runs in-memory)
-   Ethernet connection during boot

### Optional Hardware for Full Testing

-   Custom USB test fixture (VID: 0x1209, PID: 0x4004) for USB port diagnostics
-   Hardware loopback adapters for serial port testing
-   Storage devices (NVMe/SATA) for disk health testing

---

## License

This diagnostic tool is provided as-is under the MIT License. Modify and adapt as needed for your environment.

---

## Contact

For support or contributions, please contact albin.nojback@gmail.com
