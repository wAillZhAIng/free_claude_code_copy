"""No network. Source-patch guards plus optional actual FCC converter regressions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

compat = load("pmg_compat_tests", ROOT / "scripts/fcc_compat.py")
FCC_AVAILABLE = importlib.util.find_spec("free_claude_code") is not None


class PatchGuards(unittest.TestCase):
    def test_unreviewed_source_rejected(self):
        with self.assertRaises(ValueError):
            compat.patched_source(b"unreviewed source")

    def test_newline_preservation(self):
        original = compat.ANCHOR
        with patch.object(compat, "ORIGINAL_SHA256", compat.digest(original)):
            self.assertEqual(compat.patched_source(original), compat.REPLACEMENT)
            self.assertEqual(compat.patched_source(original.replace(b"\n", b"\r\n")), compat.REPLACEMENT.replace(b"\n", b"\r\n"))

    def test_prepare_never_edits_installed_source_and_refuses_overlay_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "runtime/Lib/site-packages/free_claude_code/core/chat_completions/responses_stream.py"
            source.parent.mkdir(parents=True)
            source.write_bytes(compat.ANCHOR)
            project = root / "project"
            project.mkdir()
            with patch.object(compat, "ROOT", project), patch.object(compat, "ORIGINAL_SHA256", compat.digest(compat.ANCHOR)):
                compat.prepare(root)
                self.assertFalse((project / "compat").exists())
                compat.prepare(root, execute=True)
                self.assertEqual(source.read_bytes(), compat.ANCHOR)
                overlay = project / "compat/fcc_responses_stream.py"
                self.assertEqual(overlay.read_bytes(), compat.REPLACEMENT)
                overlay.write_bytes(b"other project changes")
                with self.assertRaises(ValueError):
                    compat.prepare(root, execute=True)
                self.assertEqual(overlay.read_bytes(), b"other project changes")


@unittest.skipUnless(FCC_AVAILABLE, "Run with isolated FCC Python 3.14 for converter regressions")
class ConverterRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launcher = load("pmg_launcher_tests", ROOT / "scripts/fcc_launcher.py")
        cls.overlay = launcher.install_overlay()
        from free_claude_code.core.chat_completions.responses_stream import ChatResponsesStream
        from free_claude_code.core.chat_completions.response import ChatResponseAccumulator
        from free_claude_code.core.failures import ExecutionFailure
        from free_claude_code.core.history_replay import ReplayOrigin
        cls.Stream = ChatResponsesStream
        cls.Accumulator = ChatResponseAccumulator
        cls.Failure = ExecutionFailure
        cls.Origin = ReplayOrigin

    def stream(self):
        return self.Stream(model="fixture/model", origin=self.Origin(provider="fixture", protocol="responses", endpoint="fixture", connection="fixture", model="fixture/model"), reserved_tool_ids=frozenset(), include_usage=True, include_thoughts=True)

    def aggregate(self, frames):
        accumulator = self.Accumulator()
        for raw in frames:
            data = raw.removeprefix("data: ").strip()
            if data == "[DONE]":
                accumulator.finish()
            else:
                accumulator.feed(json.loads(data))
        return accumulator.result()

    def test_actual_module_is_project_copy(self):
        import sys
        module = sys.modules["free_claude_code.core.chat_completions.responses_stream"]
        self.assertEqual(Path(module.__file__), self.overlay)

    def test_metadata_preserved_in_json_not_content_and_not_mutated(self):
        stream = self.stream()
        metadata = {"type": "response.metadata", "response_id": "resp_fixture", "sequence_number": 3, "metadata": {"synthetic_moderation": {"blocked": False}}}
        frames = stream.start() + stream.feed("response.metadata", metadata)
        metadata["metadata"]["synthetic_moderation"]["blocked"] = True
        frames += stream.feed("response.output_text.delta", {"delta": "Hello"})
        frames += stream.feed("response.completed", {"response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}]}})
        message = self.aggregate(frames)["choices"][0]["message"]
        self.assertEqual(message["content"], "Hello")
        self.assertFalse(message["provider_metadata"][0]["metadata"]["synthetic_moderation"]["blocked"])

    def test_malformed_metadata_rejected(self):
        for payload in ({"metadata": []}, {"metadata": {}, "item": {}}, {"type": "response.failed", "metadata": {}}):
            with self.subTest(payload=payload), self.assertRaises(self.Failure):
                self.stream().feed("response.metadata", payload)

    def test_unknown_and_failure_events_still_fail(self):
        for event in ("response.unrecognized", "response.failed", "response.error", "error"):
            with self.subTest(event=event), self.assertRaises(self.Failure):
                self.stream().feed(event, {})

    def test_metadata_after_completion_rejected(self):
        stream = self.stream()
        stream.feed("response.completed", {"response": {"output": []}})
        with self.assertRaises(self.Failure):
            stream.feed("response.metadata", {"metadata": {}})

    def test_incomplete_and_refusal_are_not_changed_to_success_text(self):
        stream = self.stream()
        frames = stream.start() + stream.feed("response.refusal.delta", {"delta": "synthetic refusal"})
        frames += stream.feed("response.incomplete", {"response": {"output": [], "incomplete_details": {"reason": "content_filter"}}})
        choice = self.aggregate(frames)["choices"][0]
        self.assertEqual(choice["finish_reason"], "content_filter")
        self.assertEqual(choice["message"]["refusal"], "synthetic refusal")
        self.assertIsNone(choice["message"]["content"])

    def test_tool_call_after_metadata_keeps_id_and_arguments(self):
        stream = self.stream()
        frames = stream.start() + stream.feed("response.metadata", {"metadata": {}})
        frames += stream.feed("response.function_call_arguments.delta", {"output_index": 0, "delta": "{"})
        frames += stream.feed("response.function_call_arguments.delta", {"output_index": 0, "delta": "}"})
        item = {"id": "fc_fixture", "type": "function_call", "call_id": "call_fixture", "name": "gateway_probe", "arguments": "{}", "status": "completed"}
        frames += stream.feed("response.output_item.done", {"output_index": 0, "item": item})
        frames += stream.feed("response.completed", {"response": {"output": [item]}})
        choice = self.aggregate(frames)["choices"][0]
        call = choice["message"]["tool_calls"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertEqual(call["id"], "call_fixture")
        self.assertEqual(call["function"], {"name": "gateway_probe", "arguments": "{}"})


if __name__ == "__main__":
    unittest.main()
