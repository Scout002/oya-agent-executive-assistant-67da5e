import os, json, time, httpx
from email.utils import parsedate_to_datetime
try:
    from google.oauth2 import credentials, service_account
    from google.auth.transport.requests import Request as AuthRequest
except ImportError:
    print(json.dumps({"error": "google-auth not installed. pip install google-auth"}))
    raise SystemExit(1)


def _parse_rfc2822_to_iso(raw_date):
    """Convert RFC 2822 ('Mon, 13 May 2026 14:30:00 -0400') to ISO 8601 with offset.
    Returns empty string when unparseable so callers don't have to handle exceptions."""
    if not raw_date:
        return ""
    try:
        return parsedate_to_datetime(raw_date).isoformat()
    except Exception:
        return ""


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
    max_results = inp.get("max_results", 5)
    query = inp.get("query", "")
    params = {"maxResults": max_results}
    if query:
        params["q"] = query
    def _gmail_get(client, url, auth_headers, params=None):
        for _attempt in range(4):
            r = client.get(url, headers=auth_headers, params=params or {})
            if r.status_code == 429 and _attempt < 3:
                time.sleep(min(2 ** _attempt, 30))
                continue
            r.raise_for_status()
            return r.json()
    with httpx.Client(timeout=15) as c:
        auth_hdrs = {"Authorization": f"Bearer {creds.token}"}
        list_resp = _gmail_get(c, "https://gmail.googleapis.com/gmail/v1/users/me/messages", auth_hdrs, params=params)
        msg_list = list_resp.get("messages", []) or []
        next_page_token = list_resp.get("nextPageToken", "")
        emails = []
        for m in msg_list[:max_results]:
            detail = _gmail_get(c, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}", auth_hdrs,
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]})
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            raw_date = headers.get("Date", "")
            emails.append({
                "id": m["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": raw_date,
                "date_iso": _parse_rfc2822_to_iso(raw_date),
                "snippet": detail.get("snippet", ""),
            })
    # truncated is true when we hit the cap OR Gmail says there are more pages.
    # Either signal means the LLM must not claim "all" emails.
    truncated = len(emails) >= max_results or bool(next_page_token)
    print(json.dumps({
        "emails": emails,
        "count": len(emails),
        "query_used": query,
        "max_results_used": max_results,
        "truncated": truncated,
    }))
except Exception as e:
    print(json.dumps({"error": str(e)}))
