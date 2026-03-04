"""
Alert Evaluator
================
Core alert evaluation logic — determines when to fire alerts
based on built-in rules and custom per-service rules from the DB.
"""

import time

from config import SLOW_THRESHOLD_MS, ALERT_COOLDOWN_SECONDS, logger
from db import save_alert, create_incident, resolve_incident, fetch_alert_rules_for_service
from notifiers import send_slack_alert, send_email_alert

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
last_known_status: dict[int, str] = {}       # service_id → "UP" | "DOWN"
last_alert_time: dict[int, float] = {}       # service_id → epoch seconds
custom_rule_last_alert: dict[int, float] = {}  # rule_id → epoch seconds


def _compare(value, operator: str, threshold: float) -> bool:
    """Evaluate a comparison expression."""
    ops = {
        ">": lambda v, t: v > t,
        "<": lambda v, t: v < t,
        ">=": lambda v, t: v >= t,
        "<=": lambda v, t: v <= t,
        "==": lambda v, t: v == t,
        "!=": lambda v, t: v != t,
    }
    fn = ops.get(operator)
    if fn is None:
        return False
    try:
        return fn(float(value), float(threshold))
    except (TypeError, ValueError):
        return False


def evaluate_and_alert(data: dict, db_pool):
    """
    Decide whether an alert should fire and, if so, dispatch it
    through all configured channels.  Also evaluates custom
    per-service alert rules from the database.
    """
    service_id = data["service_id"]
    service_name = data["service_name"]
    status = data["status"]
    response_time_ms = data.get("response_time_ms", 0) or 0
    timestamp = data["checked_at"]

    now = time.time()
    previous_status = last_known_status.get(service_id)
    alert_type = None

    # --- Determine alert type (built-in rules) ---
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

    if alert_type is not None:
        message = (
            f"[{alert_type}] {service_name} — status={status}, "
            f"response_time={response_time_ms:.0f}ms, time={timestamp}"
        )
        logger.info("Alert triggered: %s", message)

        send_slack_alert(alert_type, service_name, status, response_time_ms, timestamp)
        send_email_alert(alert_type, service_name, status, response_time_ms, timestamp)
        save_alert(db_pool, service_id, alert_type, message)

        if alert_type == "DOWN":
            create_incident(db_pool, service_id)
            last_alert_time[service_id] = now
        elif alert_type == "RECOVERED":
            resolve_incident(db_pool, service_id)

    # --- Evaluate custom per-service alert rules ---
    custom_rules = fetch_alert_rules_for_service(db_pool, service_id)
    status_numeric = 0.0 if status == "DOWN" else 1.0
    status_code = data.get("status_code") or 0

    metric_values = {
        "response_time_ms": response_time_ms,
        "status_code": float(status_code),
        "status": status_numeric,
    }

    for rule in custom_rules:
        rule_id = rule["id"]
        metric_val = metric_values.get(rule["metric"])
        if metric_val is None:
            continue

        if not _compare(metric_val, rule["operator"], rule["threshold"]):
            continue

        # Cooldown check
        last_rule_alert = custom_rule_last_alert.get(rule_id, 0)
        if now - last_rule_alert < rule["cooldown_s"]:
            continue

        severity = rule["severity"].upper()
        desc = rule["description"] or f"{rule['metric']} {rule['operator']} {rule['threshold']}"
        custom_message = (
            f"[CUSTOM-{severity}] {service_name} — rule: {desc}, "
            f"actual {rule['metric']}={metric_val}, time={timestamp}"
        )
        logger.info("Custom alert rule %d triggered: %s", rule_id, custom_message)

        alert_type_custom = "SLOW" if rule["metric"] == "response_time_ms" else "DOWN"
        send_slack_alert(alert_type_custom, service_name, status, response_time_ms, timestamp)
        send_email_alert(alert_type_custom, service_name, status, response_time_ms, timestamp)
        save_alert(db_pool, service_id, alert_type_custom, custom_message)
        custom_rule_last_alert[rule_id] = now
