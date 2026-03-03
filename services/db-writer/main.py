"""
DB Writer Service
=================
Consumes health-check results from the RabbitMQ ``health.results``
queue and inserts them into the PostgreSQL ``health_checks`` table.
"""

import json
import logging
import os
import time

import pika
import psycopg2
import psycopg2.pool

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

QUEUE_NAME = "health.results"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("db-writer")

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_pool(min_conn: int = 2, max_conn: int = 10):
    """Create a PostgreSQL connection pool with startup retries."""
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


def save_health_check(pool, data: dict):
    """Insert a single health-check row into ``health_checks``."""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO health_checks
                    (service_id, status, response_time_ms,
                     status_code, error_message, checked_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    data["service_id"],
                    data["status"],
                    data.get("response_time_ms"),
                    data.get("status_code"),
                    data.get("error"),
                    data["checked_at"],
                ),
            )
        conn.commit()
        logger.info(
            "Saved health check: service_id=%s status=%s",
            data["service_id"],
            data["status"],
        )
    except Exception:
        conn.rollback()
        raise
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
# Consumer callback
# ---------------------------------------------------------------------------

def make_callback(pool):
    """Return a pika callback that writes messages to the DB."""

    def callback(ch, method, _properties, body):
        try:
            data = json.loads(body)
            save_health_check(pool, data)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in message: %s", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
            logger.error("DB error — requeueing message: %s", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception as exc:
            logger.error("Unexpected error processing message: %s", exc)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    return callback

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("DB Writer starting …")

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
            logger.error("RabbitMQ connection lost: %s — reconnecting in 5s", exc)
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down …")
            break
        except Exception as exc:
            logger.error("Unexpected error: %s — reconnecting in 5s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
