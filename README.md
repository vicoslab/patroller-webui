# Patroller WebUI

Streamlit dashboard, history and reservation management for Patroller nodes.

## Run

Install `requirements.txt`, then run:

```bash
streamlit run patroller_webui/webui.py -- [CONFIG.json]
```

The default config is `/etc/patroller/web-ui.json`. Streamlit 1.36.0 is required.

## Configuration

```json
{
  "http_auth_user": "monitor-user",
  "http_auth_pass": "monitor-password",
  "reservation_token": "server-side-write-token",
  "timezone": "Europe/Ljubljana",
  "reservation_users": [
    {"email": "person@example.org", "name": "Person"}
  ],
  "servers": [
    {"name": "node-1", "url": "https://node-1.example.org"},
    {"name": "node-2", "url": "https://node-2.example.org", "reservation_token": "node-specific-token"}
  ],
  "user_label": "name"
}
```

Keep the config file private on the Streamlit server. `reservation_token` can be global or per node; an absent token makes the calendar read-only. `reservation_users` is optional; without it the manager enters an email. `timezone` defaults to `Europe/Ljubljana`; local times that are ambiguous or nonexistent during daylight saving transitions are rejected. Existing per-node HTTP Basic Auth overrides and `disable_auth` continue to apply. When Basic Auth is enabled, writes use `X-Patroller-Reservation-Token`; otherwise they use a Bearer authorization header.

Reservation management is a trusted-lab model: everyone with a write credential can manage bookings for any owner. A booking beginning immediately can terminate non-owner GPU processes if backend enforcement is enabled. During an active reservation the dashboard's primary status is `🔒 RESERVED: <owner name>` regardless of GPU occupancy (email fallback if no configured name). When only a future reservation exists, free/occupied status remains visible with a separate `🔓` details button. Dates and notes are shown only on click. Future bookings do not block present availability.

Nodes must implement the reservation API v1: `GET /reservations`, `POST /reserve`, `PATCH /reservations/<id>`, and `POST /unreserve`. Lists are JSON arrays; writes use GPU UUIDs and offset-aware timestamps. The dashboard uses `active_reservation` and `next_reservation` in each GPU's `/status` record, with device index and model from `/devices`. Old nodes lacking those status fields have unknown reservation availability; a 404 list endpoint is unsupported and a 503 is disabled or unavailable, not an empty calendar. Enable and configure the backend separately. The frontend does not cache reservation lists, so actions refetch on rerun.
