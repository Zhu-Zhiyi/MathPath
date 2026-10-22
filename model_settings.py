"""本机模型配置；只将公开字段交给界面，完整记录由 Windows DPAPI 保护。"""

from dataclasses import dataclass, field
import ipaddress
import json
import re
import secrets
import threading
from urllib.parse import unquote, urlsplit, urlunsplit

from chatgpt_login import DATA_DIR, RESOURCE, atomic_write, protect_bytes

SETTINGS_FILE = DATA_DIR / "api_settings.dpapi"
DEFAULT_BASE_URL = "https://models.sjtu.edu.cn/api/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-reasoner"
DEFAULT_CHATGPT_MODEL = "gpt-5.6-sol"
_settings_lock = threading.RLock()
_PUBLIC_FIELDS = ("provider", "base_url", "model", "api_format", "output_mode", "revision")
_INPUT_FIELDS = set(_PUBLIC_FIELDS) - {"revision"} | {"api_key", "clear_api_key"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SettingsError(Exception):
    """固定、安全的配置错误；从不包含提交的值或底层异常。"""


@dataclass(frozen=True)
class GenerationConfig:
    provider: str
    base_url: str
    model: str
    api_format: str
    output_mode: str
    revision: str
    api_key: str = field(default="", repr=False, compare=False)


def _defaults():
    return {"provider": "api", "base_url": DEFAULT_BASE_URL, "model": DEFAULT_DEEPSEEK_MODEL,
            "api_format": "chat_completions", "output_mode": "json_object",
            "api_key": "", "revision": "default"}


def _text(value, *, message, limit, empty=True):
    if not isinstance(value, str) or len(value) > limit or _CONTROL.search(value):
        raise SettingsError(message)
    value = value.strip()
    if not empty and not value:
        raise SettingsError(message)
    return value


def _base_url(value):
    message = ("API 基础地址必须是 HTTPS 地址；本机服务可使用 HTTP。"
               "请填写基础地址，不要包含完整生成端点、账号、查询参数或片段。")
    value = _text(value, message=message, limit=2048, empty=False)
    if any(character.isspace() for character in value) or "\\" in value:
        raise SettingsError(message)
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme not in {"https", "http"} or not host or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or "?" in value or "#" in value or "%" in parsed.netloc
                or parsed.netloc.endswith(":") or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
        if ":" in host:
            ipaddress.IPv6Address(host)
            normalized_host = "[" + host.lower() + "]"
        else:
            normalized_host = host.encode("idna").decode("ascii").lower()
            if not re.fullmatch(r"[a-z0-9.-]+", normalized_host) or any(
                    not segment or segment.startswith("-") or segment.endswith("-")
                    for segment in normalized_host.split(".")):
                raise ValueError
        if parsed.scheme == "http" and host.lower() not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError
        decoded_path = unquote(parsed.path).rstrip("/")
        if (_CONTROL.search(decoded_path) or "\\" in decoded_path
                or any(segment in {".", ".."} for segment in decoded_path.split("/"))
                or decoded_path.lower().endswith(("/chat/completions", "/responses"))):
            raise ValueError
        netloc = normalized_host + (":" + str(port) if port is not None else "")
        return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
    except (ValueError, UnicodeError):
        raise SettingsError(message) from None


def _validate(record, *, allow_missing_key=False):
    validated = dict(record)
    if not isinstance(validated.get("provider"), str) or validated["provider"] not in {"chatgpt", "api"}:
        raise SettingsError("请选择 ChatGPT 登录或自定义 API。")
    validated["base_url"] = _base_url(validated.get("base_url"))
    validated["model"] = _text(validated.get("model"), message="模型名称须为不超过 200 字的文本。", limit=200)
    if not isinstance(validated.get("api_format"), str) or validated["api_format"] not in {"chat_completions", "responses"}:
        raise SettingsError("请选择 Chat Completions 或 Responses 请求格式。")
    if not isinstance(validated.get("output_mode"), str) or validated["output_mode"] not in {"json_schema", "json_object", "prompt_only"}:
        raise SettingsError("请选择有效的 JSON 输出方式。")
    validated["api_key"] = _text(validated.get("api_key"), message="API 密钥须为不超过 4096 字的文本。", limit=4096)
    if validated["provider"] == "api":
        if not validated["model"]:
            raise SettingsError("使用 API 前，请填写模型名称。")
        if not validated["api_key"] and not allow_missing_key:
            raise SettingsError("使用 API 前，请填写并保存 API 密钥。")
    return validated


def _load_locked():
    # 默认读取不创建文件，也不触及独立的 ChatGPT OAuth 登录记录。
    try:
        if not SETTINGS_FILE.exists():
            return _defaults()
        raw = json.loads(protect_bytes(SETTINGS_FILE.read_bytes(), decrypt=True))
        if not isinstance(raw, dict) or set(raw) != set(_defaults()):
            raise ValueError
        if not isinstance(raw["revision"], str) or not re.fullmatch(r"[a-f0-9]{32}", raw["revision"]):
            raise ValueError
        return _validate(raw, allow_missing_key=True)
    except Exception:
        raise SettingsError("本地 API 配置无法读取，请保留文件并反馈此提示。") from None


def _public(record):
    return {**{name: record[name] for name in _PUBLIC_FIELDS}, "has_api_key": bool(record["api_key"])}


def get_public_settings():
    with _settings_lock:
        return _public(_load_locked())


def save_settings(data):
    if not isinstance(data, dict) or set(data) - _INPUT_FIELDS:
        raise SettingsError("模型配置格式不正确。")
    clear_key = data.get("clear_api_key", False)
    if not isinstance(clear_key, bool):
        raise SettingsError("清除密钥选项格式不正确。")
    with _settings_lock:
        record = _load_locked()
        previous_base_url = record["base_url"]
        previous_key = record["api_key"]
        for name in _INPUT_FIELDS - {"api_key", "clear_api_key"}:
            if name in data:
                record[name] = data[name]
        supplied_key = data.get("api_key")
        if supplied_key is not None:
            supplied_key = _text(supplied_key, message="API 密钥须为不超过 4096 字的文本。", limit=4096)
            if supplied_key:
                record["api_key"] = supplied_key
        record["base_url"] = _base_url(record["base_url"])
        if record["base_url"] != previous_base_url and previous_key and not supplied_key:
            if record["provider"] == "api" and not clear_key:
                raise SettingsError("API 地址已变更，请重新填写该平台的 API 密钥；原配置仍保留。")
            record["api_key"] = ""
        if clear_key:
            record["api_key"] = ""
        record = _validate(record, allow_missing_key=clear_key)
        record["revision"] = secrets.token_hex(16)
        try:
            encoded = json.dumps(record, ensure_ascii=False).encode("utf-8")
            atomic_write(SETTINGS_FILE, protect_bytes(encoded))
        except Exception:
            raise SettingsError("本地 API 配置无法保存，请检查文件访问权限后重试。") from None
        return _public(record)


def resolve_generation_config(default_model=DEFAULT_CHATGPT_MODEL, override_model=None):
    """一次读取形成不可变快照，供缓存身份和实际请求共同使用。"""
    with _settings_lock:
        record = _load_locked()
    if record["provider"] == "api":
        return GenerationConfig(**_validate(record))
    model = default_model if override_model is None else override_model
    model = _text(model, message="模型名称须为不超过 200 字的非空文本。", limit=200, empty=False)
    return GenerationConfig(provider="chatgpt", base_url=RESOURCE, model=model,
                            api_format="responses", output_mode="json_schema", revision=record["revision"])


def config_identity(configuration):
    """公开、可序列化的缓存身份；revision 让密钥更新也使缓存失效。"""
    return {name: getattr(configuration, name) for name in _PUBLIC_FIELDS}
