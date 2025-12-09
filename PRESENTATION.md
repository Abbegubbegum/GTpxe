# 🔧 GTPxe

## Nätverksbaserad Automatisk Hårdvarudiagnostik

---

## 📋 Systemöversikt

### Vad är det?

Ett komplett diagnostikverktyg som bootar helt från nätverket - ingen installation krävs på target-datorn, allt körs i RAM.

### Arkitektur

-   **Client-server system** med PXE boot
-   **Alpine Linux** som OS-bas
-   **iPXE** för bootloader
-   **Custom Rust/Python** mjukvara för diagnostik
-   **Målhårdvara:** x86/x86_64 datorer (både BIOS och UEFI)

### Vad testas?

✓ CPU & RAM stress
✓ Disk health (NVMe/SATA SMART)
✓ USB ports (data + power)
✓ Serial ports
✓ Tangentbord & touchscreen
✓ Skärm (dead pixels, gradients)
✓ Ljud (speaker-test)
✓ Batteri & temperatur
✓ GPS (optional)

---

# 🖥️ DEL 1: SERVER-DELEN

## Server-arkitektur

### Plattformar

| Plattform              | Roll          | Tjänster                  |
| ---------------------- | ------------- | ------------------------- |
| **Rock 4SE** (Armbian) | Full server   | DHCP + TFTP + HTTP        |
| **Ubuntu**             | Delvis server | TFTP + HTTP (extern DHCP) |

### Nätverkstjänster

-   **dnsmasq** → DHCP + DNS + TFTP server
-   **Flask/gunicorn** → HTTP server för boot-kontroll och intelligent boot-logic

### Nätverkskonfiguration

-   **Rock 4SE:** `192.168.200.1/24` (dedikerat PXE-nätverk)
-   **Ubuntu:** `192.168.150.62` (befintligt nätverk)

### Boot-flöde

```
┌─────────┐    DHCP Request      ┌──────────────┐
│ Client  │ ───────────────────> │   dnsmasq    │
└─────────┘                      │ 192.168.200.1│
     │                           └──────────────┘
     │ TFTP: boot.kpxe/snponly.efi
     ▼
┌─────────────────────┐
│  iPXE Script laddar │
└─────────────────────┘
     │ HTTP GET
     ▼
┌────────────────────────────┐
│ Alpine kernel + initramfs  │
│   + localhost.apkovl.tar.gz│
└────────────────────────────┘
```

### Tekniska detaljer

-   **Arkitekturspecifik boot:** BIOS får `boot.kpxe`, UEFI får `snponly.efi`

---

## iPXE Boot Script & Intelligent Boot-kontroll

### Boot-sekvens

```
1. DHCP             → Hämta IP-adress
2. CPU-detektering  → x86 vs x86_64
3. Arkitekturval    → 5s timeout, default baserat på CPU
4. Flask-server     → GET /bootstage?mac=XX:XX:XX:XX
5. Boot-beslut      → memtest eller alpine diagnostik
6. Ladda Alpine     → kernel + initramfs + overlay
```

### Intelligent boot-logik (Flask)

```python
# pxe_http.py - Automatisk växling mellan test-typer
if entry.get("last_memtest_date") == today:
    return "set def_target alpine"  # Kör diagnostik
else:
    entry["last_memtest_date"] = today
    return "set def_target memtest"  # Kör memtest först
```

### Varför intelligent boot?

-   ✓ Varje MAC-adress diregeras till **memtest första gången per dag**
-   ✓ Därefter automatisk switch till **alpine diagnostik**
-   ✓ **Shelve-databas** sparar memtest-historik
-   ✓ Ingen manuell intervention krävs

---

## Server Setup & Deployment

### Setup-script funktioner

```bash
# Rock 4SE (full server med DHCP)
./setup_server.sh --type rock

# Ubuntu (TFTP+HTTP, extern DHCP)
./setup_server.sh --type ubuntu
```

### Vad gör scriptet?

1. **Paketinstallation** → dnsmasq, netplan, python3-venv, tftpd-hpa
2. **Katalogstruktur** → `/srv/tftp`, `/srv/http/alpine/boot/`
3. **Alpine-nedladdningar** → kernel, initramfs, modloop, APK-paket
4. **Nätverkskonfiguration** → Plattformspecifik (Rock/Ubuntu)
5. **Tjänststarter** → dnsmasq, pxe-http (Flask), tftpd-hpa

### Fördelar

-   ✓ **Automatiserad setup** för snabb deployment
-   ✓ Hämtar Alpine-komponenter från **officiella källor**

---

# 💻 DEL 2: CLIENT-DELEN

## Alpine Linux Overlay System

### Boot-process

```
1. PXE boot          → Från nätverket (DHCP + TFTP)
2. Alpine kernel     → vmlinuz-lts + initramfs-lts laddar
3. Overlay appliceras → localhost.apkovl.tar.gz
4. RAM-system        → Allt körs i minnet (diskless)
5. Auto-start        → /etc/local.d/run_diagnostic.start
```

### Overlay-struktur

```
localhost.apkovl.tar.gz (tar.gz arkiv)
├── etc/local.d/                      # Startup scripts
│   ├── 00-preinstall.start           # Paketinstallation
│   └── run_diagnostic.start          # Huvudscript (254 rader)
├── home/ssh/                         # Diagnostikfiler
│   ├── binaries/                     # Rust-applikationer
│   │   ├── input_device_test         # 3200 rader Rust
│   │   └── screen_test               # 792 rader Rust
│   ├── scripts/                      # Shell-scripts
│   └── python/                       # Python-scripts
│       ├── disk_health.py            # 572 rader
│       └── usb_test.py               # 650 rader
├── var/custom-repo/                  # Lokal APK-repository
└── root/
    ├── restart_test.sh
    └── instructions.txt
```

### Vad är ett overlay?

-   **Format:** `.apkovl` = Alpine's overlay-format (tar.gz)
-   **Innehåll:** Alla diagnostikverktyg, configs och dependencies
-   **Persistence:** Inget sparas efter reboot (stateless)

---

## Diagnostik-sekvens (11 automatiska tester)

### Test-ordning (run_diagnostic.start - 254 rader)

| #   | Test              | Beskrivning                      | Typ          |
| --- | ----------------- | -------------------------------- | ------------ |
| 0   | **Abort watcher** | Bakgrundsprocess lyssnar på 'q'  | Kontroll     |
| 1   | **Stress-test**   | 30s stress-ng (CPU + 75% RAM)    | Kritisk      |
| 2   | **RAM-test**      | memtester 100MB (single pass)    | Kritisk      |
| 3   | **Disk health**   | disk_health.py (NVMe/SATA SMART) | Kritisk      |
| 4   | **USB-test**      | usb_test.py (extern Pico-tester) | Kritisk      |
| 5   | **ACPI status**   | Batteri + temperatur             | Info         |
| 6   | **Serial-test**   | Loopback på alla ttyS\*          | Icke-kritisk |
| 7   | **GPS-test**      | gpsd + cgps (om tillgänglig)     | Icke-kritisk |
| 8   | **Ljudtest**      | speaker-test + ALSA              | Icke-kritisk |
| 9   | **Tangentbord**   | input_device_test (ny VT)        | Interaktiv   |
| 10  | **Skärmtest**     | screen_test (ny VT)              | Interaktiv   |

### Output och loggning

