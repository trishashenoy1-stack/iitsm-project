# Notifications

Turns P1's domain events into in-app (SSE) and email notifications.

| Pattern | Where |
| --- | --- |
| Observer | `NotificationService` subscribes to the domain `EventBus` |
| Adapter | `SmtpEmailAdapter` presents `smtplib` as an `EmailGateway` |
| Factory | `NotificationChannelFactory` builds channels by name |
| Repository | `NotificationRepository` stores history |

To add a mechanism such as SMS: implement `NotificationChannel`, register it with the factory, and name it in a rule in `rules.py`. Nothing else changes.

## How a notification travels

1. The domain publishes an event. The handler only queues work, because P1's bus runs inside the user's request.
2. The worker thread picks matching rules from `rules.py` and finds recipients.
3. Each channel delivers separately, so a failing mail server can't stop in-app delivery.
4. The in-app channel saves to history, then pushes to open SSE connections.

## Connecting it to the backend

```python
module = NotificationModule(bus, MyRecipientDirectory(), repository=MyDbRepository())
app.include_router(module.router(get_current_user), prefix="/api")
# In the FastAPI lifespan: module.start() at startup, module.stop() at shutdown.
```

The backend must provide:

- **`RecipientDirectory`**: looks up an incident's reporter and technician, a user by ID, and all administrators. It runs on the worker thread, so it needs its own database session.
- **`NotificationRepository`**: a database version with increasing IDs. Until then history is in memory.
- **`get_current_user`**: a FastAPI dependency returning an object with `user_id`.

### Publish domain events after the database commit

The worker can run before the request's transaction commits. `IncidentCreated` is also published before the incident is saved. If the worker looks up an incident too early, that notification is lost. Buffer events during the request and publish them after the commit.

### Run one server worker

Open SSE connections live in the process, so run Uvicorn with a single worker. Scaling out needs a shared channel such as Redis pub/sub in place of `SseBroker`.

## Email

Simulated by default. For real email, set `EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_SENDER`, and optionally `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_USE_TLS`. Never commit these values.

A failed email is logged and not retried.

## Tests

```bash
pip install -r notifications/requirements.txt
python -m pytest tests/test_notifications.py tests/test_notification_api.py
```
