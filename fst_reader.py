"""Decode an FL Studio mixer-track preset (.fst) into a plain JSON effect chain.

Format: "FLhd" header + "FLdt" event stream (same as .flp). Each event = 1-byte id,
then 1/2/4 bytes (id <64 / <128 / <192) or a varint length + bytes (id >=192).
  201 = plugin name (UTF-16)      213 = plugin state blob (per-plugin layout)
  225 = mixer params: 12-byte records (u32 0, u32 id, i32 value); per slot
        id&0xff==0 -> slot enabled, ==1 -> slot mix (12800 = 100%)

Every decoded value carries "confidence": "high" = proven from the data itself
(defaults vs. changed values, known ranges); "check" = scale assumed, confirm in FL.

Usage:  python fst_reader.py preset.fst [out.json]
"""
import json
import math
import struct
import sys

# ---------- raw event stream ----------

def read_events(data: bytes):
    if data[:4] != b"FLhd" or data[14:18] != b"FLdt":
        raise ValueError("not an FL Studio preset (missing FLhd/FLdt)")
    p, end = 22, 22 + struct.unpack("<I", data[18:22])[0]
    while p < end:
        eid = data[p]; p += 1
        if eid < 64:
            yield eid, data[p]; p += 1
        elif eid < 128:
            yield eid, struct.unpack("<H", data[p:p + 2])[0]; p += 2
        elif eid < 192:
            yield eid, struct.unpack("<I", data[p:p + 4])[0]; p += 4
        else:
            n = s = 0
            while True:
                b = data[p]; p += 1
                n |= (b & 0x7F) << s; s += 7
                if b < 128:
                    break
            yield eid, data[p:p + n]; p += n


