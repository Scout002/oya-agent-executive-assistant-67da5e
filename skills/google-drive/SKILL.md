---
name: google-drive
display_name: "Google Drive"
description: "Manage Google Drive — list, search, create, upload, share, and organize files, folders, docs, and sheets"
category: productivity
icon: hard-drive
skill_type: sandbox
catalog_type: platform
skip_summarization_on_structured: true
requirements: "httpx>=0.25,google-auth>=2.0,requests>=2.20"
resource_requirements:
  - env_var: GOOGLE_DRIVE_CREDENTIALS_JSON
    name: "Google Drive Credentials JSON"
    description: "OAuth2 credentials JSON (auto-provided by gateway connection)"
  - env_var: GOOGLE_DRIVE_USER_EMAIL
    name: "Google Drive User Email"
    description: "Email address of the connected Google account"
config_schema:
  properties:
    default_folder_id:
      type: string
      label: "Default Folder ID"
      description: "Default folder ID for file operations (use 'root' for My Drive root)"
      placeholder: "root"
      default: "root"
      group: defaults
    default_share_role:
      type: select
      label: "Default Share Role"
      description: "Default permission role when sharing files"
      options: ["reader", "commenter", "writer"]
      default: "reader"
      group: defaults
    file_rules:
      type: text
      label: "File Organization Rules"
      description: "Rules for how the LLM should organize files and folders"
      placeholder: "- Create project folders with date prefix (YYYY-MM-DD)\n- Always share with the team group email\n- Use descriptive file names"
      group: rules
    sharing_rules:
      type: text
      label: "Sharing Rules"
      description: "Rules for file sharing permissions"
      placeholder: "- Default to viewer access\n- Only give editor access when explicitly requested\n- Always notify when sharing"
      group: rules
    naming_rules:
      type: text
      label: "Naming Conventions"
      description: "Rules for file and folder naming"
      placeholder: "- Use kebab-case for file names\n- Prefix project docs with project code\n- Include version numbers for iterations"
      group: rules
tool_schema:
  name: google_drive
  description: "Manage Google Drive — list, search, create, upload, share, and organize files, folders, docs, and sheets"
  parameters:
    type: object
    properties:
      action:
        type: "string"
        description: "Which operation to perform"
        enum: ['list_files', 'search_files', 'get_file_info', 'create_folder', 'create_document', 'create_spreadsheet', 'upload_text', 'download_text', 'move_file', 'copy_file', 'rename_file', 'trash_file', 'share_file', 'list_permissions', 'verify_file']
      expected_state:
        type: "string"
        description: "For verify_file: exists | trashed | shared_with"
        enum: ['exists', 'trashed', 'shared_with']
        default: "exists"
      expected_name:
        type: "string"
        description: "For verify_file: expected file name. Mismatch flips verified=false."
        default: ""
      expected_shared_with:
        type: "string"
        description: "For verify_file with expected_state=shared_with: the email that MUST be in the permissions list."
        default: ""
      folder_id:
        type: "string"
        description: "Folder ID for list_files, create_folder (parent), upload/create targets. Use 'root' for My Drive root."
        default: ""
      query:
        type: "string"
        description: "Search query for search_files — supports Drive query syntax (e.g. \"name contains 'report'\" or \"mimeType='application/pdf'\")"
        default: ""
      file_id:
        type: "string"
        description: "File ID — required for get_file_info, download_text, move_file, copy_file, rename_file, trash_file, share_file, list_permissions"
        default: ""
      name:
        type: "string"
        description: "File or folder name — for create_folder, create_document, create_spreadsheet, upload_text, copy_file, rename_file"
        default: ""
      content:
        type: "string"
        description: "Text content — for create_document (becomes Google Doc), create_spreadsheet (CSV content), upload_text"
        default: ""
      mime_type:
        type: "string"
        description: "MIME type for upload_text (e.g. 'text/plain', 'text/csv', 'application/json')"
        default: "text/plain"
      destination_folder_id:
        type: "string"
        description: "Target folder ID for move_file"
        default: ""
      share_email:
        type: "string"
        description: "Email address to share with — for share_file"
        default: ""
      share_role:
        type: "string"
        description: "Permission role: reader, commenter, writer — for share_file"
        default: "reader"
      share_type:
        type: "string"
        description: "Permission type for share_file: 'user' for individual emails, 'group' for Google Group emails (e.g. team@company.com Google Groups), 'domain' for entire domain, 'anyone' for public link. IMPORTANT: use 'group' when sharing with a Google Group address."
        default: "user"
      notify:
        type: "boolean"
        description: "Send notification email when sharing"
        default: true
      max_results:
        type: "integer"
        description: "Max results for list/search operations"
        default: 20
    required: [action]
