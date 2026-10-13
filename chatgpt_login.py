"""MathPath 的单账号 ChatGPT 登录检查；运行时才打开授权页面。

官方协议：https://developers.openai.com/siwc/token-sharing-open-source/sign-in
凭证用 Windows 当前用户的 DPAPI 加密；本脚本不调用模型生成接口。
"""

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

import jwt

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
_configured_data_dir = os.environ.get("MATHPATH_DATA_DIR")
DATA_DIR = (Path(_configured_data_dir).expanduser().resolve() if _configured_data_dir
            else Path(__file__).resolve().parent) / ".mathpath"
SESSION_FILE = DATA_DIR / "chatgpt_session.dpapi"
HOST_FILE = DATA_DIR / "host_id.json"
SAFE_ALGORITHMS = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
REFRESH_LEEWAY = 60
SESSION_LOCK_TIMEOUT = 10
SUBSCRIPTION_SCOPES = {"resource.invoke", "chatgpt.tokens.use.direct"}
INVALID_REFRESH_CODES = {"invalid_grant", "invalid_refresh_token", "token_expired",
                         "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}
SAFE_OAUTH_CODES = INVALID_REFRESH_CODES | {"invalid_client", "invalid_request", "invalid_scope",
    "unauthorized_client", "unsupported_grant_type", "access_denied", "interaction_required",
    "consent_required", "login_required", "temporarily_unavailable", "server_error", "insufficient_scope"}
TRANSPORT_MESSAGES = {
    "timeout": "连接 OpenAI 超时，请检查当前网络或代理后重试。",
    "tls": "与 OpenAI 的 TLS 连接失败，请检查当前网络或代理后重试。",
    "connection": "连接 OpenAI 失败，请检查当前网络后重试。",
}
_session_thread_lock = threading.Lock()


class LoginError(Exception):
    """只包含可安全复制到聊天里的诊断信息。"""

    def __init__(self, message=""):
        if getattr(sys, "frozen", False):
            message = str(message).replace("请检查注册配置后运行 chatgpt_login.py", "请点击「MathPath → 连接 ChatGPT」重试")
            message = message.replace("运行 chatgpt_login.py", "点击「MathPath → 连接 ChatGPT」")
            message = message.replace("重新运行脚本", "再次点击「MathPath → 连接 ChatGPT」")
        super().__init__(message)


class StateMismatch(LoginError):
    pass


class OAuthRequestError(LoginError):
    def __init__(self, status_code, error_code=""):
        self.status_code = status_code if (isinstance(status_code, int) and not isinstance(status_code, bool)
                                           and 100 <= status_code <= 599) else 0
        self.error_code = error_code if isinstance(error_code, str) and error_code in SAFE_OAUTH_CODES else ""
        suffix = "，错误代码：" + self.error_code if self.error_code else ""
        super().__init__(f"OpenAI 请求失败：HTTP {self.status_code}{suffix}。")


class OAuthTransportError(LoginError):
    def __init__(self, category):
        self.category = category if isinstance(category, str) and category in TRANSPORT_MESSAGES else "connection"
        super().__init__(TRANSPORT_MESSAGES[self.category])


def _transport_category(error):
    # 只判断异常类型；底层异常文字可能含代理地址或其他敏感数据。
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, TimeoutError):
        return "timeout"
    if isinstance(reason, ssl.SSLError):
        return "tls"
    return "connection"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, *, form=None, bearer=None):
    headers = {"Accept": "application/json", "User-Agent": "MathPath/0.1"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if bearer is not None:
        headers["Authorization"] = "Bearer " + bearer
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # 不输出原始响应、请求 URL 或凭证。
        code = ""
        try:
            error = json.loads(exc.read(8192)).get("error", "")
            if isinstance(error, dict):
                error = error.get("code", "")
            if isinstance(error, str) and error in SAFE_OAUTH_CODES:
                code = error
        except (ValueError, AttributeError):
            pass
        finally:
            exc.close()
        raise OAuthRequestError(exc.code, code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OAuthTransportError(_transport_category(exc)) from None
    except ValueError:
        raise LoginError("OpenAI 返回的内容无法解析为 JSON。") from None
    if not isinstance(result, dict):
        raise LoginError("OpenAI 返回的数据格式不符合预期。")
    return result


def load_discovery():
    metadata = request_json(ISSUER + "/.well-known/openid-configuration")
    if metadata.get("issuer") != ISSUER:
        raise LoginError("登录服务的 issuer 校验失败。")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = metadata.get(field)
        parsed = urllib.parse.urlsplit(value) if isinstance(value, str) else None
        if parsed is None or parsed.scheme != "https" or parsed.netloc != "auth.openai.com" or parsed.fragment:
            raise LoginError("登录服务的端点校验失败。")
    advertised = metadata.get("id_token_signing_alg_values_supported", [])
    if not isinstance(advertised, list):
        raise LoginError("登录服务未提供有效的签名算法信息。")
    metadata["allowed_algorithms"] = sorted(SAFE_ALGORITHMS.intersection(advertised))
    if not metadata["allowed_algorithms"]:
        raise LoginError("登录服务未提供支持的安全签名算法。")
    return metadata


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def protect_bytes(data, *, decrypt=False):
    if os.name != "nt":
        raise LoginError("此登录脚本使用 Windows 凭证保护，请在 Windows 中运行。")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_pointer = ctypes.POINTER(DataBlob)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [blob_pointer, ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                         blob_pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_pointer]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN；不用 LOCAL_MACHINE，凭证绑定当前用户。
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise LoginError(f"Windows 凭证保护失败，系统错误代码：{ctypes.get_last_error()}。")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_session(record):
    encoded = json.dumps(record, ensure_ascii=False).encode("utf-8")
    atomic_write(SESSION_FILE, protect_bytes(encoded))


def load_session():
    if not SESSION_FILE.exists():
        return {}
    try:
        return json.loads(protect_bytes(SESSION_FILE.read_bytes(), decrypt=True))
    except (ValueError, OSError):
        raise LoginError("本地登录记录无法读取，请保留文件并反馈此提示。") from None


@contextmanager
def _session_transaction():
    """线程和进程共享同一把锁；锁内重读，避免重复使用轮换的 refresh token。"""
    deadline = time.monotonic() + SESSION_LOCK_TIMEOUT
    if not _session_thread_lock.acquire(timeout=SESSION_LOCK_TIMEOUT):
        raise LoginError("另一个请求正在更新登录，请稍后重试。")
    stream, locked = None, False
    try:
        if os.name != "nt":
            raise LoginError("此登录脚本使用 Windows 凭证保护，请在 Windows 中运行。")
        import msvcrt

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stream = (DATA_DIR / "session.lock").open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        while True:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LoginError("另一个程序正在更新登录，请稍后重试。") from None
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        yield
    except OSError:
        raise LoginError("本地登录记录暂时无法更新，请关闭其他占用文件的程序后重试。") from None
    finally:
        try:
            if locked:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            if stream is not None:
                stream.close()
            _session_thread_lock.release()


def _identity_summary(identity):
    return {field: identity[field] for field in ("iss", "sub", "aud", "auth_time", "nonce") if field in identity}


def _original_identity(record):
    identity = record.get("oidc_identity")
    if not isinstance(identity, dict):
        # 仅提取以前已验证且由 DPAPI 保护的摘要；不以此验证新的令牌。
        try:
            identity = jwt.decode(record.get("id_token", ""), options={"verify_signature": False})
        except jwt.PyJWTError:
            return {}
    if identity.get("iss") != record.get("issuer") or identity.get("sub") != record.get("subject"):
        return {}
    return _identity_summary(identity)


def _clear_unusable_tokens(record):
    retained = dict(record)
    for field in ("access_token", "refresh_token", "id_token", "token_type", "expires_in",
                  "expires_at", "earliest_refresh_at", "saved_at"):
        retained.pop(field, None)
    save_session(retained)


def get_usable_session():
    """返回可用的订阅会话，临近到期自动续期；不会自动登录或改用 API 计费。"""
    with _session_transaction():
        record = load_session()
        if not isinstance(record, dict) or not record:
            raise LoginError("尚未登录 ChatGPT，请运行 chatgpt_login.py 完成登录。")
        client_id, subject = record.get("client_id"), record.get("subject")
        if (record.get("issuer") != ISSUER or not isinstance(subject, str) or not subject
                or not isinstance(client_id, str) or not client_id or client_id == "dynamic_agent_client"):
            raise LoginError("本地登录身份不完整，请运行 chatgpt_login.py 重新登录。")
        scopes = record.get("scopes")
        if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
            raise LoginError("本地授权记录无效，请运行 chatgpt_login.py 重新登录。")
        if not SUBSCRIPTION_SCOPES.issubset(scopes):
            raise LoginError("尚未授予订阅使用权限，请运行 chatgpt_login.py 完成授权。")
        expires_at = record.get("expires_at")
        if (not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool)
                or not math.isfinite(expires_at)):
            raise LoginError("本地登录记录缺少到期时间，请运行 chatgpt_login.py 重新登录。")
        if not isinstance(record.get("access_token"), str) or not record["access_token"]:
            raise LoginError("本地登录已失效，请运行 chatgpt_login.py 重新登录。")
        if str(record.get("token_type", "")).lower() != "bearer":
            raise LoginError("本地登录令牌类型无效，请运行 chatgpt_login.py 重新登录。")
        if expires_at > time.time() + REFRESH_LEEWAY:
            return record
        refresh_token = record.get("refresh_token")
        if "offline_access" not in scopes or not isinstance(refresh_token, str) or not refresh_token:
            raise LoginError("登录已到期且无法自动续期，请运行 chatgpt_login.py 重新登录。")
        metadata = load_discovery()
        try:
            tokens = request_json(metadata["token_endpoint"], form={"grant_type": "refresh_token",
                                  "client_id": client_id, "refresh_token": refresh_token, "resource": RESOURCE})
        except OAuthRequestError as exc:
            if exc.error_code in INVALID_REFRESH_CODES:
                _clear_unusable_tokens(record)
                raise LoginError("ChatGPT 授权已失效，请运行 chatgpt_login.py 重新登录。") from None
            if exc.error_code == "invalid_client":
                raise LoginError("ChatGPT 客户端注册无法使用，请检查注册配置后运行 chatgpt_login.py。") from None
            raise LoginError("ChatGPT 登录续期暂时失败，原登录记录已保留。"
                             + str(exc) + "请检查网络或稍后重试。") from None
        except OAuthTransportError as exc:
            raise LoginError("ChatGPT 登录续期暂时失败，原登录记录已保留。"
                             + TRANSPORT_MESSAGES[exc.category]) from None
        except LoginError:
            raise LoginError("ChatGPT 登录续期暂时失败，原登录记录已保留，请检查网络后重试。") from None
        received_at = time.time()
        expires_in = tokens.get("expires_in")
        if (not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]
                or not isinstance(tokens.get("refresh_token"), str) or not tokens["refresh_token"]
                or str(tokens.get("token_type", "")).lower() != "bearer"
                or not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0):
            raise LoginError("ChatGPT 续期结果无效，请运行 chatgpt_login.py 重新登录。")
        if "scope" in tokens and not isinstance(tokens["scope"], str):
            raise LoginError("ChatGPT 续期权限格式无效，请运行 chatgpt_login.py 重新登录。")
        updated_scopes = tokens["scope"].split() if "scope" in tokens else list(scopes)
        original = _original_identity(record)
        identity = None
        if "id_token" in tokens:
            try:
                identity = validate_identity(tokens, metadata, client_id, original.get("nonce"), subject, refresh=True)
            except LoginError:
                raise LoginError("续期返回的身份无法验证，请检查网络；仍失败时运行 chatgpt_login.py 重新登录。") from None
            if not original or identity["aud"] != original.get("aud"):
                raise LoginError("续期返回的身份与原登录不一致，请运行 chatgpt_login.py 重新登录。")
            if "auth_time" in identity and identity["auth_time"] != original.get("auth_time"):
                raise LoginError("续期返回的认证时间与原登录不一致，请运行 chatgpt_login.py 重新登录。")
        updated = dict(record, access_token=tokens["access_token"], refresh_token=tokens["refresh_token"],
                       token_type=tokens["token_type"], expires_in=expires_in, expires_at=received_at + expires_in,
                       scope=" ".join(updated_scopes), scopes=updated_scopes, saved_at=received_at)
        updated.pop("earliest_refresh_at", None)
        if "earliest_refresh_at" in tokens:
            updated["earliest_refresh_at"] = tokens["earliest_refresh_at"]
        if original:
            updated["oidc_identity"] = original
        if identity is not None:
            updated["id_token"] = tokens["id_token"]
            if "email" in identity:
                updated["email"] = identity["email"]
        save_session(updated)
        if not SUBSCRIPTION_SCOPES.issubset(updated_scopes):
            raise LoginError("订阅使用权限已停用，请运行 chatgpt_login.py 重新授权。")
        return updated