```
/dev/tty1                      → Konsol-output (live)
/root/diagnostic_report.txt    → Fullständig logg (alla tester)
/root/usb_report.json          → Detaljerad USB-analys
```

### Felhantering

-   **Kritiska tester** → Stoppar vid fel med prompt (ask_continue)
-   **Icke-kritiska** → Fortsätter vid fel med varning
-   **Interaktiva** → Kräver användarinteraktion
-   **Abort-funktion** → 'q' avbryter hela sekvensen kontrollerat

### Tekniska detaljer

-   **VT-switching** → Separata virtuella terminaler för interaktiva tester
-   **Background watcher** → Kontinuerlig övervakning för abort-signal

---

## Paket-dependencies & Custom Mjukvara

### Alpine Linux paket (från repositories)

| Paket             | Syfte                          | Används i test |
| ----------------- | ------------------------------ | -------------- |
| **stress-ng**     | CPU och RAM stress-test        | Stress-test    |
| **memtester**     | RAM-integritet (single pass)   | RAM-test       |
| **smartmontools** | SATA/SAS SMART (smartctl)      | Disk health    |
| **nvme-cli**      | NVMe health monitoring         | Disk health    |
| **util-linux**    | Block device utilities (lsblk) | Disk health    |
| **python3**       | Runtime för diagnostikscript   | Flera          |
| **py3-usb**       | USB-kommunikation (pyusb)      | USB-test       |
| **acpi**          | Batteri och temperaturstatus   | ACPI status    |
| **alsa-utils**    | Ljudtest (speaker-test, aplay) | Ljudtest       |
| **gpsd**          | GPS-test daemon                | GPS-test       |
| **gpsd-clients**  | GPS TUI (cgps)                 | GPS-test       |

### Custom mjukvara (ingår i overlay)

| Fil                      | Språk  | Rader | Syfte                              |
| ------------------------ | ------ | ----- | ---------------------------------- |
| **input_device_test**    | Rust   | 3200  | Tangentbord, touchscreen, mus      |
| **screen_test**          | Rust   | 792   | DRM-baserad skärmtestare           |
| **disk_health.py**       | Python | 572   | NVMe/SATA SMART-diagnostik         |
| **usb_test.py**          | Python | 650   | USB port tester (Pico-integration) |
| **run_diagnostic.start** | Shell  | 254   | Huvudscript för testsekvens        |

### Distribution

-   **Standardpaket** → Installeras från lokal APK-repository i overlay
-   **Custom binaries** → Cross-kompilerade (x86_64 + i686), inkluderade i overlay
-   **Offline-installation** → Allt finns i overlay, ingen internet-anslutning krävs

---

## Overlay-skapande & Deployment Workflow

### Steg 1: Bygg klient-paket

```bash
./build_client_packages.sh
```

-   Cross-compile Rust-applikationer (x86_64 + i686)
-   Paketera binaries, scripts, python-filer
-   Skapar `client/packages/{x86_64,x86}/`

### Steg 2: Skapa overlay från scratch (PXE boot utan overlay)

```bash
# 1. Boota target-dator via PXE
#    I iPXE boot menu: Välj "Boot Alpine" → "Boot without Overlay"

# 2. På target-datorn (efter boot till clean Alpine):
setup-alpine  # Konfigurera keyboard (se), nätverk, användare (ssh)

# 3. Från utvecklingsmaskin - kopiera paket till target-datorn
scp client/packages/x86_64/* ssh@<target-ip>:~
ssh ssh@<target-ip>
/home/ssh/setup_client.sh  # Installera + skapa overlay

# 4. Hämta tillbaka overlay
scp ssh@<target-ip>:~/localhost.apkovl.tar.gz \
    ./client/overlays/x86_64.apkovl.tar.gz

# 5. Kör create_overlay (flyttar overlayen till rätt ställe i server/package)
./create_overlays.sh

# 6. Deploy till servern
scp ./client/overlays/x86_64.apkovl.tar.gz \
    tele@192.168.150.62:/srv/http/alpine/boot/x86_64/localhost.apkovl.tar.gz
```

### Steg 3: Uppdatera overlay (incrementell)

```bash
./create_overlays.sh
```

Scriptet:

1. Packar upp befintlig overlay
2. Uppdaterar filer (binaries, scripts, configs)
3. Komprimerar ny overlay
4. Kopierar till `server/package/srv/http/alpine/boot/{x86_64,x86}/`

### Deployment till PXE-server

```bash
scp server/package/srv/http/alpine/boot/x86_64/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86_64/
scp server/package/srv/http/alpine/boot/x86/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86/
```

### Fördelar med två workflows

-   **Från scratch** → För ändringar av annat än egna scripts/program, ex. nya paket
-   **Incrementell** → För snabba uppdateringar (90% av fallen)
-   **Multi-arch** → En byggprocess för både 32-bit och 64-bit

---

## 🔨 Build & Setup Scripts - Djupdykning

### build_client_packages.sh

#### Syfte

Bygg Rust-applikationer och paketera all client-mjukvara för båda arkitekturerna (x86_64 och i686/x86).

#### Vad scriptet faktiskt gör

```bash
#!/bin/sh
# Faktisk implementation av build_client_packages.sh

1. Bygg Rust-applikationer via deras egna build-scripts
   cd client/input_device_test
   ./build.sh    # Bygger både x86_64 och i686

   cd ../screen_test
   ./build.sh    # Bygger både x86_64 och i686

2. Rensa gamla paket
   rm -rf packages/x86_64
   rm -rf packages/x86

3. Skapa paket-struktur
   mkdir -p packages/x86_64/binaries
   mkdir -p packages/x86/binaries

4. Kopiera startup scripts (för båda arkitekturer)
   cp -r startup packages/x86_64/
   cp -r startup packages/x86/

5. Kopiera Rust-binaries till rätt arkitektur
   # x86_64 binaries
   cp input_device_test/build/input_device_test_x86_64 \
      packages/x86_64/binaries/input_device_test
   cp screen_test/build/screen_test_x86_64 \
      packages/x86_64/binaries/screen_test

   # i686/x86 binaries
   cp input_device_test/build/input_device_test_i686 \
      packages/x86/binaries/input_device_test
   cp screen_test/build/screen_test_i686 \
      packages/x86/binaries/screen_test

6. Kopiera andra filer (arkitektur-oberoende)
   cp setup_client.sh packages/x86_64/
   cp setup_client.sh packages/x86/

   cp -r scripts packages/x86_64/
   cp -r scripts packages/x86/

   cp -r python packages/x86_64/
   cp -r python packages/x86/

   cp instructions.txt packages/x86_64/
   cp instructions.txt packages/x86/
```

#### När används det?

-   **Före setup_client.sh** → För att skapa paket som ska scp:as till target-dator
-   **Före create_overlays.sh** → För incrementella uppdateringar (anropas automatiskt)

#### Output

```
client/packages/
├── x86_64/
│   ├── binaries/
│   │   ├── input_device_test
│   │   └── screen_test
│   ├── python/
│   ├── scripts/
│   ├── startup/
│   ├── setup_client.sh
│   └── instructions.txt
└── x86/
    ├── binaries/
    │   ├── input_device_test
    │   └── screen_test
    ├── python/
    ├── scripts/
    ├── startup/
    ├── setup_client.sh
    └── instructions.txt
```

---

### create_overlays.sh

#### Syfte

