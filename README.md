# 🔍 Microservices Monitoring & Alerting System

A production-ready, event-driven monitoring platform that health-checks your microservices and alerts you in real-time via Slack and email.

> **Resume Highlights:**
> * Designed and built a production-grade, event-driven monitoring platform that health-checks 9+ microservices in real time via HTTP (GET/POST/HEAD) and TCP probes, with configurable polling intervals.
> * Engineered a decoupled microservices architecture using RabbitMQ as a message broker — a Poller publishes health results, a DB Writer persists them to PostgreSQL, and an Alerter evaluates alert conditions and dispatches notifications via Slack webhooks and SMTP email.
> * Developed a RESTful API with FastAPI featuring JWT-based authentication, role-based access control (admin/editor/viewer), service CRUD, health history, uptime analytics (1h/24h/7d/30d), CSV/JSON data export, and a Prometheus-compatible `/metrics` endpoint for Grafana integration.
> * Built a real-time dashboard with WebSocket live updates, multi-service response time charts, an incident timeline tracking outage duration, custom per-service alert rules, and dynamic configuration.

---

## Architecture

```
┌──────────────┐       ┌───────────────────────────────┐
│   Frontend   │       │         REST API (FastAPI)    │
│  (nginx:80)  │──────▶│  :8000  /services  /dashboard │
└──────────────┘   ws  │         /alerts    /ws (live) │
                       └────────────┬──────────────────┘
                                    │  SQLAlchemy async
                                    ▼
                            ┌──────────────┐
                            │  PostgreSQL  │
                            │  :5432       │
                            └──────┬───────┘
                                   ▲
            ┌──────────────────────┤
            │                      │
  ┌─────────┴──────┐   ┌──────────┴─────────┐
  │   DB Writer    │   │     Alerter        │
  │  (consumer)    │   │   (consumer)       │
  └────────┬───────┘   │  Slack / Email     │
           │           └──────────┬─────────┘
           │                      │
           ▼                      ▼
      ┌──────────────────────────────────┐
      │         RabbitMQ                 │
      │    queue: health.results         │
      │    :5672  mgmt :15672            │
      └──────────────┬──────────────────┘
                     ▲
                     │  publish
           ┌─────────┴─────────┐
           │      Poller       │
           │  (every X sec)    │
           │  HTTP/TCP → svc   │
           └───────────────────┘
```

### Microservices Structure

The backend is built with independent, highly-modularized Python 3.11 services:

1. **API (`services/api/`)**: Evaluates HTTP requests, handles JWT authentication, and pushes live WebSocket updates. Heavily modularized into focused route modules (`auth`, `services`, `health`, `uptime`, `alerts`, `dashboard`, `incidents`, `alert_rules`, `metrics`).
2. **Alerter (`services/alerter/`)**: Consumes RabbitMQ messages, evaluates status and custom alert rules, and sends notifications. Modularized into components (`config`, `db`, `rabbitmq`, `notifiers`, `evaluator`).
3. **Poller (`services/poller/`)**: Probes target services via HTTP/TCP and publishes results.
4. **DB Writer (`services/db-writer/`)**: Consumes the queue and persists checks to PostgreSQL to optimize write operations.
5. **Frontend (`frontend/`)**: Static dashboard served by nginx using Chart.js, raw WebSockets for real-time updates, and an incident timeline tracker.

---

## Quick Start

### Prerequisites

- Docker & Docker Compose v2+

### 1. Clone & Configure

```bash
cd monitoring-system
cp .env .env.local   # edit .env.local to set your own secrets
```

Ensure `.env` contains your preferred threshold, interval, and credentials. (e.g., `SLACK_WEBHOOK_URL`, `ALERT_EMAIL`).

### 2. Start Everything

```bash
docker-compose up -d --build
```
Wait ~30 seconds for all containers to report health.

### 3. Load Sample Services

Load 10+ target microservices for testing purposes:
```bash
docker exec -i monitor-postgres psql -U monitor -d monitoring < sample_services.sql
```

### 4. View the Dashboard

Open **http://localhost:3001** in your browser.
*(Login with `admin` / `admin123` to add new services or manage alert rules).*

### 5. Explore API Docs

Open **http://localhost:8000/docs** to access the Swagger OpenAPI documentation.

### 6. Export Metrics for Grafana

Point Prometheus to the metrics endpoint: **http://localhost:8000/metrics**.

---

## Key Endpoints

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| `POST` | `/auth/login` | Receive JWT Token | ❌ |
| `GET`  | `/dashboard` | Dashboard summary | ✅ |
| `WS`   | `/ws`  | Live dashboard WebSocket | ❌ |
| `GET`  | `/services/{id}/health` | Health checks history | ✅ |
| `GET`  | `/services/{id}/export` | Export CSV/JSON history | ✅ |
| `GET`  | `/incidents` | Incident timeline history | ✅ |
| `GET`  | `/alert-rules` | Custom per-service alerts | ✅ |
| `GET`  | `/metrics` | Prometheus metrics scrape | ❌ |

---

## Stopping

```bash
docker-compose down           # stop containers
docker-compose down -v        # stop + remove volumes (clears DB)
```

---

## License
MIT
