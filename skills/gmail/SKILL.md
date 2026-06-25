---
name: gmail
display_name: "Gmail"
description: "Comprehensive Gmail — read, search, send, reply, draft, label, and manage emails"
category: communication
icon: mail
skill_type: sandbox
catalog_type: platform
requirements: "httpx>=0.25"
resource_requirements:
  - env_var: GMAIL_CREDENTIALS_JSON
    name: "Gmail Credentials JSON"
    description: "OAuth2 credentials JSON (auto-provided by gateway connection)"
  - env_var: GMAIL_USER_EMAIL
    name: "Gmail User Email"
    description: "Email address of the connected Gmail account"
config_schema:
  properties:
    default_from_name:
      type: string
      label: "Default Sender Name"
      description: "Display name for outgoing emails"
      placeholder: "AI Assistant"
      group: defaults
    default_signature:
      type: text
      label: "Email Signature"
      description: "Signature appended to outgoing emails"
      placeholder: "---\nSent by AI Assistant"
      group: defaults
    max_results:
      type: number
      label: "Default Max Results"
      description: "Default number of emails to return in list/search"
      default: 10
      group: defaults
    send_rules:
      type: text
      label: "Send Rules"
      description: "Rules for when and how the LLM should send emails"
      placeholder: "- Always confirm with user before sending\n- Include a clear subject line\n- Keep emails professional and concise"
      group: rules
    reply_rules:
      type: text
      label: "Reply Rules"
      description: "Rules for replying to emails"
      placeholder: "- Quote relevant parts of the original message\n- Address all points raised in the original\n- Use Reply-All only when explicitly requested"
      group: rules
    label_rules:
      type: text
      label: "Label Rules"
      description: "Rules for auto-labeling emails"
      placeholder: "- Label invoices as 'Finance/Invoices'\n- Label support emails as 'Support'\n- Apply 'Action Required' to urgent items"
      group: rules
    safety_rules:
      type: text
      label: "Safety Rules"
      description: "Safety constraints for email operations"
      placeholder: "- Never send to more than 10 recipients at once\n- Always confirm before trashing emails\n- Never auto-reply to external senders"
      group: rules
tool_schema:
  name: gmail
  description: "Comprehensive Gmail — read, search, send, reply, draft, label, and manage emails"
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which operation to perform"
        enum: ['read_inbox', 'search', 'get_message', 'send', 'reply', 'create_draft', 'send_draft', 'list_labels', 'modify_labels', 'trash', 'mark_read']
      query:
        type: "string"
        description: "Gmail search query for search action (e.g. 'from:john subject:meeting is:unread')"
        default: ""
      message_id:
        type: "string"
        description: "Message ID — required for get_message, reply, modify_labels, trash, mark_read"
        default: ""
      draft_id:
        type: "string"
        description: "Draft ID — required for send_draft"
        default: ""
      to:
        type: "string"
        description: "Primary recipient(s) only — comma-separated. Do NOT put CC or BCC recipients here. Required for send, create_draft."
        default: ""
      cc:
        type: "string"
        description: "CC (carbon copy) recipients — comma-separated. Use when the user says 'CC', 'copy', or 'loop in'. These recipients receive the email visibly."
        default: ""
      bcc:
        type: "string"
        description: "BCC (blind carbon copy) recipients — comma-separated. Use when the user says 'BCC' or 'blind copy'. These recipients are hidden from others."
        default: ""
      subject:
        type: "string"
        description: "Email subject — for send, create_draft"
        default: ""
      body:
        type: "string"
        description: "Email body (plain text) — for send, reply, create_draft. Used as the fallback when html is also provided."
        default: ""
      html:
        type: "string"
        description: "Optional HTML body for send/create_draft. Prefer this for digests, reports, and any formatted email — it is wrapped in a clean responsive template automatically. Provide an HTML fragment (headings, paragraphs, lists, tables); keep a short plain-text body as the fallback."
        default: ""
      thread_id:
        type: "string"
        description: "Thread ID — for reply (keeps message in same thread)"
        default: ""
      add_labels:
        type: "string"
        description: "Comma-separated label IDs to add — for modify_labels"
        default: ""
      remove_labels:
        type: "string"
        description: "Comma-separated label IDs to remove — for modify_labels"
        default: ""
      max_results:
        type: "integer"
        description: "Max results for read_inbox and search"
        default: 10
    required: [action]
---
# Gmail

Comprehensive Gmail management — read, search, compose, reply, draft, label, and organize emails.

## Reading
- **read_inbox** — Read recent inbox messages. Optional `max_results` (default 10).
- **search** — Search emails with Gmail query syntax. Provide `query`. Optional `max_results`.
- **get_message** — Get full message content. Provide `message_id`.

## Composing
- **send** — Send a new email. Provide `to`, `subject`, `body`. Optional `cc`, `bcc`.
  - **Important:** When the user specifies CC or BCC recipients, put them in the `cc`/`bcc` fields — NOT in `to`. Only primary recipients go in `to`.
- **reply** — Reply to a message. Provide `message_id`, `body`. Optional `to` (defaults to original sender), `thread_id`.
- **create_draft** — Create a draft. Provide `to`, `subject`, `body`. Optional `cc`, `bcc`.
- **send_draft** — Send an existing draft. Provide `draft_id`.

## Organization
- **list_labels** — List all Gmail labels with IDs.
- **modify_labels** — Add/remove labels on a message. Provide `message_id`, `add_labels` and/or `remove_labels` (comma-separated label IDs).
- **trash** — Move a message to trash. Provide `message_id`.
- **mark_read** — Mark a message as read. Provide `message_id`.

## Example: Send with CC and BCC
```
action: send
to: "alice@example.com"
cc: "bob@example.com, carol@example.com"
bcc: "manager@example.com"
subject: "Q2 Planning"
body: "Hi Alice, ..."
```

## Gmail search query examples
- `from:john@example.com` — from specific sender
- `subject:meeting` — subject contains "meeting"
- `is:unread` — unread messages only
- `has:attachment` — messages with attachments
- `after:2024/01/01 before:2024/02/01` — date range
- `label:important` — messages with label
- `in:sent` — sent messages
