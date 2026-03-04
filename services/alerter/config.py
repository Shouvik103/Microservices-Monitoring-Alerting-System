"""
Alerter Configuration
=====================
Environment variables, constants, and logging setup.
"""

import logging
import os

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "monitoring")
POSTGRES_USER = os.getenv("POSTGRES_USER", "monitor")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "monitor_secret_pass")

# ---------------------------------------------------------------------------
# RabbitMQ
# ---------------------------------------------------------------------------
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")

# ---------------------------------------------------------------------------
# Thresholds & constants
# ---------------------------------------------------------------------------
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
