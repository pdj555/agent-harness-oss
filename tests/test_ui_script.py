from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "harness" / "static" / "app.js"
CSS = Path(__file__).resolve().parent.parent / "harness" / "static" / "app.css"


def test_hidden_attribute_is_forced_in_css():
    assert "[hidden]" in CSS.read_text(encoding="utf-8")


def test_classic_script_executes_with_window_and_without_node_globals(tmp_path: Path):
    node = shutil.which("node")
    if not node:
        return
    source = JS.read_text(encoding="utf-8")
    runner = tmp_path / "browser-like.js"
    runner.write_text(
        """
delete globalThis.module;
delete globalThis.require;
globalThis.window = globalThis;
globalThis.fetch = function () {
  return Promise.resolve({
    ok: false,
    status: 401,
    json: function () { return Promise.resolve({ error: "authentication required" }); }
  });
};
globalThis.document = {
  getElementById: function () {
    return {
      hidden: false,
      textContent: "",
      innerHTML: "",
      value: "",
      addEventListener: function () {},
      appendChild: function () {},
      setAttribute: function () {},
      getAttribute: function () { return null; }
    };
  },
  querySelectorAll: function () { return []; }
};
"""
        + source
        + "\nconsole.log('script-ok');\n",
        encoding="utf-8",
    )
    proc = subprocess.run([node, str(runner)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "script-ok" in proc.stdout
