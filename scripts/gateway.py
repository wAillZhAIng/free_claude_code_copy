#!/usr/bin/env python3
"""Portable FCC helper. Python 3.10+, standard library only. Never reads OAuth tokens."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/Alishahryar1/free-claude-code"
REVISION = "56621010ada15b633d76ab19178764bb3e81bcc5"
FCC_PYTHON = "3.14.10"
PACKAGE = f"git+{UPSTREAM}.git@{REVISION}"


class ConfigError(ValueError):
    """A safe, credential-free message that can be displayed to the user."""


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def state_path(value=None):
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return Path(value).expanduser().resolve() if value else base / "portable-model-gateway"


def executable(state, name):
    return state / "runtime" / ("Scripts" if os.name == "nt" else "bin") / (
        name + (".exe" if os.name == "nt" else "")
    )


def base_url(value, allow_remote=False):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError("Base URL must use http:// or https://")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ConfigError("Do not embed credentials, queries or fragments in the Base URL")
    if parsed.path.rstrip("/") != "/v1":
        raise ConfigError("Base URL must end at /v1, not /chat/completions")
    if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"} and not allow_remote:
        raise ConfigError("Remote endpoint requires --allow-remote (may disclose prompts or keys)")
    return value.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ConfigError("HTTP redirects are refused to avoid forwarding credentials")


def request(base, path, token=None, payload=None, timeout=90):
    headers = {"Accept": "text/event-stream" if payload and payload.get("stream") else "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    return opener.open(req, timeout=timeout)


def events(response):
    """Parse SSE data fields, including multiline events; reject truncated frames."""
    data, size = [], 0
    for raw in response:
        size += len(raw)
        if size > 8 * 1024 * 1024:
            raise ConfigError("SSE exceeds the 8 MiB probe limit")
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        raise ConfigError("SSE ended in an unterminated event")


def parse_stream(response):
    if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
        raise ConfigError("Expected text/event-stream, not buffered JSON")
    text, tools, finish, done, count = [], {}, None, False, 0
    replay, metadata_events = {}, 0
    for data in events(response):
        if data == "[DONE]":
            done = True
            break
        chunk = json.loads(data)
        if chunk.get("error"):
            raise ConfigError("Upstream sent an error event")
        choices = chunk.get("choices", [])
        if not choices:
            continue
        choice = choices[0]
        count += 1
        delta = choice.get("delta", {})
        if delta.get("content"):
            text.append(delta["content"])
        if delta.get("reasoning_details"):
            replay.setdefault("reasoning_details", []).extend(delta["reasoning_details"])
        if delta.get("reasoning_content"):
            replay["reasoning_content"] = replay.get("reasoning_content", "") + delta["reasoning_content"]
        metadata_events += len(delta.get("provider_metadata", []))
        for part in delta.get("tool_calls", []):
            index = part.get("index")
            if not isinstance(index, int) or isinstance(index, bool):
                raise ConfigError("Streaming tool_calls must carry an integer index")
            call = tools.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if part.get("id"):
                call["id"] += part["id"]
            for key in ("name", "arguments"):
                call["function"][key] += part.get("function", {}).get(key, "")
        if choice.get("finish_reason"):
            finish = choice["finish_reason"]
    if not done or not finish or not count:
        raise ConfigError("Incomplete stream: require choices, finish_reason and [DONE]")
    if finish not in {"stop", "tool_calls"}:
        raise ConfigError("Generation was truncated, refused, or unfinished")
    return {"text": "".join(text), "tool_calls": [tools[k] for k in sorted(tools)], "finish_reason": finish, "chunks": count, "replay": replay, "metadata_events": metadata_events}


def chat(base, model, token, messages, *, stream, tools=None):
    body = {"model": model, "messages": messages, "stream": stream}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    with request(base, "/chat/completions", token, body) as response:
        if stream:
            return parse_stream(response)
        payload = json.load(response)
    choice = payload["choices"][0]
    if choice.get("finish_reason") not in {"stop", "tool_calls"}:
        raise ConfigError("Non-streaming response was truncated, refused or unfinished")
    message = choice["message"]
    return {"text": message.get("content") or "", "tool_calls": message.get("tool_calls", []), "finish_reason": choice["finish_reason"], "replay": {k: message[k] for k in ("reasoning_details", "reasoning_content") if k in message}, "metadata_events": len(message.get("provider_metadata", []))}


def smoke(base, model, token, with_tools=False):
    messages = [{"role": "user", "content": "Reply with a short greeting."}]
    results = {}
    for stream in (False, True):
        reply = chat(base, model, token, messages, stream=stream)
        if not reply["text"].strip():
            raise ConfigError("Empty text response in chat smoke test")
        results["stream" if stream else "json"] = {"ok": True, "characters": len(reply["text"]), "metadata_events": reply.get("metadata_events", 0)}
    if with_tools:
        tools = [{"type": "function", "function": {"name": "gateway_probe", "description": "Get the probe nonce. Call once, then report the nonce.", "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}}]
        history = [{"role": "user", "content": "Call gateway_probe once with no arguments. Then tell me the returned nonce."}]
        first = chat(base, model, token, history, stream=True, tools=tools)
        calls = first["tool_calls"]
        if not calls or first["finish_reason"] != "tool_calls":
            raise ConfigError("No native tool calls; tool compatibility NOT proven")
        history.append({"role": "assistant", "content": first["text"] or None, "tool_calls": calls, **first.get("replay", {})})
        seen = set()
        for call in calls:
            if not call["id"] or call["id"] in seen or call["function"]["name"] != "gateway_probe":
                raise ConfigError("Invalid or duplicate tool id/name")
            seen.add(call["id"])
            if json.loads(call["function"]["arguments"]) != {}:
                raise ConfigError("Probe tool arguments must be an empty object")
            history.append({"role": "tool", "tool_call_id": call["id"], "content": '{"nonce":"portable-probe-7429"}'})
        final = chat(base, model, token, history, stream=True)
        if "portable-probe-7429" not in final["text"] or final["tool_calls"]:
            raise ConfigError("Tool result round-trip was not successfully consumed")
        results["tools_roundtrip"] = {"ok": True, "calls": len(calls)}
    results["billing_verified"] = False
    results["note"] = "Protocol only; does not prove subscription billing, quota, or WeKnora end-to-end compatibility."
    return results


def responses_result(payload):
    """Validate terminal native output; retain the full output for stateless replay."""
    if payload.get("error") or payload.get("status") != "completed":
        raise ConfigError("Responses generation failed, refused, or unfinished")
    native = payload.get("output")
    if not isinstance(native, list):
        raise ConfigError("Responses output must be a list")
    text, calls = [], []
    for item in native:
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    raise ConfigError("Responses generation was refused")
                if part.get("type") == "output_text":
                    text.append(part["text"])
        elif item.get("type") == "function_call":
            calls.append({"id": item.get("call_id"), "function": {"name": item.get("name"), "arguments": item.get("arguments")}})
        elif item.get("type") != "reasoning":
            raise ConfigError("Probe cannot validate this Responses output item")
    return {"text": "".join(text), "tool_calls": calls, "output": native}


def parse_responses_stream(response):
    if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
        raise ConfigError("Expected native Responses event-stream")
    terminal, text, arguments, count = None, [], {}, 0
    for raw in events(response):
        if raw == "[DONE]":
            if terminal is None:
                raise ConfigError("Responses ended before response.completed")
            continue
        data = json.loads(raw)
        kind = data.get("type")
        if terminal is not None:
            raise ConfigError("Responses event arrived after completion")
        count += 1
        if data.get("error") or kind in {"error", "response.error", "response.failed", "response.incomplete"}:
            raise ConfigError("Native Responses stream failed or was incomplete")
        if kind == "response.output_text.delta":
            text.append(data["delta"])
        elif kind == "response.function_call_arguments.delta":
            index = data.get("output_index")
            if not isinstance(index, int) or isinstance(index, bool):
                raise ConfigError("Responses arguments require an integer output_index")
            arguments[index] = arguments.get(index, "") + data["delta"]
        elif kind == "response.completed":
            terminal = responses_result(data["response"])
        # Native metadata/lifecycle events remain on the wire. This probe derives
        # output only from completed canonical items, not unrecognized events.
    if terminal is None:
        raise ConfigError("Responses stream missing response.completed")
    if terminal["text"] != "".join(text):
        raise ConfigError("Responses text deltas disagree with completed output")
    for index, item in enumerate(terminal["output"]):
        if item.get("type") == "function_call" and arguments.get(index) != item.get("arguments"):
            raise ConfigError("Responses tool deltas disagree with completed output")
    terminal["events"] = count
    return terminal


def responses(base, model, token, history, *, stream, tools=None):
    body = {"model": model, "input": history, "stream": stream, "store": False}
    if tools:
        body.update(tools=tools, tool_choice="auto")
    with request(base, "/responses", token, body) as response:
        return parse_responses_stream(response) if stream else responses_result(json.load(response))


def smoke_responses(base, model, token, with_tools=False, stream_only=False):
    history = [{"role": "user", "content": [{"type": "input_text", "text": "Reply with a short greeting."}]}]
    result = {"api": "openai-responses"}
    if stream_only:
        result["json"] = {"ok": False, "tested": False, "reason": "Skipped explicitly: pinned FCC Responses endpoint supports streaming only"}
    for stream in ((True,) if stream_only else (False, True)):
        reply = responses(base, model, token, history, stream=stream)
        if not reply["text"].strip() or reply["tool_calls"]:
            raise ConfigError("Invalid greeting in native Responses probe")
        result["stream" if stream else "json"] = {"ok": True, "characters": len(reply["text"])}
    if with_tools:
        tools = [{"type": "function", "name": "gateway_probe", "description": "Get the probe nonce. Call once, then report the nonce.", "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, "strict": True}]
        history = [{"role": "user", "content": [{"type": "input_text", "text": "Call gateway_probe once with no arguments. Then tell me the returned nonce."}]}]
        first = responses(base, model, token, history, stream=True, tools=tools)
        calls = first["tool_calls"]
        if len(calls) != 1:
            raise ConfigError("Expected exactly one native Responses tool call")
        call = calls[0]
        if not call["id"] or call["function"]["name"] != "gateway_probe" or json.loads(call["function"]["arguments"]) != {}:
            raise ConfigError("Invalid native Responses probe tool call")
        # Replay every output item, including reasoning, not just the function.
        history.extend(first["output"])
        history.append({"type": "function_call_output", "call_id": call["id"], "output": '{"nonce":"portable-probe-7429"}'})
        final = responses(base, model, token, history, stream=True, tools=tools)
        if "portable-probe-7429" not in final["text"] or final["tool_calls"]:
            raise ConfigError("Native Responses tool result was not consumed")
        result["tools_roundtrip"] = {"ok": True, "calls": len(calls)}
    result["billing_verified"] = False
    result["note"] = "Protocol only; does not prove subscription billing, quota, or WeKnora end-to-end compatibility."
    return result


# Explicit distribution list: never copy incidental credentials, state, or a
# user's extra files merely because they happen to be inside the repository.
SKILL_FILES = (
    ".gitignore", "LICENSE", "LICENSES/FCC-Upstream.txt", "README.md", "SKILL.md",
    "VALIDATION.md", "upstream.json", "docs/QUICKSTART.zh-CN.md",
    "references/weknora.md", "scripts/gateway.py", "scripts/fcc_compat.py",
    "scripts/fcc_launcher.py", "tests/test_gateway.py", "tests/test_fcc_compat.py",
)


def install_skill(target):
    dest = Path(target).expanduser().resolve() / "portable-model-gateway"
    if dest.exists() or dest.is_symlink():
        raise ConfigError("Destination already exists; refusing to overwrite")
    if dest == ROOT or ROOT in dest.parents:
        raise ConfigError("Cannot install a skill inside itself")
    for relative in SKILL_FILES:
        source = ROOT / relative
        if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):
            raise ConfigError("Skill distribution file missing or unsafe: " + relative)
    dest.mkdir(parents=True)
    for relative in SKILL_FILES:
        source = ROOT / relative
        copied = dest / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, copied)
    return dest


def runtime_install(state, execute, uv_path=None):
    uv = str(Path(uv_path).expanduser().resolve()) if uv_path else shutil.which("uv")
    if uv_path and not Path(uv).is_file():
        raise ConfigError("The specified --uv-path does not exist")
    py = executable(state, "python")
    commands = [[uv or "uv", "venv", "--python", FCC_PYTHON, str(state / "runtime")],
                [uv or "uv", "pip", "install", "--python", str(py), PACKAGE]]
    if not execute:
        output({"dry_run": True, "commands": commands, "warning": "Downloads Python/dependencies and executes upstream build code. Re-run with --execute only after review."})
        return
    if not uv:
        raise ConfigError("Install uv from https://docs.astral.sh/uv/getting-started/installation/ first")
    if (state / "runtime").exists():
        raise ConfigError("Runtime exists, possibly partial. Inspect it or choose another --state-dir")
    state.mkdir(parents=True, exist_ok=True)
    for cmd in commands:
        subprocess.run(cmd, check=True, cwd=ROOT)
    output({"installed": True, "revision": REVISION, "state_dir": str(state)})


def runtime_environment(state, port):
    home = state / "home"
    home.mkdir(parents=True, exist_ok=True)
    names = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
    env = {k: v for k, v in os.environ.items() if k.upper() in names}
    env.update(HOME=str(home), USERPROFILE=str(home), HOST="127.0.0.1", PORT=str(port), FCC_OPEN_BROWSER="false", PYTHONNOUSERSITE="1")
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    install = sub.add_parser("install-skill")
    install.add_argument("--skills-dir", required=True, help="Host skills directory, not the skill itself")
    for name in ("install-runtime", "start"):
        p = sub.add_parser(name)
        p.add_argument("--state-dir")
        if name == "install-runtime":
            p.add_argument("--execute", action="store_true")
            p.add_argument("--uv-path", help="Optional absolute path to a separately installed uv executable")
        else:
            p.add_argument("--port", type=int, default=8082)
            p.add_argument("--compat-metadata", action="store_true", help="Load the reviewed project-local FCC metadata overlay, without modifying the installed package")
    for name in ("models", "probe", "weknora-config"):
        p = sub.add_parser(name)
        p.add_argument("--base-url", default="http://127.0.0.1:8082/v1")
        p.add_argument("--allow-remote", action="store_true")
        if name != "weknora-config":
            p.add_argument("--token-env", default="MODEL_GATEWAY_TOKEN", help="Variable containing the local FCC proxy token, NOT an OAuth token")
        if name != "models":
            p.add_argument("--model", required=True, help="Exact FCC id from the admin model picker")
        if name != "models":
            p.add_argument("--api", choices=("openai-completions", "openai-responses"), default="openai-completions", help="Select the protocol to probe or emit; use openai-responses for the verified ChatGPT route")
        if name == "probe":
            p.add_argument("--tools", action="store_true")
            p.add_argument("--stream-only", action="store_true", help="Responses only: skip JSON for streaming-only gateways (1 request, 3 with tools)")
            p.add_argument("--confirm-usage", action="store_true", help="Allow 2 requests (4 with tools; 1/3 in stream-only mode), consuming provider quota")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        output({"helper_python": sys.version.split()[0], "fcc_python_required": FCC_PYTHON, "uv_found": bool(shutil.which("uv")), "git_found": bool(shutil.which("git")), "state_dir": str(state_path()), "upstream_revision": REVISION, "credentials_read": False})
    elif args.command == "install-skill":
        output({"installed": str(install_skill(args.skills_dir))})
    elif args.command == "install-runtime":
        runtime_install(state_path(args.state_dir), args.execute, args.uv_path)
    elif args.command == "start":
        if not 1 <= args.port <= 65535:
            raise ConfigError("Port must be between 1 and 65535")
        state = state_path(args.state_dir)
        server = executable(state, "fcc-server")
        if not server.is_file():
            raise ConfigError("FCC runtime missing. Run install-runtime first")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
                check.bind(("127.0.0.1", args.port))
        except OSError:
            raise ConfigError("Port unavailable; leave the existing service untouched and choose another --port") from None
        print(f"FCC Admin: http://127.0.0.1:{args.port}/admin\nLocal Base URL: http://127.0.0.1:{args.port}/v1", flush=True)
        command = ([str(executable(state, "python")), "-I", str(ROOT / "scripts/fcc_launcher.py")]
                   if args.compat_metadata else [str(server)])
        result = subprocess.run(command, cwd=ROOT, env=runtime_environment(state, args.port))
        return result.returncode
    else:
        base = base_url(args.base_url, args.allow_remote)
        if args.command == "weknora-config":
            settings = {"provider": "generic", "base_url": base,
                        "api_key": "<local FCC proxy token if enabled; otherwise empty>",
                        "extra_config": {"api": args.api, "remote_model_name": args.model},
                        "spec": {"api": args.api}}
            if args.api == "openai-completions":
                settings["spec"]["compat"] = {"thinking_format": "none"}
            output({"source": "remote", "name": args.model, "parameters": settings,
                    "note": "Configuration reference, NOT an auto-submitted API payload. Backend must reach this hostname. Chat uses spec.compat.thinking_format=none to avoid chat_template_kwargs; remove any conflicting legacy thinking_control. Keep embedding/rerank separate."})
        else:
            token = os.environ.get(args.token_env)
            if args.command == "models":
                with request(base, "/models", token) as response:
                    payload = json.load(response)
                output({"models": [x["id"] for x in payload["data"]], "note": "Select exact openai/<id> from the FCC admin picker for ChatGPT; openai_api/<id> uses separate API billing."})
            else:
                if not args.confirm_usage:
                    raise ConfigError("Probe consumes quota. Pass --confirm-usage after approval")
                if args.stream_only and args.api != "openai-responses":
                    raise ConfigError("--stream-only requires --api openai-responses")
                result = (smoke_responses(base, args.model, token, args.tools, args.stream_only)
                          if args.api == "openai-responses" else smoke(base, args.model, token, args.tools))
                output(result)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}. Check FCC locally; no response body logged.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, TypeError, IndexError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Failed: {type(exc).__name__}. No request or response details logged.", file=sys.stderr)
        sys.exit(1)
