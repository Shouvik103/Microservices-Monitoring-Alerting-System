"""
RabbitMQ Helpers
================
Connection establishment with retry logic.
"""

import time

import pika

from config import RABBITMQ_HOST, RABBITMQ_USER, RABBITMQ_PASS, logger


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