def ints(blob: bytes):
    return list(struct.unpack("<%di" % (len(blob) // 4), blob[: len(blob) // 4 * 4]))

# ---------- per-plugin decoders ----------

def db(lin):
    return round(20 * math.log10(lin), 2) if lin > 0 else -120.0

# Parametric EQ 2: version 8; 7 bands stored column-wise:
#   [1..7] gain (0.01 dB, +-1800 = +-18 dB)   [8..14] freq (0..65535, log scale)
#   [15..21] width (0..65535)                 [22..28] shape (manual order below)
# Proof: a fresh PEQ2 stores defaults shape 5,6,6,6,6,6,7 = LowShelf, 5x Peak, HighShelf,
# which is FL's documented default; ints [44..64] hold that untouched default copy.
PEQ2_SHAPES = {0: "off", 1: "lowpass", 2: "bandpass", 3: "highpass", 4: "notch",
               5: "lowshelf", 6: "peak", 7: "highshelf"}
PEQ_FMIN, PEQ_FMAX = 20.0, 20000.0          # CHECK: assumed 20 Hz-20 kHz log scale


def peq_freq(x):
    return round(PEQ_FMIN * (PEQ_FMAX / PEQ_FMIN) ** (x / 65536), 1)


def peq_bw_octaves(x):
    # CHECK: assumed linear 0..~9 octaves; FL default 25412 -> ~1.4 oct (Q ~1.0)
    return round(max(0.05, x / 65536 * 3.6), 3)


def decode_peq2(v):
    bands = []
    for b in range(7):
        shape = PEQ2_SHAPES.get(v[22 + b], "unknown")
        gain = v[1 + b] / 100
        used = shape in ("lowpass", "highpass", "bandpass", "notch") or abs(gain) > 0.01
        bands.append({"band": b + 1, "shape": shape, "gain_db": gain,
                      "freq_hz": peq_freq(v[8 + b]), "bw_oct": peq_bw_octaves(v[15 + b]),
                      "active": used,
                      "raw": {"gain": v[1 + b], "freq": v[8 + b], "width": v[15 + b]}})
    return {"bands": bands, "confidence": {"shape": "high", "gain_db": "high",
                                           "freq_hz": "check", "bw_oct": "check"}}


# Fruity Limiter: version 7. Levels are linear amplitude x1000 (1000 = 0 dB).
# ints[1..18] = live settings, ints[19..36] = untouched default copy. Diffing the two shows
# the ONLY knob changed is index 3 (ceiling 1000 -> 854). Comp threshold (idx 9) = 1000 =
# max = compressor OFF; noise gain (idx 16) = 1000 = 100% = gate OFF (manual defaults).
def decode_limiter(v):
    live, dflt = v[1:19], v[19:37]
    changed = [i + 1 for i in range(18) if live[i] != dflt[i]]
    return {
        "input_gain_db": db(v[1] / 1000), "saturation_db": db(v[2] / 1000),
        "ceiling_db": db(v[3] / 1000),
        "attack_raw": v[4], "release_raw": v[6], "sustain_raw": v[8],
        "compressor_on": v[9] < 1000, "gate_on": v[16] < 1000,
        "changed_from_default": changed,
        "confidence": {"ceiling_db": "high", "comp/gate off": "high",
                       "attack/release": "defaults (FL ~ fast lookahead limiter)"},
    }


# Soundgoodizer: layout from PyFLP (u32 ?, u32 mode A..D, u32 amount 0..1000)
def decode_soundgoodizer(v):
    return {"mode": "ABCD"[v[1]], "amount": v[2] / 1000, "confidence": "high"}


# Fruity Reeverb 2: version 10001 + 15 values. Order assumed from the manual's control
# order; units are FL's internal ones -> CHECK against the plugin window.
# Levels look like a 0..128 scale: dry 128 (=100%, FL default), ER 39 (~30%), wet 36 (~28%).
REEVERB_KEYS = ["high_cut", "low_cut", "predelay", "size", "diffusion", "mod",
                "mod_speed", "bass_mult", "crossover", "unk10", "dry", "er", "wet",
                "unk14", "sep"]


def decode_reeverb2(v):
    raw = dict(zip(REEVERB_KEYS, v[1:16]))
    return {"raw": raw, "confidence": "check (order/units unverified)"}


# Fruity Phaser: version 1 + 9 values, order assumed from the manual.
PHASER_KEYS = ["sweep_freq", "min_depth", "max_depth", "freq_range", "stereo",
               "stages", "feedback", "dry_wet", "out_gain"]


def decode_phaser(v):
    return {"raw": dict(zip(PHASER_KEYS, v[1:10])), "confidence": "check"}


# Pitcher (FL auto-tune): "SSLF" chunk of float32. Key/scale = 12 note on/off bytes at the
# end (C..B). This file: C D E F G A B on = C major / A minor -> "high" confidence.
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def decode_pitcher(v):
    blob = struct.pack("<%di" % len(v), *v)
    f = struct.unpack("<%df" % len(v), blob)
    mask = blob[-16:-4]
    on = [NOTES[i] for i in range(12) if mask[i]]
    return {"speed": round(f[3], 3), "amount": round(f[4], 3), "fine": round(f[5], 3),
            "gender": round(f[6], 3), "scale_notes": on,
            "confidence": {"scale_notes": "high", "speed/gender": "check"}}


# Fruity Delay 3: ints. Time (idx 5) in ticks at 96 PPQ (192 = 2 beats? -> CHECK);
# feedback / wet assumed /10000.
def decode_delay3(v):
    return {"time_ticks": v[5], "feedback": round(v[15] / 10000, 3),
            "wet": round(v[17] / 10000, 3), "raw": v, "confidence": "check"}


DECODERS = {"Fruity Parametric EQ 2": ("peq2", decode_peq2),
            "Fruity Limiter": ("limiter", decode_limiter),
            "Soundgoodizer": ("soundgoodizer", decode_soundgoodizer),
            "Fruity Reeverb 2": ("reeverb2", decode_reeverb2),
            "Fruity Phaser": ("phaser", decode_phaser),
            "Pitcher": ("pitcher", decode_pitcher),
            "Fruity Delay 3": ("delay3", decode_delay3)}

# ---------- whole preset ----------

def decode(path):
    data = open(path, "rb").read()
    chain, name, version, mixer = [], None, None, {}
    for eid, val in read_events(data):
        if eid == 199:
            version = val.decode("utf-16le", "replace").strip("\0")
        elif eid == 201:
            name = val.decode("utf-16le").strip("\0")
        elif eid == 213 and name:
            kind, fn = DECODERS.get(name, ("unknown", lambda v: {"raw": v}))
            chain.append({"slot": len(chain), "plugin": name, "type": kind,
                          "params": fn(ints(val)), "raw_ints": ints(val)})
            name = None
        elif eid == 225:
            for i in range(0, len(val) - 11, 12):
                _, pid, value = struct.unpack("<IIi", val[i:i + 12])
                mixer[pid] = value
    # slot enable / mix from mixer params: slot n -> id base + (n << 16)
    base = min(mixer) if mixer else 0
    for s in chain:
        en = mixer.get(base + (s["slot"] << 16))
        mix = mixer.get(base + (s["slot"] << 16) + 1)
        s["enabled"] = bool(en) if en is not None else True
        s["mix"] = round(mix / 12800, 4) if mix is not None else 1.0
    track = {"volume": mixer.get(base + 0xC0, 12800) / 12800,
             "pan": mixer.get(base + 0xC1, 0)}
    return {"source": path.split("/")[-1], "fl_version": version, "track": track,
            "chain": chain}


if __name__ == "__main__":
    out = decode(sys.argv[1])
    text = json.dumps(out, indent=2)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(text)
    for s in out["chain"]:
        p = dict(s["params"])
        print(f"[{s['slot']}] {s['plugin']}  enabled={s['enabled']} mix={s['mix']:.0%}")
        if s["type"] == "peq2":
            for b in p["bands"]:
                if b["active"]:
                    print(f"     band {b['band']}: {b['shape']:9s} {b['freq_hz']:>8} Hz "
                          f"{b['gain_db']:+6.2f} dB  bw {b['bw_oct']} oct")
        else:
            p.pop("confidence", None)
            print("    ", json.dumps(p))
    print("track:", out["track"])
