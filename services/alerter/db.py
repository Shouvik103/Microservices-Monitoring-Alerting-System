"""
Database Helpers
================
PostgreSQL connection pool creation, alert persistence,
incident management, and custom alert rule fetching.
"""

import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.pool

from config import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    logger,
)


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


def create_incident(pool, service_id: int):
    """Open a new incident for a service going DOWN."""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            # Only create if there is no ongoing incident for this service
            cur.execute(
                "SELECT id FROM incidents WHERE service_id = %s AND status = 'ongoing'",
                (service_id,),
            )
            if cur.fetchone():
                return  # already an ongoing incident
            cur.execute(
                "INSERT INTO incidents (service_id, started_at, status) VALUES (%s, %s, 'ongoing')",
                (service_id, datetime.now(timezone.utc)),
            )
        conn.commit()
        logger.info("Incident created for service_id=%s", service_id)
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to create incident: %s", exc)
    finally:
        pool.putconn(conn)


def resolve_incident(pool, service_id: int):
    """Resolve the ongoing incident for a service that RECOVERED."""
    conn = pool.getconn()
    try:
        now = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, started_at FROM incidents WHERE service_id = %s AND status = 'ongoing'",
                (service_id,),
            )
            row = cur.fetchone()
            if not row:
                return  # no ongoing incident
            incident_id, started_at = row
            duration = int((now - started_at).total_seconds())
            cur.execute(
                "UPDATE incidents SET resolved_at = %s, duration_s = %s, status = 'resolved' WHERE id = %s",
                (now, duration, incident_id),
            )
        conn.commit()
        logger.info("Incident %s resolved (duration=%ds)", incident_id, duration)
    except Exception as exc:
        conn.rollback()
        logger.error("Failed to resolve incident: %s", exc)
    finally:
        pool.putconn(conn)


def fetch_alert_rules_for_service(pool, service_id: int) -> list:
    """Fetch active custom alert rules for a given service."""
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, metric, operator, threshold, severity, cooldown_s, description "
                "FROM alert_rules WHERE service_id = %s AND is_active = TRUE",
                (service_id,),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "metric": r[1],
                    "operator": r[2],
                    "threshold": r[3],
                    "severity": r[4],
                    "cooldown_s": r[5],
                    "description": r[6],
                }
                for r in rows
            ]
    except Exception as exc:
        logger.error("Failed to fetch alert rules: %s", exc)
        return []
    finally:
        pool.putconn(conn)