Uppdatera befintliga Alpine overlays med ny mjukvara utan att behöva skapa dem från scratch via PXE boot.

#### Flaggor

```bash
-n    # Skip unpacking (använd befintliga uppackade overlays)
```

#### Vad scriptet faktiskt gör

```bash
#!/bin/sh
# Faktisk implementation av create_overlays.sh

1. Anropa build_client_packages.sh automatiskt
   ./build_client_packages.sh

2. Packa upp befintliga overlays (om inte -n flaggan används)
   cd client
   rm -rf overlays/x86_64 overlays/x86
   mkdir -p overlays/x86_64/home/ssh
   mkdir -p overlays/x86/home/ssh

   tar -xzf overlays/x86_64.apkovl.tar.gz -C overlays/x86_64
   tar -xzf overlays/x86.apkovl.tar.gz -C overlays/x86

3. Skapa deployment-kataloger
   mkdir -p ../server/package/srv/http/alpine/boot/x86_64
   mkdir -p ../server/package/srv/http/alpine/boot/x86

4. Rensa gamla filer i uppackade overlays
   rm -rf overlays/x86_64/home/ssh/*
   rm -rf overlays/x86/home/ssh/*
   rm -rf overlays/x86_64/etc/local.d/*
   rm -rf overlays/x86/etc/local.d/*

5. Kopiera nya startup scripts till /etc/local.d
   cp -r startup/* overlays/x86_64/etc/local.d/
   cp -r startup/* overlays/x86/etc/local.d/
   chmod +x overlays/x86_64/etc/local.d/*.start
   chmod +x overlays/x86/etc/local.d/*.start

6. Kopiera packages till /home/ssh
   cp -r packages/x86_64/* overlays/x86_64/home/ssh
   cp -r packages/x86/* overlays/x86/home/ssh

7. Rensa onödiga filer från /home/ssh
   rm -rf overlays/x86_64/home/ssh/startup
   rm -rf overlays/x86/home/ssh/startup
   rm -rf overlays/x86_64/home/ssh/setup_client.sh
   rm -rf overlays/x86/home/ssh/setup_client.sh

8. Sätt executable permissions
   chmod +x overlays/x86_64/home/ssh/binaries/*
   chmod +x overlays/x86_64/home/ssh/scripts/*
   chmod +x overlays/x86/home/ssh/binaries/*
   chmod +x overlays/x86/home/ssh/scripts/*

9. Flytta speciella filer till /root
   mv overlays/x86_64/home/ssh/scripts/restart_test.sh overlays/x86_64/root/
   mv overlays/x86/home/ssh/scripts/restart_test.sh overlays/x86/root/
   mv overlays/x86_64/home/ssh/instructions.txt overlays/x86_64/root/
   mv overlays/x86/home/ssh/instructions.txt overlays/x86/root/

10. Komprimera nya overlays
    cd overlays/x86_64
    tar -czf ../x86_64.apkovl.tar.gz .
    cd ../x86
    tar -czf ../x86.apkovl.tar.gz .

11. Kopiera till deployment (server/package)
    cp client/overlays/x86_64.apkovl.tar.gz \
       server/package/srv/http/alpine/boot/x86_64/localhost.apkovl.tar.gz
    cp client/overlays/x86.apkovl.tar.gz \
       server/package/srv/http/alpine/boot/x86/localhost.apkovl.tar.gz
```

#### När används det?

-   **Efter kodändringar** → När diagnostik-scripts modifieras
-   **Daglig utveckling** → 90% av uppdateringar går via detta script
-   **Snabba iterationer** → Tar ~5 sekunder vs 10+ minuter för från-scratch

#### Viktigt

-   ⚠️ **Anropar build_client_packages.sh automatiskt** - ingen manuell build krävs
-   ⚠️ **Kan användas med -n flaggan** för att skippa unpacking och bevara manuella ändringar i den uppackade overlayen (t.ex. om du har ändrat repository IP-adress eller andra konfigfiler direkt i `client/overlays/x86_64/` och vill att dessa ändringar ska bibehållas)

#### Förutsättningar

-   ✓ Befintlig overlay måste finnas i `client/overlays/` (x86_64.apkovl.tar.gz och x86.apkovl.tar.gz)

#### Output

```
server/package/srv/http/alpine/boot/
├── x86_64/
│   └── localhost.apkovl.tar.gz  (uppdaterad overlay)
└── x86/
    └── localhost.apkovl.tar.gz  (uppdaterad overlay)
```

#### Begränsningar

-   **Kan INTE** lägga till nya Alpine-paket (kräver från-scratch)
-   **KAN** uppdatera egna scripts och binaries
-   **KAN** ändra configs i /etc/local.d/
-   **KAN** ändra Alpine-systemkonfiguration **med -n flaggan** (gör manuella ändringar i uppackad overlay, kör sedan `./create_overlays.sh -n`)

---

### setup_client.sh

#### Syfte

Installera alla dependencies och skapa en Alpine overlay från scratch på en target-dator bootad via PXE (utan overlay).

#### Vad scriptet faktiskt gör

```bash
#!/bin/ash
# Körs INUTI target-dator (bootad via PXE utan overlay)
# Faktisk implementation av setup_client.sh

1. Aktivera community repositories
   sed -i 's/^\s*#//' /etc/apk/repositories

2. Skapa lokal APK-repository med alla dependencies
   ARCH=$(apk --print-arch)
   REPO_PATH="/var/custom-repo/main/$ARCH"
   mkdir -p "$REPO_PATH"
   cd "$REPO_PATH"

   # Ladda ner alla paket rekursivt (med dependencies)
   apk update
   apk fetch --recursive memtester stress-ng smartmontools \
             nvme-cli util-linux python3 acpi py3-usb \
             alsa-utils gpsd gpsd-clients

   # Skapa paketindex för lokal repo
   apk index -o APKINDEX.tar.gz -- *.apk

   # Lägg till repo i overlay
   lbu add /var/custom-repo/

3. Flytta startup scripts till /etc/local.d
   mv /home/ssh/startup/* /etc/local.d/
   chmod +x /etc/local.d/*.start
   lbu add /etc/local.d/

4. Aktivera local startup service
   rc-update add local default

5. Inaktivera savecache (behövs inte för diskless boot)
   rc-update del savecache shutdown

6. Gör binaries och scripts exekverbara
   chmod +x /home/ssh/binaries/*
   chmod +x /home/ssh/scripts/*

7. Flytta speciella filer till /root
   mv /home/ssh/scripts/restart_test.sh /root
   mv /home/ssh/instructions.txt /root
   lbu add /root

8. Inaktivera online APK repositories
   sed -i 's|^http://dl|#|' /etc/apk/repositories

9. Lägg till lokal repository
   echo 'file:///var/custom-repo/main' >> /etc/apk/repositories

10. Ta bort statisk interface-konfiguration
    sed -i '/^iface eth0/,$d' /etc/network/interfaces

11. Skapa overlay-paket
    lbu pkg /home/ssh
    # Skapar /home/ssh/localhost.apkovl.tar.gz
```

#### När används det?

-   **Första gången** → Vid initial setup av projektet
-   **Nya Alpine-paket** → När dependencies ändras
-   **Systemkonfiguration** → När /etc-filer behöver ändras
-   **Efter Alpine-upgrade** → När ny Alpine-version används

#### Viktigt om lokal repository

Detta script skapar en **offline-kapabel overlay** genom att:

-   Ladda ner alla Alpine-paket med dependencies till `/var/custom-repo/`
-   Skapa ett lokalt APK-index
-   Inaktivera online repositories
-   Lägga till lokal repo i `/etc/apk/repositories`

Detta betyder att target-datorer **inte behöver internet** för att installera paket vid boot!

#### Workflow

```
Utvecklingsmaskin                    Target-dator (PXE boot utan overlay)
─────────────────                    ────────────────────────────────────
1. ./build_client_packages.sh
   (skapar packages/)

2. scp packages/x86_64/* ssh@target:~/   ──→  (tar emot filer i /home/ssh/)

3. ssh ssh@target                    ──→  4. /home/ssh/setup_client.sh
                                              (installerar + skapar overlay)

5. scp ssh@target:~/localhost.apkovl.tar.gz  ←── (från ~/ som är /home/ssh/)
      ./client/overlays/x86_64.apkovl.tar.gz
```

#### Förutsättningar

-   ✓ Fungerande PXE-server
-   ✓ Target-dator bootad via PXE **utan overlay** (välj "Boot without Overlay" i iPXE menu)
-   ✓ `setup-alpine` har körts (keyboard layout: se, network, user: ssh)
-   ✓ SSH-server aktiverad (openssh package)
-   ✓ Paket-filer finns i `/home/ssh/` på target-datorn (scp:ade dit)
-   ✓ Internet-anslutning (behövs för att ladda ner Alpine-paket)

#### Output

-   **Overlay:** `/home/ssh/localhost.apkovl.tar.gz` (på target-datorn)

---

### setup_server.sh

#### Syfte

Automatisera installation och konfiguration av PXE-server (Rock 4SE eller Ubuntu).

#### Flaggor

```bash
--type rock      # Full server (DHCP + TFTP + HTTP) - default
--type ubuntu    # Partial server (TFTP + HTTP only, no DHCP)
```

#### Vad scriptet faktiskt gör

```bash
#!/bin/sh
# Faktisk implementation av setup_server.sh

1. Installera paket baserat på typ
   apt update

   if [ "$SERVER_TYPE" = "rock" ]; then
     apt install -y dnsmasq netplan.io python3-venv python3-pip
   else # ubuntu
     apt install -y tftpd-hpa python3-venv python3-pip
   fi

2. Skapa katalogstruktur
   mkdir -p /srv/tftp/
   mkdir -p /srv/http/alpine/boot/{x86_64,x86}
   mkdir -p /srv/http/alpine/apks/{x86_64,x86}

3. Kopiera server-filer
   cp -r ./srv/* /srv/
   chmod -R 777 /srv

4. Setup Python HTTP-server (Flask)
   python3 -m venv /srv/python/.venv
   /srv/python/.venv/bin/pip install --upgrade pip
   /srv/python/.venv/bin/pip install flask gunicorn

   cp ./conf/pxe-http.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now pxe-http

5. Ladda ner Alpine netboot komponenter
   # x86_64
   wget -P /srv/http/alpine/boot/x86_64 \
     http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/\
x86_64/netboot/vmlinuz-lts
   wget -P /srv/http/alpine/boot/x86_64 \
     http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/\
x86_64/netboot/initramfs-lts
   wget -P /srv/http/alpine/boot/x86_64 \
     http://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/\
x86_64/netboot/modloop-lts

   # x86 (samma för 32-bit)

6. Ladda ner och extrahera Alpine APKs från .iso
   # x86_64
   wget alpine-standard-3.22.0-x86_64.iso
   mount -o loop alpine-standard-3.22.0-x86_64.iso /mnt/alpine-x64
   cp -a /mnt/alpine-x64/apks/x86_64/* /srv/http/alpine/apks/x86_64/
   umount /mnt/alpine-x64
   rm alpine-standard-3.22.0-x86_64.iso

   # x86 (samma för 32-bit)

7. Konfigurera nätverk och tjänster (om Rock)
   if [ "$SERVER_TYPE" = "rock" ]; then
     # Ta bort gamla netplan-configs
     rm -rf /etc/netplan/*.yaml

     # Skapa ny netplan för PXE-nätverk (192.168.200.1/24)
     cp ./conf/armbian/01-netcfg.yaml /etc/netplan/
     chmod 600 /etc/netplan/01-netcfg.yaml

     # Inaktivera systemd-resolved (konflikt med dnsmasq port 53)
     systemctl disable systemd-resolved
     systemctl stop systemd-resolved

     # Applicera netplan
     netplan apply

     # VIKTIGT: Inaktivera networkd-wait-online EFTER netplan
     # (netplan kan re-enable den)
     systemctl disable systemd-networkd-wait-online.service
     systemctl mask systemd-networkd-wait-online.service

     # Kopiera dnsmasq config
     cp ./conf/armbian/dnsmasq.conf /etc/dnsmasq.conf

     # Skapa systemd override för dnsmasq
     mkdir -p /etc/systemd/system/dnsmasq.service.d
     cp ./conf/armbian/dnsmasq-override.conf \
        /etc/systemd/system/dnsmasq.service.d/override.conf

     # Setup path unit för automatisk dnsmasq-restart
     cp ./conf/armbian/dnsmasq-ifup.path /etc/systemd/system/
     cp ./conf/armbian/dnsmasq-ifup.service /etc/systemd/system/

     systemctl daemon-reload
     systemctl enable dnsmasq-ifup.path
     systemctl start dnsmasq-ifup.path

     # Starta dnsmasq
     systemctl restart dnsmasq
     systemctl enable dnsmasq

8. Konfigurera TFTP (om Ubuntu)
   else # ubuntu
     cp ./conf/ubuntu/tftpd-hpa /etc/default/
     systemctl restart tftpd-hpa
     systemctl enable tftpd-hpa
   fi
```

#### Viktiga detaljer

**Alpine APKs från .iso:**
Scriptet laddar ner hela Alpine .iso-filer (ca 200 MB vardera), mountar dem, och kopierar alla APK-paket till `/srv/http/alpine/apks/`. Dessa paket behövs **under boot-processen** för Alpine initramfs. De paket som ligger i client-overlayens lokala repo (`/var/custom-repo/`) är separata och används för **diagnostiktesterna**.

**Rock 4SE nätverkshantering:**

-   **Byter nätverk** från setup-nätverk (192.168.150.x) till PXE-nätverk (192.168.200.x)
-   **Inaktiverar systemd-resolved** för att undvika port 53-konflikt med dnsmasq
-   **Inaktiverar networkd-wait-online** för att undvika långa boot-delays när ethernet-kabel inte är inkopplad
-   **Path unit** övervakar `/sys/class/net/end0` och startar om dnsmasq när kabel kopplas in

**Flask HTTP-server:**
Servern lyssnar på port **80** (specificerat i gunicorn-konfigurationen) och hanterar:

-   `/bootstage?mac=XX:XX:XX:XX:XX:XX` → Beslutar om memtest eller alpine boot
-   Servar Alpine boot-filer via HTTP (kernel, initramfs, overlay)

#### När används det?

-   **Första installation** → Setup av ny PXE-server
-   **Efter OS-reinstall** → Om servern byggts om från scratch
-   **Ny server** → Setup av backup-server eller test-server
-   **Alpine-version upgrade** → För att uppdatera kernel/initramfs

#### Skillnader mellan Rock och Ubuntu

