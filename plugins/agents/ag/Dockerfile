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
ARG ANTIGRAVITY_IDE_VERSION=2.6.0
ARG ANTIGRAVITY_IDE_BUILD=5526304964083712

# agy, the CLI the 2.6 IDE runs as its Agent Manager backend. Left to
# itself the IDE downloads it on first use and replaces it in the
# background, so the image would pin the editor and not the agent.
# Bump it with the IDE, from the manifest the IDE itself reads:
#   <agy updater>/manifests/<linux_amd64|linux_arm64>.json
#                       -> .version, the build id in .url, .sha512
# where <agy updater> is
#   https://antigravity-cli-auto-updater-974169037036.us-central1.run.app
ARG AGY_VERSION=1.4.8
ARG AGY_BUILD=5447777392656384

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
        amd64) sha="b060a7c7679103b2b619752f8ee7a3088dd241a7d207d4311974b56ea6f94356" \
               agy_sha="b23683771438e72bffe0a2231168f65a16a0d73ed2c7a8460b311dc5fe0c3c9d9dfc6cbfb7d8755173340071aa4cc5c7a552fb5d1be3fdd31c2b7559d67e404a" ;; \
        arm64) sha="4953ccb52bf909582a1711a3dd26d640efb45fe555a17ebeff8bc7e2eaa052de" \
               agy_sha="783ee9edd0f73e853af977e2848294ffb97b67b31ee19dccafb001f03f34b033371a2bb3371b61b78843c61bd4817ef1d2863a2d371b26513ea17d921c584bee" ;; \
        *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && /usr/local/bin/gravity-cli ide install \
        "${ANTIGRAVITY_IDE_VERSION}" "${ANTIGRAVITY_IDE_BUILD}" "${sha}" \
    && /usr/local/bin/gravity-cli agy install \
        "${AGY_VERSION}" "${AGY_BUILD}" "${agy_sha}"
