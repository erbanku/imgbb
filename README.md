# ImgBB

Native Dify plugin `erbanku/imgbb`, version `0.0.1`. Upload one image up to **32 MB (32,000,000 bytes)** and receive a direct image URL, Markdown image, and HTML embed. Anonymous uploads are the default; an API key is optional. There are no albums or account-session-cookie settings.

## Install and use

1. Install `artifacts/imgbb-0.0.1.difypkg` from **Dify → Plugins → Install from local package**.
2. For anonymous uploads, leave the provider API key blank. If Dify asks to authorize the provider, save the empty optional key.
3. Add **ImgBB → Upload Image** to a workflow and connect one native Dify image file to **Image**. For multiple files, use a Dify iteration node.
4. Leave **Upload Mode** as **Anonymous**, or select **API key** after configuring your own ImgBB API key.
5. Optionally enter **Image Name**. Without a name, the outgoing filename uses Unix timestamp seconds and preserves the input extension, for example `1788678000.png`.
6. Choose **Text Output Format**: direct URL (default), Markdown image, or both. Connect the tool's `text` output directly to a downstream text or Answer node.

The named `direct_url`, `markdown`, and `html` string outputs are always available for direct variable selection in downstream nodes, regardless of the selected text format. The same values also appear in the JSON output.

## Inputs

| Input | Required | Behavior |
| --- | --- | --- |
| Image | Yes | One Dify file variable, not a pasted URL, local path, or list |
| Upload Mode | Default: Anonymous | Anonymous website upload or official API-key upload |
| Image Name | No | Custom filename/name, or current Unix timestamp seconds |
| Text Output Format | Default: Direct URL | Direct URL, Markdown image, or both separated by a newline |

Input extensions are preserved when naming the multipart upload. `report` or `report.png` with a PNG input becomes `report.png`; a conflicting known image suffix is replaced with the input extension. Names may contain spaces or Unicode, but not paths/control characters, and must fit in 200 UTF-8 bytes including the extension. ImgBB may normalize names or return a URL with its own unique path; always use the returned URL. Timestamp names use seconds, so concurrent uploads may share a filename but have distinct host-generated URLs.

Common image formats include PNG, JPEG, GIF, WebP, BMP, TIFF, AVIF, HEIC/HEIF, and ICO. The original file bytes are uploaded unchanged: this plugin does not resize, recompress, convert, or remove EXIF metadata. ImgBB ultimately validates the format and may apply additional service restrictions.

## Output example

For a custom name `report`, JSON has this shape (the host path below is illustrative):

```json
{
  "direct_url": "https://i.ibb.co/example/report.png",
  "markdown": "![report](<https://i.ibb.co/example/report.png>)",
  "html": "<img src=\"https://i.ibb.co/example/report.png\" alt=\"report\" />",
  "name": "report",
  "filename": "report.png",
  "size": 12345,
  "upload_mode": "anonymous"
}
```

`filename` describes the filename submitted to ImgBB; `size` is the actual uploaded byte count. HTML attribute values and Markdown labels are escaped. Output URLs must be HTTPS. API keys, anonymous session tokens/cookies, Dify signed URLs, and host deletion links are not included in outputs.

## Authentication and reliability

**Anonymous:** opens a fresh session on `https://imgbb.com/`, reads the public upload form token, and submits the image to `https://imgbb.com/json` with that session's cookies. It does not use or transmit a configured API key. This is the website's upload flow, not a documented public API contract; it may change or require browser verification. The plugin reports those failures without attempting to bypass challenges. Switch to API-key mode if anonymous upload is unavailable.

**API key:** posts multipart image bytes to `https://api.imgbb.com/1/upload`. The API key goes in the POST form rather than the URL, and is never attached to Dify file downloads. Credential setup validates format locally and never uploads a probe image; actual key authorization happens at upload time. It never silently falls back to anonymous mode.

There are no automatic upload retries: a lost response may still mean the image was published, and retrying can create a duplicate. Error messages omit raw remote responses and signed file URLs. Uploaded images are externally hosted, not private workflow storage; do not upload secrets or sensitive images without appropriate authorization.

## Limits and resource use

Exactly 32,000,000 bytes is accepted; 32 MiB (33,554,432 bytes) exceeds the limit. Declared Dify size, HTTP content length, and actual streamed bytes are checked, including when metadata is absent or incorrect. Oversized downloads are stopped before any upload to ImgBB. Empty images are rejected.

The download is streamed to a temporary spool with a 1 MiB in-memory threshold and automatic cleanup. Dify file URLs must be reachable from the plugin runtime; signed URLs may expire. File downloads use an isolated client without ImgBB credentials. ImgBB uploads do not follow redirects. Dify workflow/proxy timeouts may need adjustment for slow 32 MB transfers; the plugin runner allows 600 seconds per request.

## Development and packaging

From the repository root:

```bash
uv sync --directory ai-pkgs/imgbb --all-groups --python 3.12
python .agents/skills/dify-plugin-generator-by-erbanku/scripts/validate_plugin.py ai-pkgs/imgbb --with-pytest --with-offline-check
python .agents/skills/dify-plugin-generator-by-erbanku/scripts/package_plugin.py ai-pkgs/imgbb --cli-path /usr/local/bin/dify
```

The package bundles Python 3.12 runtime wheels for Linux amd64 and arm64. Deployment uses `requirements.txt` for offline dependency installation, while the source retains the development `pyproject.toml` and lockfile. Generated packages and caches are ignored by Git. Network access is still required for uploads.

Automated tests mock HTTP requests and cover anonymous/API isolation, default and custom names, text/named/JSON outputs, escaping, exact 32 MB boundaries, failed downloads, challenge responses, safe errors, and SDK schema loading. A separate live anonymous smoke test successfully uploaded a synthetic 68-byte PNG on September 6, 2026; no user image was used. API-key uploads are covered by mocks, not a live credential test.

## References and branding

- Public API: https://api.imgbb.com/
- Anonymous website uploader: https://imgbb.com/
- Website upload client reference: https://simgbb.com/8179/ibb.js
- Icon downloaded on September 6, 2026: https://simgbb.com/images/favicon.png

This is an independent integration. The ImgBB name and icon belong to their owners. See `PRIVACY.md` for data handling.
