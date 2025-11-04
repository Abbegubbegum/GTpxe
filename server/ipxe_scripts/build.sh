#!/bin/sh

make bin/undionly.kpxe EMBED=boot.ipxe
cp bin/undionly.kpxe ../../package/boot/tftp/boot.kpxe