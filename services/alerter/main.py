"""
Alerter Service
===============
Consumes health-check results from the RabbitMQ ``health.results``
queue, evaluates alert conditions (DOWN / SLOW / RECOVERED), and
dispatches notifications via Slack webhook and SMTP email.

Modules
-------
- config      – environment variables, constants, logging
- db          – PostgreSQL pool, alert/incident persistence
- rabbitmq    – RabbitMQ connection helper
- notifiers   – Slack and email senders
- evaluator   – alert evaluation logic
"""

import json
import time

import pika

from config import QUEUE_NAME, logger
from db import get_db_pool
from rabbitmq import get_rabbitmq_connection
from evaluator import evaluate_and_alert


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
