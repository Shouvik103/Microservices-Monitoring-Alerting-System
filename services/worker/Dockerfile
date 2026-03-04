FROM python:3.11-slim

WORKDIR /app

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# These files are copied from the build context (services/)
COPY poller/main.py      /app/poller/main.py
COPY db-writer/main.py   /app/db-writer/main.py
COPY alerter/main.py     /app/alerter/main.py
COPY worker/supervisord.conf /etc/supervisord.conf

CMD ["supervisord", "-c", "/etc/supervisord.conf"]
