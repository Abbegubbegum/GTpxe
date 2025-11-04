# Alpine PXE Diagnostic Tool

This project provides a lightweight, PXE-bootable diagnostic Linux environment based on Alpine Linux. It boots entirely into RAM and automatically runs hardware diagnostics to verify essential system components are working correctly.

---

## Features

-   **Memory & CPU Check**

    -   Quick 30-second test using `stress-ng` to verify CPU cores and RAM functionality
    -   Optional quick RAM sanity check using `memtester`
    -   Reports CPU and memory information via `lscpu` and `free`

-   **USB Subsystem Test**

    -   Detects connected USB devices with `lsusb`
    -   Confirms USB controller and devices are recognized
    -   Can be scripted to detect specific USB peripherals

-   **Display Test**

    -   Visual color pattern tests on framebuffer using `fbi` (no GUI required)
    -   Terminal color block test using ANSI escape sequences for basic visual confirmation
    -   Optional GUI-based display test with Xorg and lightweight desktop environment for advanced testing (if needed)

-   **Touchpad & Keyboard Test (No GUI Required)**

    -   Uses `evtest` to read raw input events from the touchpad and keyboard devices
    -   Confirms movement, taps, and key presses
    -   Includes scriptable detection and event logging for automated testing

-   **Keyboard Basic Test**
    -   Simple keypress detection via terminal input or evtest

---

## Included Packages

| Package                                              | Purpose                                            |
| ---------------------------------------------------- | -------------------------------------------------- |
| `stress-ng`                                          | CPU and memory stress and diagnostics              |
| `memtester`                                          | RAM sanity check                                   |
| `lscpu`                                              | CPU information                                    |
| `free`                                               | Memory information                                 |
| `usbutils`                                           | USB device detection (`lsusb`)                     |
| `fbi`                                                | Framebuffer image viewer for display tests         |
| `evtest`                                             | Input device event monitoring (touchpad, keyboard) |
| `busybox-extras`                                     | Additional useful tools and utilities              |
| `bash` (optional)                                    | For scripting convenience                          |
| `xorg-server`, `xf86-video-vesa`, `xfce4` (optional) | GUI environment for advanced display/input tests   |

---

## How It Works

1. **PXE Boot**  
   The system boots Alpine Linux entirely into RAM via PXE, using the provided kernel and initramfs.

2. **Auto Startup Script**  
   A startup script runs automatically on boot, performing hardware diagnostics:

    - Runs CPU and RAM quick tests (`stress-ng`, `memtester`)
    - Scans and lists USB devices (`lsusb`)
    - Performs a visual display test (color blocks or images via `fbi`)
    - Monitors touchpad and keyboard events with `evtest`

3. **Results Reporting**  
   Test results are output to the console and can be logged for later analysis.

---

## Create Alpine Overlay file (.apkovl)

This is a file that is a compressed version of the file system.
Then during the pxe boot, this file can be applied to the file system.
This will contain all of our scripts, diagnostic packages and system settings.

1. Start an Alpine machine
2. Run 'setup-alpine' to set all of the necessary settings

-   keyboard se > se
-   A network connection is required for the setup to download the packages
-   empty password on the root user
-   add an ssh user to copy the .apkovl file over scp
-   The rest of the options, leave as default

3. Create and send the correct client package

-   Run build_client_packages.sh to create the "packages"
-   Send over the correct package to the alpine client

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r client/packages/x86_64/* ssh@192.168.150.105:~
```

-   Then run the setup_client script on the alpine machine
    it will be located in /home/ssh

7. Copy over the .apkovl file to the pxe server or your host pc

MAKE SURE TO COPY IT TO THE CORRECT ARCHITECTURE FOLDER, x86 or x86_64

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ssh@192.168.150.105:~/localhost.apkovl.tar.gz ./client/overlays/x86_64.apkovl.tar.gz
```

or

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ssh@192.168.150.105:~/localhost.apkovl.tar.gz ./client/overlays/x86.apkovl.tar.gz
```

---

## Update overlays on PXE server

To update the overlay files on the pxe server that is persistant on the internal network

1. Run ./create_overlays.sh

2. Copy over the files

```sh
scp server/package/boot/x86_64/* tele@192.168.150.62:/srv/www/alpine/boot/x86_64/
scp server/package/boot/x86/* tele@192.168.150.62:/srv/www/alpine/boot/x86/
```

---

## Setup PXE Server on Rock 4

1. Download the ubuntu armbian community image for the Rock 4SE and flash it to an SD card
   https://github.com/armbian/community/releases/download/25.11.0-trunk.413/Armbian_community_25.11.0-trunk.413_Rock-4se_trixie_current_6.12.57_minimal.img.xz

On Linux:

```sh
#Identify where the SD card is
lsblk

xzcat rock-4se_debian_bullseye_cli_b38.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

(Replace /dev/sdX with what your sd card device is)

2. Startup the Rock 4 and enable ssh
   Connect the sim-card, an ethernet cable and mouse & keyboard and then connect power to start it up.

Setup root password 'opled' and user tele/opled

setup the networking and keyboard with

```sh
armbian-config
```

I use static ip 192.168.150.30 for the setup
After you set the ip, you have to select "drop the fallback DHCP configuration" to apply the settings

3. Start ssh

```sh
sudo systemctl enable ssh
sudo systemctl start ssh
```

Now you can connect to the Rock with SSH with the user tele@192.168.150.30

3. Setup the DHCP, tftp and http servers
   Copy over the server/package folder and run the script

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r ./server/package tele@192.168.150.30:~/
ssh rock@192.168.150.30
cd /home/tele/package
sudo chmod +x ./setup_server.sh
sudo ./setup_server.sh
```

---

## Setup PXE Server

I used this as a guide: https://www.apalrd.net/posts/2022/alpine_pxe/

1. Get any Linux distro you please

2.

3. Copy the boot files the server

-   On the source pc, run
-   'scp -r ./server/boot tele@192.168.150.62:~/'
-   On the server, run
-   'sudo mv /home/tele/boot /srv/tftp/images/alpine-custom'

---

## Usage

-   PXE boot your target machine from the Alpine diagnostic environment.
-   The diagnostics run automatically and display results on screen.
-   For interactive testing, you can connect via keyboard and observe output or interact with input tests.

---

## Customization

-   You can add or remove diagnostic scripts by modifying the initramfs or the auto-start scripts.
-   Display test images can be customized and added to the PXE image.
-   Additional hardware tests (serial ports, network interfaces, disks) can be scripted similarly.

---

## Requirements

-   PXE boot server with TFTP and DHCP services configured.
-   Alpine Linux kernel (`vmlinuz-lts`) and initramfs (`initramfs-lts`) placed in the TFTP root.
-   Network connectivity for initial Alpine package downloads or prebuilt custom initramfs including required packages.
-   Target hardware supporting PXE boot.

---

## License

This diagnostic tool is provided as-is under the MIT License. Modify and adapt as needed for your environment.

---

## Contact

For support or contributions, please contact albin.nojback@gmail.com
