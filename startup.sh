service memcached start
python manage.py migrate
python manage.py create_admin_user
python manage.py collectstatic --no-input

# Send a message to Slack when restarting
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    curl -X POST -H 'Content-type: application/json' --data '{"text":"The nachopr application is restarting."}' "$SLACK_WEBHOOK_URL"
else
    echo "SLACK_WEBHOOK_URL is not set. Skipping Slack notification."
fi
gunicorn --bind=0.0.0.0:80 --timeout 600 --workers=4 --chdir nachopr nachopr.wsgi --access-logfile '-' --error-logfile '-'
