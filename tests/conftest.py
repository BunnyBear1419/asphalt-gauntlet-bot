"""Test-only compatibility source for legacy contracts after the web refactor.

The runtime server.py is intentionally a tiny facade. Older source-contract tests still
refer to server.py; this adapter dynamically composes the real route-family files in the
same order as WebControlCenter, so those tests inspect current production code rather
than a hard-coded method snapshot.
"""
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ALU_Gauntlet" / "web"
SERVER = (WEB / "server.py").resolve()
CONTROL_CENTER = (WEB / "control_center.py").resolve()


def _composed_server_source() -> str:
    control = CONTROL_CENTER.read_text(encoding="utf-8")
    mixins = re.findall(r"([A-Za-z]+RoutesMixin)", control)
    if not mixins:
        raise AssertionError("WebControlCenter has no route-family mixins.")

    chunks = []
    for mixin in mixins:
        module = re.sub(r"RoutesMixin$", "", mixin)
        module = re.sub(r"(?<!^)(?=[A-Z])", "_", module).lower()
        path = WEB / "routes" / f"{module}.py"
        if not path.is_file():
            raise AssertionError(f"Missing route family for {mixin}: {path}")
        chunks.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(chunks)


@pytest.fixture(autouse=True)
def _legacy_server_source_adapter(monkeypatch):
    original = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.resolve() == SERVER:
            return _composed_server_source()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
