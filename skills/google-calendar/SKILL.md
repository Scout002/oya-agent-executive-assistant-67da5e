---
name: google-calendar
display_name: "Google Calendar"
description: "Comprehensive Google Calendar — list, create, update, reschedule, delete events, manage guests, add Google Meet, check availability, and more"
category: productivity
icon: calendar
skill_type: sandbox
catalog_type: platform
skip_summarization_on_structured: true
requirements: "httpx>=0.25,google-auth>=2.0,requests>=2.20"
resource_requirements:
  - env_var: GOOGLE_SERVICE_ACCOUNT_JSON
    name: "Google Calendar Credentials JSON"
    description: "OAuth2 credentials JSON (auto-provided by gateway connection)"
  - env_var: CALENDAR_ID
    name: "Calendar ID"
    description: "Google Calendar ID (default: primary)"
config_schema:
  properties:
    default_calendar:
      type: string
      label: "Default Calendar ID"
      description: "Calendar ID to use when not specified"
      placeholder: "primary"
      default: "primary"
      group: defaults
    default_duration:
      type: select
      label: "Default Duration"
      description: "Default meeting duration when not specified"
      options: ["15 min", "30 min", "45 min", "1 hour", "1.5 hours", "2 hours"]
      default: "30 min"
      group: defaults
    timezone:
      type: string
      label: "Timezone"
      description: "Default timezone for events"
      placeholder: "America/New_York"
      group: defaults
    event_rules:
      type: text
      label: "Event Rules"
      description: "Rules for creating and managing events"
      placeholder: "- Always add Google Meet to meetings with guests\n- Default to 30 min for 1:1s\n- Include agenda in description"
      group: rules
    invite_rules:
      type: text
      label: "Invite Rules"
      description: "Rules for adding attendees and sending invitations"
      placeholder: "- Confirm with user before inviting external guests\n- Always set RSVP to needsAction for new guests"
      group: rules
tool_schema:
  name: google_calendar
  description: "Comprehensive Google Calendar — list, create, update, reschedule, delete events, manage guests, add Google Meet, check availability"
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which operation to perform"
        enum: ['list_events', 'get_event', 'create_event', 'update_event', 'delete_event', 'quick_add', 'find_free_busy', 'list_calendars', 'verify_event']
      expected_status:
        type: "string"
        description: "For verify_event: expected status (confirmed, cancelled, tentative). If supplied and the live event's status differs, verified=false."
        default: ""
      expected_start:
        type: "string"
        description: "For verify_event: expected start (ISO 8601). If supplied and differs, verified=false."
        default: ""
      expected_end:
        type: "string"
        description: "For verify_event: expected end (ISO 8601). If supplied and differs, verified=false."
        default: ""
      expected_attendees:
        type: "string"
        description: "For verify_event: comma-separated attendee emails that MUST be on the event. Missing ones flip verified to false."
        default: ""
      calendar_id:
        type: "string"
        description: "Calendar ID to operate on (default: from gateway config)"
        default: ""
      event_id:
        type: "string"
        description: "Event ID — required for get_event, update_event, delete_event"
        default: ""
      summary:
        type: "string"
        description: "Event title — for create_event, update_event"
        default: ""
      description:
        type: "string"
        description: "Event description/notes — supports plain text"
        default: ""
      location:
        type: "string"
        description: "Event location (address or place name)"
        default: ""
      start_time:
        type: "string"
        description: "Start time in ISO 8601 (e.g. 2025-03-15T10:00:00-05:00) — for create_event, update_event. For all-day events use date format YYYY-MM-DD"
        default: ""
      end_time:
        type: "string"
        description: "End time in ISO 8601 — for create_event, update_event. For all-day events use date format YYYY-MM-DD (exclusive end date)"
        default: ""
      timezone:
        type: "string"
        description: "Timezone for the event (e.g. America/New_York, Europe/London). Defaults to calendar timezone"
        default: ""
      attendees:
        type: "string"
        description: "Comma-separated email addresses of guests to invite"
        default: ""
      add_meet:
        type: "boolean"
        description: "Add a Google Meet video conference link to the event"
        default: false
      recurrence:
        type: "string"
        description: "Recurrence rule (RRULE format, e.g. RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR or RRULE:FREQ=DAILY;COUNT=5)"
        default: ""
      reminders:
        type: "string"
        description: "Comma-separated reminders in minutes before event (e.g. '10,30' for 10 and 30 min reminders). Use 'none' to disable, 'default' for calendar defaults"
        default: "default"
      visibility:
        type: "string"
        description: "Event visibility: default, public, private, confidential"
        default: "default"
      color_id:
        type: "string"
        description: "Event color ID (1=lavender, 2=sage, 3=grape, 4=flamingo, 5=banana, 6=tangerine, 7=peacock, 8=graphite, 9=blueberry, 10=basil, 11=tomato)"
        default: ""
      send_updates:
        type: "string"
        description: "Who to notify about changes: all, externalOnly, none"
        default: "all"
      time_min:
        type: "string"
        description: "Start of time range (ISO 8601) — for list_events, find_free_busy"
        default: ""
      time_max:
        type: "string"
        description: "End of time range (ISO 8601) — for list_events, find_free_busy"
        default: ""
      max_results:
        type: "integer"
        description: "Max events to return for list_events"
        default: 10
      query:
        type: "string"
        description: "Free text search query for list_events"
        default: ""
      text:
        type: "string"
        description: "Natural language event text for quick_add (e.g. 'Lunch with John tomorrow at noon')"
        default: ""
    required: [action]
