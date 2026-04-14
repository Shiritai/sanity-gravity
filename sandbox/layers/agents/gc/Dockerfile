ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Gemini CLI Agent Layer
# Installs Node.js LTS and Google Gemini CLI

# Install Node.js 22 LTS via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Gemini CLI globally, then patch npm's bundled picomatch (CVE-2026-33671)
RUN npm install -g @google/gemini-cli && \
    cd /usr/lib/node_modules/npm/node_modules/picomatch && \
    npm pack picomatch@4.0.4 && tar xzf picomatch-4.0.4.tgz --strip-components=1 && rm picomatch-4.0.4.tgz && \
    npm cache clean --force
