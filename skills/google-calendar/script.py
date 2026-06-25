import os
import json
import httpx
import uuid
import time
from datetime import datetime, timezone

BASE = "https://www.googleapis.com/calendar/v3"
MAX_RETRIES = 3


def get_access_token(creds_json):
    """Exchange refresh token for a fresh access token from credentials JSON."""
    creds = json.loads(creds_json) if isinstance(creds_json, str) else creds_json
    if creds.get("type") == "authorized_user":
        r = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]
    else:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        sa_creds = service_account.Credentials.from_service_account_info(
            creds, scopes=["https://www.googleapis.com/auth/calendar"]
        )
        sa_creds.refresh(Request())
        return sa_creds.token


def _retry_request(method, url, headers, timeout=15, **kwargs):
    """Execute HTTP request with exponential backoff on 429 rate limits."""
    for attempt in range(MAX_RETRIES + 1):
        with httpx.Client(timeout=timeout) as c:
            r = c.request(method, url, headers=headers, **kwargs)
        if r.status_code == 429:
            if attempt < MAX_RETRIES:
                wait = min(2 ** attempt, 30)
                time.sleep(wait)
                continue
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:500]
            raise Exception(f"HTTP {r.status_code}: {json.dumps(detail) if isinstance(detail, dict) else detail}")
        return r


def api_get(headers, path, params=None, timeout=15):
    return _retry_request("GET", f"{BASE}/{path}", headers, timeout=timeout, params=params or {}).json()


def api_post(headers, path, body, params=None, timeout=15):
    return _retry_request("POST", f"{BASE}/{path}", headers, timeout=timeout, json=body, params=params or {}).json()


def api_patch(headers, path, body, params=None, timeout=15):
    return _retry_request("PATCH", f"{BASE}/{path}", headers, timeout=timeout, json=body, params=params or {}).json()


def api_delete(headers, path, params=None, timeout=15):
    _retry_request("DELETE", f"{BASE}/{path}", headers, timeout=timeout, params=params or {})


def parse_attendees(attendees_str):
    """Parse comma-separated emails into attendee list."""
    if not attendees_str or not attendees_str.strip():
        return []
    return [{"email": e.strip()} for e in attendees_str.split(",") if e.strip()]


def parse_reminders(reminders_str):
    """Parse reminders string into API format."""
    if not reminders_str or reminders_str == "default":
        return {"useDefault": True}
    if reminders_str == "none":
        return {"useDefault": False, "overrides": []}
    overrides = []
    for m in reminders_str.split(","):
        m = m.strip()
        if m.isdigit():
            overrides.append({"method": "popup", "minutes": int(m)})
    if not overrides:
        return {"useDefault": True}
    return {"useDefault": False, "overrides": overrides}


