from collections.abc import Generator
import html
import mimetypes
from pathlib import PurePosixPath
import re
import tempfile
import time
from typing import Any, BinaryIO
from urllib.parse import urlsplit

import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File

from provider.imgbb import validate_api_key


MAX_IMAGE_BYTES = 32_000_000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif", ".ico"}
USER_AGENT = "erbanku-imgbb-dify/0.0.1"


class UploadError(ValueError):
    pass


def image_filename(file: File, custom_name: Any, timestamp: int) -> tuple[str, str]:
    if custom_name is not None and not isinstance(custom_name, str):
        raise UploadError("Image Name must be text.")
    extension = PurePosixPath((file.filename or "").replace("\\", "/")).suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        extension = (file.extension or "").lower()
        if extension and not extension.startswith("."):
            extension = "." + extension
    if extension not in IMAGE_EXTENSIONS:
        extension = mimetypes.guess_extension(file.mime_type or "") or ""
    if extension not in IMAGE_EXTENSIONS:
        raise UploadError("Select an image with a supported filename extension or image MIME type.")
    name = (custom_name or "").strip() or str(timestamp)
    if any(ord(character) < 32 or character in "/\\" for character in name):
        raise UploadError("Image Name must not contain paths or control characters.")
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        name = name[:-len(suffix)]
    if name in {"", ".", ".."} or len((name + extension).encode("utf-8")) > 200:
        raise UploadError("Image Name must be nonempty and fit within 200 UTF-8 bytes including the extension.")
    return name, name + extension


def download_image(file: File, destination: BinaryIO) -> int:
    if file.size is not None and (file.size < 0 or file.size > MAX_IMAGE_BYTES):
        raise UploadError("Image exceeds 32 MB (32,000,000 bytes), or has an invalid declared size.")
    try:
        parsed = urlsplit(file.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise UploadError("The Dify image must have a reachable HTTP(S) file URL without embedded credentials.")
    except ValueError:
        raise UploadError("The Dify image has an invalid file URL.") from None
    size = 0
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True, max_redirects=5) as client:
            with client.stream("GET", file.url) as response:
                response.raise_for_status()
                declared_length = response.headers.get("content-length", "")
                if declared_length.isdigit() and int(declared_length) > MAX_IMAGE_BYTES:
                    raise UploadError("Image exceeds 32 MB (32,000,000 bytes).")
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise UploadError("Image exceeds 32 MB (32,000,000 bytes).")
                    destination.write(chunk)
    except (httpx.HTTPError, httpx.InvalidURL):
        raise UploadError("Cannot download the Dify image. Check that the file URL is reachable and has not expired.") from None
    if size == 0:
        raise UploadError("The image file is empty.")
    destination.seek(0)
    return size


def response_image(response: httpx.Response, mode: str) -> dict[str, Any]:
    if not 200 <= response.status_code < 300:
        if response.status_code == 413:
            reason = "ImgBB rejected the image size. The maximum is 32 MB."
        elif response.status_code == 429:
            reason = "ImgBB rate-limited the upload. Retry later."
        elif mode == "anonymous" and response.status_code in {401, 403}:
            reason = "Anonymous upload is unavailable or needs browser verification. Try API-key mode."
        elif response.status_code in {400, 401, 403}:
            reason = "Check the API key, image format and account restrictions."
        else:
            reason = "ImgBB upload failed. Check its availability before retrying."
        raise UploadError(f"ImgBB HTTP {response.status_code}: {reason}")
    try:
        payload = response.json()
    except ValueError:
        raise UploadError("ImgBB returned a non-JSON response. Upload status is unknown; check before retrying.") from None
    if not isinstance(payload, dict):
        raise UploadError("ImgBB returned an unexpected response. Upload status is unknown.")
    if payload.get("success") is False or str(payload.get("status_code", payload.get("status", 200))) != "200" or payload.get("error"):
        raise UploadError("ImgBB rejected the upload. Check the image and chosen authentication mode; anonymous uploads may require browser verification.")
    image = payload.get("image" if mode == "anonymous" else "data")
    if not isinstance(image, dict):
        raise UploadError("ImgBB returned no image details. Upload status is unknown.")
    return image


def upload_image(content: BinaryIO, filename: str, name: str, mode: str, api_key: str, timestamp: int) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            if mode == "api_key":
                response = client.post(
                    "https://api.imgbb.com/1/upload",
                    data={"key": api_key, "name": name},
                    files={"image": (filename, content, mime_type)},
                )
            else:
                homepage = client.get("https://imgbb.com/")
                if homepage.status_code != 200:
                    raise UploadError("Cannot start an anonymous ImgBB session. Try later or use API-key mode.")
                token = re.search(r'''(?:auth_token["']?\s*[:=]\s*)["']([A-Za-z0-9_-]{16,256})["']''', homepage.text)
                if not token:
                    raise UploadError("ImgBB's anonymous upload form changed or requires browser verification. Use API-key mode.")
                response = client.post(
                    "https://imgbb.com/json",
                    data={"action": "upload", "type": "file", "auth_token": token.group(1), "timestamp": str(timestamp * 1000), "title": name},
                    files={"source": (filename, content, mime_type)},
                    headers={"Origin": "https://imgbb.com", "Referer": "https://imgbb.com/", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
                )
    except httpx.HTTPError:
        raise UploadError("ImgBB network request failed. Upload status may be unknown; retries can create duplicates.") from None
    return response_image(response, mode)


def image_outputs(image: dict[str, Any], name: str, filename: str, size: int, mode: str) -> dict[str, Any]:
    direct_url = image.get("url")
    if not isinstance(direct_url, str) or any(character.isspace() or character in '<>"\\`' for character in direct_url):
        raise UploadError("ImgBB returned no safe direct image URL. Upload status is unknown.")
    try:
        parsed = urlsplit(direct_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
    except ValueError:
        raise UploadError("ImgBB returned an invalid direct image URL. Upload status is unknown.") from None
    alt = html.escape(name, quote=False).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return {
        "direct_url": direct_url,
        "markdown": f"![{alt}](<{direct_url}>)",
        "html": f'<img src="{html.escape(direct_url, quote=True)}" alt="{html.escape(name, quote=True)}" />',
        "name": name,
        "filename": filename,
        "size": size,
        "upload_mode": mode,
    }


class UploadImageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        mode = tool_parameters.get("upload_mode") or "anonymous"
        text_format = tool_parameters.get("text_format") or "direct_url"
        if mode not in {"anonymous", "api_key"}:
            raise UploadError("Upload Mode must be Anonymous or API key.")
        if text_format not in {"direct_url", "markdown", "both"}:
            raise UploadError("Text Output Format must be Direct URL, Markdown image, or both.")
        api_key = validate_api_key(self.runtime.credentials.get("api_key"), required=True) if mode == "api_key" else ""
        file = tool_parameters.get("image")
        if not isinstance(file, File):
            raise UploadError("Select one native Dify image file, not a URL, local path or file list.")
        timestamp = int(time.time())
        name, filename = image_filename(file, tool_parameters.get("name"), timestamp)
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as content:
            size = download_image(file, content)
            image = upload_image(content, filename, name, mode, api_key, timestamp)
        output = image_outputs(image, name, filename, size, mode)
        yield self.create_json_message(output)
        for field in ("direct_url", "markdown", "html"):
            yield self.create_variable_message(field, output[field])
        text = output["direct_url"] + "\n" + output["markdown"] if text_format == "both" else output[text_format]
        yield self.create_text_message(text)
