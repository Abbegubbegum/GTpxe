#!/bin/sh

make bin/undionly.kpxe EMBED=boot.ipxe
cp bin/undionly.kpxe ../../package/srv/tftp/boot.kpxe