def host_id():
    if HOST_FILE.exists():
        try:
            value = json.loads(HOST_FILE.read_text(encoding="utf-8"))["ext_agent_host_id"]
            if not isinstance(value, str) or not value.startswith("urn:uuid:"):
                raise ValueError
            uuid.UUID(value[9:])
            return value
        except (ValueError, KeyError):
            raise LoginError("本地 host ID 记录无效。") from None
    value = "urn:uuid:" + str(uuid.uuid4())
    atomic_write(HOST_FILE, json.dumps({"ext_agent_host_id": value}).encode("utf-8"))
    return value


def validate_callback(query, state, existing_client=None):
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    states = params.get("state", [])
    if len(states) != 1 or not secrets.compare_digest(states[0].encode("utf-8"), state.encode("utf-8")):
        raise StateMismatch("登录回调的 state 校验失败。")
    if any(len(values) != 1 for values in params.values()):
        raise LoginError("登录回调包含重复参数。")
    if "error" in params:
        raise LoginError("授权未完成或已取消；可以重新运行脚本。")
    code = params.get("code", [""])[0]
    client_id = params.get("client_id", [existing_client or ""])[0]
    if not code or not client_id or client_id == "dynamic_agent_client":
        raise LoginError("登录回调未提供有效的授权码或正式 client ID。")
    if existing_client and client_id != existing_client:
        raise LoginError("返回的 client ID 与本次登录不一致。")
    return {"code": code, "client_id": client_id}


