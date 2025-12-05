#!/bin/sh

make bin/undionly.kpxe EMBED=boot.ipxe
make bin-x86_64-efi/snponly.efi EMBED=boot.ipxe
cp bin/undionly.kpxe ../../package/srv/tftp/boot.kpxe
cp bin-x86_64-efi/snponly.efi ../../package/srv/tftp/snponly.efi