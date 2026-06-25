import os, json, httpx

_allowed = [c.strip() for c in os.environ.get("SLACK_ALLOWED_CHANNELS", "").split(",") if c.strip()]
_allowed_names = [n.strip() for n in os.environ.get("SLACK_ALLOWED_CHANNEL_NAMES", "").split(",") if n.strip()]


def _resolve_channel(channel: str) -> tuple[str, str | None]:
    """Returns (canonical_channel_id, error). Accepts ID, name, or `#name`."""
    raw = (channel or "").strip()
    if not _allowed:
        return raw, None
    bare = raw.lstrip("#").strip()
    if raw in _allowed or bare in _allowed:
        return bare if bare in _allowed else raw, None
    if bare in _allowed_names:
        idx = _allowed_names.index(bare)
        return _allowed[idx] if idx < len(_allowed) else bare, None
    pretty = ", ".join(f"#{n}" for n in _allowed_names) or ", ".join(_allowed)
    return raw, (
        f"Channel {channel} is not in this agent's allowed Slack channels "
        f"({pretty}). Refusing. Ask the user to update the gateway "
        f"configuration if access to this channel is intended."
    )


try:
    token = os.environ["SLACK_BOT_TOKEN"]
    inp = json.loads(os.environ.get("INPUT_JSON", "{}"))
    channel = inp.get("channel", "")
    thread_ts = inp.get("thread_ts", "")
    limit = inp.get("limit", 10)
    if not channel or not thread_ts:
        print(json.dumps({"error": "channel and thread_ts are required"}))
    else:
        channel, blocked = _resolve_channel(channel)
        if blocked is not None:
            print(json.dumps({"error": blocked}))
            raise SystemExit(0)
        params = {"channel": channel, "ts": thread_ts, "limit": limit}
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=15) as c:
            r = c.get("https://slack.com/api/conversations.replies", headers=headers, params=params)
            data = r.json()
            if not data.get("ok") and data.get("error") in ("not_in_channel", "channel_not_found"):
                join_r = c.post("https://slack.com/api/conversations.join",
                    headers={**headers, "Content-Type": "application/json"}, json={"channel": channel})
                if join_r.json().get("ok"):
                    r2 = c.get("https://slack.com/api/conversations.replies", headers=headers, params=params)
                    data = r2.json()
        if data.get("ok"):
            messages = [{"text": m.get("text",""), "user": m.get("user",""), "ts": m.get("ts","")} for m in data.get("messages", [])]
            print(json.dumps({"messages": messages, "count": len(messages)}))
        else:
            err = data.get("error", "unknown")
            diag = {}
            if err == "channel_not_found":
                with httpx.Client(timeout=10) as dc:
                    info_r = dc.get("https://slack.com/api/conversations.info",
                        headers={"Authorization": f"Bearer {token}"}, params={"channel": channel})
                    info = info_r.json()
                diag["conversations_info_ok"] = info.get("ok")
                diag["conversations_info_error"] = info.get("error") if not info.get("ok") else None
            out = {"error": err}
            if err in ("not_in_channel", "channel_not_found"):
                out["hint"] = "Invite the bot to the channel if it's private."
            if diag:
                out["diagnostic"] = diag
            print(json.dumps(out))
except Exception as e:
    print(json.dumps({"error": str(e)}))