def is_all_day(time_str):
    """Check if a time string is a date-only (all-day event)."""
    if not time_str:
        return False
    try:
        datetime.strptime(time_str.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def make_time_body(start_time, end_time, tz):
    """Build start/end dicts for the API, handling all-day vs timed events."""
    body = {}
    if start_time:
        if is_all_day(start_time):
            body["start"] = {"date": start_time.strip()}
            body["end"] = {"date": end_time.strip()} if end_time else {"date": start_time.strip()}
        else:
            body["start"] = {"dateTime": start_time}
            body["end"] = {"dateTime": end_time} if end_time else {"dateTime": start_time}
            if tz:
                body["start"]["timeZone"] = tz
                body["end"]["timeZone"] = tz
    return body


def make_conference_data():
    """Build conferenceData for a Google Meet link."""
    return {
        "createRequest": {
            "requestId": str(uuid.uuid4()),
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def _parse_event_end_to_utc(end_dict):
    """Parse an event's end into a tz-aware UTC datetime, or None if unparseable.
    Handles both dateTime (ISO 8601, possibly with offset) and date (all-day)."""
    if not isinstance(end_dict, dict):
        return None
    raw = end_dict.get("dateTime") or end_dict.get("date") or ""
    if not raw:
        return None
    try:
        if "T" in raw:
            # ISO 8601 with offset (or Z). Python 3.11+ handles "Z" via fromisoformat.
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                # Fall back to event-level timeZone if present
                tz_name = end_dict.get("timeZone") or "UTC"
                try:
                    from zoneinfo import ZoneInfo
                    dt = dt.replace(tzinfo=ZoneInfo(tz_name))
                except Exception:
                    dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        # All-day event: end is exclusive in Google's API (the day AFTER the last day).
        # Treat the event as past once that exclusive boundary has passed in UTC.
        date_only = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return date_only
    except Exception:
        return None


def format_event(e):
    """Format a calendar event for output."""
    start = e.get("start", {})
    end = e.get("end", {})
    attendees = e.get("attendees", [])
    conference = e.get("conferenceData", {})
    meet_link = ""
    for ep in conference.get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            meet_link = ep.get("uri", "")
            break
    # is_past: computed server-side so the LLM cannot reason wrong about
    # past-vs-future. True when the event's end is earlier than now (UTC).
    # For events with no parseable end, defaults to False (treat as current).
    end_utc = _parse_event_end_to_utc(end)
    is_past = bool(end_utc and end_utc < datetime.now(timezone.utc))
    return {
        "id": e.get("id", ""),
        "summary": e.get("summary", "(no title)"),
        "description": (e.get("description") or "")[:500],
        "location": e.get("location", ""),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
        "timezone": start.get("timeZone", ""),
        "status": e.get("status", ""),
        "is_past": is_past,
        "visibility": e.get("visibility", "default"),
        "htmlLink": e.get("htmlLink", ""),
        "meet_link": meet_link,
        "organizer": e.get("organizer", {}).get("email", ""),
        "creator": e.get("creator", {}).get("email", ""),
        "attendees": [
            {
                "email": a.get("email", ""),
                "name": a.get("displayName", ""),
                "response": a.get("responseStatus", ""),
                "organizer": a.get("organizer", False),
            }
            for a in attendees
        ],
        "recurrence": e.get("recurrence", []),
        "color_id": e.get("colorId", ""),
        "reminders": e.get("reminders", {}),
    }


# --- Actions ---


def do_list_events(headers, calendar_id, inp):
    time_min = inp.get("time_min") or datetime.now(timezone.utc).isoformat()
    max_results = min(int(inp.get("max_results", 10)), 50)
    params = {
        "maxResults": max_results,
        "timeMin": time_min,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if inp.get("time_max"):
        params["timeMax"] = inp["time_max"]
    if inp.get("query"):
        params["q"] = inp["query"]
    data = api_get(headers, f"calendars/{calendar_id}/events", params=params)
    events = [format_event(e) for e in data.get("items", [])]
    return {
        "events": events,
        "count": len(events),
        "time_min_used": time_min,
        "time_max_used": params.get("timeMax", ""),
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "truncated": len(events) == max_results,
    }


def do_get_event(headers, calendar_id, event_id):
    if not event_id:
        return {"error": "event_id is required for get_event"}
    e = api_get(headers, f"calendars/{calendar_id}/events/{event_id}")
    return format_event(e)


def _refetch_event(headers, calendar_id, event_id):
    """Re-fetch an event by id. Returns the formatted event dict, or
    {'_refetch_error': str} if the fetch fails (e.g. 404 after a hard delete).
    Used by every write action to compute `verified` server-side."""
    try:
        e = api_get(headers, f"calendars/{calendar_id}/events/{event_id}")
        return format_event(e)
    except Exception as exc:
        return {"_refetch_error": str(exc)[:300]}


def _start_iso(e_dict):
    return (e_dict.get("start") or "") if isinstance(e_dict, dict) else ""


def _end_iso(e_dict):
    return (e_dict.get("end") or "") if isinstance(e_dict, dict) else ""


def _attendee_emails(e_dict):
    if not isinstance(e_dict, dict):
        return []
    return sorted({a.get("email", "") for a in e_dict.get("attendees", []) if a.get("email")})


def do_create_event(headers, calendar_id, inp):
    if not inp.get("summary"):
        return {"error": "summary is required for create_event"}
    if not inp.get("start_time"):
        return {"error": "start_time is required for create_event"}

    tz = inp.get("timezone", "")
    body = {"summary": inp["summary"]}
    body.update(make_time_body(inp["start_time"], inp.get("end_time"), tz))

    if inp.get("description"):
        body["description"] = inp["description"]
    if inp.get("location"):
        body["location"] = inp["location"]

    attendees = parse_attendees(inp.get("attendees", ""))
    if attendees:
        body["attendees"] = attendees

    if inp.get("add_meet"):
        body["conferenceData"] = make_conference_data()

    if inp.get("recurrence"):
        rules = inp["recurrence"]
        body["recurrence"] = [rules] if isinstance(rules, str) else rules

    body["reminders"] = parse_reminders(inp.get("reminders", "default"))

    if inp.get("visibility") and inp["visibility"] != "default":
        body["visibility"] = inp["visibility"]
    if inp.get("color_id"):
        body["colorId"] = inp["color_id"]

    params = {"sendUpdates": inp.get("send_updates", "all")}
    if inp.get("add_meet"):
        params["conferenceDataVersion"] = 1

    data = api_post(headers, f"calendars/{calendar_id}/events", body, params=params)
    result = format_event(data)
    result["created"] = True
    # Auto-verify: re-fetch by id and confirm the event landed with matching
    # core fields. The wrapper LLM cannot claim "created" if verified=false.
    verification = _refetch_event(headers, calendar_id, result["id"])
    if "_refetch_error" in verification:
        result["verified"] = False
        result["verification"] = {
            "found": False,
            "mismatch": f"re-fetch failed: {verification['_refetch_error']}",
        }
    else:
        requested_attendees = sorted({a["email"] for a in body.get("attendees", [])})
        actual_attendees = _attendee_emails(verification)
        missing_attendees = [a for a in requested_attendees if a not in actual_attendees]
        mismatches = []
        if verification.get("summary") != body.get("summary"):
            mismatches.append(f"summary: requested={body.get('summary')!r}, actual={verification.get('summary')!r}")
        if missing_attendees:
            mismatches.append(f"attendees not added: {missing_attendees}")
        if verification.get("status") not in ("confirmed", "tentative", ""):
            mismatches.append(f"unexpected status: {verification.get('status')}")
        result["verified"] = len(mismatches) == 0
        result["verification"] = {
            "found": True,
            "status": verification.get("status"),
            "start": verification.get("start"),
            "end": verification.get("end"),
            "attendees": actual_attendees,
            "mismatch": "; ".join(mismatches) if mismatches else "",
        }
    return result


def do_update_event(headers, calendar_id, inp):
    event_id = inp.get("event_id", "")
    if not event_id:
        return {"error": "event_id is required for update_event"}

    # Fetch existing event to merge
    existing = api_get(headers, f"calendars/{calendar_id}/events/{event_id}")
    body = {}

    if inp.get("summary"):
        body["summary"] = inp["summary"]
    if inp.get("description") is not None:
        body["description"] = inp["description"]
    if inp.get("location") is not None:
        body["location"] = inp["location"]

    tz = inp.get("timezone", "")
    time_updates = make_time_body(inp.get("start_time"), inp.get("end_time"), tz)
    # For partial time updates, fill in the missing side from existing
    if "start" in time_updates and "end" not in time_updates:
        time_updates["end"] = existing.get("end", time_updates["start"])
    elif "end" in time_updates and "start" not in time_updates:
        time_updates["start"] = existing.get("start", time_updates["end"])
    body.update(time_updates)

    if inp.get("attendees"):
        new_attendees = parse_attendees(inp["attendees"])
        # Merge with existing attendees (don't remove existing ones)
        existing_emails = {a["email"] for a in existing.get("attendees", [])}
        merged = list(existing.get("attendees", []))
        for a in new_attendees:
            if a["email"] not in existing_emails:
                merged.append(a)
        body["attendees"] = merged

    if inp.get("add_meet") and not existing.get("conferenceData"):
        body["conferenceData"] = make_conference_data()

    if inp.get("recurrence"):
        rules = inp["recurrence"]
        body["recurrence"] = [rules] if isinstance(rules, str) else rules

    if inp.get("reminders"):
        body["reminders"] = parse_reminders(inp["reminders"])

    if inp.get("visibility") and inp["visibility"] != "default":
        body["visibility"] = inp["visibility"]
    if inp.get("color_id"):
        body["colorId"] = inp["color_id"]

    if not body:
        return {"error": "No fields to update"}

    params = {"sendUpdates": inp.get("send_updates", "all")}
    if inp.get("add_meet"):
        params["conferenceDataVersion"] = 1

    data = api_patch(headers, f"calendars/{calendar_id}/events/{event_id}", body, params=params)
    result = format_event(data)
    result["updated"] = True
    # Auto-verify: re-fetch and diff requested-vs-applied for each field.
    verification = _refetch_event(headers, calendar_id, event_id)
    changes_requested = {}
    if "summary" in body:
        changes_requested["summary"] = body["summary"]
    if "start" in body:
        changes_requested["start"] = body["start"]
    if "end" in body:
        changes_requested["end"] = body["end"]
    if "attendees" in body:
        changes_requested["attendees"] = sorted({a["email"] for a in body["attendees"]})
    if "_refetch_error" in verification:
        result["verified"] = False
        result["verification"] = {
            "found": False,
            "mismatch": f"re-fetch failed: {verification['_refetch_error']}",
        }
    else:
        drift = []
        if "summary" in changes_requested and verification.get("summary") != changes_requested["summary"]:
            drift.append(f"summary: requested={changes_requested['summary']!r}, actual={verification.get('summary')!r}")
        if "attendees" in changes_requested:
            actual = _attendee_emails(verification)
            missing = [a for a in changes_requested["attendees"] if a not in actual]
            if missing:
                drift.append(f"attendees not added: {missing}")
        result["verified"] = len(drift) == 0
        result["verification"] = {
            "found": True,
            "status": verification.get("status"),
            "start_applied": verification.get("start"),
            "end_applied": verification.get("end"),
            "attendees_applied": _attendee_emails(verification),
            "drift": drift,
            "mismatch": "; ".join(drift) if drift else "",
        }
    result["changes_requested"] = changes_requested
    return result


def do_delete_event(headers, calendar_id, inp):
    event_id = inp.get("event_id", "")
    if not event_id:
        return {"error": "event_id is required for delete_event"}
    # Capture previous status BEFORE delete so we can include it in verification.
    previous_status = ""
    try:
        prev = api_get(headers, f"calendars/{calendar_id}/events/{event_id}")
        previous_status = prev.get("status", "")
    except Exception:
        # Event might not exist; let the delete itself surface the 404.
        pass
    params = {"sendUpdates": inp.get("send_updates", "all")}
    api_delete(headers, f"calendars/{calendar_id}/events/{event_id}", params=params)
    # Auto-verify: re-fetch and confirm status == "cancelled" (Google soft-deletes)
    # OR the event is no longer retrievable. Either is a valid cancellation.
    verification = _refetch_event(headers, calendar_id, event_id)
    if "_refetch_error" in verification:
        # 404/410 after delete is the strongest signal it's gone.
        err = verification["_refetch_error"].lower()
        if "404" in err or "410" in err or "not found" in err or "gone" in err:
            verified = True
            current_status = "deleted"
            mismatch = ""
        else:
            verified = False
            current_status = "unknown"
            mismatch = f"re-fetch error: {verification['_refetch_error']}"
    else:
        current_status = verification.get("status", "")
        verified = current_status == "cancelled"
        mismatch = "" if verified else f"expected status=cancelled, got status={current_status!r}"
    return {
        "deleted": True,
        "event_id": event_id,
        "verified": verified,
        "verification": {
            "previous_status": previous_status,
            "current_status": current_status,
            "mismatch": mismatch,
        },
    }


def do_verify_event(headers, calendar_id, inp):
    """Pure verification, no write. Returns the live state of an event vs the
    caller's expectations. Used by the runtime guard in chat/service.py and
    available to the LLM on demand."""
    event_id = inp.get("event_id", "")
    if not event_id:
        return {"error": "event_id is required for verify_event"}
    fetched = _refetch_event(headers, calendar_id, event_id)
    if "_refetch_error" in fetched:
        err = fetched["_refetch_error"].lower()
        not_found = "404" in err or "410" in err or "not found" in err or "gone" in err
        return {
            "event_id": event_id,
            "exists": not not_found,
            "verified": False,
            "error": fetched["_refetch_error"],
        }
    mismatches = []
    expected_status = inp.get("expected_status")
    if expected_status and fetched.get("status") != expected_status:
        mismatches.append(f"status: expected={expected_status!r}, actual={fetched.get('status')!r}")
    expected_start = inp.get("expected_start")
    if expected_start and fetched.get("start") != expected_start:
        mismatches.append(f"start: expected={expected_start!r}, actual={fetched.get('start')!r}")
    expected_end = inp.get("expected_end")
    if expected_end and fetched.get("end") != expected_end:
        mismatches.append(f"end: expected={expected_end!r}, actual={fetched.get('end')!r}")
    expected_attendees = inp.get("expected_attendees")
    if expected_attendees:
        exp = sorted([a.strip() for a in expected_attendees.split(",")] if isinstance(expected_attendees, str) else expected_attendees)
        actual = _attendee_emails(fetched)
        missing = [a for a in exp if a not in actual]
        if missing:
            mismatches.append(f"attendees missing: {missing}")
    return {
        "event_id": event_id,
        "exists": True,
        "verified": len(mismatches) == 0,
        "actual": {
            "status": fetched.get("status"),
            "summary": fetched.get("summary"),
            "start": fetched.get("start"),
            "end": fetched.get("end"),
            "attendees": _attendee_emails(fetched),
            "is_past": fetched.get("is_past", False),
        },
        "mismatches": mismatches,
    }


def do_quick_add(headers, calendar_id, text):
    if not text:
        return {"error": "text is required for quick_add"}
    with httpx.Client(timeout=15) as c:
        r = c.post(
            f"{BASE}/calendars/{calendar_id}/events/quickAdd",
            headers=headers,
            params={"text": text, "sendUpdates": "all"},
        )
        r.raise_for_status()
        data = r.json()
    result = format_event(data)
    result["created"] = True
    return result


def do_find_free_busy(headers, calendar_id, inp):
    time_min = inp.get("time_min")
    time_max = inp.get("time_max")
    if not time_min or not time_max:
        return {"error": "time_min and time_max are required for find_free_busy"}
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": calendar_id}],
    }
    with httpx.Client(timeout=15) as c:
        r = c.post(f"{BASE}/freeBusy", headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    cal_data = data.get("calendars", {}).get(calendar_id, {})
    busy_periods = cal_data.get("busy", [])
    return {
        "calendar_id": calendar_id,
        "time_min": time_min,
        "time_max": time_max,
        "busy": [
            {"start": b["start"], "end": b["end"]}
            for b in busy_periods
        ],
        "busy_count": len(busy_periods),
    }


def do_list_calendars(headers):
    data = api_get(headers, "users/me/calendarList")
    calendars = data.get("items", [])
    return {
        "calendars": [
            {
                "id": c.get("id", ""),
                "summary": c.get("summary", ""),
                "description": c.get("description", ""),
                "primary": c.get("primary", False),
                "access_role": c.get("accessRole", ""),
                "timezone": c.get("timeZone", ""),
                "color": c.get("backgroundColor", ""),
            }
            for c in calendars
        ],
        "count": len(calendars),
    }


# --- Main ---

try:
    creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    calendar_id = os.environ.get("CALENDAR_ID", "primary")
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "")

    if inp.get("calendar_id"):
        calendar_id = inp["calendar_id"]

    token = get_access_token(creds_json)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if action == "list_events":
        result = do_list_events(headers, calendar_id, inp)
    elif action == "get_event":
        result = do_get_event(headers, calendar_id, inp.get("event_id", ""))
    elif action == "create_event":
        result = do_create_event(headers, calendar_id, inp)
    elif action == "update_event":
        result = do_update_event(headers, calendar_id, inp)
    elif action == "delete_event":
        result = do_delete_event(headers, calendar_id, inp)
    elif action == "quick_add":
        result = do_quick_add(headers, calendar_id, inp.get("text", ""))
    elif action == "find_free_busy":
        result = do_find_free_busy(headers, calendar_id, inp)
    elif action == "list_calendars":
        result = do_list_calendars(headers)
    elif action == "verify_event":
        result = do_verify_event(headers, calendar_id, inp)
    else:
        result = {"error": f"Unknown action: {action}. Available: list_events, get_event, create_event, update_event, delete_event, quick_add, find_free_busy, list_calendars, verify_event"}

    print(json.dumps(result))

except httpx.HTTPStatusError as e:
    detail = ""
    try:
        detail = e.response.json().get("error", {}).get("message", "")
    except Exception:
        detail = e.response.text[:200]
    print(json.dumps({"error": f"Google Calendar API error {e.response.status_code}: {detail}" if detail else f"Google Calendar API error {e.response.status_code}"}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
