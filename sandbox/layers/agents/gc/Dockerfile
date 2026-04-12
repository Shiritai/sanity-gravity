# Gemini CLI Agent Layer
# Installs Node.js LTS and Google Gemini CLI

# Install Node.js 22 LTS via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Gemini CLI globally
RUN npm install -g @google/gemini-cli && \
    npm cache clean --force
