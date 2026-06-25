import os, json, time, httpx
from email.utils import parsedate_to_datetime
try:
    from google.oauth2 import credentials, service_account
    from google.auth.transport.requests import Request as AuthRequest
except ImportError:
    print(json.dumps({"error": "google-auth not installed. pip install google-auth"}))
    raise SystemExit(1)


def _parse_rfc2822_to_iso(raw_date):
    if not raw_date:
        return ""
    try:
        return parsedate_to_datetime(raw_date).isoformat()
    except Exception:
        return ""


def _gmail_get(client, url, auth_headers, params=None):
    for _attempt in range(4):
        r = client.get(url, headers=auth_headers, params=params or {})
        if r.status_code == 429 and _attempt < 3:
            time.sleep(min(2 ** _attempt, 30))
            continue
        r.raise_for_status()
        return r.json()


def _fetch_metadata(c, auth_hdrs, message_id):
    detail = _gmail_get(
        c,
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
        auth_hdrs,
        params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
    )
    headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
    raw_date = headers.get("Date", "")
    return {
        "id": message_id,
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "date": raw_date,
        "date_iso": _parse_rfc2822_to_iso(raw_date),
        "snippet": detail.get("snippet", ""),
        "label_ids": detail.get("labelIds", []) or [],
    }


def do_search(c, auth_hdrs, query, max_results):
    list_resp = _gmail_get(
        c, "https://gmail.googleapis.com/gmail/v1/users/me/messages", auth_hdrs,
        params={"q": query, "maxResults": max_results},
    )
    msg_list = list_resp.get("messages", []) or []
    next_page_token = list_resp.get("nextPageToken", "")
    emails = [_fetch_metadata(c, auth_hdrs, m["id"]) for m in msg_list[:max_results]]
    truncated = len(emails) >= max_results or bool(next_page_token)
    return {
        "emails": emails,
        "count": len(emails),
        "query_used": query,
        "max_results_used": max_results,
        "truncated": truncated,
    }


def do_verify_emails(c, auth_hdrs, query, claimed_ids):
    """Re-run the query and check which of the claimed_ids actually appear in
    the live result set. Returns:
      - all_present: bool (every claimed id is in the real results)
      - missing_ids: ids the agent claimed that the query does NOT return
      - unexpected_real_ids: ids in the query result that the agent did NOT mention
      - emails: full metadata for each claimed id that actually exists
    Used by the runtime verify-on-claim guard, or by the LLM on demand."""
    list_resp = _gmail_get(
        c, "https://gmail.googleapis.com/gmail/v1/users/me/messages", auth_hdrs,
        params={"q": query, "maxResults": 50},
    )
    real_ids = [m["id"] for m in (list_resp.get("messages", []) or [])]
    real_id_set = set(real_ids)
    claimed_set = set(claimed_ids)
    missing = [cid for cid in claimed_ids if cid not in real_id_set]
    unexpected = [rid for rid in real_ids if rid not in claimed_set]
    # Fetch metadata only for claimed ids that exist (cheaper than full hydration).
    emails = []
    for cid in claimed_ids:
        if cid in real_id_set:
            try:
                emails.append(_fetch_metadata(c, auth_hdrs, cid))
            except Exception as exc:
                emails.append({"id": cid, "error": str(exc)[:200]})
    return {
        "query": query,
        "claimed_ids": list(claimed_ids),
        "real_ids_sample": real_ids[:50],
        "all_present": len(missing) == 0,
        "verified": len(missing) == 0,
        "missing_ids": missing,
        "unexpected_real_ids": unexpected,
        "emails": emails,
    }


try:
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    creds_json = json.loads(os.environ["GMAIL_CREDENTIALS_JSON"])
    user_email = os.environ.get("GMAIL_USER_EMAIL", "")
    if creds_json.get("type") == "authorized_user":
        creds = credentials.Credentials.from_authorized_user_info(
            creds_json, scopes=["https://www.googleapis.com/auth/gmail.readonly"]
        )
    else:
        creds = service_account.Credentials.from_service_account_info(
            creds_json, scopes=["https://www.googleapis.com/auth/gmail.readonly"], subject=user_email
        )
    creds.refresh(AuthRequest())
    action = inp.get("action", "search")
    with httpx.Client(timeout=15) as c:
        auth_hdrs = {"Authorization": f"Bearer {creds.token}"}
        if action == "verify_emails":
            query = inp.get("query", "")
            raw_claimed = inp.get("claimed_message_ids") or inp.get("claimed_ids") or []
            if isinstance(raw_claimed, str):
                claimed_ids = [x.strip() for x in raw_claimed.split(",") if x.strip()]
            else:
                claimed_ids = [str(x) for x in raw_claimed]
            if not query:
                result = {"error": "query is required for verify_emails"}
            elif not claimed_ids:
                result = {"error": "claimed_message_ids is required for verify_emails"}
            else:
                result = do_verify_emails(c, auth_hdrs, query, claimed_ids)
        else:
            # Default "search" action. `action` field is optional for back-compat.
            query = inp.get("query", "")
            if not query:
                result = {"error": "query is required for gmail-search"}
            else:
                max_results = inp.get("max_results", 10)
                result = do_search(c, auth_hdrs, query, max_results)
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({"error": str(e)}))
