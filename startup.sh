#!/bin/sh
set -e
if [ -n "$AZURE" ]; then
    service ssh start
    mkdir -p /home/persistent
    chmod 755 /home/persistent
fi
service memcached start
uv run manage.py migrate
uv run manage.py crontab add
uv run manage.py crontab show
uv run manage.py create_admin_user
uv run manage.py add_news_sources
uv run manage.py generate_social_img
uv run manage.py collectstatic --no-input


# Send a message to Slack when restarting
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -X POST -H 'Content-type: application/json' --data '{"text":"The nachopr application is restarting."}' "$SLACK_WEBHOOK_URL"
else
    echo "SLACK_WEBHOOK_URL is not set. Skipping Slack notification."
fi

uv run granian --interface asgi --host 0.0.0.0 --port 80 --workers 4 nachopr.asgi:application
