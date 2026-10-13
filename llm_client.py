"""MathPath 模型调用：用户明确选择 ChatGPT 登录或本机保存的 API 配置。"""

import json
import time

from openai import APIConnectionError, APITimeoutError, DefaultHttpxClient, OpenAI

from chatgpt_login import RESOURCE, get_usable_session
from model_settings import GenerationConfig, resolve_generation_config

MODEL = "gpt-5.6-sol"
_SAFE_CODES = frozenset({
    "subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable",
    "subscription_sharing_not_enabled", "invalid_api_key", "incorrect_api_key", "authentication_error",
    "invalid_request_error", "model_not_found", "insufficient_quota", "rate_limit_exceeded",
    "context_length_exceeded", "unsupported_parameter", "invalid_json_schema", "server_error",
    "service_unavailable", "timeout", "connection_error", "unknown_error",
})


class ModelError(Exception):
    pass


def safe_error_code(value):
    return value if isinstance(value, str) and value in _SAFE_CODES else "unknown_error"


def response_error(code):
    code = safe_error_code(code)
    messages = {
        "subscription_sharing_usage_limit_exceeded": "ChatGPT 共享额度已达到限制，请稍后重试。",
        "subscription_sharing_usage_unavailable": "当前账号的 ChatGPT 额度暂时不可用。",
        "subscription_sharing_not_enabled": "当前授权未启用 ChatGPT 订阅使用权限。",
    }
    return ModelError(messages.get(code, "模型请求未完成，错误代码：" + code + "。"))


def _api_error(error=None, *, code=None):
    status = getattr(error, "status_code", None)
    status_text = f"HTTP {status}；" if type(status) is int and 100 <= status <= 599 else ""
    if code is None:
        code = getattr(error, "code", None)
    if isinstance(error, (TimeoutError, APITimeoutError)):
        code = "timeout"
    elif isinstance(error, APIConnectionError):
        code = "connection_error"
    return ModelError("当前模型服务请求失败。" + status_text + "错误代码：" + safe_error_code(code)
                      + "。请检查 API 地址、密钥、模型及输出方式后重试。")


def _schema_instructions(instructions, schema):
    if schema is None:
        return instructions
    schema_hint = ("只返回符合以下完整 JSON Schema 的 JSON 对象，不要使用 Markdown 代码块或附加说明：\n"
                   + json.dumps(schema, ensure_ascii=False))
    return (instructions + "\n\n" + schema_hint) if instructions else schema_hint


def _format(schema, mode):
    if mode == "prompt_only":
        return None
    if mode == "json_object":
        return {"type": "json_object"}
    if schema is None:
        return None
    return {"type": "json_schema", "name": "mathpath_output", "strict": True, "schema": schema}


def _consume_responses(stream, *, api=False):
    completed_response = None
    text_parts = {}
    for event in stream:
        event_type = getattr(event, "type", None)
        if event_type == "response.output_text.delta":
            key = (event.output_index, event.content_index)
            text_parts[key] = text_parts.get(key, "") + event.delta
        elif event_type == "response.output_text.done":
            key = (event.output_index, event.content_index)
            # done 替换 delta，避免拼接同一答案两次。
            text_parts[key] = event.text
        elif event_type == "response.completed":
            completed_response = event.response
        elif event_type == "response.failed":
            error = getattr(event.response, "error", None)
            code = getattr(error, "code", None)
            raise _api_error(code=code) if api else response_error(code)
        elif event_type == "response.incomplete":
            raise ModelError("模型返回了不完整结果，请检查输出限制后重试。")
        elif event_type in {"response.refusal.delta", "response.refusal.done"}:
            raise ModelError("模型拒绝了此次生成，请调整学习目标后重试。")
        elif event_type == "error":
            code = getattr(event, "code", None)
            raise _api_error(code=code) if api else response_error(code)
    if completed_response is None:
        raise ModelError("连接已结束，但没有收到生成完成事件。")
    if getattr(completed_response, "status", None) != "completed":
        raise ModelError("生成完成事件的响应状态异常。")
    if getattr(completed_response, "error", None):
        raise ModelError("模型服务返回了生成错误，请检查配置后重试。")
    final_output = getattr(completed_response, "output", None)
    if isinstance(final_output, list):
        for item in final_output:
            for content in getattr(item, "content", None) or []:
                if getattr(content, "type", None) == "refusal":
                    raise ModelError("模型拒绝了此次生成，请调整学习目标后重试。")
    output_text = getattr(completed_response, "output_text", None)
    text = output_text.strip() if isinstance(final_output, list) and isinstance(output_text, str) else ""
    if not text:
        text = "".join(text_parts[key] for key in sorted(text_parts)).strip()
    if not text:
        raise ModelError("生成已完成，但文本流和完成快照都没有可显示的文本。")
    return text


