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
COPY requirements.txt pyproject.toml* poetry.lock* /usr/src/app/

# Pre-download and cache dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-deps -r requirements.txt && \
    uv pip install -r requirements.txt

# Start and enable SSH
RUN apt-get update \
    && apt-get install -y --no-install-recommends dialog \
    && apt-get install -y --no-install-recommends openssh-server \
    && echo "root:Docker!" | chpasswd \
    && chmod u+x ./entrypoint.sh
COPY sshd_config /etc/ssh/

# Copy the rest of the application
COPY . /usr/src/app

EXPOSE 80 2222

CMD ["sh", "./startup.sh"]
 