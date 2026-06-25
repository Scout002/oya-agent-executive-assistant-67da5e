---
name: gmail-search
display_name: "Gmail Search"
description: "Search emails in Gmail with a query, or verify that claimed message ids actually appear in a query result"
category: communication
icon: search
skill_type: sandbox
catalog_type: platform
skip_summarization_on_structured: true
requirements: "httpx>=0.25,google-auth>=2.0,requests>=2.20"
resource_requirements:
  - env_var: GMAIL_CREDENTIALS_JSON
    name: "Gmail Service Account JSON"
    description: "Google service account credentials JSON"
  - env_var: GMAIL_USER_EMAIL
    name: "Gmail User Email"
    description: "Email address to search"
tool_schema:
  name: gmail_search
  description: "Search emails in Gmail, or verify that claimed message ids exist in a query result"
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "search (default) or verify_emails. Use verify_emails to re-run a query and confirm specific message ids actually appear in the result set."
        enum: ['search', 'verify_emails']
        default: "search"
      query:
        type: "string"
        description: "Gmail search query (e.g. 'from:john subject:meeting')"
      max_results:
        type: "integer"
        description: "Max results for search (default 10)"
        default: 10
      claimed_message_ids:
        type: "string"
        description: "For verify_emails: comma-separated message ids the agent claims came from this query. Returns all_present + missing_ids."
        default: ""
    required: [query]
---
# Gmail Search

Search emails in Gmail with a Gmail search query, or verify message ids.

## search (default)
Returns the matching emails with metadata: `id`, `subject`, `from`, `date` (RFC 2822), `date_iso` (parsed ISO 8601 with offset), `snippet`, `label_ids`. The response includes:
- `query_used`: the actual query that was sent.
- `truncated`: true when results hit `max_results` OR Gmail returned a `nextPageToken`. When true, the agent must NOT claim "all" or "every" email — say "showing first N matching `<query>`".

## verify_emails
Re-runs a query and checks which of the supplied `claimed_message_ids` actually appear in the live result set. Returns:
- `all_present`/`verified`: true when every claimed id is present.
- `missing_ids`: ids the agent claimed but the query does not return.
- `unexpected_real_ids`: ids in the query result that the agent did not mention.
- `emails`: full metadata for each claimed id that actually exists.

The runtime verify-on-claim guard calls this automatically when the EA narrates email content ("I read 5 emails from John"); the LLM can also call it on demand.
