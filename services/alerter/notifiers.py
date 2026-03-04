"""
Notification Senders
=====================
Slack webhook and SMTP email alert dispatching.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests as http_requests

from config import (
    SLACK_WEBHOOK_URL,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASS,
    ALERT_EMAIL,
    logger,
)

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
