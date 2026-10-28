# Patroller WebUI

Streamlit dashboard, history and reservation management for Patroller nodes.

## Run

Install `requirements.txt`, then run:

```bash
streamlit run patroller_webui/webui.py -- [CONFIG.json]
```

The default config is `/etc/patroller/web-ui.json`. Streamlit 1.36.0 is required.

## Owner selection

**Owner** is the first dropdown in the booking row. Known users appear as `Name (email)` or just email. **New / custom owner** is always available and reveals **Owner email** (required) and **Owner name (optional)** below the row. Enter the email used by the CCC account/container; only that email determines process ownership. Selecting a known owner hides the custom fields. Custom drafts survive switching owners and Repeat options; changing the custom email clears its previous name to avoid mislabelling. Existing bookings keep their owner even if it is absent from the suggestions. Selecting or typing an owner does not save a booking.

Suggestions combine already-loaded bookings, optional configured users, and a bounded background history sample. The existing chronicle Parquet path is used (`/etc/patroller/history/data.parquet` by default); an optional `reservation_history_path` config setting overrides it. Only real email values or `Name <email>` labels are accepted—name-only history is not guessed into an email. History is advisory and incomplete.

The page never waits for history I/O: one daemon worker refreshes a five-minute cache, with at most eight cached paths. Each sample inspects at most 256 directory entries, four files, eight row groups, 8,192 rows and an 8 MiB conservative decoded-memory allowance for selected email/name columns; footers are limited to 1 MiB per file. Dictionary/delta reuse is included in the pre-decode worst-case estimate, so some otherwise small groups may also be skipped. Oversized groups, missing/corrupt files and unavailable optional readers are skipped. A stuck reader leaves cached/empty suggestions while manual booking remains usable. Suggestions appear on a later page rerun/Refresh.

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

Keep the config file private on the Streamlit server. `reservation_token` can be global or per node; an absent token makes the calendar read-only. `reservation_users` is optional and supplies suggestions only; it never restricts who can reserve. `timezone` defaults to `Europe/Ljubljana`; local times that are ambiguous or nonexistent during daylight saving transitions are rejected. Existing per-node HTTP Basic Auth overrides and `disable_auth` continue to apply. When Basic Auth is enabled, writes use `X-Patroller-Reservation-Token`; otherwise they use a Bearer authorization header.

Reservation management is a trusted-lab model: everyone with a write credential can manage bookings for any owner. A booking beginning immediately can terminate non-owner GPU processes if backend enforcement is enabled. During an active reservation the dashboard's primary status is `🔒 RESERVED: <owner name>` regardless of GPU occupancy (email fallback if neither the booking nor optional config has a name). When only a future reservation exists, free/occupied status remains visible with a separate `🔓 Reservations in 2h 15m` details button. Time remaining is calculated from the booking's start, shown in days/hours/minutes (or `<1m`), and recalculated when the dashboard is loaded or refreshed. Dates and notes are shown only on click. Future bookings do not block present availability.

Nodes must implement the reservation API v1: `GET /reservations`, `POST /reserve`, `PATCH /reservations/<id>`, and `POST /unreserve`. Lists are JSON arrays; writes use GPU UUIDs and offset-aware timestamps. The dashboard uses `active_reservation` and `next_reservation` in each GPU's `/status` record, with device index and model from `/devices`. Old nodes lacking those status fields have unknown reservation availability; a 404 list endpoint is unsupported and a 503 is disabled or unavailable, not an empty calendar. Enable and configure the backend separately. The frontend does not cache reservation lists, so actions refetch on rerun.

The Reservations page takes a local start date, hour and minute, plus an elapsed duration in hours (0.25–8784, including fractional hours). Repeat reuses the same local start time and duration: Daily means every day, Weekly every 7 days, Every two weeks every 14 days, and Monthly the same day of the month. There is no weekday picker or compatibility mode; saving always uses the start date as the repeat anchor. For day 29/30/31, months without that date have no booking. **Last repeat date** is the last day a new booking may start, not the end of a booking; the duration is unchanged. It initially suggests 90 days after the start and may be set up to 366 days after it. A saved series has a **Scheduled bookings (N)** popover listing each actual start and duration, including all dates in long series. A one-booking series explains that a later Last repeat date is needed for more repeats. The popover shows the saved schedule, not unsaved edits. Status and date filters use actual booking windows. Editing/cancelling affects the whole series. The backend validates daylight-saving start times and rejects overlapping bookings. Recurring reservations require a backend that supports the recurrence extension.
