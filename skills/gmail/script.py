import os
import json
import time
import httpx
import re
from base64 import urlsafe_b64encode, urlsafe_b64decode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _wrap_html(html):
    """Wrap an HTML fragment in a clean, mobile-friendly email template. A full
    <html> document is passed through untouched."""
    if re.search(r"<!doctype|<html", html, re.IGNORECASE):
        return html
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#f4f5f7;">'
        '<div style="max-width:600px;margin:0 auto;padding:24px;">'
        '<div style="background:#ffffff;border-radius:12px;padding:28px 32px;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;'
        'font-size:15px;line-height:1.6;color:#1a1a1a;">'
        f"{html}</div></div></body></html>"
    )


def _strip_tags(html):
    text = re.sub(r"<(br|/p|/div|/h[1-6]|/li)\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

BASE = "https://gmail.googleapis.com/gmail/v1"
DELAY = 0.05
MAX_RETRIES = 3


def get_access_token(creds_json):
    """Exchange refresh token for a fresh access token from credentials JSON."""
    creds = json.loads(creds_json) if isinstance(creds_json, str) else creds_json
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


def _retry_request(method, url, headers, timeout=15, **kwargs):
    """Execute HTTP request with exponential backoff on 429 rate limits."""
    time.sleep(DELAY)
    for attempt in range(MAX_RETRIES + 1):
        with httpx.Client(timeout=timeout) as c:
            r = c.request(method, url, headers=headers, **kwargs)
        if r.status_code == 429:
            if attempt < MAX_RETRIES:
                wait = min(2 ** attempt, 30)
                time.sleep(wait)
                continue
        r.raise_for_status()
        return r.json()


def api_get(headers, path, params=None, timeout=15):
    return _retry_request("GET", f"{BASE}/{path}", headers, timeout=timeout, params=params or {})


def api_post(headers, path, body, timeout=15):
    return _retry_request("POST", f"{BASE}/{path}", headers, timeout=timeout, json=body)


def extract_header(msg_headers, name):
    """Extract a header value from Gmail message headers."""
    for h in msg_headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def extract_body_text(payload):
    """Extract plain text body from Gmail message payload."""
    # Direct body
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    # Multipart — look for text/plain part
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        # Nested multipart
        if part.get("parts"):
            text = extract_body_text(part)
            if text:
                return text
    return ""


def parse_message_summary(msg):
    """Parse a Gmail message into a summary dict."""
    hdrs = msg.get("payload", {}).get("headers", [])
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": extract_header(hdrs, "Subject"),
        "from": extract_header(hdrs, "From"),
        "to": extract_header(hdrs, "To"),
        "date": extract_header(hdrs, "Date"),
        "snippet": msg.get("snippet", ""),
        "labels": msg.get("labelIds", []),
    }


