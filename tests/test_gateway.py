"""Offline integration tests. Only localhost fixtures; never contact a model provider."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("gateway", Path(__file__).resolve().parents[1] / "scripts/gateway.py")
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


def frame(data):
    return "data: " + (data if isinstance(data, str) else json.dumps(data)) + "\n\n"


def chunk(delta, finish=None):
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def sse_response(*chunks):
    response = io.BytesIO("".join(frame(x) for x in chunks).encode())
    response.headers = {"Content-Type": "text/event-stream; charset=utf-8"}
    return response


def native_payload(text="Hello fixture", tool=False):
    output = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]
    if tool:
        output = [{"type": "reasoning", "id": "rs_fixture", "summary": [], "encrypted_content": "synthetic-replay"}, {"type": "function_call", "id": "fc_fixture", "call_id": "call_fixture", "name": "gateway_probe", "arguments": "{}", "status": "completed"}]
    return {"id": "resp_fixture", "status": "completed", "output": output}


class Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def reply(self, data, content_type="application/json", status=200):
        raw = data.encode() if isinstance(data, str) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/v1/models")
            self.end_headers()
            return
        if self.headers.get("Authorization") != "Bearer local-test":
            self.reply({"error": "missing proxy token"}, status=401)
            return
        if self.path == "/v1/models":
            self.reply({"data": [{"id": "fixture/test"}]})
        else:
            self.reply({}, status=404)

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer local-test":
            self.reply({}, status=401)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(body)
        if self.path == "/v1/responses":
            self.native_reply(body)
        elif self.path != "/v1/chat/completions":
            self.reply({}, status=404)
        elif body.get("tools"):
            # Split function name/arguments across separate SSE chunks.
            first = chunk({"tool_calls": [{"index": 0, "id": "call_fixture", "function": {"name": "gateway_", "arguments": "{"}}]})
            last = chunk({"tool_calls": [{"index": 0, "function": {"name": "probe", "arguments": "}"}}]}, "tool_calls")
            self.reply(frame(first) + frame(last) + frame("[DONE]"), "text/event-stream")
        else:
            is_tool_result = body["messages"][-1]["role"] == "tool"
            if is_tool_result:
                assert body["messages"][-1]["tool_call_id"] == "call_fixture"
                text = "portable-probe-7429"
            else:
                text = "Hello fixture"
            if body.get("stream"):
                self.reply(frame(chunk({"content": text})) + frame(chunk({}, "stop")) + frame("[DONE]"), "text/event-stream")
            else:
                self.reply({"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]})

    def native_reply(self, body):
        assert isinstance(body["input"], list)
        assert body["store"] is False
        is_result = body["input"][-1].get("type") == "function_call_output"
        if is_result:
            assert body["input"][-1]["call_id"] == "call_fixture"
            assert body["input"][-2]["type"] == "function_call"
            assert body["input"][-3]["encrypted_content"] == "synthetic-replay"
        tool = bool(body.get("tools")) and not is_result
        text = "portable-probe-7429" if is_result else "Hello fixture"
        payload = native_payload(text, tool=tool)
        if not body["stream"]:
            self.reply(payload)
            return
        chunks = [{"type": "response.created"}, {"type": "response.metadata", "metadata": {"synthetic": True}}]
        if tool:
            chunks.extend([{"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "{"}, {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "}"}])
        else:
            chunks.append({"type": "response.output_text.delta", "delta": text})
        chunks.append({"type": "response.completed", "response": payload})
        self.reply("".join(frame(x) for x in chunks), "text/event-stream")


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_loopback_base_url(self):
        self.assertEqual(gateway.base_url(self.base + "/"), self.base)
        self.assertEqual(gateway.base_url("http://[::1]:8082/v1"), "http://[::1]:8082/v1")

    def test_remote_requires_opt_in(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.base_url("https://example.com/v1")
        self.assertEqual(gateway.base_url("https://example.com/v1", True), "https://example.com/v1")

    def test_full_endpoint_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.base_url(self.base + "/chat/completions")

    def test_credentials_query_fragment_rejected(self):
        for value in ("http://key:secret@localhost/v1", "http://localhost/v1?key=secret", "http://localhost/v1#key"):
            with self.subTest(value=value), self.assertRaises(gateway.ConfigError):
                gateway.base_url(value)

    def test_json_sse_and_tool_roundtrip(self):
        before = len(Handler.seen)
        result = gateway.smoke(self.base, "fixture/test", "local-test", True)
        self.assertEqual(len(Handler.seen) - before, 4)
        self.assertTrue(result["json"]["ok"])
        self.assertTrue(result["stream"]["ok"])
        self.assertTrue(result["tools_roundtrip"]["ok"])
        self.assertFalse(result["billing_verified"])

    def test_native_responses_json_sse_tools_and_reasoning_replay(self):
        before = len(Handler.seen)
        result = gateway.smoke_responses(self.base, "fixture/test", "local-test", True)
        self.assertEqual(len(Handler.seen) - before, 4)
        self.assertTrue(result["json"]["ok"])
        self.assertTrue(result["stream"]["ok"])
        self.assertTrue(result["tools_roundtrip"]["ok"])
        self.assertFalse(result["billing_verified"])

    def test_native_stream_only_skips_json_and_uses_three_requests(self):
        before = len(Handler.seen)
        result = gateway.smoke_responses(self.base, "fixture/test", "local-test", True, True)
        self.assertEqual(len(Handler.seen) - before, 3)
        self.assertFalse(result["json"]["tested"])
        self.assertTrue(result["stream"]["ok"])
        self.assertTrue(result["tools_roundtrip"]["ok"])

    def test_chat_replay_and_metadata_not_treated_as_text(self):
        detail = {"type": "reasoning.encrypted", "data": "synthetic-replay"}
        result = gateway.parse_stream(sse_response(chunk({"reasoning_details": [detail], "provider_metadata": [{"metadata": {"synthetic": True}}]}), chunk({"content": "Hello"}, "stop"), "[DONE]"))
        self.assertEqual(result["text"], "Hello")
        self.assertEqual(result["replay"]["reasoning_details"], [detail])
        self.assertEqual(result["metadata_events"], 1)

    def test_native_errors_and_incomplete_rejected(self):
        for kind in ("error", "response.error", "response.failed", "response.incomplete"):
            with self.subTest(kind=kind), self.assertRaises(gateway.ConfigError):
                gateway.parse_responses_stream(sse_response({"type": kind}))

    def test_native_missing_terminal_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_responses_stream(sse_response({"type": "response.output_text.delta", "delta": "Hello fixture"}))

    def test_native_early_done_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_responses_stream(sse_response("[DONE]"))

    def test_native_text_mismatch_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_responses_stream(sse_response({"type": "response.output_text.delta", "delta": "wrong"}, {"type": "response.completed", "response": native_payload()}))

    def test_native_tool_argument_mismatch_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_responses_stream(sse_response({"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "{"}, {"type": "response.completed", "response": native_payload(tool=True)}))

    def test_native_events_after_terminal_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_responses_stream(sse_response({"type": "response.output_text.delta", "delta": "Hello fixture"}, {"type": "response.completed", "response": native_payload()}, {"type": "response.metadata"}))

    def test_native_wrong_mime_rejected(self):
        response = io.BytesIO(b"{}")
        response.headers = {"Content-Type": "application/json"}
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_responses_stream(response)

    def test_native_refusal_and_incomplete_status_rejected(self):
        payload = native_payload()
        payload["output"][0]["content"] = [{"type": "refusal", "refusal": "synthetic refusal"}]
        with self.assertRaises(gateway.ConfigError):
            gateway.responses_result(payload)
        payload = native_payload()
        payload["status"] = "incomplete"
        with self.assertRaises(gateway.ConfigError):
            gateway.responses_result(payload)

    def test_native_cli_requires_usage_approval(self):
        before = len(Handler.seen)
        with self.assertRaises(gateway.ConfigError):
            gateway.main(["probe", "--model", "fixture/test", "--base-url", self.base, "--api", "openai-responses"])
        self.assertEqual(len(Handler.seen), before)

    def test_weknora_native_profile(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            gateway.main(["weknora-config", "--model", "openai/fixture", "--api", "openai-responses"])
        settings = json.loads(buffer.getvalue())["parameters"]
        self.assertEqual(settings["extra_config"]["api"], "openai-responses")
        self.assertEqual(settings["spec"], {"api": "openai-responses"})
        self.assertNotIn("compat", settings["spec"])

    def test_models(self):
        with gateway.request(self.base, "/models", "local-test") as response:
            self.assertEqual(json.load(response)["data"][0]["id"], "fixture/test")

    def test_redirect_refused(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.request(self.base.removesuffix("/v1"), "/redirect", "local-test")

    def test_probe_without_usage_approval_makes_no_request(self):
        before = len(Handler.seen)
        with self.assertRaises(gateway.ConfigError):
            gateway.main(["probe", "--model", "fixture/test", "--base-url", self.base])
        self.assertEqual(len(Handler.seen), before)

    def test_cli_models_uses_token_environment_without_printing_it(self):
        buffer = io.StringIO()
        with patch.dict(os.environ, {"MODEL_GATEWAY_TOKEN": "local-test"}), contextlib.redirect_stdout(buffer):
            gateway.main(["models", "--base-url", self.base])
        self.assertIn("fixture/test", buffer.getvalue())
        self.assertNotIn("local-test", buffer.getvalue())

    def test_truncated_stream_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_stream(sse_response(chunk({"content": "partial"}, "stop")))

    def test_unterminated_frame_rejected(self):
        with self.assertRaises(gateway.ConfigError):
            list(gateway.events(io.BytesIO(b'data: {"choices": []}\n')))

    def test_stream_malformed_json_rejected(self):
        with self.assertRaises(ValueError):
            gateway.parse_stream(sse_response("{bad-json}"))

    def test_stream_wrong_mime_rejected(self):
        response = io.BytesIO(b"{}")
        response.headers = {"Content-Type": "application/json"}
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_stream(response)

    def test_stream_refusal_or_length_rejected(self):
        for finish in ("length", "content_filter"):
            with self.subTest(finish=finish), self.assertRaises(gateway.ConfigError):
                gateway.parse_stream(sse_response(chunk({}, finish), "[DONE]"))

    def test_stream_tool_index_required(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.parse_stream(sse_response(chunk({"tool_calls": [{"function": {"name": "probe"}}]}, "tool_calls"), "[DONE]"))

    def test_install_skill_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as target:
            dest = gateway.install_skill(target)
            self.assertTrue((dest / "SKILL.md").is_file())
            self.assertTrue((dest / "scripts/gateway.py").is_file())
            with self.assertRaises(gateway.ConfigError):
                gateway.install_skill(target)

    def test_install_skill_only_copies_explicit_distribution_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            for relative in gateway.SKILL_FILES:
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("synthetic public source", encoding="utf-8")
            for relative in (".env", "home/.fcc/oauth.json", "compat/generated.py", "unlisted.txt"):
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("synthetic private fixture", encoding="utf-8")
            with patch.object(gateway, "ROOT", root):
                dest = gateway.install_skill(Path(directory) / "host-skills")
            actual = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
            self.assertEqual(actual, set(gateway.SKILL_FILES))

    def test_install_skill_missing_distribution_refuses_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "incomplete-source"
            root.mkdir()
            target = Path(directory) / "host-skills"
            with patch.object(gateway, "ROOT", root), self.assertRaises(gateway.ConfigError):
                gateway.install_skill(target)
            self.assertFalse((target / "portable-model-gateway").exists())

    def test_install_skill_refuses_recursion(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.install_skill(gateway.ROOT)

    def test_runtime_home_and_environment_isolated(self):
        with tempfile.TemporaryDirectory() as target, patch.dict(os.environ, {"OPENAI_API_KEY": "not-inherited", "ANTHROPIC_AUTH_TOKEN": "not-inherited", "MODEL": "not-inherited"}):
            env = gateway.runtime_environment(Path(target), 8082)
            self.assertEqual(env["HOST"], "127.0.0.1")
            self.assertEqual(env["HOME"], env["USERPROFILE"])
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
            self.assertNotIn("MODEL", env)

    def test_runtime_install_dry_run_does_not_create_or_run(self):
        with tempfile.TemporaryDirectory() as target, patch.object(gateway.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as buffer:
            state = Path(target) / "state"
            gateway.runtime_install(state, False)
            run.assert_not_called()
            self.assertFalse(state.exists())
            self.assertIn(gateway.REVISION, buffer.getvalue())

    def test_weknora_profile_is_reference_and_has_no_secret(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            gateway.main(["weknora-config", "--model", "openai/fixture"])
        result = json.loads(buffer.getvalue())
        self.assertEqual(result["parameters"]["extra_config"]["api"], "openai-completions")
        self.assertEqual(result["parameters"]["provider"], "generic")
        self.assertEqual(result["parameters"]["extra_config"]["remote_model_name"], "openai/fixture")
        self.assertEqual(result["parameters"]["spec"], {"api": "openai-completions", "compat": {"thinking_format": "none"}})
        self.assertEqual(result["source"], "remote")
        self.assertIn("reference", result["note"])

    def test_start_refuses_occupied_port_without_launching(self):
        with patch.object(gateway.Path, "is_file", return_value=True), patch.object(gateway.subprocess, "run") as run:
            with self.assertRaises(gateway.ConfigError):
                gateway.main(["start", "--port", str(self.server.server_port)])
            run.assert_not_called()

    def test_uv_path_validation(self):
        with tempfile.TemporaryDirectory() as target:
            with self.assertRaises(gateway.ConfigError):
                gateway.runtime_install(Path(target), False, str(Path(target) / "missing-uv"))

    def test_revision_matches_manifest(self):
        manifest = json.loads((gateway.ROOT / "upstream.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["revision"], gateway.REVISION)
        self.assertEqual(manifest["python"], gateway.FCC_PYTHON)


if __name__ == "__main__":
    unittest.main()
