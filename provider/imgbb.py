from typing import Any
import re

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


def validate_api_key(value: Any, required: bool = False) -> str:
    if value is None or value == "":
        if required:
            raise ToolProviderCredentialValidationError("Configure an ImgBB API key or choose Anonymous upload mode.")
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value.strip()):
        raise ToolProviderCredentialValidationError("The ImgBB API key must contain only letters, digits, underscores or hyphens.")
    return value.strip()


class ImgbbProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        validate_api_key(credentials.get("api_key"))
