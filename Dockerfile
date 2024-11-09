FROM library/python:3.11-slim-buster

# Install dependencies for building Python packages
RUN apt-get update \
    && apt-get install -y build-essential \
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
    # Install Rust and Cargo
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    # SQLite installation
    && wget https://www.sqlite.org/2024/sqlite-autoconf-3470000.tar.gz \
    && tar xvfz sqlite-autoconf-3470000.tar.gz \
    && cd sqlite-autoconf-3470000 \
    && ./configure --prefix=/usr/local \
    && make \
    && make install \
    && cd .. \
    && rm -rf sqlite-autoconf-3470000* \
    # cleaning up unused files
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/*

# Update SSH configuration for Azure compatibility
RUN apt-get update \
    && apt-get install -y --no-install-recommends dialog openssh-server \
    && echo "root:Docker!" | chpasswd \
    && mkdir -p /run/sshd \
    && cp sshd_config /etc/ssh/ \
    && chmod 755 /etc/ssh/sshd_config

# Configure SQLite
ENV LD_LIBRARY_PATH=/usr/local/lib

# Add cargo to PATH
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip install uv

# Create a virtual environment using uv
RUN uv venv /usr/src/app/venv
ENV PATH="/usr/src/app/venv/bin:$PATH"

RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

# Copy just requirements files first for better layer caching
COPY pyproject.toml* uv.lock* /usr/src/app/

# Pre-download and cache dependencies
RUN uv sync --frozen

# Copy application code
COPY . /usr/src/app/

# Modify startup script to ensure SSH starts properly
COPY startup.sh /usr/src/app/
RUN chmod +x /usr/src/app/startup.sh

EXPOSE 80 2222

# Ensure proper initialization
ENTRYPOINT ["/usr/src/app/startup.sh"]
 