def _generate_chatgpt(prompt, configuration, instructions, json_schema):
    session = get_usable_session()
    if not isinstance(session, dict) or not session.get("access_token"):
        raise ModelError("没有可用的 MathPath 登录记录，请先运行登录脚本。")
    if not {"resource.invoke", "chatgpt.tokens.use.direct"}.issubset(session.get("scopes", [])):
        raise ModelError("登录记录未启用 ChatGPT 订阅使用权限。")
    if session.get("expires_at", 0) <= time.time() + 5:
        raise ModelError("登录凭证已到期，请重新运行登录脚本，再进行此测试。")

    # 显式传入 OAuth token，不读取 OPENAI_API_KEY，不改变计费方式。
    with OpenAI(api_key=session["access_token"], base_url=RESOURCE, max_retries=0, timeout=90) as client:
        options = {}
        if instructions is not None:
            options["instructions"] = instructions
        if json_schema is not None:
            options["text"] = {"format": {"type": "json_schema", "name": "mathpath_graph",
                                          "strict": True, "schema": json_schema}}
        with client.responses.create(model=configuration.model, input=[{"role": "user", "content": prompt}],
                                     store=False, stream=True, **options) as stream:
            return _consume_responses(stream)


def _generate_api(prompt, configuration, instructions, json_schema):
    # 禁止自动跟随重定向；同一调用失败也不重试、不换模型服务或请求格式。
    try:
        with DefaultHttpxClient(follow_redirects=False) as transport:
            with OpenAI(api_key=configuration.api_key, base_url=configuration.base_url, max_retries=0,
                        timeout=90, http_client=transport, organization="", project="", admin_api_key="",
                        webhook_secret="", default_headers={"Authorization": "Bearer " + configuration.api_key}) as client:
                # 固定 SDK 会合并 OPENAI_CUSTOM_HEADERS；移除环境继承的认证/自定义头，
                # 只发送用户为这个明确端点保存的密钥。SDK 仍负责通常的请求头。
                client._custom_headers = {"Authorization": "Bearer " + configuration.api_key}
                mode = configuration.output_mode
                system_text = (_schema_instructions(instructions, json_schema)
                               if mode in {"json_object", "prompt_only"} else instructions)
                if mode == "json_object" and json_schema is None:
                    system_text = (system_text + "\n\n" if system_text else "") + "请只返回一个有效的 JSON 对象。"
                response_format = _format(json_schema, mode)
                if configuration.api_format == "chat_completions":
                    messages = []
                    if system_text is not None:
                        messages.append({"role": "system", "content": system_text})
                    messages.append({"role": "user", "content": prompt})
                    options = {}
                    if response_format is not None:
                        if mode == "json_schema":
                            options["response_format"] = {"type": "json_schema", "json_schema": {
                                key: value for key, value in response_format.items() if key != "type"}}
                        else:
                            options["response_format"] = response_format
                    response = client.chat.completions.create(model=configuration.model, messages=messages,
                                                              stream=False, **options)
                    if getattr(response, "error", None):
                        raise ModelError("模型服务返回了生成错误，请检查配置后重试。")
                    choices = getattr(response, "choices", None)
                    if not isinstance(choices, list) or not choices:
                        raise ModelError("模型服务没有返回可显示的文本，请检查请求格式后重试。")
                    choice = choices[0]
                    message = getattr(choice, "message", None)
                    if getattr(message, "refusal", None):
                        raise ModelError("模型拒绝了此次生成，请调整学习目标后重试。")
                    if getattr(choice, "finish_reason", None) != "stop":
                        raise ModelError("模型返回了不完整结果，请检查输出限制后重试。")
                    content = getattr(message, "content", None)
                    if not isinstance(content, str) or not content.strip():
                        raise ModelError("模型服务没有返回可显示的文本，请检查请求格式后重试。")
                    return content.strip()
                options = {}
                if system_text is not None:
                    options["instructions"] = system_text
                if response_format is not None:
                    options["text"] = {"format": response_format}
                with client.responses.create(model=configuration.model, input=[{"role": "user", "content": prompt}],
                                             store=False, stream=True, **options) as stream:
                    return _consume_responses(stream, api=True)
    except ModelError:
        raise
    except Exception as error:
        raise _api_error(error) from None


def generate_text(prompt, model=None, *, instructions=None, json_schema=None, configuration=None):
    if configuration is None:
        configuration = resolve_generation_config(default_model=MODEL, override_model=model)
    if not isinstance(configuration, GenerationConfig):
        raise ModelError("模型配置快照无效，请重新保存配置。")
    if configuration.provider == "api":
        return _generate_api(prompt, configuration, instructions, json_schema)
    if configuration.provider == "chatgpt":
        return _generate_chatgpt(prompt, configuration, instructions, json_schema)
    raise ModelError("模型服务选择无效，请重新保存配置。")
