#!/bin/sh
# Install the in-container browser and make it the system default.
#
# Run from a desktop layer's Dockerfile (`RUN /usr/local/lib/sanity-gravity/
# install-browser.sh`), never from the base layer: the browser belongs to
# the desktops, and the headless `none` variants must stay headless.
#
# A plugin builds with its own directory as the build context, so it can
# copy nothing from the repo but its own tree. The base image's rootfs is
# the one place three desktop layers can share a file, which is why the
# recipe lives here instead of once per desktop.
set -eu

# Chrome ships no arm64 Linux build, so Apple Silicon hosts get chromium
# from the PPA that packages it for Ubuntu. xdg-utils carries xdg-open,
# where every "open this link" path ends up; Chrome's deb depends on it,
# the chromium route does not, so both branches ask for it by name.
arch=$(dpkg --print-architecture)
if [ "$arch" = "amd64" ]; then
    apt-get update
    apt-get install -y --no-install-recommends gnupg xdg-utils
    mkdir -p /etc/apt/keyrings
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list
    apt-get update
    apt-get install -y --no-install-recommends google-chrome-stable
else
    apt-get update
    apt-get install -y --no-install-recommends software-properties-common xdg-utils
    add-apt-repository -y ppa:xtradeb/apps
    apt-get update
    apt-get install -y --no-install-recommends chromium
    # add-apt-repository was the only reason for it; it pulls in python3
    # and half of dbus-glib, so it leaves with the repository added.
    apt-get remove --purge -y software-properties-common
    apt-get autoremove -y
fi
apt-get clean
rm -rf /var/lib/apt/lists/*

# One wrapper for both architectures. --no-sandbox is not optional: the
# browser's own sandbox needs privileges this container does not grant,
# and --disable-dev-shm-usage keeps it off the small default /dev/shm.
cat > /usr/bin/google-chrome-safe <<'EOF'
#!/bin/bash
CHROME_FLAGS="--no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run --no-default-browser-check"
if [ -f "/usr/bin/chromium" ]; then
    exec /usr/bin/chromium $CHROME_FLAGS "$@"
elif [ -f "/opt/google/chrome/google-chrome" ]; then
    exec /opt/google/chrome/google-chrome $CHROME_FLAGS "$@"
else
    echo "No browser executable found!"
    exit 1
fi
EOF
chmod +x /usr/bin/google-chrome-safe

# Everything that opens a link has to arrive at the wrapper, not at the
# binary. Two names for callers that spell the binary, whichever arch
# this is.
ln -sf /usr/bin/google-chrome-safe /usr/bin/google-chrome
ln -sf /usr/bin/google-chrome-safe /usr/bin/google-chrome-stable

# The xdg-open chain ends at x-www-browser (xdg-open -> sensible-browser
# -> x-www-browser), and both packages register that link through
# update-alternatives: chrome's deb for /usr/bin/google-chrome-stable,
# chromium's for /usr/bin/chromium. Overwriting the symlink underneath
# alternatives would leave the database naming the bare binary, and the
# next --auto pass (any browser package upgrade) would restore it -
# dropping --no-sandbox, which is the one flag the browser cannot start
# without here. So the wrapper is registered as an alternative and pinned
# in manual mode instead. gnome-www-browser is a second link group with
# the same role; GNOME-flavoured callers read that one.
for alt in x-www-browser gnome-www-browser; do
    update-alternatives --install "/usr/bin/$alt" "$alt" \
        /usr/bin/google-chrome-safe 500
    update-alternatives --set "$alt" /usr/bin/google-chrome-safe
done

# The menu entry the desktop launches. Its file name belongs to whichever
# package was installed - google-chrome.desktop on amd64,
# chromium.desktop from the PPA on arm64 - so it is resolved by glob
# rather than named, and a build where the glob matches nothing fails
# here instead of shipping an entry that starts an unwrapped browser.
# Every Exec line is rewritten, including any Desktop Action's.
patched=0
for f in /usr/share/applications/google-chrome*.desktop \
         /usr/share/applications/chromium*.desktop; do
    [ -f "$f" ] || continue
    sed -i 's|Exec=[^ ]*|Exec=/usr/bin/google-chrome|g' "$f"
    patched=$((patched + 1))
done
if [ "$patched" -eq 0 ]; then
    echo "install-browser: no browser .desktop entry to point at the wrapper" >&2
    exit 1
fi
