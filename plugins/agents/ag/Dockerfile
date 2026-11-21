ARG BASE_IMAGE=sanity-gravity:_ubuntu-xfce
FROM ${BASE_IMAGE}

# The browser comes from the desktop layer below (ag requires a display,
# so there is always one): Chrome/chromium, the --no-sandbox wrapper and
# the x-www-browser registration are installed once per desktop rather
# than once per agent. The IDE's own browser integration finds it as
# /usr/bin/google-chrome, the first path its launcher probes, which the
# desktop layer points at the wrapper on both architectures. The browser
# has to be in the container for another reason now: 2.x sign-in ends in
# an antigravity-ide:// deep link back to the IDE, which only resolves for
# a browser running beside it.

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
ARG ANTIGRAVITY_IDE_VERSION=2.8.0
ARG ANTIGRAVITY_IDE_BUILD=6733682917113856

# agy, the CLI the 2.6+ IDE runs as its Agent Manager backend. Left to
# itself the IDE downloads it on first use and replaces it in the
# background, so the image would pin the editor and not the agent.
# Bump it with the IDE, from the manifest the IDE itself reads:
#   <agy updater>/manifests/<linux_amd64|linux_arm64>.json
#                       -> .version, the build id in .url, .sha512
# where <agy updater> is
#   https://antigravity-cli-auto-updater-974169037036.us-central1.run.app
ARG AGY_VERSION=1.5.13
ARG AGY_BUILD=5999302598852608

COPY rootfs/ /

# The runtime libraries the 1.x deb declared as Depends. A tarball
# declares nothing, so they are named here rather than left to whatever
# the desktop layer below happens to have pulled in - this layer should
# not depend on another layer's transitive dependencies. Ubuntu 24.04
# renamed eight of them with a t64 suffix that Debian 12 does not have,
# so the suffix is set per distro. Then the tools the install itself
# needs: jq patches product.json and the agy extension's settings,
# desktop-file-utils registers the URL handler.
#
# gravity-cli does the install so there is one copy of it: the same
# script runs `ide update` inside a live sandbox, and the wrapper and
# .desktop entries a built image carries are therefore the ones
# tests/integration/test_gravity_cli.py reads. They used to be written
# twice - here and there - and the two had already drifted apart.
RUN t64=t64; if [ "$(. /etc/os-release && echo "$ID")" = "debian" ]; then t64=; fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates desktop-file-utils jq xdg-utils \
        libasound2${t64} libatk-bridge2.0-0${t64} libatk1.0-0${t64} \
        libatspi2.0-0${t64} libcairo2 libcups2${t64} libcurl4${t64} libdbus-1-3 \
        libexpat1 libgbm1 libglib2.0-0${t64} libgtk-3-0${t64} libnspr4 \
        libnss3 libpango-1.0-0 \
        libstdc++6 libudev1 libvulkan1 libx11-6 libxcb1 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxkbfile1 libxrandr2 \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) sha="7baa36baab285cb46101af958b8f7be6305458db9a44d8b3d0938d61f38597d7" \
               agy_sha="014b37387703acab1f47cd532c8bb60167a6a3537b0f9891de03f1b1ffa9614307bc83c4b2f7551273b0877d722716b0cd9e26782f6b2a50705db4f05e18c68f" ;; \
        arm64) sha="d8f85ce40306587a80a7478af4de85cb10b83cf26dd9179b902afa9933fcf9f2" \
               agy_sha="dccea2eb455099f5175f0c87cc47b38fcefe4cb0cb44dea3927469bb4bbf68ac3c0b30fc04affb24c17e90959386a93c3785e8e4b8b1a3338ca4e4d57b80057b" ;; \
        *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && /usr/local/bin/gravity-cli ide install \
        "${ANTIGRAVITY_IDE_VERSION}" "${ANTIGRAVITY_IDE_BUILD}" "${sha}" \
    && /usr/local/bin/gravity-cli agy install \
        "${AGY_VERSION}" "${AGY_BUILD}" "${agy_sha}"
