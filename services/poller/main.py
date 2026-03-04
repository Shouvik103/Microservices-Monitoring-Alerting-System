"""
Poller Service
==============
Periodically polls all active microservices for health and publishes
results to the RabbitMQ ``health.results`` queue.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import pika
import psycopg2
import psycopg2.pool
import requests

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

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))
SERVICE_REFRESH_INTERVAL = 300  # 5 minutes
REQUEST_TIMEOUT = 5  # seconds

QUEUE_NAME = "health.results"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("poller")

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_connection_pool(min_conn: int = 1, max_conn: int = 5):
    """Create a thread-safe PostgreSQL connection pool with retries."""
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
            logger.info("Connected to PostgreSQL (attempt %d)", attempt)
            return pool
        except psycopg2.OperationalError as exc:
            logger.warning(
                "PostgreSQL not ready (attempt %d/30): %s", attempt, exc
            )
            time.sleep(2)
    raise RuntimeError("Could not connect to PostgreSQL after 30 attempts")


def fetch_active_services(pool):
    """Return list of active services from the database."""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, url, check_interval, custom_headers, check_method, check_body "
                "FROM services WHERE is_active = TRUE"
            )
            rows = cur.fetchall()
            services = []
            for row in rows:
                headers = row[4] if row[4] else {}
                # Ensure headers is a dict (psycopg2 auto-parses JSONB)
                if isinstance(headers, str):
                    import json as _json
                    headers = _json.loads(headers)
                services.append({
                    "id": row[0],
                    "name": row[1],
                    "url": row[2],
                    "check_interval": row[3],
                    "custom_headers": headers,
                    "check_method": row[5] or "GET",
                    "check_body": row[6],
                })
            logger.info("Fetched %d active service(s) from DB", len(services))
            return services
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
# Health-check logic
# ---------------------------------------------------------------------------

def check_service(service: dict) -> dict:
    """
    Check a service using the configured method (GET, POST, HEAD, or TCP).
    Custom headers from the DB are included in HTTP requests.
    """
    method = service.get("check_method", "GET").upper()
    headers = service.get("custom_headers") or {}
    start = time.time()

    if method == "TCP":
        return _check_tcp(service, start)

    return _check_http(service, method, headers, start)


def _check_tcp(service: dict, start: float) -> dict:
    """Perform a raw TCP connection check (host:port)."""
    import socket

    url = service["url"]
    # Strip protocol prefix if accidentally provided
    addr = url.replace("https://", "").replace("http://", "").strip("/")
    if ":" in addr:
        host, port_str = addr.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 443
    else:
        host = addr
        port = 443

    try:
        sock = socket.create_connection((host, port), timeout=REQUEST_TIMEOUT)
        elapsed_ms = round((time.time() - start) * 1000, 2)
        sock.close()
        return {
            "service_id": service["id"],
            "service_name": service["name"],
            "url": service["url"],
            "status": "UP",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "check_method": "TCP",
        }
    except socket.timeout:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "service_id": service["id"],
            "service_name": service["name"],
            "url": service["url"],
            "status": "DOWN",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": f"TCP connection timed out after {REQUEST_TIMEOUT}s",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "check_method": "TCP",
        }
    except Exception as exc:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "service_id": service["id"],
            "service_name": service["name"],
            "url": service["url"],
            "status": "DOWN",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": str(exc),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "check_method": "TCP",
        }


def _check_http(service: dict, method: str, headers: dict, start: float) -> dict:
    """Perform an HTTP health check using GET, POST, or HEAD."""
    try:
        body = service.get("check_body")
        kwargs = {
            "url": service["url"],
            "timeout": REQUEST_TIMEOUT,
            "headers": headers,
        }
        if method == "POST":
            kwargs["data"] = body
            resp = requests.post(**kwargs)
        elif method == "HEAD":
            resp = requests.head(**kwargs)
        else:  # GET (default)
            resp = requests.get(**kwargs)

        elapsed_ms = round((time.time() - start) * 1000, 2)
        status = "UP" if 200 <= resp.status_code < 300 else "DOWN"
        return {
            "service_id": service["id"],
            "service_name": service["name"],
            "url": service["url"],
            "status": status,
            "response_time_ms": elapsed_ms,
            "status_code": resp.status_code,
            "error": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "check_method": method,
        }
    except requests.exceptions.Timeout:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "service_id": service["id"],
            "service_name": service["name"],
            "url": service["url"],
            "status": "DOWN",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": f"{method} request timed out after {REQUEST_TIMEOUT}s",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "check_method": method,
        }
    except requests.exceptions.RequestException as exc:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "service_id": service["id"],
            "service_name": service["name"],
            "url": service["url"],
            "status": "DOWN",
            "response_time_ms": elapsed_ms,
            "status_code": None,
            "error": str(exc),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "check_method": method,
        }

# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

def publish_result(channel, result: dict):
    """Publish a health-check result to the RabbitMQ queue."""
    channel.basic_publish(
        exchange="",
        routing_key=QUEUE_NAME,
        body=json.dumps(result),
        properties=pika.BasicProperties(
            delivery_mode=2,  # persistent
            content_type="application/json",
        ),
    )
    logger.info(
        "Published: service=%s method=%s status=%s time=%.1fms",
        result["service_name"],
        result.get("check_method", "GET"),
        result["status"],
        result["response_time_ms"],
    )

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    logger.info("Poller starting …")

    db_pool = get_db_connection_pool()
    rmq_connection = get_rabbitmq_connection()
    channel = rmq_connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    services = fetch_active_services(db_pool)
    last_refresh = time.time()

    while True:
        # Refresh service list every SERVICE_REFRESH_INTERVAL seconds
        if time.time() - last_refresh >= SERVICE_REFRESH_INTERVAL:
            try:
                services = fetch_active_services(db_pool)
                last_refresh = time.time()
            except Exception as exc:
                logger.error("Failed to refresh services: %s", exc)

        for svc in services:
            try:
                result = check_service(svc)

                # Reconnect to RabbitMQ if needed
                if rmq_connection.is_closed:
                    logger.warning("RabbitMQ connection lost — reconnecting")
                    rmq_connection = get_rabbitmq_connection()
                    channel = rmq_connection.channel()
                    channel.queue_declare(queue=QUEUE_NAME, durable=True)

                publish_result(channel, result)
            except Exception as exc:
                logger.error(
                    "Error polling service %s: %s", svc["name"], exc
                )
                # Attempt to reconnect for the next iteration
                try:
                    if rmq_connection.is_closed:
                        rmq_connection = get_rabbitmq_connection()
                        channel = rmq_connection.channel()
                        channel.queue_declare(queue=QUEUE_NAME, durable=True)
                except Exception as reconn_exc:
                    logger.error("RabbitMQ reconnection failed: %s", reconn_exc)

        logger.info("Sleeping %ds until next poll cycle …", CHECK_INTERVAL)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
