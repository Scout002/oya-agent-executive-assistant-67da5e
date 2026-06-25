---
name: slack-read-messages
display_name: "Slack Read Messages"
description: "Read messages from a Slack thread"
category: communication
icon: message-square
skill_type: sandbox
catalog_type: platform
resource_requirements:
  - env_var: SLACK_BOT_TOKEN
    name: "Slack Bot Token"
    description: "Slack Bot OAuth token (xoxb-...)"
tool_schema:
  name: slack_read_messages
  description: "Read messages from a Slack thread (thread_ts is the root message timestamp)"
  parameters:
    type: object
    properties:
      channel:
        type: "string"
        description: "Channel ID"
      thread_ts:
        type: "string"
        description: "Thread ID (timestamp of the root message, e.g. 1709827000.000001)"
      limit:
        type: "integer"
        description: "Number of messages to fetch (default 10)"
    required: [channel, thread_ts]
---
# Slack Read Messages
Read messages from a Slack thread. Requires channel and thread_ts (the root message timestamp).
