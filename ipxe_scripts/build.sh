#!/bin/sh

make bin/undionly.kpxe EMBED=boot.ipxe
cp bin/undionly.kpxe ../../server/boot/boot.kpxe