import os
import json
import time
import uuid
import httpx

BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
DELAY = 0.05
MAX_RETRIES = 3


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
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:500]
            raise Exception(f"HTTP {r.status_code}: {json.dumps(detail) if isinstance(detail, dict) else detail}")
        return r


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


def api_get(headers, path, params=None, timeout=15):
    return _retry_request("GET", f"{BASE}/{path}", headers, timeout=timeout, params=params or {}).json()


def api_post(headers, path, body, timeout=15):
    return _retry_request("POST", f"{BASE}/{path}", headers, timeout=timeout, json=body).json()


def api_patch(headers, path, body, timeout=15):
    return _retry_request("PATCH", f"{BASE}/{path}", headers, timeout=timeout, json=body).json()


def multipart_upload(headers, metadata, content, content_type, timeout=30):
    """Upload file using multipart/related for Drive API."""
    time.sleep(DELAY)
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--"
    )
    upload_headers = dict(headers)
    upload_headers["Content-Type"] = f"multipart/related; boundary={boundary}"
    with httpx.Client(timeout=timeout) as c:
        r = c.post(
            f"{UPLOAD_BASE}/files?uploadType=multipart&fields=id,name,mimeType,webViewLink",
            headers=upload_headers,
            content=body.encode("utf-8"),
        )
        r.raise_for_status()
        return r.json()


def file_link(file_id):
    return f"https://drive.google.com/file/d/{file_id}/view"


def _refetch_file_state(headers, file_id):
    """Re-fetch a file's live state for verification. Returns dict with
    name/mimeType/parents/trashed/owners/shared, or {'_refetch_error': str}
    when the file is not retrievable (e.g. 404 after a hard delete)."""
    try:
        data = api_get(
            headers,
            f"files/{file_id}",
            params={"fields": "id,name,mimeType,parents,trashed,shared,owners"},
        )
        return {
            "id": data.get("id"),
            "name": data.get("name", ""),
            "mimeType": data.get("mimeType", ""),
            "parents": data.get("parents", []),
            "trashed": data.get("trashed", False),
            "shared": data.get("shared", False),
            "owners": [o.get("emailAddress", "") for o in data.get("owners", [])],
        }
    except Exception as exc:
        return {"_refetch_error": str(exc)[:300]}


def _verify_create(headers, file_id, expected_name, expected_mime, expected_parent):
    """Confirm a created file landed with the right name/type/parent. Returns
    (verified: bool, verification: dict)."""
    state = _refetch_file_state(headers, file_id)
    if "_refetch_error" in state:
        return False, {
            "found": False,
            "mismatch": f"re-fetch failed: {state['_refetch_error']}",
        }
    mismatches = []
    if expected_name and state.get("name") != expected_name:
        mismatches.append(f"name: requested={expected_name!r}, actual={state.get('name')!r}")
    if expected_mime and state.get("mimeType") != expected_mime:
        mismatches.append(f"mimeType: requested={expected_mime!r}, actual={state.get('mimeType')!r}")
    if expected_parent and expected_parent not in state.get("parents", []):
        mismatches.append(f"parent {expected_parent!r} missing from parents={state.get('parents')!r}")
    if state.get("trashed"):
        mismatches.append("file is already trashed")
    return (len(mismatches) == 0), {
        "found": True,
        "name": state.get("name"),
        "mimeType": state.get("mimeType"),
        "parents": state.get("parents"),
        "trashed": state.get("trashed"),
        "mismatch": "; ".join(mismatches),
    }


# --- Actions ---


def do_list_files(headers, folder_id, max_results):
    fid = folder_id or "root"
    q = f"'{fid}' in parents and trashed = false"
    data = api_get(
        headers,
        "files",
        params={
            "q": q,
            "pageSize": max_results,
            "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink),nextPageToken",
            "orderBy": "modifiedTime desc",
        },
    )
    files = data.get("files", [])
    truncated = len(files) >= max_results or bool(data.get("nextPageToken"))
    return {
        "files": [
            {
                "id": f["id"],
                "name": f["name"],
                "type": f.get("mimeType", ""),
                "modified": f.get("modifiedTime", ""),
                "size": f.get("size"),
                "url": f.get("webViewLink", file_link(f["id"])),
            }
            for f in files
        ],
        "count": len(files),
        "folder_id_used": fid,
        "truncated": truncated,
    }


