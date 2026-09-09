from io import BytesIO
from pathlib import Path
import tempfile

import httpx
import pytest
import yaml
from dify_plugin.entities.tool import ToolProviderConfiguration
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from dify_plugin.file.file import File

from provider.imgbb import ImgbbProvider, validate_api_key
from tools import upload_image as module
from tools.upload_image import MAX_IMAGE_BYTES, UploadError, UploadImageTool, download_image, image_filename, image_outputs, response_image

FAKE_AUTH_TOKEN = "x" * 32


@pytest.fixture
def image():
    return File(url="https://dify.example.test/image?signature=private", type="image", filename="original.png", mime_type="image/png", size=4)


def fake_network(monkeypatch, mode="anonymous", status=200, payload=None, homepage=None, upload_error=None):
    requests = []
    original_client = httpx.Client
    if payload is None:
        payload = {"status_code": 200, "image": {"url": "https://i.ibb.co/test/image.png"}} if mode == "anonymous" else {"success": True, "status": 200, "data": {"url": "https://i.ibb.co/test/image.png", "delete_url": "secret-delete"}}

    def handler(request):
        requests.append(request)
        if request.url.host == "dify.example.test":
            return httpx.Response(200, content=b"data")
        if request.method == "GET":
            return httpx.Response(200, text=homepage if homepage is not None else f'PF.obj.config.auth_token="{FAKE_AUTH_TOKEN}";', headers={"set-cookie": "PHPSESSID=testsession; Path=/; Secure"})
        if upload_error:
            raise upload_error
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(module.time, "time", lambda: 1788678000.25)
    return requests


def invoke(image, **parameters):
    return list(UploadImageTool.from_credentials({"api_key": "test_api_key"})._invoke({"image": image, **parameters}))


def test_anonymous_is_default_and_does_not_send_key(monkeypatch, image):
    requests = fake_network(monkeypatch)
    messages = invoke(image)
    assert len(requests) == 3
    assert requests[0].url.host == "dify.example.test"
    upload = requests[-1]
    assert str(upload.url) == "https://imgbb.com/json"
    assert upload.headers["cookie"] == "PHPSESSID=testsession"
    assert "cookie" not in requests[0].headers
    assert b'name="source"; filename="1788678000.png"' in upload.content
    assert FAKE_AUTH_TOKEN.encode() in upload.content
    assert b"1788678000000" in upload.content
    assert all(b"test_api_key" not in request.content and "test_api_key" not in str(request.url) for request in requests)
    output = messages[0].message.json_object
    assert output["name"] == "1788678000"
    assert output["filename"] == "1788678000.png"
    assert output["size"] == 4
    assert output["upload_mode"] == "anonymous"
    assert output["html"] == '<img src="https://i.ibb.co/test/image.png" alt="1788678000" />'
    assert messages[-1].message.text == output["direct_url"]
    named = {message.message.variable_name: message.message.variable_value for message in messages[1:4]}
    assert named == {key: output[key] for key in ("direct_url", "markdown", "html")}
    assert "private" not in str(messages)


def test_anonymous_without_credentials(monkeypatch, image):
    fake_network(monkeypatch)
    assert list(UploadImageTool.from_credentials({})._invoke({"image": image}))[0].message.json_object["upload_mode"] == "anonymous"


def test_api_key_upload_has_no_anonymous_session(monkeypatch, image):
    requests = fake_network(monkeypatch, mode="api_key")
    messages = invoke(image, upload_mode="api_key", name="report")
    assert len(requests) == 2
    upload = requests[-1]
    assert str(upload.url) == "https://api.imgbb.com/1/upload"
    assert b'name="image"; filename="report.png"' in upload.content
    assert b'name="key"\r\n\r\ntest_api_key' in upload.content
    assert b"test_api_key" not in requests[0].content
    assert "test_api_key" not in str(upload.url)
    assert "secret-delete" not in str(messages)


@pytest.mark.parametrize("text_format", ["direct_url", "markdown", "both"])
def test_text_output_formats(monkeypatch, image, text_format):
    fake_network(monkeypatch)
    messages = invoke(image, text_format=text_format)
    output = messages[0].message.json_object
    expected = output["direct_url"] + "\n" + output["markdown"] if text_format == "both" else output[text_format]
    assert messages[-1].message.text == expected


@pytest.mark.parametrize("name,expected", [(None, "123.png"), ("", "123.png"), ("  ", "123.png"), ("report", "report.png"), ("report.png", "report.png"), ("report.jpg", "report.png"), ("季度报告", "季度报告.png")])
def test_names_and_extensions(image, name, expected):
    assert image_filename(image, name, 123)[1] == expected


@pytest.mark.parametrize("name", ["../report", "folder\\report", "bad\nname", ".", "..", "a" * 201, 123])
def test_invalid_names(image, name):
    with pytest.raises(UploadError):
        image_filename(image, name, 123)


def test_extension_fallbacks(image):
    image.filename = None
    image.extension = "webp"
    assert image_filename(image, "logo", 123)[1] == "logo.webp"
    image.extension = None
    assert image_filename(image, "logo", 123)[1] == "logo.png"
    image.mime_type = "application/pdf"
    with pytest.raises(UploadError):
        image_filename(image, "logo", 123)


def test_html_and_markdown_escape_user_name():
    output = image_outputs({"url": "https://i.ibb.co/a.png?x=1&y=2"}, 'Report [Q3] <b>"', "report.png", 4, "anonymous")
    assert output["html"] == '<img src="https://i.ibb.co/a.png?x=1&amp;y=2" alt="Report [Q3] &lt;b&gt;&quot;" />'
    assert "\\[Q3\\]" in output["markdown"]
    assert "<b>" not in output["markdown"]