---
# Google Drive

Manage Google Drive files, folders, docs, and sheets. Supports the full file lifecycle: create, search, organize, share, and download.

## Navigation
- **list_files** — List files in a folder. Provide `folder_id` (defaults to root). Optional `max_results`.
- **search_files** — Search files by query. Provide `query` (Drive query syntax). Optional `max_results`.
- **get_file_info** — Get file metadata. Provide `file_id`.

## Creation
- **create_folder** — Create a folder. Provide `name` and optional `folder_id` (parent).
- **create_document** — Create a Google Doc. Provide `name` and optional `content` (plain text, converted to Doc). Optional `folder_id`.
- **create_spreadsheet** — Create a Google Sheet. Provide `name` and optional `content` (CSV data, converted to Sheet). Optional `folder_id`.
- **upload_text** — Upload a text file. Provide `name`, `content`, and optional `mime_type` (default: text/plain). Optional `folder_id`.

## Reading
- **download_text** — Download text content of a file. Provide `file_id`. Exports Google Docs as plain text, Google Sheets as CSV.

## Organization
- **move_file** — Move a file to a different folder. Provide `file_id` and `destination_folder_id`.
- **copy_file** — Copy a file. Provide `file_id` and optional `name` (new name).
- **rename_file** — Rename a file. Provide `file_id` and `name`.
- **trash_file** — Move a file to trash. Provide `file_id`.

## Sharing
- **share_file** — Share a file. Provide `file_id`, `share_email`, `share_role` (reader/commenter/writer), `share_type` (user/group/domain/anyone). Optional `notify`.
  - Use `share_type: "user"` for individual Google accounts.
  - Use `share_type: "group"` for Google Group email addresses. If sharing fails with "user" type, retry with "group" type.
  - Use `share_type: "anyone"` for public access (no email needed).
- **list_permissions** — List sharing permissions. Provide `file_id`.

## Verification (truthfulness guard)
Every write action (`create_folder`, `create_document`, `create_spreadsheet`, `upload_text`, `share_file`, `trash_file`) automatically re-fetches the file or permissions list after the write and returns:
- `verified: bool` — true iff the live state matches the requested change.
- `verification.mismatch` — human-readable diff when verified is false (e.g. `name: requested='Q3 deck', actual='Q3 deck (1)'`, `permission_id ... not in current permissions list`).
- For `list_files` and `search_files`, the response includes `truncated: bool` (true when results hit `max_results` OR Drive returned a `nextPageToken`). The agent must NOT claim "all" matching files when `truncated` is true.

- **verify_file** — pure verification, no write. Provide `file_id` and `expected_state` (one of `exists`, `trashed`, `shared_with`). For `shared_with`, also provide `expected_shared_with` email. Returns `{exists, verified, actual: {name, mimeType, parents, trashed, shared}, mismatch}`. Use as a standalone audit, or rely on auto-verification baked into every write.

## Drive query syntax examples
- `name contains 'budget'` — files with "budget" in name
- `mimeType = 'application/pdf'` — PDF files only
- `modifiedTime > '2024-01-01'` — recently modified
- `'folder_id' in parents` — files in specific folder
- `trashed = false` — exclude trashed files
