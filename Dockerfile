FROM library/python:3.11-slim-buster

# Install dependencies for building Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gettext \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    memcached \
    libmemcached-dev \
    libssl-dev \
    pkg-config \
    curl \
    wget \
    cron \
    dialog \
    openssh-server \
    # psycopg2 dependencies
    && apt-get install -y libpq-dev \
    # Translations dependencies
    && apt-get install -y gettext \
    && apt-get install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info  \
    # Add memcached and its dependencies
    && apt-get install -y memcached libmemcached-dev \
    # Add Rust and Cargo for maturin
    && apt-get install -y libssl-dev pkg-config \
    && apt-get install -y curl \
    && apt-get install -y wget \
    && apt-get install -y cron \
    # Install Rust and Cargo
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    # Install Node.js
    #&& curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    #&& apt-get install -y nodejs \
    #&& npm install -g npm@latest

# Move SQLite installation into its own layer for better caching
RUN wget https://www.sqlite.org/2024/sqlite-autoconf-3470000.tar.gz \
    && tar xvfz sqlite-autoconf-3470000.tar.gz \
    && cd sqlite-autoconf-3470000 \
    && ./configure --prefix=/usr/local \
    && make \
    && make install \
    && cd .. \
    && rm -rf sqlite-autoconf-3470000* \
    # cleaning up unused files
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get install -y --no-install-recommends dialog openssh-server \
    && echo "root:Docker!" | chpasswd \
    && mkdir -p /run/sshd

# Now copy and set permissions for SSH config
COPY sshd_config /etc/ssh/
RUN chmod 755 /etc/ssh/sshd_config

# Configure SQLite
ENV LD_LIBRARY_PATH=/usr/local/lib

# Add cargo to PATH
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip install uv


RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

# Combine Python dependency installation steps
COPY pyproject.toml* uv.lock* /usr/src/app/
RUN uv venv /usr/src/app/venv \
    && . /usr/src/app/venv/bin/activate \
    && uv sync --frozen
ENV PATH="/usr/src/app/venv/bin:$PATH"


# Copy application code
COPY . /usr/src/app/

# Modify startup script to ensure SSH starts properly
COPY startup.sh /usr/src/app/
RUN chmod +x /usr/src/app/startup.sh && rm -rf /var/lib/apt/lists/* /tmp/*

EXPOSE 80 2222

# Ensure proper initialization
ENTRYPOINT ["/usr/src/app/startup.sh"]
 