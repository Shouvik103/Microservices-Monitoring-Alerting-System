"""
Alerter Service
===============
Consumes health-check results from the RabbitMQ ``health.results``
queue, evaluates alert conditions (DOWN / SLOW / RECOVERED), and
dispatches notifications via Slack webhook and SMTP email.
"""

import json
import logging
import os
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pika
import psycopg2
import psycopg2.pool
import requests as http_requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "monitoring")
POSTGRES_USER = os.getenv("POSTGRES_USER", "monitor")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "monitor_secret_pass")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")

SLOW_THRESHOLD_MS = int(os.getenv("SLOW_THRESHOLD_MS", "2000"))
ALERT_COOLDOWN_SECONDS = 300  # 5 minutes

QUEUE_NAME = "health.results"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("alerter")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
last_known_status: dict[int, str] = {}       # service_id → "UP" | "DOWN"
last_alert_time: dict[int, float] = {}       # service_id → epoch seconds

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_pool(min_conn: int = 1, max_conn: int = 5):
    """Create a PostgreSQL connection pool with retries."""
    for attempt in range(1, 31):
        try:
            pool = psycopg2.pool.ThreadedConnectionPool(
                min_conn,
                max_conn,
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                dbname=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
            )
            logger.info("PostgreSQL pool created (attempt %d)", attempt)
            return pool
        except psycopg2.OperationalError as exc:
            logger.warning(
                "PostgreSQL not ready (attempt %d/30): %s", attempt, exc
            )
            time.sleep(2)
    raise RuntimeError("Could not connect to PostgreSQL after 30 attempts")


def save_alert(pool, service_id: int, alert_type: str, message: str):
    """Insert an alert row into the ``alerts`` table."""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (service_id, alert_type, message, sent_at)
                VALUES (%s, %s, %s, %s)
                """,
                (service_id, alert_type, message, datetime.now(timezone.utc)),
            )
        conn.commit()
        logger.info(
            "Alert saved: service_id=%s type=%s", service_id, alert_type
        )
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to save alert to DB: %s", exc)
    finally:
        pool.putconn(conn)

# ---------------------------------------------------------------------------
# RabbitMQ helpers
# ---------------------------------------------------------------------------

def get_rabbitmq_connection():
    """Establish a blocking RabbitMQ connection with retries."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300,
    )
    for attempt in range(1, 31):
        try:
            connection = pika.BlockingConnection(params)
            logger.info("Connected to RabbitMQ (attempt %d)", attempt)
            return connection
        except pika.exceptions.AMQPConnectionError as exc:
            logger.warning(
                "RabbitMQ not ready (attempt %d/30): %s", attempt, exc
            )
            time.sleep(2)
    raise RuntimeError("Could not connect to RabbitMQ after 30 attempts")

# ---------------------------------------------------------------------------
# Notification senders
# ---------------------------------------------------------------------------

EMOJI = {"DOWN": "\U0001f6a8", "SLOW": "\u26a0\ufe0f", "RECOVERED": "\u2705"}


def send_slack_alert(alert_type: str, service_name: str,
                     status: str, response_time_ms: float,
                     timestamp: str):
    """Post a formatted message to the Slack webhook."""
    if not SLACK_WEBHOOK_URL or SLACK_WEBHOOK_URL.startswith("https://hooks.slack.com/services/REPLACE"):
        logger.warning("Slack webhook not configured — skipping Slack alert")
        return

    emoji = EMOJI.get(alert_type, "")
    text = (
        f"{emoji} *{alert_type}* — *{service_name}*\n"
        f"> Status: `{status}` | Response: `{response_time_ms:.0f}ms`\n"
        f"> Time: {timestamp}"
    )
    try:
        resp = http_requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": text},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Slack alert sent for %s", service_name)
        else:
            logger.error(
                "Slack webhook returned %s: %s", resp.status_code, resp.text
            )
    except Exception as exc:
        logger.error("Failed to send Slack alert: %s", exc)


