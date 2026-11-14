"""Pro processors through pedalboard: Airwindows Consolidated (VST3; MIT code, GPL-3 build, airwindows.com) for air,
de-essing and console colour. They beat our own exciter / de-esser / saturation in the owner's blind A/B (2026-11-13).
Optional: start.ps1 installs the plugin into plugins/; without it fixer keeps its own DSP for those steps."""
import functools
import os
import re
import threading

import numpy as np
import pedalboard as pb

SR = 44100
_BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins", "Airwindows Consolidated.vst3")
_INNER = os.path.join(_BUNDLE, "Contents", "x86_64-win", "Airwindows Consolidated.vst3")   # Windows loads the inner DLL
PATH = _INNER if os.path.isfile(_INNER) else _BUNDLE
_LEVEL = {"bypass": 0.0, "dry_wet": 1.0, "mono_behaviour": 0.0}
_LOCK = threading.Lock()          # fixes run in threads; load and run one plugin instance at a time


@functools.cache
def available():
    try:
        return os.path.exists(PATH) and _switch(pb.load_plugin(PATH), "Air3") == "Air3"
    except Exception as e:       # a broken install must not break the fix: fall back to our own DSP
        print(f"Airwindows unavailable, using built-in DSP: {e}")
        return False


def airwindows(name, mono, **knobs):
    """Airwindows effect `name` on a mono voice, with every knob set (values carry over between effects otherwise),
    level-matched back to the input so the chain's gain staging stays put."""
    with _LOCK:
        p = pb.load_plugin(PATH)
        assert _switch(p, name) == name, name
        unknown = set(knobs) - set(p.parameters)
        assert not unknown, (name, unknown)
        for k, v in p.parameters.items():
            if k in knobs:
                v.raw_value = float(knobs[k])
            elif k in _LEVEL:
                v.raw_value = _LEVEL[k]
            elif k not in ("input_level", "output_level"):
                v.raw_value = 0.5
        z = p(np.stack([mono, mono]).astype(np.float32), SR).mean(0)
    return z * np.sqrt(np.mean(mono ** 2) / (np.mean(z ** 2) + 1e-12))


# ---- picking the effect: Consolidated hosts every Airwindows effect; the choice lives in its JUCE state ----
_B64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"   # JUCE MemoryBlock base64 alphabet


def _jdec(s):
    size, data = s.split(".", 1)
    size, out, pos = int(size), bytearray(int(size)), 0
    for ch in data:
        v = _B64.index(ch)
        for b in range(6):                       # JUCE setBitRange: little-endian bit order
            if pos >= size * 8:
                break
            if v >> b & 1:
                out[pos >> 3] |= 1 << (pos & 7)
            pos += 1
    return bytes(out)


def _jenc(raw):
    bits, s = len(raw) * 8, []
    for pos in range(0, bits, 6):
        v = 0
        for b in range(6):
            p = pos + b
            if p < bits and raw[p >> 3] >> (p & 7) & 1:
                v |= 1 << b
        s.append(_B64[v])
    return f"{len(raw)}." + "".join(s)


def _component(state):
    return _jdec(re.search(rb"<IComponent>(.*?)</IComponent>", state).group(1).decode())


def _switch(plugin, name):
    """Switch the plugin to Airwindows effect `name`; returns the effect it now runs."""
    st = plugin.raw_state
    raw = _component(st)
    xml_end = raw.index(b"/>") + 2
    xml = re.sub(r'currentProcessorName="[^"]*"', f'currentProcessorName="{name}"', raw[8:xml_end].decode()).encode()
    new_raw = raw[:4] + (len(xml) + 1).to_bytes(4, "little") + xml + raw[xml_end:]   # NUL + JUCE private data kept
    outer = re.sub(rb"<IComponent>.*?</IComponent>", b"<IComponent>" + _jenc(new_raw).encode() + b"</IComponent>",
                   st[8:].rstrip(b"\x00"))
    plugin.raw_state = st[:4] + len(outer).to_bytes(4, "little") + outer + b"\x00"
    return re.search(r'currentProcessorName="([^"]*)"', _component(plugin.raw_state).decode("latin1")).group(1)
