"""Load tools/agent_client.py as a module without requiring `tools/` to be a
package or be on sys.path -- this IDE package lives at the repo root
(`python -m irobot_gym_ide.app` run from there) and must reuse
agent_client.py's wire helpers (touch_message, keycode_message, send_json,
read_blob_message, android_keycode) rather than duplicating the wire format
a second time.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_NAME = "irobot_gym_ide._agent_client_impl"
_PATH = Path(__file__).resolve().parent.parent / "tools" / "agent_client.py"


def _load():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


agent_client = _load()