def do_search_files(headers, query, max_results):
    q = f"{query} and trashed = false" if query else "trashed = false"
    data = api_get(
        headers,
        "files",
        params={
            "q": q,
            "pageSize": max_results,
            "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink),nextPageToken",
            "orderBy": "modifiedTime desc",
        },
    )
    files = data.get("files", [])
    truncated = len(files) >= max_results or bool(data.get("nextPageToken"))
    return {
        "files": [
            {
                "id": f["id"],
                "name": f["name"],
                "type": f.get("mimeType", ""),
                "modified": f.get("modifiedTime", ""),
                "size": f.get("size"),
                "url": f.get("webViewLink", file_link(f["id"])),
            }
            for f in files
        ],
        "count": len(files),
        "query_used": query,
        "truncated": truncated,
    }


def do_get_file_info(headers, file_id):
    data = api_get(
        headers,
        f"files/{file_id}",
        params={
            "fields": "id,name,mimeType,modifiedTime,createdTime,size,webViewLink,owners,sharingUser,shared,parents"
        },
    )
    return {
        "id": data["id"],
        "name": data.get("name", ""),
        "type": data.get("mimeType", ""),
        "created": data.get("createdTime", ""),
        "modified": data.get("modifiedTime", ""),
        "size": data.get("size"),
        "shared": data.get("shared", False),
        "owners": [o.get("emailAddress", "") for o in data.get("owners", [])],
        "parents": data.get("parents", []),
        "url": data.get("webViewLink", file_link(data["id"])),
    }


def _create_result(data, expected_name, expected_mime, expected_parent, headers):
    verified, verification = _verify_create(
        headers, data["id"], expected_name, expected_mime, expected_parent,
    )
    return {
        "id": data["id"],
        "file_id": data["id"],
        "name": data.get("name", ""),
        "type": data.get("mimeType", ""),
        "url": data.get("webViewLink", file_link(data["id"])),
        "verified": verified,
        "verification": verification,
    }


def do_create_folder(headers, name, folder_id):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if folder_id:
        metadata["parents"] = [folder_id]
    data = api_post(headers, "files?fields=id,name,mimeType,webViewLink,parents", metadata)
    return _create_result(data, name, "application/vnd.google-apps.folder", folder_id, headers)


def do_create_document(headers, name, content, folder_id):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        metadata["parents"] = [folder_id]
    if content:
        data = multipart_upload(headers, metadata, content, "text/plain")
    else:
        data = api_post(headers, "files?fields=id,name,mimeType,webViewLink,parents", metadata)
    return _create_result(data, name, "application/vnd.google-apps.document", folder_id, headers)


def do_create_spreadsheet(headers, name, content, folder_id):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    if folder_id:
        metadata["parents"] = [folder_id]
    if content:
        data = multipart_upload(headers, metadata, content, "text/csv")
    else:
        data = api_post(headers, "files?fields=id,name,mimeType,webViewLink,parents", metadata)
    return _create_result(data, name, "application/vnd.google-apps.spreadsheet", folder_id, headers)


def do_upload_text(headers, name, content, mime_type, folder_id):
    metadata = {"name": name}
    if folder_id:
        metadata["parents"] = [folder_id]
    data = multipart_upload(headers, metadata, content, mime_type)
    # `mime_type` on upload may be transformed by Drive (e.g. plain text stays
    # text/plain, but binary uploads can shift). Verify against requested.
    return _create_result(data, name, mime_type, folder_id, headers)


def do_download_text(headers, file_id):
    """Download file content. Exports Google Docs as text, Sheets as CSV."""
    time.sleep(DELAY)
    # First get the file type
    info = api_get(headers, f"files/{file_id}", params={"fields": "id,name,mimeType"})
    mime = info.get("mimeType", "")

    with httpx.Client(timeout=30) as c:
        if mime == "application/vnd.google-apps.document":
            r = c.get(
                f"{BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/plain"},
            )
        elif mime == "application/vnd.google-apps.spreadsheet":
            r = c.get(
                f"{BASE}/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/csv"},
            )
        else:
            r = c.get(
                f"{BASE}/files/{file_id}",
                headers=headers,
                params={"alt": "media"},
            )
        r.raise_for_status()
        return {
            "id": file_id,
            "name": info.get("name", ""),
            "type": mime,
            "content": r.text,
        }


def do_move_file(headers, file_id, destination_folder_id):
    # Get current parents
    info = api_get(headers, f"files/{file_id}", params={"fields": "id,name,parents"})
    current_parents = ",".join(info.get("parents", []))
    time.sleep(DELAY)
    with httpx.Client(timeout=15) as c:
        r = c.patch(
            f"{BASE}/files/{file_id}",
            headers=headers,
            params={
                "addParents": destination_folder_id,
                "removeParents": current_parents,
                "fields": "id,name,parents,webViewLink",
            },
        )
        r.raise_for_status()
        data = r.json()
    return {
        "id": data["id"],
        "name": data.get("name", ""),
        "parents": data.get("parents", []),
        "url": data.get("webViewLink", file_link(data["id"])),
    }