```
Rock 4SE (--type rock):
├── Installerar: dnsmasq, netplan.io
├── Kör DHCP + TFTP (via dnsmasq)
├── Byter nätverk till 192.168.200.1/24
├── Netplan-konfiguration + systemd overrides
├── Auto-restart vid ethernet up/down
└── Inaktiverar systemd-resolved och networkd-wait-online

Ubuntu (--type ubuntu):
├── Installerar: tftpd-hpa (standalone TFTP)
├── Ingen DHCP (använder befintlig DHCP-server)
├── Befintligt nätverk oförändrat (ex. 192.168.150.62)
├── Ingen netplan-ändring
└── Endast TFTP + HTTP
```

#### Förutsättningar

-   ✓ Ren Linux-installation (Armbian för Rock, Ubuntu Server för Ubuntu)
-   ✓ Root-access (kör med sudo)
-   ✓ Internet-anslutning (för att ladda ner Alpine netboot + .iso:er)
-   ✓ Ethernet-interface (`end0` för Rock 4SE, valfritt för Ubuntu)

#### Output

```
/srv/
├── tftp/
│   ├── boot.kpxe         (BIOS boot loader från ./srv/)
│   ├── snponly.efi       (UEFI boot loader från ./srv/)
│   ├── memtest.bin       (Memtest86+ binary från ./srv/)
│   └── (boot.ipxe kopieras inte hit, ligger kvar i ./srv/)
├── http/alpine/
│   ├── boot/
│   │   ├── x86_64/
│   │   │   ├── vmlinuz-lts        (från Alpine CDN)
│   │   │   ├── initramfs-lts      (från Alpine CDN)
│   │   │   ├── modloop-lts        (från Alpine CDN)
│   │   │   └── localhost.apkovl.tar.gz  (skapas av create_overlays.sh)
│   │   └── x86/
│   │       ├── vmlinuz-lts
│   │       ├── initramfs-lts
│   │       ├── modloop-lts
│   │       └── localhost.apkovl.tar.gz  (skapas av create_overlays.sh)
│   └── apks/              (behövs för Alpine boot-processen)
│       ├── x86_64/        (~200 MB APK-paket från .iso)
│       └── x86/           (~200 MB APK-paket från .iso)
└── python/
    ├── .venv/             (Python virtual environment för Flask)
    └── pxe_http.py        (Flask-applikation för boot-kontroll)
```

**OBS:** `localhost.apkovl.tar.gz` skapas automatiskt i `server/package/srv/http/alpine/boot/` av `create_overlays.sh`, så de finns redan här efter att du kört det scriptet. Du behöver bara kopiera `server/package/` till servern.

---

# 🦀 DEL 3: CUSTOM MJUKVARA

## Input Device Test (Rust - 3200 rader)

### Teknologier

-   **TUI Framework:** ratatui + crossterm (terminal UI)
-   **Input Layer:** evdev (raw `/dev/input/event*`)
-   **Tangentbord Layout:** Förprogrammerade layouts för olika hårdvarumaskiner

### Modulstruktur

```rust
main.rs              // App state + navigation         (254 rader)
keyboard_test.rs     // Visuell layout, färgkodning   (317 rader)
touchscreen_test.rs  // 4-punkts kalibrering          (1170 rader)
mouse_test.rs        // Muspekare + knappar           (131 rader)
serial_touch.rs      // Seriell touchscreen support   (136 rader)
machine_detect.rs    // DMI hårdvaru-detektering      (92 rader)
keyboard_layouts.rs  // Svenska tangentpositioner     (774 rader)
event_handler.rs     // Evdev event aggregering       (326 rader)
```

---

## Screen Test (Rust - 792 rader)

### Teknologier

-   **DRM:** Direct Rendering Manager (kernel mode-setting)
-   **Input:** evdev (keyboard för navigation)

### Test-patterns (5 kategorier)

#### 1. Solid Colors (6 stycken)

-   Red, Green, Blue, White, Gray, Black
-   **Syfte:** Dead pixels, färgåtergivning

#### 2. Gradients (2 stycken)

-   Horizontal/Vertical luma gradient
-   **Syfte:** Banding, gradient smoothness

#### 3. Checkerboard

-   8x8 pixel rutor (svart/vit)
-   **Syfte:** Skärpa, contrast, pixel alignment

#### 4. Motion Bar

-   Rörlig vit bar (16 px/frame)
-   **Syfte:** Motion blur, response time

#### 5. Viewing Card

-   Kantlinje, color bars, fine checkerboard, stripes, crosshair
-   **Syfte:** Komplett test-card för manuell inspektion

### Navigation

```
Space / Right Arrow  →  Nästa pattern
Left Arrow           →  Föregående pattern
Q / Esc              →  Avsluta
```

---

## Disk Health (Python - 572 rader)

### Teknologier

-   **NVMe:** `nvme-cli` (smart-log, device-self-test)
-   **SATA/SAS:** `smartctl` (SMART attributes)
-   **Inventory:** `lsblk` (modell, storlek, serial)

### Test-sekvens

```
1. Inventory          → lsblk (list alla diskar)
2. Kör self-test      → NVMe: device-self-test -s 1
                        SATA: smartctl -t short
3. Vänta              → Max 130s (polling)
4. Hämta SMART-data   → NVMe: smart-log
                        SATA: smartctl -A
5. Analysera          → Intelligent bedömning
```

### Output-exempel

```
Device: /dev/nvme0n1
  Model: Samsung 980 PRO | Size: 500GB | Type: SSD/NVMe
  Health: PASS
    Power-on hours: 2340 (~0.27 years)
    Wear level: 2%
    Temperature: 42°C
    Data units written: 15.4 TB

Device: /dev/sda
  Model: WD Blue 1TB | Size: 1TB | Type: HDD/SATA
  Health: WARN
    Power-on hours: 45600 (~5.2 years)
    Reallocated sectors: 12 (WARNING)
    Pending sectors: 0
```

### Bedömningskriterier

| Attribut                | PASS   | WARN    | FAIL   |
| ----------------------- | ------ | ------- | ------ |
| **Wear level**          | < 80%  | 80-95%  | > 95%  |
| **Reallocated sectors** | 0      | 1-50    | > 50   |
| **Pending sectors**     | 0      | 1-10    | > 10   |
| **Temperature**         | < 60°C | 60-70°C | > 70°C |

### Stöd för olika media

-   ✓ **NVMe** (native nvme-cli)
-   ✓ **SATA/SAS** (smartctl)
-   ✓ **USB** (SAT protocol fallback)

---

# 🔌 DEL 4: USB TESTAREN

## USB Port Test - Översikt

### Extern hårdvara (separat projekt)

```
Projekt: /home/tele/Documents/pico/RPI_LOOPBACK
Hårdvara: Raspberry Pi Pico med custom C++ firmware
VID/PID: 0x1209:0x4004
Protokoll: USB vendor requests + bulk loopback
```

### Alpine-sidan (Python)

```
Fil: client/python/usb_test.py
Storlek: 650 rader Python
Bibliotek: pyusb (py3-usb)
```

### Test-typer

#### 1. Data Throughput

-   **Metod:** Loopback bulk transfer (3s per port)
-   **Protokoll:** Sequenced packets med CRC-validering
-   **Minimum:** 0.2 Mbps diff mellan portar

#### 2. Power Delivery