def build_email(to, subject, body, cc="", bcc="", in_reply_to="", references="", thread_subject="", html=""):
    """Build a MIME email message and return base64url-encoded raw. When `html` is
    given, send multipart/alternative (plain-text fallback + styled HTML)."""
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body or _strip_tags(html), "plain", "utf-8"))
        msg.attach(MIMEText(_wrap_html(html), "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["Subject"] = subject if not thread_subject else f"Re: {thread_subject}"
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    return urlsafe_b64encode(msg.as_bytes()).decode("ascii")


# --- Actions ---


def do_read_inbox(headers, max_results):
    data = api_get(
        headers,
        "users/me/messages",
        params={"maxResults": max_results, "labelIds": "INBOX"},
    )
    messages = []
    for item in data.get("messages", []):
        msg = api_get(
            headers,
            f"users/me/messages/{item['id']}",
            params={"format": "metadata", "metadataHeaders": "Subject,From,To,Date"},
        )
        messages.append(parse_message_summary(msg))
    return {"emails": messages, "count": len(messages)}


def do_search(headers, query, max_results):
    data = api_get(
        headers,
        "users/me/messages",
        params={"q": query, "maxResults": max_results},
    )
    messages = []
    for item in data.get("messages", []):
        msg = api_get(
            headers,
            f"users/me/messages/{item['id']}",
            params={"format": "metadata", "metadataHeaders": "Subject,From,To,Date"},
        )
        messages.append(parse_message_summary(msg))
    return {"emails": messages, "count": len(messages), "query": query}


def do_get_message(headers, message_id):
    msg = api_get(headers, f"users/me/messages/{message_id}", params={"format": "full"})
    hdrs = msg.get("payload", {}).get("headers", [])
    body_text = extract_body_text(msg.get("payload", {}))
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": extract_header(hdrs, "Subject"),
        "from": extract_header(hdrs, "From"),
        "to": extract_header(hdrs, "To"),
        "cc": extract_header(hdrs, "Cc"),
        "date": extract_header(hdrs, "Date"),
        "message_id_header": extract_header(hdrs, "Message-ID"),
        "body": body_text,
        "snippet": msg.get("snippet", ""),
        "labels": msg.get("labelIds", []),
    }


def do_send(headers, to, subject, body, cc="", bcc="", html=""):
    raw = build_email(to, subject, body, cc=cc, bcc=bcc, html=html)
    data = api_post(headers, "users/me/messages/send", {"raw": raw})
    return {
        "id": data.get("id", ""),
        "thread_id": data.get("threadId", ""),
        "to": to,
        "subject": subject,
        "format": "html" if html else "plain",
    }


def do_reply(headers, message_id, body, to="", thread_id=""):
    # Fetch original message for reply context
    orig = api_get(
        headers,
        f"users/me/messages/{message_id}",
        params={"format": "metadata", "metadataHeaders": "Subject,From,To,Message-ID,References"},
    )
    orig_hdrs = orig.get("payload", {}).get("headers", [])
    orig_from = extract_header(orig_hdrs, "From")
    orig_subject = extract_header(orig_hdrs, "Subject")
    orig_msg_id = extract_header(orig_hdrs, "Message-ID")
    orig_refs = extract_header(orig_hdrs, "References")

    reply_to = to or orig_from
    tid = thread_id or orig.get("threadId", "")
    references = f"{orig_refs} {orig_msg_id}".strip() if orig_refs else orig_msg_id

    raw = build_email(
        reply_to,
        orig_subject,
        body,
        in_reply_to=orig_msg_id,
        references=references,
        thread_subject=orig_subject.removeprefix("Re: "),
    )
    send_body = {"raw": raw}
    if tid:
        send_body["threadId"] = tid

    data = api_post(headers, "users/me/messages/send", send_body)
    return {
        "id": data.get("id", ""),
        "thread_id": data.get("threadId", ""),
        "to": reply_to,
        "subject": f"Re: {orig_subject}" if not orig_subject.startswith("Re:") else orig_subject,
    }


def do_create_draft(headers, to, subject, body, cc="", bcc="", html=""):
    raw = build_email(to, subject, body, cc=cc, bcc=bcc, html=html)
    data = api_post(headers, "users/me/drafts", {"message": {"raw": raw}})
    return {
        "draft_id": data.get("id", ""),
        "message_id": data.get("message", {}).get("id", ""),
        "to": to,
        "subject": subject,
    }


def do_send_draft(headers, draft_id):
    data = api_post(headers, "users/me/drafts/send", {"id": draft_id})
    return {
        "id": data.get("id", ""),
        "thread_id": data.get("threadId", ""),
    }


def do_list_labels(headers):
    data = api_get(headers, "users/me/labels")
    labels = data.get("labels", [])
    return {
        "labels": [
            {
                "id": l["id"],
                "name": l.get("name", ""),
                "type": l.get("type", ""),
            }
            for l in labels
        ],
        "count": len(labels),
    }


def do_modify_labels(headers, message_id, add_labels, remove_labels):
    body = {}
    if add_labels:
        body["addLabelIds"] = [l.strip() for l in add_labels.split(",") if l.strip()]
    if remove_labels:
        body["removeLabelIds"] = [l.strip() for l in remove_labels.split(",") if l.strip()]
    data = api_post(headers, f"users/me/messages/{message_id}/modify", body)
    return {
        "id": data.get("id", ""),
        "labels": data.get("labelIds", []),
    }


def do_trash(headers, message_id):
    data = api_post(headers, f"users/me/messages/{message_id}/trash", {})
    return {"id": data.get("id", ""), "trashed": True}


def do_mark_read(headers, message_id):
    data = api_post(
        headers,
        f"users/me/messages/{message_id}/modify",
        {"removeLabelIds": ["UNREAD"]},
    )
    return {"id": data.get("id", ""), "labels": data.get("labelIds", [])}


# --- Main ---

try:
    creds_json = os.environ["GMAIL_CREDENTIALS_JSON"]
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "")

    token = get_access_token(creds_json)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if action == "read_inbox":
        result = do_read_inbox(headers, inp.get("max_results", 10))
    elif action == "search":
        result = do_search(headers, inp.get("query", ""), inp.get("max_results", 10))
    elif action == "get_message":
        result = do_get_message(headers, inp["message_id"])
    elif action == "send":
        result = do_send(headers, inp["to"], inp.get("subject", ""), inp.get("body", ""), cc=inp.get("cc", ""), bcc=inp.get("bcc", ""), html=inp.get("html", ""))
    elif action == "reply":
        result = do_reply(headers, inp["message_id"], inp.get("body", ""), to=inp.get("to", ""), thread_id=inp.get("thread_id", ""))
    elif action == "create_draft":
        result = do_create_draft(headers, inp["to"], inp.get("subject", ""), inp.get("body", ""), cc=inp.get("cc", ""), bcc=inp.get("bcc", ""), html=inp.get("html", ""))
    elif action == "send_draft":
        result = do_send_draft(headers, inp["draft_id"])
    elif action == "list_labels":
        result = do_list_labels(headers)
    elif action == "modify_labels":
        result = do_modify_labels(headers, inp["message_id"], inp.get("add_labels", ""), inp.get("remove_labels", ""))
    elif action == "trash":
        result = do_trash(headers, inp["message_id"])
    elif action == "mark_read":
        result = do_mark_read(headers, inp["message_id"])
    else:
        result = {"error": f"Unknown action: {action}"}

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"error": str(e)}))
