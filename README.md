# Patroller WebUI

Streamlit dashboard, history and reservation management for Patroller nodes.

## Run

Install `requirements.txt`, then run:

```bash
streamlit run patroller_webui/webui.py -- [CONFIG.json]
```

The default config is `/etc/patroller/web-ui.json`. Streamlit 1.36.0 is required.

## Owner selection

**Owner** is the first dropdown in the booking row. Known email users appear as `Name (email)` or just email; name-only containers appear as `Container: <name>`. **New / custom owner** is always available and reveals **Owner identity**: **Email** (the default) or **Container name**. Email mode keeps **Owner email** (required) and **Owner name (optional)**; the name is display metadata and only email determines ownership. Container name mode requires the exact, case-sensitive `ccc-user.name` label. This is a trusted-lab container identity, not an authenticated human identity. Names must be 1–200 characters after trimming, without ASCII controls/DEL or placeholder values such as Unknown, Unknown user, N/A, none or null.

Selecting a known owner hides the custom fields. Custom email, display name, container name and identity-mode drafts survive switching owners, identity modes and Repeat options; changing the custom email clears its previous display name. Existing bookings keep their owner even if absent from suggestions. Selecting or typing an owner does not save a booking. The first-row layout and duration/recurrence controls remain the same.

Suggestions combine already-loaded bookings and current selected-node claims, optional configured users, and a bounded background history sample. No additional per-GPU requests are made. Email options retain their email keys and `{email, name}` shape; name-only options use `name:<exact name>` keys and `{email: "", name: "<exact name>", owner_type: "name"}`. The existing chronicle Parquet path is used; an optional `reservation_history_path` config setting overrides it. Real email values and `Name <email>` labels supply email suggestions. Meaningful plain user strings, `name` or `ccc-user.name` history columns supply name-only suggestions, never synthetic emails. History is advisory and incomplete.

Name bookings explicitly send `owner_type: "name"`, `owner_email: ""` and the trimmed exact `owner_name`. Legacy email payloads omit `owner_type`; a display name alone never changes them into name bookings. Email identities take priority in process metadata; name identities match only name identities. Backend enforcement implements those rules independently. Tables, filters, edit selectors, cancellation dialogs and dashboard details distinguish name bookings with `Container:` labels. Occupied GPUs preserve their resolved display labels, including `ccc-user.name` when no email is available.

The page never waits for history I/O: one daemon worker refreshes a five-minute cache, with at most eight cached paths. Each sample inspects at most 256 directory entries, four files, eight row groups, 8,192 rows and an 8 MiB conservative decoded-memory allowance for selected email/name columns; footers are limited to 1 MiB per file. Dictionary/delta reuse is included in the pre-decode worst-case estimate, so some otherwise small groups may also be skipped. Oversized groups, missing/corrupt files and unavailable optional readers are skipped. A stuck reader leaves cached/empty suggestions while manual booking remains usable. Suggestions appear on a later page rerun/Refresh.

## Configuration

```json
{
  "http_auth_user": "monitor-user",
  "http_auth_pass": "monitor-password",
  "reservation_token": "server-side-write-token",
  "timezone": "Europe/Ljubljana",
  "reservation_users": [
    {"email": "person@example.org", "name": "Person"},
    {"email": "", "name": "toolbox-nanoparticles", "owner_type": "name"}
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

The Reservations page takes a local start date, hour and minute, plus an elapsed duration in hours (0.25–8784, including fractional hours). Repeat reuses the same local start time and duration: Daily means every day, Weekly every 7 days, Every two weeks every 14 days, and Monthly the same day of the month. There is no weekday picker or compatibility mode; saving always uses the start date as the repeat anchor. For day 29/30/31, months without that date have no booking. **Last repeat date** is the last day a new booking may start, not the end of a booking; the duration is unchanged. It initially suggests 90 days after the start and may be set up to 366 days after it. A saved series has a **Scheduled bookings (N)** popover listing each actual start and duration, including all dates in long series. A one-booking series explains that a later Last repeat date is needed for more repeats. The popover shows the saved schedule, not unsaved edits. Status and date filters use actual booking windows. Editing/cancelling affects the whole series. The backend validates daylight-saving start times and rejects overlapping bookings. Recurring reservations require a backend that supports the recurrence extension. Name-only bookings require a backend that supports the explicit name identity extension.
