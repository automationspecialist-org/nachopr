#!/bin/sh
set -e

# Debug logging
echo "Starting startup script..."

# Ensure Typesense API key is set
if [ -z "$TYPESENSE_API_KEY" ]; then
    echo "TYPESENSE_API_KEY is not set. Using default value..."
    export TYPESENSE_API_KEY="xyz"
fi

# Create necessary directories
mkdir -p /var/lib/typesense
mkdir -p /var/log/typesense

# Append environment variables first
printenv | grep -Ev 'BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|LANG|PWD|GPG_KEY|_=' | while read -r line; do
    echo "environment=$line" >> /etc/supervisor/conf.d/celeryworker.conf
    echo "environment=$line" >> /etc/supervisor/conf.d/celerybeat.conf
    echo "export $line" >> /root/.bashrc
done

# Start supervisor
echo "Starting supervisor..."
supervisord -c /etc/supervisor/supervisord.conf

# Wait for Typesense to be ready
echo "Waiting for Typesense to be ready..."
i=1
max_attempts=30
while [ $i -le $max_attempts ]; do
    if curl -s -H "X-TYPESENSE-API-KEY: $TYPESENSE_API_KEY" http://127.0.0.1:8108/health > /dev/null; then
        echo "Typesense is ready!"
        break
    fi
    echo "Waiting for Typesense... attempt $i of $max_attempts"
    i=$((i + 1))
    sleep 2
done

if [ $i -gt $max_attempts ]; then
    echo "Typesense failed to start after $max_attempts attempts"
    echo "Checking Typesense logs:"
    tail -n 50 /var/log/typesense/stdout.log
    tail -n 50 /var/log/typesense/stderr.log
    exit 1
fi

if [ -n "$AZURE" ]; then
    echo "Starting SSH service..."
    service ssh start || echo "Failed to start SSH"
    mkdir -p /home/persistent
    chmod 755 /home/persistent
    service memcached start
    touch /var/log/cron.log
    uv run manage.py crontab remove
    uv run manage.py crontab add
    service cron start
fi

# Run Django management commands
uv run manage.py migrate
uv run manage.py create_admin_user
uv run manage.py add_news_sources
#uv run manage.py backfill_journalist_stats
uv run manage.py collectstatic --no-input
uv run manage.py generate_social_img
uv run manage.py collectstatic --no-input

# Trigger Typesense migration in background
echo "Triggering Typesense migration in background..."
uv run manage.py shell -c "from core.tasks import migrate_to_typesense_task; migrate_to_typesense_task.delay()"

# Send a message to Slack when restarting
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -X POST -H 'Content-type: application/json' --data '{"text":"The nachopr application is restarting."}' "$SLACK_WEBHOOK_URL"
else
    echo "SLACK_WEBHOOK_URL is not set. Skipping Slack notification."
fi

echo "Starting Granian..."
exec uv run granian --interface asginl \
    --host 0.0.0.0 \
    --port 80 \
    --workers 4 \
    nachopr.asgi:application
