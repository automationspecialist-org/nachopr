#!/bin/sh
set -e
if [ -n "$AZURE" ]; then
    service ssh start
fi
mkdir -p /home/persistent
chmod 777 /home/persistent
service memcached start
python manage.py migrate
python manage.py create_admin_user
python manage.py add_news_sources
python manage.py collectstatic --no-input


# Send a message to Slack when restarting
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -X POST -H 'Content-type: application/json' --data '{"text":"The nachopr application is restarting."}' "$SLACK_WEBHOOK_URL"
else
    echo "SLACK_WEBHOOK_URL is not set. Skipping Slack notification."
fi

granian --interface asgi --host 0.0.0.0 --port 80 --workers 4 nachopr.asgi:application & python manage.py crawl
