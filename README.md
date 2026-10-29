# Patroller WebUI

Streamlit dashboard, history and reservation management for Patroller nodes.

## Run

Install `requirements.txt`, then run:

```bash
streamlit run patroller_webui/webui.py -- [CONFIG.json]
```

The default config is `/etc/patroller/web-ui.json`. Streamlit 1.36.0 is required.

## Browser-session reservation write access

The Reservations page is read-only until **you supply a token in this browser
session**. Prefer the masked **Write token** textbox and explicitly click
**Unlock reservations**. The password draft is cleared after submission. The
page verifies the candidate with the selected backend's nonmutating
`GET /reservation-access`; no trial booking is created. Only a successful
`200 {"writable": true}` enables Add, Save and cancellation. Missing, invalid,
unavailable, disabled or older unsupported verification endpoints stay read-only.

Alternatively open `/reservations?write-token=YOUR_TOKEN` (URL-encode the value
when needed). Exactly one nonempty token of at most 4096 printable ASCII
characters (33–126; no whitespace/control characters) is accepted. The URL token
replaces the current session token and is removed from the query parameters,
preserving unrelated parameters. Duplicate, malformed or explicitly empty URL
tokens clear the current credential and fail closed. A textbox token is applied
only on Unlock, not by typing alone.

**URL tokens may be recorded in initial proxy/access logs and browser history
before removal. Stripping the parameter does not erase those records. Prefer
the masked textbox.** Use HTTPS; existing proxy/HTTP Basic Auth remains necessary
and unchanged. Tokens are forwarded only in backend authentication headers, never
backend query strings. With Basic Auth the dedicated
`X-Patroller-Reservation-Token` header preserves Basic authorization; otherwise
the request uses Bearer authorization. Redirects are not followed.

The credential stays in Streamlit's current browser session, not a global cache,
configuration file, disk or persistent browser storage. It is shared across the
configured nodes within that session, but the selected node is verified on each
page rerun, including switches; a rejected candidate is retained for retry or
another node without permitting writes. Independent browser sessions do not
inherit it. While read-only, one bordered panel contains the access explanation,
masked token input and same-row Unlock button (including validation errors).
After verification the entire panel disappears; no success banner or Clear
button is shown. The unlock panel sits above the Server selector. While
read-only, Add reservation and Edit reservation panels are not rendered; the
reservation list and its filters remain available. Node switches still reverify access and restore the panel if
verification fails, without resetting booking drafts. Ending the session does
not globally revoke a token: real rotation requires changing the
backend configuration on all nodes. This shared-token model is not per-human
authentication: anyone holding the token can manage **any owner's bookings on
all nodes** accepting it. Unlocking does not enable or change process-kill
enforcement.

Configure the same backend write token separately on all nodes, and update both
backend and WebUI code for the verification endpoint. Do not inject that secret
into WebUI JSON or environment. The page explicitly ignores any legacy global or
per-node WebUI `reservation_token`; only a verified browser-supplied credential
unlocks it. Standalone Python `ReservationClient` callers retain legacy config
token support for compatibility; its `writable` property alone indicates only
token presence, while `verify_write_access()` performs server verification.

The packaged `pages/reservations.py` is a thin cold-start bootstrap for
Streamlit 1.36: its legacy discovery recognizes the first `/reservations`
request before `st.navigation` has registered routes. It delegates immediately
to the same entrypoint and URL-token capture; no second page or credential store
exists. Subsequent routing remains owned by `st.navigation`.

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
  "timezone": "Europe/Ljubljana",
  "reservation_users": [
    {"email": "person@example.org", "name": "Person"},
    {"email": "", "name": "toolbox-nanoparticles", "owner_type": "name"}
  ],
  "servers": [
    {"name": "node-1", "url": "https://node-1.example.org"},
    {"name": "node-2", "url": "https://node-2.example.org"}
  ],
  "user_label": "name"
}
```

Keep the config file private on the Streamlit server. Reservation writes require a verified browser-session token as described above, even if old config credentials remain. `reservation_users` is optional and supplies suggestions only; it never restricts who can reserve. `timezone` defaults to `Europe/Ljubljana`; local times that are ambiguous or nonexistent during daylight saving transitions are rejected. Existing per-node HTTP Basic Auth overrides and `disable_auth` continue to apply.

Reservation management is a trusted-lab model: everyone with a write credential can manage bookings for any owner. A booking beginning immediately can terminate non-owner GPU processes if backend enforcement is enabled. During an active reservation the dashboard's primary status is `🔒 RESERVED: <owner name>` regardless of GPU occupancy (email fallback if neither the booking nor optional config has a name). When only a future reservation exists, free/occupied status remains visible with a separate `🔓 Reservations in 2h 15m` details button. Time remaining is calculated from the booking's start, shown in days/hours/minutes (or `<1m`), and recalculated when the dashboard is loaded or refreshed. Dates and notes are shown only on click. Future bookings do not block present availability.

Nodes must implement the reservation API v1: `GET /reservations`, `POST /reserve`, `PATCH /reservations/<id>`, and `POST /unreserve`, plus `GET /reservation-access` for browser-session write verification. Lists are JSON arrays; writes use GPU UUIDs and offset-aware timestamps. The dashboard uses `active_reservation` and `next_reservation` in each GPU's `/status` record, with device index and model from `/devices`. Old nodes lacking those status fields have unknown reservation availability; a 404 list endpoint is unsupported and a 503 is disabled or unavailable, not an empty calendar. Enable and configure the backend separately. The frontend does not cache reservation lists, so actions refetch on rerun.

The Reservations page takes a local start date, hour and minute, plus an elapsed duration in hours (0.25–8784, including fractional hours). Repeat reuses the same local start time and duration: Daily means every day, Weekly every 7 days, Every two weeks every 14 days, and Monthly the same day of the month. There is no weekday picker or compatibility mode; saving always uses the start date as the repeat anchor. For day 29/30/31, months without that date have no booking. **Last repeat date** is the last day a new booking may start, not the end of a booking; the duration is unchanged. It initially suggests 90 days after the start and may be set up to 366 days after it. A saved series has a **Scheduled bookings (N)** popover listing each actual start and duration, including all dates in long series. A one-booking series explains that a later Last repeat date is needed for more repeats. The popover shows the saved schedule, not unsaved edits. Status and date filters use actual booking windows. Editing/cancelling affects the whole series. The backend validates daylight-saving start times and rejects overlapping bookings. Recurring reservations require a backend that supports the recurrence extension. Name-only bookings require a backend that supports the explicit name identity extension.
