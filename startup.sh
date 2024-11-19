#!/bin/sh
set -e
if [ -n "$AZURE" ]; then
    service ssh start
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
uv run manage.py clean_db
uv run manage.py algolia_reindex
uv run manage.py crontab remove

if [ -n "$AZURE" ]; then
    uv run manage.py crontab add
    uv run manage.py crontab show
fi

uv run manage.py create_admin_user
uv run manage.py add_news_sources
uv run manage.py collectstatic --no-input
#uv run manage.py generate_social_img


# Send a message to Slack when restarting
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -X POST -H 'Content-type: application/json' --data '{"text":"The nachopr application is restarting."}' "$SLACK_WEBHOOK_URL"
else
    echo "SLACK_WEBHOOK_URL is not set. Skipping Slack notification."
fi

uv run granian --interface asgi --host 0.0.0.0 --port 80 --workers 4 nachopr.asgi:application