-   **Belastning:** 5 nivåer (0-100% PWM)
-   **Mätningar:** Voltage, Current, Ripple, Resistance
-   **Gränser:** Mjuka gränser för fälttest

### Output

```
Konsol:  Sammanfattning per port (PASS/FAIL)
JSON:    /root/usb_report.json (fullständig analys)
```

## USB Test - Data Throughput

### Test-parametrar

```
Duration:     3 sekunder per port
Packet size:  1024 bytes
Protocol:     Sequenced packets + CRC-validering
Minimum:      0.2 Mbps diff mellan portar
```

### Algoritm

```python
# Loopback bulk transfer test
for duration in range(3 seconds):
    1. Host → Pico:  Skicka paket (seq_num, data[1024], crc16)
    2. Pico → Host:  Eka tillbaka identiskt paket
    3. Host validerar:
       - Sequence number (detektera förlorade paket)
       - CRC (detektera korruption)
    4. Räkna bytes

5. Beräkna throughput: (total_bytes / 3s) → Mbps
```

### Output-exempel

```
USB Port 1 — PASS: 1.54 Mbps
USB Port 2 — PASS: 1.52 Mbps
USB Port 3 — FAIL: 0.38 Mbps (< 0.2 Mbps diff från median)
USB Port 4 — PASS: 1.51 Mbps
```

### Bedömning

-   **Median throughput** beräknas från alla portar
-   **FAIL** om port < (median - 0.2 Mbps)
-   **FAIL** om CRC-fel eller sequence-fel

### Varför detta fungerar

-   ✓ **Sequenced packets** → Upptäcker förlorade paket
-   ✓ **CRC-validering** → Upptäcker data corruption
-   ✓ **Relativ jämförelse** → Upptäcker problem genom avvikelse från median

---

## USB Test - Power Delivery

### Mätningar per belastningsnivå

```
Voltage:     Idle, Mean, Min (mV)
Current:     mA (beräknas från belastning)
Droop:       V_idle - V_mean (mV) - spänningsfallet
Ripple:      Peak-to-peak (mVpp)
Resistance:  droop / current (mΩ) - beräknas som (V_idle - V_mean) / I
```

**Resistance-beräkning:**
Resistansen approximeras genom att dela spänningsfallet (V_idle - V_mean) med strömmen. Detta ger en uppskattning av den totala resistansen i kedjan (kontakter, kablar, PSU). Måttet används för att:

-   Upptäcka smutsiga/oxiderade kontakter (hög resistans)
-   Upptäcka PSU-problem (varierar mycket mellan belastningsnivåer)
-   Verifiera att spänningsfallet är Ohmskt (linjärt med strömmen)

### Test-sekvens (5 belastningsnivåer)

```
1. Idle (0%)          → Mät V_idle, ripple
2. Load 20% (100mA)   → Mät V, I, droop, ripple, R
3. Load 40% (200mA)   → Mät V, I, droop, ripple, R
..
6. Load 100% (500mA)  → Mät V, I, droop, ripple, R (max current)
```

### Bedömningsgränser (mjuka för fälttest)

| Parameter        | PASS      | FAIL      |
| ---------------- | --------- | --------- |
| **V_idle**       | ≥ 4800 mV | < 4800 mV |
| **V_min (load)** | ≥ 3800 mV | < 3800 mV |
| **I_max**        | ≥ 400 mA  | < 400 mA  |
| **Ripple**       | ≤ 50 mVpp | > 50 mVpp |
| **R_mean**       | ≤ 2000 mΩ | > 2000 mΩ |
| **R_variation**  | ≤ 500 mΩ  | > 500 mΩ  |

### Output-exempel

```
USB Port 1 — PASS
  Idle: 5.02V, ripple 12mVpp
  Load: Vmin 4.23V @ 487mA
  Resistance: 1850±150mΩ

USB Port 2 — FAIL
  Idle: 4.65V (< 4.8V limit)
  Load: Vmin 3.72V @ 410mA
  Resistance: 2280±80mΩ (dirty contacts)
```

### Hårdvara på Pico

-   **ADC:** 12-bit, 48 kHz sampling (kontinuerlig VBUS-mätning)
-   **Electronic load:** PWM-styrd MOSFET array
-   **Fixture resistance:** ~2Ω (därför mjuka gränser)

### Vad upptäcks?

-   ✓ **Låg idle voltage** → PSU-problem eller dålig kabel
-   ✓ **Hög droop** → Hög resistans (smutsiga kontakter)
-   ✓ **Hög ripple** → Dålig kondensator eller PSU
-   ✓ **Resistance variation** → Inkonsistent kontakt eller PSU-problem

---

## USB Test - Pico Firmware (C++)

### Firmware-komponenter

#### 1. USB Device Stack

```cpp
// Custom USB descriptor
- Device class: Vendor-specific (0xFF)
- VID: 0x1209 (pid.codes)
- PID: 0x4004
- Endpoints: Bulk IN/OUT (EP1)
```

#### 2. Loopback Engine

```cpp
// Ringbuffer för bulk loopback
- Buffer size: 4096 bytes
- TinyUSB callbacks: tud_vendor_rx_cb, tud_vendor_tx_cb
- Zero-copy design (efficient)
```

#### 3. ADC Sampling

```cpp
// Kontinuerlig VBUS-mätning
- Resolution: 12-bit ADC
- Sample rate: 48 kHz
```

#### 4. Electronic Load

```cpp
// PWM-styrd MOSFET array
- Load levels: 0-100% (5 steg används)
- Fixture resistance: ~2Ω
- Max current: ~500mA @ 5V
```

### Vendor Requests (USB Control Transfers)

```cpp
SET_LOAD_LEVEL (0x01)
  - wValue: load_level (0-100)
  - Action: Sätt PWM duty cycle

GET_VOLTAGE (0x02)
  - Return: uint16_t voltage_mv

GET_POWER_REPORT (0x03)
  - Return: struct {
      uint16_t v_idle_mv;
      uint16_t v_mean_mv;
      uint16_t v_min_mv;
      uint16_t ripple_mvpp;
    }
```

### Design-filosofi

-   **Stateless** → Host styr alla mätningar
-   **Zero-copy loopback** → Minimal latency för throughput-test

---

# 🔗 DEL 5: INTEGRATION & SAMMANFATTNING

## System-integration & Dataflöde

### Komplett boot-flöde

```
1. Client Power On
   ↓
2. BIOS PXE Boot
   ↓
3. DHCP → dnsmasq (192.168.200.1)
   ↓ [IP-adress, TFTP-server, boot-fil]
   ↓
4. TFTP: boot.kpxe (BIOS) / snponly.efi (UEFI)
   ↓
5. iPXE Script: boot.ipxe laddar
   ↓
6. HTTP: GET /bootstage?mac=XX:XX:XX:XX
   ↓ [Flask beslut: memtest eller alpine]
   ↓
7. HTTP: Ladda Alpine-komponenter
   - vmlinuz-lts (kernel)
   - initramfs-lts (initial ramdisk)
   - localhost.apkovl.tar.gz (overlay)
   ↓
8. Alpine Boot → Applicera overlay (i RAM)
   ↓
9. /etc/local.d/00-preinstall.start
   - Installera paket från lokal repo
   ↓
10. /etc/local.d/run_diagnostic.start
    ↓
[DIAGNOSTIK-SEKVENS STARTAR]
```

### Diagnostik-komponent integration