---
# Google Calendar

Comprehensive Google Calendar management — list, create, update, reschedule, delete events, manage guests, video conferencing, and check availability.

## Reading
- **list_events** — List upcoming events. Optional `time_min`, `time_max`, `max_results`, `query`, `calendar_id`.
- **get_event** — Get full event details. Provide `event_id`.
- **list_calendars** — List all calendars the user has access to.

## Creating
- **create_event** — Create a new event. Provide `summary`, `start_time`, `end_time`. Optional: `description`, `location`, `attendees`, `add_meet`, `recurrence`, `reminders`, `visibility`, `color_id`, `timezone`, `send_updates`.
- **quick_add** — Create event from natural language. Provide `text` (e.g. "Team standup every weekday at 9am").

## Modifying
- **update_event** — Update an existing event. Use this for ANY modification: reschedule, change title, add guests, add Meet link, etc. Provide `event_id` and any fields to change. New attendees are merged with existing ones (no one is removed). Fields: `summary`, `description`, `location`, `start_time`, `end_time`, `attendees`, `add_meet`, `recurrence`, `reminders`, `visibility`, `color_id`, `timezone`, `send_updates`.
- **delete_event** — Delete/cancel an event. Provide `event_id`. Optional `send_updates`.

## Availability
- **find_free_busy** — Check free/busy status. Provide `time_min`, `time_max`. Optional `calendar_id`.

## Verification (truthfulness guard)
Every write action (`create_event`, `update_event`, `delete_event`) automatically re-fetches the event after the write and returns:
- `verified: bool` — true if the live state matches the requested change.
- `verification.mismatch` — human-readable diff when verified is false (e.g. `attendees not added: [...]`, `expected status=cancelled, got status=confirmed`).
- For `list_events`, every event carries `is_past: bool` (computed server-side against `now()` in UTC) and the response top-level carries `time_min_used`, `time_max_used`, and `now_utc` so the LLM cannot mislabel past events as upcoming.

- **verify_event** — pure verification, no write. Provide `event_id` and optionally `expected_status` / `expected_start` / `expected_end` / `expected_attendees`. Returns `{exists, verified, actual: {status, start, end, attendees, is_past}, mismatches: [...]}`. Use this as a standalone audit, or rely on the auto-verification baked into every write.

## Important: Adding guests to an existing event
When asked to add a guest/attendee to an event that already exists, ALWAYS use `update_event` with the event's `event_id` — never create a new event. The `update_event` action automatically merges new attendees with existing ones (it won't remove anyone already invited).

## Tips
- For all-day events, use date format `YYYY-MM-DD` for start_time/end_time (end is exclusive)
- For recurring events, use RRULE format: `RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR`
- Attendees receive email invitations by default (control with `send_updates`)
- Set `add_meet: true` to auto-generate a Google Meet link
- Color IDs: 1=lavender, 2=sage, 3=grape, 4=flamingo, 5=banana, 6=tangerine, 7=peacock, 8=graphite, 9=blueberry, 10=basil, 11=tomato
