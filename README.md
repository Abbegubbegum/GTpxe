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

4. Revert some settings in setup-alpine

-   Mainly remove the networking if necessary
-   Also remove the apk repos so it doesn't try to fetch during boot, slowing down the boot

Do this by when the APK mirror option comes up, choose edit in text editor and put # infront of the 2 online repos

5. Enable the local service with 'rc-update add local default'
   We do this now because if we do it before, when we run setup-alpine, diagnostics start because it restarts

6. Create the backup using 'lbu pkg /home/ssh'
7. Copy over the .apkovl file to the pxe server or your host pc

MAKE SURE TO COPY IT TO THE CORRECT ARCHITECTURE FOLDER, x86 or x86_64

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ssh@192.168.150.105:~/localhost.apkovl.tar.gz /srv/www/alpine/boot/x86_64/
```

or

```sh
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ssh@192.168.150.105:~/localhost.apkovl.tar.gz server/boot/x86_64/
```

---

## Update overlays on PXE server
To update the overlay files on the pxe server that is persistant on the internal network

1. Run ./create_overlay.sh



---

## Setup PXE Server on Rock 4

1. Download the official debian cli os and flash it to the simcard
   https://github.com/radxa-build/rock-4se/releases

On Linux:

```sh
xzcat rock-4se_debian_bullseye_cli_b38.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

(Replace /dev/sdX with what your sd card device is)

2. Startup the Rock 4 and enable ssh
   Connect the sim-card, an ethernet cable and mouse & keyboard and then connect power to start it up.

Login with user/pwd: Rock/Rock

setup the networking

```sh
sudo nano /etc/network/interfaces.d/eth0
```

```ini
auto eth0
iface eth0 inet static
    address 192.168.150.30
    netmask 255.255.255.0
    gateway 192.168.150.254
    dns-nameservers 1.1.1.1
```

```sh
sudo systemctl restart networking
sudo systemctl enable ssh
sudo systemctl start ssh
```

Now you can connect to the Rock with SSH with the user Rock@192.168.150.30

3. Setup the DHCP, tftp and http servers
   Copy over the server/package folder and run the script

```sh
scp -r ./server/package rock@192.168.150.30:~/
ssh rock@192.168.150.30
cd package
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

## Explanation of ssty flags (by chatgpt)

You bet—here’s what each stty bit in the line does (this is POSIX/BusyBox-compatible):

-   -F "$p" → operate on the device file $p (not on your stdin TTY).

-   115200 → set both input & output speed to 115200 baud.

-   cs8 → 8 data bits per character.

-   -cstopb → one stop bit (clears cstopb, which would mean 2 stop bits).

-   -parenb → disable parity (no even/odd parity bit).

-   -ixon → disable software flow control on input (ignore XON/XOFF characters like Ctrl-S/Ctrl-Q).

-   -ixoff → disable software flow control on output (don’t transmit XON/XOFF).

-   -crtscts → disable hardware RTS/CTS flow control. (Use crtscts if you want hardware flow control.)

-   -echo → don’t echo back typed/received characters locally.

-   -icanon → non-canonical (“raw-ish”) mode: input isn’t line-buffered and special edit keys aren’t interpreted.

-   -opost → disable output post-processing (e.g., no automatic \n → \r\n translation).

-   clocal → ignore modem control lines (DCD/CTS/DSR); treat the line as “local” so opens/IO don’t depend on carrier.

-   min 0 / time 10 → read timeout settings that only apply in non-canonical mode:

-   VMIN=0, VTIME=10 (tenths of a second) ⇒ a read() returns immediately with whatever is available, or waits up to ~1.0 s if nothing is available, then returns (possibly with 0 bytes).

Why these matter for your loopback test:

-   Ensures a known 8N1, no-flow-control, raw path so your bytes go out exactly as sent.

-   Prevents \n from turning into \r\n (-opost), which would break exact string compares.

-   The min/time combo gives you a clean per-read timeout without needing external timeout.

---

## License

This diagnostic tool is provided as-is under the MIT License. Modify and adapt as needed for your environment.

---

## Contact

For support or contributions, please contact albin.nojback@gmail.com