def send_email_alert(alert_type: str, service_name: str,
                     status: str, response_time_ms: float,
                     timestamp: str):
    """Send an HTML-formatted email alert via SMTP."""
    if not SMTP_USER or not ALERT_EMAIL:
        logger.warning("SMTP not configured — skipping email alert")
        return

    emoji = EMOJI.get(alert_type, "")
    subject = f"{emoji} [{alert_type}] {service_name}"

    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif; padding:20px;">
      <h2 style="color:{'#e74c3c' if alert_type == 'DOWN'
                        else '#f39c12' if alert_type == 'SLOW'
                        else '#27ae60'};">
        {emoji} Service Alert: {alert_type}
      </h2>
      <table style="border-collapse:collapse; width:100%; max-width:500px;">
        <tr><td style="padding:8px; border:1px solid #ddd;"><b>Service</b></td>
            <td style="padding:8px; border:1px solid #ddd;">{service_name}</td></tr>
        <tr><td style="padding:8px; border:1px solid #ddd;"><b>Status</b></td>
            <td style="padding:8px; border:1px solid #ddd;">{status}</td></tr>
        <tr><td style="padding:8px; border:1px solid #ddd;"><b>Response Time</b></td>
            <td style="padding:8px; border:1px solid #ddd;">{response_time_ms:.0f} ms</td></tr>
        <tr><td style="padding:8px; border:1px solid #ddd;"><b>Timestamp</b></td>
            <td style="padding:8px; border:1px solid #ddd;">{timestamp}</td></tr>
      </table>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [ALERT_EMAIL], msg.as_string())
        logger.info("Email alert sent for %s to %s", service_name, ALERT_EMAIL)
    except Exception as exc:
        logger.error("Failed to send email alert: %s", exc)

# ---------------------------------------------------------------------------
# Alert evaluation
# ---------------------------------------------------------------------------

def evaluate_and_alert(data: dict, db_pool):
    """
    Decide whether an alert should fire and, if so, dispatch it
    through all configured channels.
    """
    service_id = data["service_id"]
    service_name = data["service_name"]
    status = data["status"]
    response_time_ms = data.get("response_time_ms", 0) or 0
    timestamp = data["checked_at"]

    now = time.time()
    previous_status = last_known_status.get(service_id)
    alert_type = None

    # --- Determine alert type ---
    if status == "UP" and previous_status == "DOWN":
        alert_type = "RECOVERED"
    elif status == "DOWN":
        last_sent = last_alert_time.get(service_id, 0)
        if now - last_sent >= ALERT_COOLDOWN_SECONDS:
            alert_type = "DOWN"
    elif status == "UP" and response_time_ms > SLOW_THRESHOLD_MS:
        alert_type = "SLOW"

    # --- Update in-memory state ---
    last_known_status[service_id] = status

    if alert_type is None:
        return

    message = (
        f"[{alert_type}] {service_name} — status={status}, "
        f"response_time={response_time_ms:.0f}ms, time={timestamp}"
    )
    logger.info("Alert triggered: %s", message)

    # --- Dispatch ---
    send_slack_alert(alert_type, service_name, status, response_time_ms, timestamp)
    send_email_alert(alert_type, service_name, status, response_time_ms, timestamp)
    save_alert(db_pool, service_id, alert_type, message)

    if alert_type == "DOWN":
        last_alert_time[service_id] = now

# ---------------------------------------------------------------------------
# Consumer callback
# ---------------------------------------------------------------------------

def make_callback(db_pool):
    """Return a pika callback that evaluates alert conditions."""

    def callback(ch, method, _properties, body):
        try:
            data = json.loads(body)
            evaluate_and_alert(data, db_pool)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON: %s", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as exc:
            logger.error("Error processing message: %s", exc)
            ch.basic_ack(delivery_tag=method.delivery_tag)

    return callback

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("Alerter starting …")

    db_pool = get_db_pool()

    while True:
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=10)
            channel.basic_consume(
                queue=QUEUE_NAME,
                on_message_callback=make_callback(db_pool),
                auto_ack=False,
            )
            logger.info("Waiting for messages on queue '%s' …", QUEUE_NAME)
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as exc:
            logger.error(
                "RabbitMQ connection lost: %s — reconnecting in 5s", exc
            )
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down …")
            break
        except Exception as exc:
            logger.error("Unexpected error: %s — reconnecting in 5s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
