#!/usr/bin/env python3
"""Launch FCC with one verified, project-owned module overlay; no installed writes."""
import importlib.abc
import importlib.util
from pathlib import Path
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
MODULE = "free_claude_code.core.chat_completions.responses_stream"


def install_overlay():
    spec = importlib.util.spec_from_file_location("pmg_fcc_compat", ROOT / "scripts/fcc_compat.py")
    compat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compat)
    original = Path(sysconfig.get_paths()["purelib"]) / "free_claude_code/core/chat_completions/responses_stream.py"
    expected = compat.patched_source(original.read_bytes())
    overlay = ROOT / "compat/fcc_responses_stream.py"
    if not overlay.is_file() or overlay.read_bytes() != expected:
        raise ValueError("Project overlay missing or modified; run fcc_compat.py --execute first")
    if MODULE in sys.modules:
        raise ValueError("FCC converter was already imported; refusing ambiguous overlay")

    class ProjectOverlay(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == MODULE:
                return importlib.util.spec_from_file_location(fullname, overlay)
            return None

    sys.meta_path.insert(0, ProjectOverlay())
    return overlay


def main():
    overlay = install_overlay()
    print(f"FCC project compatibility overlay: {overlay}", flush=True)
    from free_claude_code.cli.entrypoints import serve
    serve()


if __name__ == "__main__":
    main()
