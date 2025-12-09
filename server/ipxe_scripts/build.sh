#!/bin/sh

rm -rf ../ipxe/src/boot.ipxe

cp boot.ipxe ../ipxe/src/boot.ipxe

cd ../ipxe/src || exit 1

make bin/undionly.kpxe EMBED=boot.ipxe
make bin-x86_64-efi/snponly.efi EMBED=boot.ipxe
cp bin/undionly.kpxe ../../package/srv/tftp/boot.kpxe
cp bin-x86_64-efi/snponly.efi ../../package/srv/tftp/snponly.efi