def wait_for_callback(metadata, record, installation_id):
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    result = {}
    existing_client = record.get("client_id")

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # 默认访问日志会泄露 URL 中的一次性授权码。

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected_host or parsed.path != "/auth/callback":
                self.send_error(404)
                return
            try:
                result["callback"] = validate_callback(parsed.query, state, existing_client)
                message = "授权结果已收到，请回到 MathPath 查看验证结果。"
                status = 200
            except LoginError as exc:
                # 错误 state 不结束监听，避免无关请求中断有效登录。
                message, status = str(exc), 400
                if not isinstance(exc, StateMismatch):
                    result["error"] = exc
            body = ("<!doctype html><meta charset='utf-8'><title>MathPath 登录</title>"
                    "<p>" + message + "</p>").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

    with HTTPServer(("127.0.0.1", 0), CallbackHandler) as server:
        server.timeout = 0.5
        redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
        params = {"client_id": existing_client or "dynamic_agent_client", "ext_agent_host_id": installation_id,
                  "response_type": "code", "redirect_uri": redirect_uri,
                  "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
                  "resource": RESOURCE, "state": state, "nonce": nonce,
                  "code_challenge_method": "S256", "code_challenge": challenge}
        if existing_client:
            if record.get("id_token"):
                params["id_token_hint"] = record["id_token"]
        else:
            params["agent_name_hint"] = "MathPath"
        url = metadata["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)
        print("正在打开 OpenAI 官方页面：Continue with ChatGPT。")
        print("请在浏览器中选择你的 Plus 账号，并查看 MathPath 请求的订阅使用权限。")
        if not webbrowser.open(url, new=1):
            raise LoginError("无法自动打开浏览器，请设置 Windows 默认浏览器后重试。")
        deadline = time.monotonic() + 600
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if "error" in result:
        raise result["error"]
    if "callback" not in result:
        raise LoginError("等待登录超过 10 分钟，请重新运行脚本。")
    return result["callback"], verifier, nonce, redirect_uri


def validate_identity(tokens, metadata, client_id, nonce, expected_subject=None, *, refresh=False):
    token = tokens.get("id_token")
    if not isinstance(token, str) or not token:
        raise LoginError("OpenAI 未返回 ID token。")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in metadata["allowed_algorithms"] or not header.get("kid"):
            raise LoginError("ID token 的签名算法或 key ID 无效。")
        jwks = request_json(metadata["jwks_uri"])
        if not isinstance(jwks.get("keys"), list):
            raise LoginError("OpenAI 签名公钥格式无效。")
        keys = [key for key in jwks["keys"]
                if isinstance(key, dict) and key.get("kid") == header["kid"] and key.get("use", "sig") == "sig"]
        if len(keys) != 1 or (keys[0].get("alg") and keys[0]["alg"] != header["alg"]):
            raise LoginError("无法找到匹配的 OpenAI 签名公钥。")
        signing_key = jwt.PyJWK.from_dict(keys[0])
        identity = jwt.decode(token, signing_key.key, algorithms=metadata["allowed_algorithms"],
                              audience=client_id, issuer=ISSUER, leeway=5,
                              options={"require": ["sub", "exp", "iat", "iss", "aud"] + ([] if refresh else ["nonce"])})
    except (jwt.PyJWTError, ValueError, TypeError):
        raise LoginError("ID token 的签名或身份信息校验失败。") from None
    actual_nonce = identity.get("nonce")
    if not refresh or "nonce" in identity:
        if (not isinstance(actual_nonce, str) or not isinstance(nonce, str)
                or not secrets.compare_digest(actual_nonce.encode("utf-8"), nonce.encode("utf-8"))):
            raise LoginError("ID token 的 nonce 校验失败。")
    if not isinstance(identity.get("sub"), str) or not identity["sub"]:
        raise LoginError("ID token 未包含有效账号标识。")
    audience = identity.get("aud")
    if isinstance(audience, list) and len(audience) > 1 and identity.get("azp") != client_id:
        raise LoginError("ID token 的授权客户端校验失败。")
    if identity.get("azp", client_id) != client_id:
        raise LoginError("ID token 的授权客户端校验失败。")
    if expected_subject and identity["sub"] != expected_subject:
        raise LoginError("本次登录账号与已保存账号不同，未替换原有凭证。")
    return identity


def run_login():
    metadata = load_discovery()
    record = load_session()
    installation_id = host_id()
    callback, verifier, nonce, redirect_uri = wait_for_callback(metadata, record, installation_id)
    # 正式 client ID 必须在换取凭证前保留；失败后仍可用同一注册重试。
    with _session_transaction():
        current = load_session()
        if current.get("client_id") and current["client_id"] != callback["client_id"]:
            raise LoginError("另一次登录已更新客户端注册，请重新运行脚本。")
        pending = dict(current, client_id=callback["client_id"], ext_agent_host_id=installation_id)
        save_session(pending)
        # 换码、校验、保存与自动续期串行；浏览器等待不占锁。
        tokens = request_json(metadata["token_endpoint"], form={"grant_type": "authorization_code",
                              "client_id": callback["client_id"], "code": callback["code"],
                              "code_verifier": verifier, "redirect_uri": redirect_uri, "resource": RESOURCE})
        identity = validate_identity(tokens, metadata, callback["client_id"], nonce, current.get("subject"))
        if not isinstance(tokens.get("scope", ""), str):
            raise LoginError("授权结果缺少有效的权限列表。")
        scopes = tokens.get("scope", "").split()
        received_at = time.time()
        saved = dict(tokens, client_id=callback["client_id"], ext_agent_host_id=installation_id,
                     issuer=ISSUER, subject=identity["sub"], email=identity.get("email"),
                     scopes=scopes, saved_at=received_at, oidc_identity=_identity_summary(identity))
        if not SUBSCRIPTION_SCOPES.issubset(scopes):
            save_session(saved)
        else:
            if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
                raise LoginError("授权结果缺少 access token。")
            if str(tokens.get("token_type", "")).lower() != "bearer":
                raise LoginError("授权结果的 token 类型不符合预期。")
            expires_in = tokens.get("expires_in")
            if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
                raise LoginError("授权结果缺少有效的到期时间。")
            if "offline_access" in scopes and not tokens.get("refresh_token"):
                raise LoginError("已授予续期权限，但授权结果未包含 refresh token。")
            saved["expires_at"] = received_at + expires_in
            save_session(saved)
    print("登录验证成功，凭证已由 Windows 当前用户加密保存。")
    if not SUBSCRIPTION_SCOPES.issubset(scopes):
        print("订阅权限：未启用。请反馈此提示；尚不能使用 Plus 额度调用模型。")
        return
    print("订阅权限：已授权 MathPath 使用 ChatGPT 额度。")
    catalog = request_json(RESOURCE + "/models", bearer=tokens["access_token"])
    models = catalog.get("models")
    if not isinstance(models, list):
        raise LoginError("登录已保存，但可用模型列表格式不符合预期。")
    visible = [model for model in models if isinstance(model, dict) and model.get("visibility") == "list"]
    print("账号可用模型：")
    for model in visible:
        if isinstance(model.get("slug"), str):
            print("  " + str(model.get("display_name") or model["slug"]) + " / " + model["slug"])
    if not visible:
        print("  当前账号未返回可展示的模型。")
    print("本次检查完成；下一步再测试模型生成。")


if __name__ == "__main__":
    try:
        run_login()
    except KeyboardInterrupt:
        print("\n登录检查已取消。")
        sys.exit(130)
    except LoginError as exc:
        print("登录检查未完成：" + str(exc))
        sys.exit(1)
    except Exception as exc:
        # 不输出含授权码/令牌的异常原文或 traceback。
        print("登录检查未完成，异常类型：" + type(exc).__name__ + "。请反馈这行提示。")
        sys.exit(1)
