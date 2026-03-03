# 🔍 Microservices Monitoring & Alerting System

A production-ready, event-driven monitoring platform that health-checks
your microservices and alerts you in real-time via Slack and email.

---

## Architecture

```
┌──────────────┐       ┌───────────────────────────────┐
│   Frontend   │       │         REST API (FastAPI)     │
│  (nginx:80)  │──────▶│  :8000  /services  /dashboard │
└──────────────┘       │         /alerts    /uptime     │
                       └────────────┬──────────────────┘
                                    │  SQLAlchemy async
                                    ▼
                            ┌──────────────┐
                            │  PostgreSQL   │
                            │  :5432        │
                            └──────┬───────┘
                                   ▲
            ┌──────────────────────┤
            │                      │
  ┌─────────┴──────┐   ┌──────────┴─────────┐
  │   DB Writer     │   │     Alerter        │
  │  (consumer)     │   │   (consumer)       │
  └────────┬───────┘   │  Slack / Email      │
           │            └──────────┬─────────┘
           │                       │
           ▼                       ▼
      ┌──────────────────────────────────┐
      │         RabbitMQ                 │
      │    queue: health.results         │
      │    :5672  mgmt :15672            │
      └──────────────┬──────────────────┘
                     ▲
                     │  publish
           ┌─────────┴─────────┐
           │      Poller       │
           │  (every 30 s)     │
           │  HTTP GET → svc   │
           └───────────────────┘
```

### Data flow

1. **Poller** reads active services from PostgreSQL, polls each via
   HTTP, and publishes results to the `health.results` RabbitMQ queue.
2. **DB Writer** consumes the queue and inserts rows into the
   `health_checks` table.
3. **Alerter** consumes the same queue, evaluates alert conditions
   (DOWN / SLOW / RECOVERED), and dispatches Slack + email
   notifications. Alerts are also persisted to the `alerts` table.
4. **API** (FastAPI) exposes REST endpoints for services CRUD,
   health history, uptime stats, alerts, and a dashboard summary.
5. **Frontend** is a single HTML page served by nginx that calls the
   API every 30 seconds and renders live cards, a table, charts, and
   an alerts feed.

---

## Quick Start

### Prerequisites

- Docker & Docker Compose v2+
- (Optional) A Slack incoming-webhook URL
- (Optional) An SMTP account for email alerts

### 1. Clone & configure

```bash
cd monitoring-system
cp .env .env.local   # edit .env.local to set your own secrets
```

Edit `.env` (or `.env.local`) — at minimum review:

| Variable | Purpose |
|---|---|
| `SLACK_WEBHOOK_URL` | Slack incoming webhook |
| `SMTP_HOST / SMTP_USER / SMTP_PASS` | SMTP credentials for email |
| `ALERT_EMAIL` | Recipient address |
| `SLOW_THRESHOLD_MS` | Slow-response threshold (default 2 000 ms) |
| `CHECK_INTERVAL` | Poll interval in seconds (default 30) |

### 2. Start everything

```bash
docker-compose up -d --build
```

Wait ~30 seconds for all services to become healthy:

```bash
docker-compose ps
```

### 3. Load sample services

```bash
docker exec -i monitor-postgres psql -U monitor -d monitoring < sample_services.sql
```

Or register via the API:

```bash
curl -X POST http://localhost:8000/services \
  -H "Content-Type: application/json" \
  -d '{"name":"HTTPBin","url":"https://httpbin.org/get","check_interval":30}'
```

### 4. View the dashboard

Open **http://localhost:3000** in your browser.

### 5. Explore the API docs

Open **http://localhost:8000/docs** for Swagger / OpenAPI.

---

## Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/services` | List all services |
| `POST` | `/services` | Register a new service |
| `DELETE` | `/services/{id}` | Deactivate a service |
| `GET` | `/services/{id}/health` | Recent health checks |
| `GET` | `/services/{id}/uptime` | Uptime & avg response time |
| `GET` | `/alerts` | Recent alerts |
| `GET` | `/dashboard` | Full dashboard summary |

---

## Configuring Slack Webhook

1. Go to **https://api.slack.com/apps** → Create New App → Incoming Webhooks.
2. Copy the webhook URL.
3. Set `SLACK_WEBHOOK_URL` in `.env`.
4. Restart the alerter: `docker-compose restart alerter`.

---

## Managing Services

```bash
# Register
curl -X POST http://localhost:8000/services \
  -H "Content-Type: application/json" \
  -d '{"name":"My API","url":"https://api.example.com/health","check_interval":30}'

# Deactivate
curl -X DELETE http://localhost:8000/services/1
```

---

## Stopping

```bash
docker-compose down           # stop containers
docker-compose down -v        # stop + remove volumes (clears DB)
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11 |
| API | FastAPI + Uvicorn |
| Database | PostgreSQL 15, SQLAlchemy (async) + asyncpg |
| Message Queue | RabbitMQ 3 (management) |
| Alerting | Slack Webhooks, SMTP email |
| Frontend | HTML + CSS + Chart.js |
| Container | Docker + Docker Compose |

---

## License

MIT