```
run_diagnostic.start (bash orchestrator)
    │
    ├─ stress-ng              → CPU + RAM stress
    ├─ memtester              → RAM integritet
    │
    ├─ disk_health.py         → nvme-cli / smartctl
    │   └─ NVMe/SATA devices → SMART data
    │
    ├─ usb_test.py            → pyusb library
    │   └─ USB Pico (0x1209:0x4004)
    │       ├─ Bulk loopback (throughput)
    │       └─ Vendor requests (power)
    │
    ├─ serial_test.sh         → loopback hardware
    │   └─ /dev/ttyS*         → UART testing
    │
    ├─ acpi                   → Batteri & temp
    ├─ gpsd + cgps            → GPS test
    ├─ speaker-test           → ALSA audio
    │
    ├─ input_device_test (Rust, VT2)
    │   ├─ evdev              → /dev/input/event*
    │   ├─ machine_detect.rs  → DMI för DATOR_BB_FÄLT
    │   └─ serial_touch.rs    → Legacy touchscreen
    │
    └─ screen_test (Rust, VT3)
        └─ DRM                → /dev/dri/card*
```

### Tekniska detaljer

-   **VT-switching** → Separata virtuella terminaler (tty1, tty2, tty3)
-   **Pyusb** → USB-kommunikation med extern Pico-tester
-   **DMI-detektering** → Platform-specifik logik (DATOR_BB_FÄLT)
-   **Centraliserad loggning** → `/root/diagnostic_report.txt`

---

## Felhantering & Rapportering

### Felhanteringsstrategi

#### Kritiska tester (stoppar vid fel)

-   Stress-test (CPU + RAM)
-   RAM-test (memtester)
-   Disk health (NVMe/SATA)
-   USB-test (data + power)

**Beteende:** Prompt `ask_continue()` → Användare måste bekräfta fortsättning

#### Icke-kritiska tester (fortsätter vid fel)

-   Serial ports (saknas ofta på moderna system)
-   GPS-test (optional hårdvara)
-   Ljudtest (optional hårdvara)

**Beteende:** Varning loggas, sekvensen fortsätter automatiskt

#### Abort-funktion

-   Bakgrundsprocess lyssnar på `'q'` keystroke
-   Kontrollerad avslutning av hela sekvensen
-   Loggar abort-event

### Rapportfiler

#### `/root/diagnostic_report.txt` (huvudlogg)

```
- Alla test-outputs (stdout + stderr)
- ANSI-koder borttagna (sed cleanup för läsbarhet)
- Timestamp för varje test
- Strukturerad formatering
```

### Test-utfall (3 nivåer)

| Utfall   | Betydelse                      | Beteende                     |
| -------- | ------------------------------ | ---------------------------- |
| **PASS** | Alla kritiska tester OK        | Fortsätt till nästa test     |
| **FAIL** | Kritisk test misslyckades      | Stoppa, vänta på bekräftelse |
| **WARN** | Icke-kritisk test misslyckades | Logga varning, fortsätt      |

---

## Deployment & Underhåll

### Utvecklingsworkflow (incrementell)

```bash
# 1. Modifiera kod
vim client/startup/run_diagnostic.start
vim client/python/disk_health.py
# ... eller Rust apps

# 2. Skapa nya overlays
./create_overlays.sh
# Kör automatiskt:
#   - build_client_packages.sh (bygger Rust apps om ändrade)
#   - Packar upp befintliga overlays
#   - Uppdaterar filer från packages/
#   - Komprimerar nya overlays
#   - Kopierar till server/package/srv/http/alpine/boot/

# 3. Deploy till PXE-server
scp server/package/srv/http/alpine/boot/x86_64/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86_64/
scp server/package/srv/http/alpine/boot/x86/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86/
```

### Från scratch workflow (sällan)

```bash
# Boota target-dator via PXE utan overlay för att skapa overlay från början
1. Boota target-dator via PXE
   I iPXE menu: Välj "Boot Alpine" → "Boot without Overlay"

2. På target-datorn (clean Alpine):
   setup-alpine  # Konfigurera system (keyboard: se, user: ssh)

3. Från utvecklingsmaskin:
   scp client/packages/x86_64/* ssh@<target-ip>:~
   ssh ssh@<target-ip>
   /home/ssh/setup_client.sh  # Installera + lbu pkg

4. Hämta tillbaka overlay:
   scp ssh@<target-ip>:~/localhost.apkovl.tar.gz \
       ./client/overlays/x86_64.apkovl.tar.gz

5. Deploy till servern:
   scp ./client/overlays/x86_64.apkovl.tar.gz \
       tele@192.168.150.62:/srv/http/alpine/boot/x86_64/localhost.apkovl.tar.gz
```

### Deployment-egenskaper

-   ✓ **Servern kräver ingen omstart** vid overlay-uppdatering
-   ✓ **Clients får nya versionen** vid nästa boot
-   ✓ **Atomic updates** - overlay byts ut helt
-   ✓ **Multi-arch** - x86 och x86_64 parallellt

---

## 🔄 Byta PXE-server (Rock vs Ubuntu)

### Scenario

Du vill byta från Rock 4SE (192.168.200.1) till Ubuntu-server (192.168.150.62) eller tvärtom.

### Vad behöver ändras?

#### 1. iPXE boot-script (`server/ipxe_scripts/boot.ipxe`)

**Ändra server-URL i boot.ipxe:**

```ipxe
# Hitta raden med set_server och ändra IP-adressen
set server 192.168.150.62     # Ubuntu-server
# ELLER
set server 192.168.200.1      # Rock 4SE
```

**Efter ändring:**

```bash
# Rebuild iPXE boot-filer
cd server/ipxe_scripts
./build.sh

# Deploy till servern
scp ../package/srv/tftp/* tele@192.168.150.62:/srv/tftp/
```

#### 2. Alpine overlays - APK repository (`client/overlays/`)

**Båda overlays behöver uppdateras:**

-   `client/overlays/x86_64.apkovl.tar.gz`
-   `client/overlays/x86.apkovl.tar.gz`

**Metod 1: Manuell ändring med -n flaggan** (snabbast)

```bash
# Packa upp befintlig overlay (lättast med ./create_overlays.sh)
./create_overlays.sh

# Ändra repository IP-adress
vim x86_64/etc/apk/repositories
# Ändra raden:
# http://192.168.200.1/alpine/apks/x86_64
# till:
# http://192.168.150.62/alpine/apks/x86_64

# Uppdatera overlay (med -n för att bevara ändringen)
cd ../..
./create_overlays.sh -n

# Deploy till servern
scp server/package/srv/http/alpine/boot/x86_64/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86_64/
scp server/package/srv/http/alpine/boot/x86/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86/
```

### Sammanfattning av ändringar

| Fil/Plats                                       | Vad ändras                       | Verktyg                     |
| ----------------------------------------------- | -------------------------------- | --------------------------- |
| **server/ipxe_scripts/boot.ipxe**               | `set server <IP>`                | vim + ./build.sh            |
| **client/overlays/x86_64/etc/apk/repositories** | `http://<IP>/alpine/apks/x86_64` | vim + create_overlays.sh -n |
| **client/overlays/x86/etc/apk/repositories**    | `http://<IP>/alpine/apks/x86`    | vim + create_overlays.sh -n |

### Viktigt!

