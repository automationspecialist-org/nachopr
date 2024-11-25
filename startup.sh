#!/bin/sh
set -e

# Debug logging
echo "Starting startup script..."

if [ -n "$AZURE" ]; then
    echo "Starting SSH service..."
    service ssh start || echo "Failed to start SSH"
    mkdir -p /home/persistent
    chmod 755 /home/persistent
    service memcached start
    touch /var/log/cron.log
    printenv | grep -Ev 'BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|LANG|PWD|GPG_KEY|_=' >> /etc/environment
    uv run manage.py crontab remove
    uv run manage.py crontab add
    service cron start
fi

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



# Send a message to Slack when restarting
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -X POST -H 'Content-type: application/json' --data '{"text":"The nachopr application is restarting."}' "$SLACK_WEBHOOK_URL"
else
    echo "SLACK_WEBHOOK_URL is not set. Skipping Slack notification."
fi

# Append environment variables to the Celery Supervisor config
printenv | grep -Ev 'BASHOPTS|BASH_VERSINFO|EUID|PPID|SHELLOPTS|UID|LANG|PWD|GPG_KEY|_=' | while read -r line; do
    echo "environment=$line" >> /etc/supervisor/conf.d/celery.conf
done

# start celery worker - in dev: uv run celery -A core worker --queues=celery
echo "Starting supervisor..."
supervisord -c /etc/supervisor/supervisord.conf

echo "Starting Granian..."
exec uv run granian --interface asginl \
    --host 0.0.0.0 \
    --port 80 \
    --workers 4 \
    nachopr.asgi:application
