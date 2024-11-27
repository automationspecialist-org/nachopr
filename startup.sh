#!/bin/sh
set -e

# Debug logging
echo "Starting startup script..."

# Append environment variables first
printenv | grep -Ev 'BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|LANG|PWD|GPG_KEY|_=' | while read -r line; do
    echo "environment=$line" >> /etc/supervisor/conf.d/celeryworker.conf
    echo "environment=$line" >> /etc/supervisor/conf.d/celerybeat.conf
done

# Source the updated environment
. /etc/environment

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
#uv run manage.py clean_db
uv run manage.py crontab remove

if [ -n "$AZURE" ]; then
    uv run manage.py crontab add
    uv run manage.py crontab show
fi

uv run manage.py create_admin_user
uv run manage.py add_news_sources
uv run manage.py collectstatic --no-input
uv run manage.py generate_social_img
uv run manage.py collectstatic --no-input

# Test OpenAI but don't fail if it doesn't work
echo "Testing OpenAI connection..."
uv run manage.py test_openai || echo "OpenAI test failed but continuing startup..."

# Send a message to Slack when restarting
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -X POST -H 'Content-type: application/json' --data '{"text":"The nachopr application is restarting."}' "$SLACK_WEBHOOK_URL"
else
    echo "SLACK_WEBHOOK_URL is not set. Skipping Slack notification."
fi

# Start supervisor
echo "Starting supervisor..."
supervisord -c /etc/supervisor/supervisord.conf

echo "Starting Granian..."
exec uv run granian --interface asginl \
    --host 0.0.0.0 \
    --port 80 \
    --workers 4 \
    nachopr.asgi:application
