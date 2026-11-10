"""Raw-take analysis with Phantom (FadeLab, https://fadelab.net), called as a stdio MCP server.

Phantom runs locally and is free (AGPL-3.0). We call it as a separate process and never copy its code.
It doesn't install on Windows (no Essentia wheel), so on Windows it runs inside WSL. Set it up with:
  wsl:  PHANTOM_NO_TELEMETRY=1 uv tool install phantom-audio --python 3.13
Env vars:
  PHANTOM_CMD      server command (default: phantom-mcp via WSL on Windows, phantom-mcp elsewhere)
  PHANTOM_TIMEOUT  seconds (default 60)
Usage: python analysis.py vocal.m4a   -> prints the full_diagnostic JSON
"""
import asyncio
import json
import os
import shlex
import subprocess
import sys
import tempfile

import engine

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_DEFAULT = (["wsl.exe", "-e", "bash", "-lc", "PHANTOM_QUIET=1 FASTMCP_SHOW_SERVER_BANNER=false FASTMCP_CHECK_FOR_UPDATES=off FASTMCP_LOG_LEVEL=WARNING exec phantom-mcp"]
            if os.name == "nt" else ["phantom-mcp"])


def _cmd():
    c = os.environ.get("PHANTOM_CMD")
    return shlex.split(c) if c else _DEFAULT


def _wsl_path(p):
    """C:\\Users\\x\\a.wav -> /mnt/c/Users/x/a.wav (WSL mounts Windows drives under /mnt)."""
    p = os.path.abspath(p)
    return f"/mnt/{p[0].lower()}{p[2:].replace(os.sep, '/')}"


async def _call(path, timeout):
    cmd = _cmd()
    params = StdioServerParameters(command=cmd[0], args=cmd[1:])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await asyncio.wait_for(s.initialize(), timeout)
        res = await asyncio.wait_for(s.call_tool("full_diagnostic", {"file_path": path}), timeout)
    text = "".join(getattr(c, "text", "") for c in res.content)
    if res.is_error:
        raise RuntimeError(f"Phantom: {text[:300]}")
    data = res.structured_content or json.loads(text)
    return data.get("result", data) if len(data) == 1 else data   # FastMCP may wrap dicts as {"result": ...}


def analyze(path, timeout=None):
    """full_diagnostic of any upload. Phantom decodes with soundfile, which can't read WhatsApp
    .mpeg, m4a or video, so we hand it a lossless float WAV of the take (same rate and channels)."""
    timeout = timeout or float(os.environ.get("PHANTOM_TIMEOUT", 60))
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        engine.run_ffmpeg([*engine.ffmpeg_input(path), "-vn", "-c:a", "pcm_f32le", wav])
        target = _wsl_path(wav) if _cmd()[0].lower().startswith("wsl") else wav
        try:
            return asyncio.run(asyncio.wait_for(_call(target, timeout), timeout + 15))
        except BaseExceptionGroup as g:   # anyio wraps the real error; surface it
            while isinstance(g, BaseExceptionGroup):
                g = g.exceptions[0]
            raise RuntimeError(f"Phantom not reachable ({type(g).__name__}: {g}). "
                               "Is it installed in WSL? See SETUP.md") from g
    finally:
        os.unlink(wav)


if __name__ == "__main__":
    assert _wsl_path(r"C:\Users\x\a b.wav") == "/mnt/c/Users/x/a b.wav" or os.name != "nt"
    print(json.dumps(analyze(sys.argv[1]), indent=2))
