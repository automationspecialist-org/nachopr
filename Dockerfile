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
    && apt-get install -y cron

# Install Typesense
RUN curl -O https://dl.typesense.org/releases/27.1/typesense-server-27.1-amd64.deb 
    #&& apt install -y ./typesense-server-27.1-amd64.deb 

# Install Redis
RUN apt-get update && apt-get install -y redis-server
# Setup Redis and its logging
RUN mkdir -p /var/log/redis \
    && chown -R redis:redis /var/log/redis

# Setup Supervisor and Celery
RUN apt-get update && apt-get install -y supervisor \
    && mkdir -p /var/log/celery \
    && mkdir -p /etc/supervisor/conf.d \
    && mkdir -p /var/log/typesense

# Copy supervisor configurations
COPY supervisor/celeryworker.conf /etc/supervisor/conf.d/
COPY supervisor/celerybeat.conf /etc/supervisor/conf.d/
COPY supervisor/redis.conf /etc/supervisor/conf.d/
COPY supervisor/typesense.conf /etc/supervisor/conf.d/

RUN apt-get install -y --no-install-recommends dialog openssh-server \
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

# Create Typesense data directory and set permissions
RUN mkdir -p /var/lib/typesense \
    && chown -R typesense:typesense /var/lib/typesense \
    && chmod 755 /var/lib/typesense

# Modify startup script to ensure SSH starts properly
COPY startup.sh /usr/src/app/
RUN chmod +x /usr/src/app/startup.sh && rm -rf /var/lib/apt/lists/* /tmp/*

EXPOSE 80

# Ensure proper initialization
ENTRYPOINT ["/usr/src/app/startup.sh"]

 