def do_copy_file(headers, file_id, name):
    body = {}
    if name:
        body["name"] = name
    data = api_post(headers, f"files/{file_id}/copy?fields=id,name,webViewLink", body)
    return {
        "id": data["id"],
        "name": data.get("name", ""),
        "url": data.get("webViewLink", file_link(data["id"])),
    }


def do_rename_file(headers, file_id, name):
    data = api_patch(
        headers, f"files/{file_id}?fields=id,name,webViewLink", {"name": name}
    )
    return {
        "id": data["id"],
        "name": data.get("name", ""),
        "url": data.get("webViewLink", file_link(data["id"])),
    }


def do_trash_file(headers, file_id):
    data = api_patch(headers, f"files/{file_id}?fields=id,name,trashed", {"trashed": True})
    # Auto-verify: re-fetch and confirm trashed=true on the live state.
    state = _refetch_file_state(headers, file_id)
    if "_refetch_error" in state:
        # 404 after trash is acceptable for hard-deleted files; not common but treat as success.
        err = state["_refetch_error"].lower()
        if "404" in err or "not found" in err:
            verified = True
            mismatch = ""
        else:
            verified = False
            mismatch = f"re-fetch failed: {state['_refetch_error']}"
    else:
        verified = bool(state.get("trashed"))
        mismatch = "" if verified else f"expected trashed=true, got trashed={state.get('trashed')}"
    return {
        "id": data["id"],
        "file_id": data["id"],
        "name": data.get("name", ""),
        "trashed": True,
        "verified": verified,
        "verification": {
            "current_trashed": state.get("trashed") if "_refetch_error" not in state else None,
            "mismatch": mismatch,
        },
    }


def do_share_file(headers, file_id, share_email, share_role, share_type, notify):
    permission = {"role": share_role, "type": share_type}
    if share_type in ("user", "group"):
        permission["emailAddress"] = share_email
    time.sleep(DELAY)
    with httpx.Client(timeout=15) as c:
        r = c.post(
            f"{BASE}/files/{file_id}/permissions",
            headers=headers,
            params={
                "sendNotificationEmail": str(notify).lower(),
                "fields": "id,role,type,emailAddress",
            },
            json=permission,
        )
        # Auto-retry with "group" if "user" type fails (e.g. sharing with a Google Group)
        if r.status_code in (400, 404) and share_type == "user":
            permission["type"] = "group"
            time.sleep(DELAY)
            r = c.post(
                f"{BASE}/files/{file_id}/permissions",
                headers=headers,
                params={
                    "sendNotificationEmail": str(notify).lower(),
                    "fields": "id,role,type,emailAddress",
                },
                json=permission,
            )
        r.raise_for_status()
        data = r.json()
    permission_id = data.get("id")
    # Auto-verify: list permissions and confirm the granted permission_id is
    # present with the requested role/type/email.
    try:
        perms_data = api_get(
            headers,
            f"files/{file_id}/permissions",
            params={"fields": "permissions(id,role,type,emailAddress)"},
        )
        all_permissions = [
            {
                "id": p.get("id"),
                "role": p.get("role"),
                "type": p.get("type"),
                "email": p.get("emailAddress", ""),
            }
            for p in (perms_data.get("permissions") or [])
        ]
        found = next((p for p in all_permissions if p["id"] == permission_id), None)
        mismatches = []
        if not found:
            mismatches.append(f"permission_id {permission_id!r} not in current permissions list")
        else:
            if found.get("role") != share_role:
                mismatches.append(f"role: requested={share_role!r}, actual={found.get('role')!r}")
            if found.get("type") != permission.get("type"):
                mismatches.append(f"type: requested={permission.get('type')!r}, actual={found.get('type')!r}")
            if share_email and found.get("email") != share_email:
                mismatches.append(f"email: requested={share_email!r}, actual={found.get('email')!r}")
        verified = len(mismatches) == 0
        verification = {
            "role_actual": (found or {}).get("role"),
            "type_actual": (found or {}).get("type"),
            "email_actual": (found or {}).get("email"),
            "all_permissions": all_permissions,
            "mismatch": "; ".join(mismatches),
        }
    except Exception as exc:
        verified = False
        verification = {"mismatch": f"permissions list re-fetch failed: {str(exc)[:200]}"}
    return {
        "permission_id": permission_id,
        "file_id": file_id,
        "role": data.get("role"),
        "type": data.get("type"),
        "email": data.get("emailAddress", ""),
        "verified": verified,
        "verification": verification,
    }


