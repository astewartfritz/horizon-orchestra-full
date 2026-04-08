# Orchestra Enterprise — Daily Briefing Integration Guide

## What Was Built

Four new modules drop directly into your existing Orchestra codebase.
No existing modules were modified — this is a clean additive layer.

```
orchestra/
  briefing_config.py      # Per-customer topic + delivery configuration
  briefing_monitor.py     # Sonar search + Kimi K2.5 email composer
  briefing_scheduler.py   # APScheduler cron engine + email delivery
  briefing_tools.py       # 7 agent-callable tools for agent_loop.py
  briefing_api.py         # FastAPI router for arch_e.py

tests/
  test_briefing.py        # 48 tests — all passing
```

---

## Step 1: Install dependencies

```bash
pip install apscheduler
```

---

## Step 2: Wire into arch_e.py

At the top of `arch_e.py`, add:

```python
from .briefing_scheduler import BriefingScheduler, EmailSender, NotificationPusher
from .briefing_api import create_briefing_router

# After your existing scheduler/notification setup:
briefing_scheduler = BriefingScheduler(
    moonshot_key=config["moonshot_key"],
    sonar_key=config["sonar_key"],
    email_sender=EmailSender(gmail_connector=your_gmail_connector),
    notification_pusher=NotificationPusher(notifications=your_notifications),
    config_dir="orchestra/data/briefings",
)
briefing_scheduler.start()

# Mount the API router (Enterprise-gated)
briefing_router = create_briefing_router(
    scheduler=briefing_scheduler,
    auth_fn=your_api_key_to_customer_id_fn,
    tier_fn=your_customer_tier_fn,
)
app.include_router(briefing_router)
```

---

## Step 3: Wire into agent_loop.py

```python
from .briefing_tools import get_briefing_tools

# Inside your tool registry build (Enterprise customers only):
if customer_tier == "enterprise":
    briefing_tool_defs, briefing_executor = get_briefing_tools(
        scheduler=briefing_scheduler,
        customer_tier_fn=lambda cid: get_customer_tier(cid),
    )
    tools.extend(briefing_tool_defs)
    tool_executors["briefing"] = briefing_executor
```

In your tool dispatch loop:
```python
if briefing_executor.can_handle(tool_name):
    result = await briefing_executor.execute(tool_name, arguments)
```

---

## API Endpoints (Enterprise only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/enterprise/briefings` | Create a new daily briefing |
| GET | `/enterprise/briefings/{customer_id}` | Get config |
| PATCH | `/enterprise/briefings/{customer_id}` | Update config |
| DELETE | `/enterprise/briefings/{customer_id}` | Delete briefing |
| POST | `/enterprise/briefings/{customer_id}/topics` | Add topic |
| DELETE | `/enterprise/briefings/{customer_id}/topics/{tid}` | Remove topic |
| POST | `/enterprise/briefings/{customer_id}/trigger` | Trigger now |
| GET | `/enterprise/briefings/{customer_id}/status` | Delivery history |

---

## Agent Tools (Kimi K2.5 callable)

| Tool | What it does |
|------|-------------|
| `briefing_create` | Create daily briefing with topics and recipients |
| `briefing_add_topic` | Add a monitored topic with search queries |
| `briefing_remove_topic` | Remove a topic by ID |
| `briefing_list` | List all topics and config for a customer |
| `briefing_trigger_now` | Fire a briefing immediately |
| `briefing_delete` | Delete the entire briefing config |
| `briefing_status` | View delivery history and success/failure logs |

---

## Tier Enforcement

All briefing features are hard-gated to `enterprise` tier ($499/mo).
Any call from a lower tier returns:

```json
{
  "error": "Daily Briefings require the Enterprise plan ($499/mo). ...",
  "upgrade_url": "horizon-orchestra.com/billing"
}
```

---

## Data Layout

```
orchestra/data/
  briefings/
    {customer_id}.json          # Config file per customer
  briefing_logs/
    {customer_id}/
      {YYYYMMDD_HHMMSS}.json    # Delivery log per run
```

---

## Pipeline Flow

```
BriefingScheduler (APScheduler cron)
  └── BriefingMonitor.run(config)
        ├── SonarSearchProvider.search() × N topics (parallel)
        ├── Deduplicate by URL fingerprint
        ├── Detect breaking keywords → is_breaking flag
        └── Kimi K2.5 Thinking mode → compose plain-text email
  └── EmailSender.send() → Gmail connector (SMTP fallback)
  └── NotificationPusher.push_breaking() → if breaking news
  └── DeliveryLog.save() → orchestra/data/briefing_logs/
```