@pytest.mark.parametrize("url", [None, "", "javascript:alert(1)", "http://i.ibb.co/a.png", "https://user:pass@i.ibb.co/a.png", "https://i.ibb.co/a.png\n", 'https://i.ibb.co/a.png" onerror="bad', "https://[bad"])
def test_reject_unsafe_response_urls(url):
    with pytest.raises(UploadError):
        image_outputs({"url": url}, "test", "test.png", 4, "anonymous")


def test_blank_provider_credentials_need_no_network(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("Credential validation must be local"))
    ImgbbProvider()._validate_credentials({})
    ImgbbProvider()._validate_credentials({"api_key": ""})
    assert validate_api_key(" test_key ") == "test_key"


def test_key_required_only_for_api_mode(monkeypatch, image):
    requests = fake_network(monkeypatch)
    with pytest.raises(ToolProviderCredentialValidationError):
        list(UploadImageTool.from_credentials({})._invoke({"image": image, "upload_mode": "api_key"}))
    assert not requests


@pytest.mark.parametrize("key", [123, "bad key", "key\nkey", "a" * 257])
def test_invalid_api_key(key):
    with pytest.raises(ToolProviderCredentialValidationError):
        validate_api_key(key)


@pytest.mark.parametrize("field,value", [("image", "https://example.test/a.png"), ("image", []), ("upload_mode", "other"), ("text_format", "html")])
def test_invalid_inputs_do_not_contact_host(monkeypatch, image, field, value):
    requests = fake_network(monkeypatch)
    parameters = {"image": image, field: value}
    with pytest.raises(UploadError):
        list(UploadImageTool.from_credentials({})._invoke(parameters))
    assert not requests


def test_oversized_metadata_rejected_before_download(monkeypatch, image):
    requests = fake_network(monkeypatch)
    image.size = MAX_IMAGE_BYTES + 1
    with pytest.raises(UploadError, match="32 MB"):
        invoke(image)
    assert not requests


class SizedStream(httpx.SyncByteStream):
    def __init__(self, size):
        self.size = size

    def __iter__(self):
        remaining = self.size
        while remaining:
            chunk = b"x" * min(remaining, 65536)
            remaining -= len(chunk)
            yield chunk


@pytest.mark.parametrize("size", [MAX_IMAGE_BYTES - 1, MAX_IMAGE_BYTES, MAX_IMAGE_BYTES + 1])
def test_actual_32mb_boundary_without_metadata(monkeypatch, image, size):
    image.size = None
    original_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SizedStream(size)))
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as destination:
        if size > MAX_IMAGE_BYTES:
            with pytest.raises(UploadError, match="32 MB"):
                download_image(image, destination)
        else:
            assert download_image(image, destination) == size
            assert destination.tell() == 0


@pytest.mark.parametrize("status,content,headers", [(200, b"", {}), (403, b"private URL", {}), (200, b"tiny", {"Content-Length": str(MAX_IMAGE_BYTES + 1)})])
def test_download_errors(monkeypatch, image, status, content, headers):
    original_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(status, content=content, headers=headers))
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    with pytest.raises(UploadError) as error:
        download_image(image, BytesIO())
    assert "signature" not in str(error.value)


@pytest.mark.parametrize("status", [400, 401, 403, 413, 429, 500, 302])
def test_http_errors_are_sanitized_and_not_retried(monkeypatch, image, status):
    requests = fake_network(monkeypatch, status=status, payload={"error": "private API key"})
    with pytest.raises(UploadError, match=f"HTTP {status}") as error:
        invoke(image)
    assert len(requests) == 3
    assert "private" not in str(error.value)


def test_missing_anonymous_token_fails_without_upload(monkeypatch, image):
    requests = fake_network(monkeypatch, homepage="Browser challenge")
    with pytest.raises(UploadError, match="browser verification"):
        invoke(image)
    assert len(requests) == 2


def test_json_style_anonymous_token(monkeypatch, image):
    requests = fake_network(monkeypatch, homepage=f'{{"auth_token": "{FAKE_AUTH_TOKEN}"}}')
    invoke(image)
    assert len(requests) == 3


def test_network_timeout_reports_uncertain_status(monkeypatch, image):
    requests = fake_network(monkeypatch, upload_error=httpx.ReadTimeout("private token"))
    with pytest.raises(UploadError, match="unknown") as error:
        invoke(image)
    assert "private" not in str(error.value)
    assert len(requests) == 3


@pytest.mark.parametrize("payload", [[], {}, {"success": False}, {"status_code": 400, "error": "secret"}, {"status_code": 200, "image": None}])
def test_bad_response_json(payload):
    with pytest.raises(UploadError) as error:
        response_image(httpx.Response(200, json=payload), "anonymous")
    assert "secret" not in str(error.value)


def test_non_json_response():
    with pytest.raises(UploadError, match="non-JSON"):
        response_image(httpx.Response(200, text="private challenge"), "anonymous")


def test_sdk_schema_and_defaults():
    root = Path(__file__).resolve().parent.parent
    provider = ToolProviderConfiguration.model_validate(yaml.safe_load((root / "provider/imgbb.yaml").read_text()))
    assert provider.identity.name == "imgbb"
    assert provider.credentials_schema[0].required is False
    tool = provider.tools[0]
    assert next(parameter for parameter in tool.parameters if parameter.name == "upload_mode").default == "anonymous"
    assert set(tool.output_schema["properties"]) == {"direct_url", "markdown", "html"}
    assert all("album" not in parameter.name for parameter in tool.parameters)