def do_verify_file(headers, file_id, expected_state, expected_name, expected_shared_with):
    """Pure verification, no write. expected_state in {exists, trashed, shared_with}.
    For shared_with, expected_shared_with must be an email; verified=true iff that
    email appears in the file's permissions list."""
    state = _refetch_file_state(headers, file_id)
    if "_refetch_error" in state:
        err = state["_refetch_error"].lower()
        not_found = "404" in err or "not found" in err or "410" in err or "gone" in err
        return {
            "file_id": file_id,
            "exists": not not_found,
            "verified": expected_state == "trashed" and not_found,
            "error": state["_refetch_error"],
        }
    if expected_state == "trashed":
        verified = bool(state.get("trashed"))
        mismatch = "" if verified else f"expected trashed, got trashed={state.get('trashed')}"
    elif expected_state == "shared_with":
        if not expected_shared_with:
            return {"error": "expected_shared_with email is required when expected_state=shared_with"}
        try:
            perms_data = api_get(
                headers,
                f"files/{file_id}/permissions",
                params={"fields": "permissions(id,role,type,emailAddress)"},
            )
            emails = [p.get("emailAddress", "") for p in (perms_data.get("permissions") or [])]
            verified = expected_shared_with in emails
            mismatch = "" if verified else f"expected_shared_with={expected_shared_with} not in permissions={emails}"
        except Exception as exc:
            verified = False
            mismatch = f"permissions fetch failed: {str(exc)[:200]}"
    else:
        # default "exists"
        verified = not bool(state.get("trashed"))
        mismatch = "" if verified else "file is trashed"
    if expected_name and state.get("name") != expected_name:
        verified = False
        mismatch = (mismatch + "; " if mismatch else "") + f"name: expected={expected_name!r}, actual={state.get('name')!r}"
    return {
        "file_id": file_id,
        "exists": True,
        "verified": verified,
        "actual": {
            "name": state.get("name"),
            "mimeType": state.get("mimeType"),
            "parents": state.get("parents"),
            "trashed": state.get("trashed"),
            "shared": state.get("shared"),
        },
        "mismatch": mismatch,
    }


def do_list_permissions(headers, file_id):
    data = api_get(
        headers,
        f"files/{file_id}/permissions",
        params={"fields": "permissions(id,role,type,emailAddress,displayName)"},
    )
    perms = data.get("permissions", [])
    return {
        "permissions": [
            {
                "id": p.get("id"),
                "role": p.get("role"),
                "type": p.get("type"),
                "email": p.get("emailAddress", ""),
                "name": p.get("displayName", ""),
            }
            for p in perms
        ],
        "count": len(perms),
    }


# --- Main ---

try:
    creds_json = os.environ["GOOGLE_DRIVE_CREDENTIALS_JSON"]
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    action = inp.get("action", "")

    token = get_access_token(creds_json)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if action == "list_files":
        result = do_list_files(headers, inp.get("folder_id", ""), inp.get("max_results", 20))
    elif action == "search_files":
        result = do_search_files(headers, inp.get("query", ""), inp.get("max_results", 20))
    elif action == "get_file_info":
        result = do_get_file_info(headers, inp["file_id"])
    elif action == "create_folder":
        result = do_create_folder(headers, inp["name"], inp.get("folder_id", ""))
    elif action == "create_document":
        result = do_create_document(headers, inp["name"], inp.get("content", ""), inp.get("folder_id", ""))
    elif action == "create_spreadsheet":
        result = do_create_spreadsheet(headers, inp["name"], inp.get("content", ""), inp.get("folder_id", ""))
    elif action == "upload_text":
        result = do_upload_text(headers, inp["name"], inp.get("content", ""), inp.get("mime_type", "text/plain"), inp.get("folder_id", ""))
    elif action == "download_text":
        result = do_download_text(headers, inp["file_id"])
    elif action == "move_file":
        result = do_move_file(headers, inp["file_id"], inp["destination_folder_id"])
    elif action == "copy_file":
        result = do_copy_file(headers, inp["file_id"], inp.get("name", ""))
    elif action == "rename_file":
        result = do_rename_file(headers, inp["file_id"], inp["name"])
    elif action == "trash_file":
        result = do_trash_file(headers, inp["file_id"])
    elif action == "share_file":
        result = do_share_file(
            headers,
            inp["file_id"],
            inp.get("share_email", ""),
            inp.get("share_role", "reader"),
            inp.get("share_type", "user"),
            inp.get("notify", True),
        )
    elif action == "list_permissions":
        result = do_list_permissions(headers, inp["file_id"])
    elif action == "verify_file":
        result = do_verify_file(
            headers,
            inp["file_id"],
            inp.get("expected_state", "exists"),
            inp.get("expected_name", ""),
            inp.get("expected_shared_with", ""),
        )
    else:
        result = {"error": f"Unknown action: {action}"}

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"error": str(e)}))
