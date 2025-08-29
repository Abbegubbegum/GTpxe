#/bin/sh

# Run this script to set up the client environment ready for the overlay.
# Run this after running setup-alpine and following the instructions in README.md

# This will remove the comment on the apk community repository, so that we can fetch community packages.
sed -i 's/^\s*#//' /etc/apk/repositories

# Create the local repository
mkdir -p /etc/apk/custom-repo
apk update
apk fetch --recursive --output /etc/apk/custom-repo memtester stress-ng
lbu add /etc/apk/custom-repo/

# Add the diagnostic scripts
mv /home/ssh/startup/* /etc/local.d/
chmod +x /etc/local.d/*.start
# Enable the local service after, because when running setup-alpine, it reboots and we don't want to wait
#rc-update add local default
lbu add /etc/local.d/

# Make the scripts executable
chmod +x /home/ssh/keyboard_test
chmod +x /home/ssh/scripts/*