"""API 调用回归：假 SDK / 完全离线 transport，不访问真实配置或模型。"""

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace as Object
import unittest
from unittest.mock import MagicMock, patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import llm_client as llm
from model_settings import GenerationConfig

CANARY = "synthetic-secret-must-not-appear"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


def configuration(api_format="chat_completions", output_mode="json_object"):
    return GenerationConfig(provider="api", base_url="https://models.example.test/v1", model="saved-model",
                            api_format=api_format, output_mode=output_mode, revision="synthetic-revision", api_key=CANARY)


def event(kind, **values):
    return Object(type=kind, **values)


def completion(text="{\"answer\":\"ok\"}"):
    return event("response.completed", response=Object(status="completed", output=[], output_text=text))


@contextmanager
def fake_sdk(*, content="{\"answer\":\"ok\"}", finish_reason="stop", refusal=None, events=None, error=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = Object(choices=[Object(
        finish_reason=finish_reason, message=Object(content=content, refusal=refusal))])
    if error is not None:
        client.chat.completions.create.side_effect = error
        client.responses.create.side_effect = error
    stream = MagicMock()
    stream.__enter__.return_value = iter([completion()] if events is None else events)
    client.responses.create.return_value = stream
    transport = MagicMock()
    transport.__enter__.return_value = transport
    with patch.object(llm, "OpenAI", return_value=client) as constructor, \
            patch.object(llm, "DefaultHttpxClient", return_value=transport) as transport_constructor:
        yield client, constructor, transport_constructor


class APIProviderTests(unittest.TestCase):
    def setUp(self):
        for name in ("get_usable_session", "resolve_generation_config", "OpenAI", "DefaultHttpxClient"):
            guard = patch.object(llm, name, side_effect=AssertionError("必须离线模拟 API 和配置"))
            guard.start()
            self.addCleanup(guard.stop)

    def generate(self, config=None):
        return llm.generate_text("学习目标", model="old-static-oauth-model", instructions="教学要求",
                                 json_schema=SCHEMA, configuration=configuration() if config is None else config)

    def test_chat_completions_uses_saved_model_and_explicit_key_without_oauth(self):
        with fake_sdk() as (client, constructor, transport_constructor):
            self.assertEqual(self.generate(), '{"answer":"ok"}')
        kwargs = constructor.call_args.kwargs
        self.assertEqual(kwargs["api_key"], CANARY)
        self.assertEqual(kwargs["base_url"], "https://models.example.test/v1")
        self.assertEqual(kwargs["max_retries"], 0)
        self.assertEqual(kwargs["timeout"], 90)
        transport_constructor.assert_called_once_with(follow_redirects=False)
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], "saved-model")
        self.assertIs(call["stream"], False)
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual(call["messages"][-1], {"role": "user", "content": "学习目标"})
        self.assertIn(json.dumps(SCHEMA, ensure_ascii=False), call["messages"][0]["content"])
        client.responses.create.assert_not_called()
        llm.get_usable_session.assert_not_called()
        llm.resolve_generation_config.assert_not_called()

    def test_all_chat_output_modes_send_requested_format_and_complete_schema(self):
        for mode in ("json_schema", "json_object", "prompt_only"):
            with self.subTest(mode=mode), fake_sdk() as (client, _, _):
                self.generate(configuration(output_mode=mode))
            call = client.chat.completions.create.call_args.kwargs
            if mode == "json_schema":
                self.assertEqual(call["response_format"], {"type": "json_schema", "json_schema": {
                    "name": "mathpath_output", "strict": True, "schema": SCHEMA}})
            else:
                self.assertIn(json.dumps(SCHEMA, ensure_ascii=False), call["messages"][0]["content"])
                if mode == "json_object":
                    self.assertEqual(call["response_format"], {"type": "json_object"})
                else:
                    self.assertNotIn("response_format", call)

    def test_sjtu_deepseek_reasoner_uses_explicit_endpoint_and_final_content_only(self):
        config = replace(configuration(), base_url="https://models.sjtu.edu.cn/api/v1", model="deepseek-reasoner")
        with fake_sdk() as (client, constructor, _):
            client.chat.completions.create.return_value.choices[0].message.reasoning_content = "synthetic-private-reasoning"
            output = self.generate(config)
        self.assertEqual(output, '{"answer":"ok"}')
        self.assertNotIn("reasoning", output)
        self.assertEqual(constructor.call_args.kwargs["base_url"], config.base_url)
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], "deepseek-reasoner")
        self.assertEqual(call["response_format"], {"type": "json_object"})
        client.responses.create.assert_not_called()
        llm.get_usable_session.assert_not_called()

    def test_missing_explicit_api_key_stops_before_sdk_or_transport(self):
        with self.assertRaises(llm.ModelError):
            self.generate(replace(configuration(), api_key=""))
        llm.OpenAI.assert_not_called()
        llm.DefaultHttpxClient.assert_not_called()
        llm.get_usable_session.assert_not_called()

    def test_json_object_without_schema_still_requests_and_mentions_json(self):
        with fake_sdk() as (client, _, _):
            llm.generate_text("目标", configuration=configuration())
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertIn("JSON", call["messages"][0]["content"])

    def test_all_responses_modes_use_stream_and_expected_format(self):
        for mode in ("json_schema", "json_object", "prompt_only"):
            with self.subTest(mode=mode), fake_sdk() as (client, _, _):
                self.assertEqual(self.generate(configuration("responses", mode)), '{"answer":"ok"}')
            call = client.responses.create.call_args.kwargs
            self.assertEqual(call["model"], "saved-model")
            self.assertIs(call["stream"], True)
            self.assertIs(call["store"], False)
            if mode == "json_schema":
                self.assertEqual(call["text"]["format"], {"type": "json_schema", "name": "mathpath_output",
                                                        "strict": True, "schema": SCHEMA})
            else:
                self.assertIn(json.dumps(SCHEMA, ensure_ascii=False), call["instructions"])
                if mode == "json_object":
                    self.assertEqual(call["text"], {"format": {"type": "json_object"}})
                else:
                    self.assertNotIn("text", call)
            client.chat.completions.create.assert_not_called()

    def test_stream_done_replaces_delta_and_requires_successful_completion(self):
        events = [event("response.output_text.delta", output_index=1, content_index=0, delta="乙"),
                  event("response.output_text.delta", output_index=0, content_index=0, delta="甲"),
                  event("response.output_text.done", output_index=0, content_index=0, text="甲"),
                  event("response.output_text.done", output_index=1, content_index=0, text="乙"), completion("")]
        with fake_sdk(events=events):
            self.assertEqual(self.generate(configuration("responses")), "甲乙")

    def test_chat_rejects_truncation_refusal_and_empty_or_nontext_content(self):
        cases = [("length", CANARY, None), ("tool_calls", CANARY, None),
                 ("content_filter", CANARY, None), ("stop", CANARY, CANARY),
                 ("stop", "", None), ("stop", None, None), ("stop", [CANARY], None)]
        for reason, content, refusal in cases:
            with self.subTest(reason=reason), fake_sdk(content=content, finish_reason=reason, refusal=refusal), \
                    self.assertRaises(llm.ModelError) as caught:
                self.generate()
            self.assertNotIn(CANARY, str(caught.exception))

    def test_responses_rejects_failed_incomplete_refusal_or_missing_completion(self):
        failed = event("response.failed", response=Object(error=Object(code=CANARY, message=CANARY)))
        bad = [[event("response.output_text.delta", output_index=0, content_index=0, delta=CANARY)],
               [failed], [event("response.incomplete", response=Object(message=CANARY))],
               [event("response.refusal.done", refusal=CANARY), completion(CANARY)],
               [event("error", code=CANARY, message=CANARY)], [completion("")]]
        for events in bad:
            with self.subTest(event_count=len(events)), fake_sdk(events=events), self.assertRaises(llm.ModelError) as caught:
                self.generate(configuration("responses"))
            self.assertNotIn(CANARY, str(caught.exception))

    def test_http_failure_is_safe_and_never_retries_or_switches_provider(self):
        error = RuntimeError("request URL and key " + CANARY)
        error.status_code = 401
        error.code = CANARY
        with fake_sdk(error=error) as (client, _, _), self.assertRaises(llm.ModelError) as caught:
            self.generate()
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertIn("unknown_error", str(caught.exception))
        self.assertNotIn(CANARY, str(caught.exception))
        client.chat.completions.create.assert_called_once()
        client.responses.create.assert_not_called()
        llm.get_usable_session.assert_not_called()

    def test_unsupported_format_does_not_fallback_or_echo_service_message(self):
        error = RuntimeError(CANARY)
        error.status_code = 400
        error.code = "unsupported_parameter"
        for api_format in ("chat_completions", "responses"):
            with self.subTest(api_format=api_format), fake_sdk(error=error) as (client, _, _), \
                    self.assertRaises(llm.ModelError) as caught:
                self.generate(configuration(api_format, "json_schema"))
            self.assertIn("unsupported_parameter", str(caught.exception))
            self.assertNotIn(CANARY, str(caught.exception))
            self.assertEqual(client.chat.completions.create.call_count + client.responses.create.call_count, 1)

    def test_real_sdk_offline_transport_never_follows_redirect_with_key(self):
        # 真 SDK + MockTransport 验证重定向边界；所有请求均由内存 handler 返回。
        import httpx2
        from openai import DefaultHttpxClient
        requests = []
        def handler(request):
            requests.append(request)
            return httpx2.Response(302, headers={"location": "https://other.example.test/collect"},
                                   json={"error": {"message": CANARY, "code": CANARY}})
        def transport_factory(**kwargs):
            return DefaultHttpxClient(transport=httpx2.MockTransport(handler), **kwargs)
        from openai import OpenAI
        with patch.object(llm, "OpenAI", OpenAI), patch.object(llm, "DefaultHttpxClient", side_effect=transport_factory), \
                patch.dict("os.environ", {"OPENAI_CUSTOM_HEADERS": "Authorization: Bearer synthetic-ambient-key\nX-Synthetic-Secret: " + CANARY}), \
                self.assertRaises(llm.ModelError) as caught:
            self.generate()
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), "https://models.example.test/v1/chat/completions")
        self.assertEqual(requests[0].headers["authorization"], "Bearer " + CANARY)
        self.assertNotIn("x-synthetic-secret", requests[0].headers)
        self.assertIn("HTTP 302", str(caught.exception))
        self.assertNotIn(CANARY, str(caught.exception))

    def test_default_resolver_keeps_explicit_oauth_model_override(self):
        snapshot = GenerationConfig(provider="chatgpt", base_url=llm.RESOURCE, model="custom-oauth-model",
                                    api_format="responses", output_mode="json_schema", revision="default")
        session = {"access_token": "synthetic-oauth-token", "scopes": ["resource.invoke", "chatgpt.tokens.use.direct"],
                   "expires_at": 9_999_999_999}
        with fake_sdk() as (client, _, _), patch.object(llm, "resolve_generation_config", return_value=snapshot) as resolve, \
                patch.object(llm, "get_usable_session", return_value=session):
            self.assertEqual(llm.generate_text("目标", model="custom-oauth-model"), '{"answer":"ok"}')
        resolve.assert_called_once_with(default_model=llm.MODEL, override_model="custom-oauth-model")
        self.assertEqual(client.responses.create.call_args.kwargs["model"], "custom-oauth-model")


if __name__ == "__main__":
    unittest.main()
