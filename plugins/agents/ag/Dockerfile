ARG BASE_IMAGE=sanity-gravity:_base-xfce
FROM ${BASE_IMAGE}

# The browser comes from the desktop layer below (ag requires a display,
# so there is always one): Chrome/chromium, the --no-sandbox wrapper and
# the x-www-browser registration are installed once per desktop rather
# than once per agent. The IDE's own browser integration finds it as
# /usr/bin/google-chrome, and the arm64 path the IDE hard-codes
# (/opt/google/chrome/google-chrome) is linked at container start by
# rootfs/etc/entrypoint.d/10-ag-startup.sh. The browser has to be in the
# container for another reason now: 2.x sign-in ends in an
# antigravity-ide:// deep link back to the IDE, which only resolves for a
# browser running beside it.

# The standalone Antigravity IDE, from the official tarball, pinned by
# version + build id and verified against the sha256 Google publishes for
# that exact artifact.
#
# It replaces an apt install that can no longer work. The repo it used
# (us-central1-apt.pkg.dev, suite antigravity-debian) froze on
# 2026-04-16 with antigravity_1.23.2 as its newest package, and 1.x is
# deprecated: the language-server certificate that build bundles expired
# on 2026-09-04, after which every extension-to-language-server call
# fails in the TLS handshake and the Agent Manager stops answering with
# no error a user can act on. Upstream's position is that 1.x gets no
# fix. There is no 2.x package in any apt or yum repo - 2.x is a tarball
# only. See issue #42.
#
# Bump the version, the build id and both sums together. Both values come
# from Google, and the second is what makes this a cross-check against
# upstream rather than against ourselves:
#   build id  <updater API>/releases              -> .execution_id
#   sha256    <updater API>/api/update/<linux-x64|linux-arm64>/stable/latest
#                                                 -> .sha256hash
# where <updater API> is
#   https://antigravity-ide-auto-updater-974169037036.us-central1.run.app
# The download path spells this architecture linux-arm where that API
# spells it linux-arm64; the tarball behind the first name is genuine
# aarch64.
ARG ANTIGRAVITY_IDE_VERSION=2.5.5
ARG ANTIGRAVITY_IDE_BUILD=4923483625488384
ARG ANTIGRAVITY_DIR=/usr/share/antigravity-ide

COPY rootfs/ /

# The runtime libraries the 1.x deb declared as Depends. A tarball
# declares nothing, so they are named here rather than left to whatever
# the desktop layer below happens to have pulled in - this layer should
# not depend on another layer's transitive dependencies. Ubuntu 24.04
# renamed seven of them with a t64 suffix. Then the tools the install
# itself needs: jq patches product.json, desktop-file-utils registers the
# URL handler, openssl runs the certificate gate below.
#
# gravity-cli does the install so there is one copy of it: the same
# script runs `ide update` inside a live sandbox, and the wrapper and
# .desktop entries a built image carries are therefore the ones
# tests/integration/test_gravity_cli.py reads. They used to be written
# twice - here and there - and the two had already drifted apart.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates desktop-file-utils jq openssl xdg-utils \
        libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
        libcairo2 libcups2t64 libcurl4 libdbus-1-3 libexpat1 libgbm1 \
        libglib2.0-0t64 libgtk-3-0t64 libnspr4 libnss3 libpango-1.0-0 \
        libstdc++6 libudev1 libvulkan1 libx11-6 libxcb1 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxkbfile1 libxrandr2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) sha="0c5233b297d2b3aebb61af49f8944012c2953d361a5ebb16978490636917f831" ;; \
        arm64) sha="88c167108980c33a223a8d7f0aa6aaf4dec61f0cc3950235a2698e9ffc38a49e" ;; \
        *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && /usr/local/bin/gravity-cli ide install \
        "${ANTIGRAVITY_IDE_VERSION}" "${ANTIGRAVITY_IDE_BUILD}" "${sha}"

# A dead Agent Manager must never ship in silence again (#42).
#
# The extension hands this file to connect-node as the only CA for its own
# connection to the language server, so an expired certificate is not a
# warning anywhere - it is every agent call failing in the handshake while
# the UI keeps accepting messages. The one in IDE 2.5.5 runs to
# 2026-11-03, so this gate is also the schedule: 1209600 seconds is 14
# days, and the build goes red while re-pinning is still possible instead
# of on the morning the Agent Manager dies.
#
# A run inside the sandbox warns instead of failing (gravity-cli):
# refusing to finish an update would leave a running container with no
# IDE at all.
RUN cert="${ANTIGRAVITY_DIR}/resources/app/extensions/antigravity/dist/languageServer/cert.pem" \
    && openssl x509 -in "$cert" -noout -subject -dates \
    && if ! openssl x509 -in "$cert" -noout -checkend 1209600; then \
        echo "FATAL: the language-server certificate bundled with Antigravity IDE ${ANTIGRAVITY_IDE_VERSION} is expired or expires within 14 days." >&2; \
        echo "Shipping it would ship a silently dead Agent Manager. Re-pin to a newer IDE build - see issue #42." >&2; \
        exit 1; \
    fi