⚠️ **Använd alltid -n flaggan** när du kör `create_overlays.sh` efter manuella ändringar i uppackade overlays, annars skrivs dina ändringar över!

---

## ➕ Lägga till ny hårdvara

### Scenario

Du har en ny datormodell med specifik tangentbordslayout eller touchscreen-konfiguration som behöver stöd.

### Vad behöver läggas till?

Allt görs i **input_device_test** Rust-projektet (`client/input_device_test/`).

#### 1. Lägg till hårdvaru-identifierare (machine_detect.rs)

**Fil:** `client/input_device_test/src/machine_detect.rs`

**Lägg till ny hårdvaru-identifiering:**

```rust
// client/input_device_test/src/machine_detect.rs

pub enum MachineType {
    DatorBbFalt,
    NyDatorModell,    // <-- Lägg till här
    Generic,
}

pub fn detect_machine() -> MachineType {
    // Läs DMI-information
    let product_name = read_dmi_field("product_name");
    let board_name = read_dmi_field("board_name");

    // Lägg till detektering baserat på DMI-info
    if product_name.contains("NY_DATOR") || board_name.contains("NY_BOARD") {
        return MachineType::NyDatorModell;
    }

    if product_name.contains("DATOR_BB_FÄLT") {
        return MachineType::DatorBbFalt;
    }

    MachineType::Generic
}
```

**Hitta DMI-värden för din hårdvara:**

```bash
# På target-datorn (Alpine eller Linux):
cat /sys/class/dmi/id/product_name
cat /sys/class/dmi/id/board_name
cat /sys/class/dmi/id/sys_vendor
```

#### 2. Lägg till tangentbordslayout (keyboard_layouts.rs)

**Fil:** `client/input_device_test/src/keyboard_layouts.rs`

**Skapa ny layout-definition:**

```rust
// client/input_device_test/src/keyboard_layouts.rs

// Keyboard layout är en nested array av tuples
pub const NY_DATOR_LAYOUT: KeyboardLayout = &[
    &[&[
        // Sektion 1 - Huvudområde (Function keys + Sifferrad + Bokstavsrader)
        &[
            // Rad 1 (Function keys)
            ("ESC", &[KeyCode::KEY_ESC]),
            ("F1", &[KeyCode::KEY_F1]),
            ("F2", &[KeyCode::KEY_F2]),
            // ... fortsätt med alla function keys
        ],
        &[
            // Rad 2 (Sifferraden)
            ("§", &[KeyCode::KEY_GRAVE]),
            ("1", &[KeyCode::KEY_1]),
            ("2", &[KeyCode::KEY_2]),
            // ... fortsätt med alla siffror

            // Observera: För tangenter som kan triggas av flera KeyCodes:
            ("7", &[KeyCode::KEY_7, KeyCode::KEY_KP7]),  // Både normal 7 och numpad 7
        ],
        &[
            // Rad 3 (Övre bokstavsraden)
            ("Tab", &[KeyCode::KEY_TAB]),
            ("Q", &[KeyCode::KEY_Q]),
            ("W", &[KeyCode::KEY_W]),
            // ... fortsätt med alla tangenter i raden
        ],
        // ... fortsätt för alla rader
    ]],
    // Lägg till fler sektioner om nödvändigt (numpad, piltangenter, etc.)
];
```

**Strukturen:**

-   `KeyboardLayout = &'static [&'static [KeyLayout]]` - Topnivå array av layoutsektioner
-   `KeyLayout = &'static [&'static [(&'static str, &'static [KeyCode])]]` - Sektion av tangentriader
-   Varje tangent: `(label: &str, keycodes: &[KeyCode])` - Label och KeyCode-array
-   **Flera KeyCodes per tangent:** Använd array för tangenter som kan triggas av flera hårdvarukoder

**Tips för att skapa layout:**

-   Kopiera `DATOR_BB_FÄLT_OLD_LAYOUT` eller `DATOR_BB_FÄLT_NEW_LAYOUT` som mall
-   **Kör `input_device_test` med en temporär/fel layout först** - programmet visar KeyCodes i headern när du trycker tangenter, vilket gör det enkelt att se vilka koder din hårdvara skickar
-   Alternativt: Använd `evtest /dev/input/eventX` från kommandoraden
-   Använd arrays för dubbelverkande tangenter (ex. `&[KeyCode::KEY_7, KeyCode::KEY_KP7]`)
-   Testa iterativt tills alla tangenter mappar korrekt

#### 3. Använd layout i keyboard_test.rs

**Fil:** `client/input_device_test/src/keyboard_test.rs`

**Uppdatera layout-valet:**

```rust
// client/input_device_test/src/keyboard_test.rs

use crate::machine_detect::{detect_machine, MachineType};
use crate::keyboard_layouts::*;

pub fn run_keyboard_test() -> Result<()> {
    let machine = detect_machine();

    let layout = match machine {
        MachineType::DatorBbFalt => DATOR_BB_FÄLT_OLD_LAYOUT,
        MachineType::NyDatorModell => NY_DATOR_LAYOUT,  // <-- Använd här
        MachineType::Generic => SWEDISH_QWERTY_LAYOUT,
    };

    // ... fortsätt med test
}
```

#### 4. (Optional) Konfigurera vilka tester som ska visas

Om din hårdvara har specifika input-enheter (touchscreen, mus, etc.):

**Fil:** `client/input_device_test/src/machine_detect.rs`

```rust
// Lägg till funktioner för att specificera vilka tester som ska köras
impl MachineType {
    pub fn has_touchscreen(&self) -> bool {
        match self {
            MachineType::DatorBbFalt => true,
            MachineType::NyDatorModell => true,   // <-- Om ny hårdvara har touchscreen
            MachineType::Generic => false,
        }
    }

    pub fn has_mouse(&self) -> bool {
        match self {
            MachineType::DatorBbFalt => false,
            MachineType::NyDatorModell => true,   // <-- Om ny hårdvara har musplatta
            MachineType::Generic => true,
        }
    }
}
```

Detta styr vilka test-tabs som visas i `input_device_test` TUI:n.

### Rebuild och deploy

Efter ändringar:

```bash
# Skapa nya overlays
./create_overlays.sh

# Deploy till servern
scp server/package/srv/http/alpine/boot/x86_64/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86_64/
scp server/package/srv/http/alpine/boot/x86/* \
    tele@192.168.150.62:/srv/http/alpine/boot/x86/
```

### Testning

1. **Boota target-dator via PXE**
2. **Verifiera hårdvaru-detektering:**
    - Kontrollera att rätt layout används
    - Testa alla tangenter visuellt
3. **Om fel layout:**
    - Dubbelkolla DMI-värden (`cat /sys/class/dmi/id/*`)
    - Verifiera match-logik i `machine_detect.rs`
4. **Om tangenter mappar fel:**
    - Använd `evtest` för att se vilka KeyCodes hårdvaran skickar
    - Justera layout-positioner

### Sammanfattning - Filer att ändra

| Fil                     | Vad görs                                             | Syfte                        |
| ----------------------- | ---------------------------------------------------- | ---------------------------- |
| **machine_detect.rs**   | Lägg till enum + detekteringslogik + has\_\*-metoder | Identifiera hårdvara via DMI |
| **keyboard_layouts.rs** | Skapa ny layout-const                                | Definiera tangentpositioner  |
| **keyboard_test.rs**    | Använd layout baserat på maskin                      | Välj rätt layout vid runtime |

---
