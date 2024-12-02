FROM typesense/typesense:0.25.1 as typesense

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHON_VERSION=3.11

# Copy Typesense binary from official image
COPY --from=typesense /opt/typesense-server /usr/local/bin/typesense-server

# Add deadsnakes PPA for Python 3.11
RUN apt-get update && apt-get install -y software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa

# Install Python and basic dependencies
RUN apt-get update && apt-get install -y \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    python${PYTHON_VERSION}-dev \
    python3-pip \
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
    redis-server \
    supervisor \
    postgresql-client \
    && ln -sf /usr/bin/python${PYTHON_VERSION} /usr/bin/python3 \
    && ln -sf /usr/bin/python${PYTHON_VERSION} /usr/bin/python

# Install Rust and Cargo
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && . $HOME/.cargo/env

# Setup Redis
RUN mkdir -p /var/log/redis \
    && chown -R redis:redis /var/log/redis

# Setup logging directories
RUN mkdir -p /var/log/celery \
    && mkdir -p /etc/supervisor/conf.d \
    && mkdir -p /var/log/typesense

# Copy supervisor configurations
COPY supervisor/celeryworker.conf /etc/supervisor/conf.d/
COPY supervisor/celerybeat.conf /etc/supervisor/conf.d/
COPY supervisor/redis.conf /etc/supervisor/conf.d/
COPY supervisor/typesense.conf /etc/supervisor/conf.d/
COPY supervisor/celeryflower.conf /etc/supervisor/conf.d/

# Configure SSH
RUN echo "root:Docker!" | chpasswd \
    && mkdir -p /run/sshd
COPY sshd_config /etc/ssh/
RUN chmod 755 /etc/ssh/sshd_config

# Configure paths
ENV LD_LIBRARY_PATH=/usr/local/lib
ENV PATH="/root/.cargo/bin:${PATH}"

# Install uv
RUN pip install uv

# Setup application
RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

# Install Python dependencies
COPY pyproject.toml* uv.lock* /usr/src/app/
RUN uv venv /usr/src/app/venv \
    && . /usr/src/app/venv/bin/activate \
    && uv sync --frozen
ENV PATH="/usr/src/app/venv/bin:$PATH"

# Copy application code
COPY . /usr/src/app/

# Setup startup script
COPY startup.sh /usr/src/app/
RUN chmod +x /usr/src/app/startup.sh && rm -rf /var/lib/apt/lists/* /tmp/*

EXPOSE 80 5555

ENTRYPOINT ["/usr/src/app/startup.sh"]

 