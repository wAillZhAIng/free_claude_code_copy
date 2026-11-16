#!/usr/bin/env python3
"""Project-local FCC metadata compatibility overlay; never edits site-packages.

AGPL-3.0-only. Upstream: https://github.com/Alishahryar1/free-claude-code
Reviewed commit: 56621010ada15b633d76ab19178764bb3e81bcc5 (FCC 6.19.11).
Only response.metadata is added. Metadata is retained as a Chat extension;
unknown events, refusals, errors and completion checks remain unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Hash after CRLF-to-LF normalization, allowing identical Windows/POSIX source.
ORIGINAL_SHA256 = "da33b85b4cf450a93b97d69892595e43de36f84730c17e492e2c5750dbba02c5"
ANCHOR = b'''        index = data.get("output_index", 0)
        if event_type in {
'''
REPLACEMENT = b'''        # portable-model-gateway: retain adjunct metadata, never assistant text.
        if event_type == "response.metadata":
            if (
                set(data) - {"type", "sequence_number", "response_id", "metadata"}
                or data.get("type", event_type) != event_type
                or not isinstance(data.get("metadata"), dict)
            ):
                raise chat_failure("Invalid Responses metadata event")
            return self._output.delta({"provider_metadata": [deepcopy(data)]})
        index = data.get("output_index", 0)
        if event_type in {
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patched_source(original):
    normalized = original.replace(b"\r\n", b"\n")
    if digest(normalized) != ORIGINAL_SHA256:
        raise ValueError("Installed FCC source differs from reviewed version")
    if normalized.count(ANCHOR) != 1:
        raise ValueError("Patch anchor is not unique")
    patched = normalized.replace(ANCHOR, REPLACEMENT, 1)
    return patched.replace(b"\n", b"\r\n") if b"\r\n" in original else patched


def source_file(state):
    relative = Path("free_claude_code/core/chat_completions/responses_stream.py")
    candidates = [state / "runtime/Lib/site-packages" / relative,
                  state / "runtime/lib/python3.14/site-packages" / relative]
    targets = [p for p in candidates if p.is_file()]
    if len(targets) != 1:
        raise ValueError("Expected exactly one installed FCC converter")
    return targets[0]


def prepare(state, execute=False):
    source = source_file(state)
    original = source.read_bytes()
    patched = patched_source(original)
    # All writes are inside this project-owned Skill directory.
    dest = ROOT / "compat/fcc_responses_stream.py"
    if dest.exists() and dest.read_bytes() != patched:
        raise ValueError("Project overlay has other changes; refusing to overwrite")
    if execute and not dest.exists():
        dest.parent.mkdir(exist_ok=True)
        with dest.open("xb") as handle:
            handle.write(patched)
    return {"dry_run": not execute, "source_unchanged": True, "overlay": str(dest),
            "original_sha256": digest(original), "overlay_sha256": digest(patched)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "portable-model-gateway"
    parser.add_argument("--state-dir", type=Path, default=default)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.state_dir.resolve(), args.execute), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
