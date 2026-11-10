import { KeyPicker, KEYS } from "./Pickers.jsx";
import { Dropzone } from "./Parts.jsx";

const LEVELS = [
  { id: "light", label: "Light", hint: "Fixes small slips, still sounds natural", amount: 0.6, glide: 0.75 },
  { id: "medium", label: "Medium", hint: "The clean, polished pop sound", amount: 0.85, glide: 0.4 },
  { id: "heavy", label: "Heavy", hint: "The robotic hip-hop effect", amount: 1, glide: 0 },
];
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const SCALE = { major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10] };
const KEY_OPTIONS = KEYS.filter((k) => k.id.includes(" "));   // the 24 real keys (no "auto"/"preset")

// A made-up sung line drifting around 5 note lanes (y = 0..4), sampled left to right.
const N = 64;
const SUNG = Array.from({ length: N }, (_, i) => {
  const t = i / (N - 1);
  return 2 + 1.6 * Math.sin(t * 7.2) + 0.35 * Math.sin(t * 31) + 0.2 * Math.sin(t * 53);
});
const Y = (lane) => 10 + lane * 14;   // svg y of a lane

function tunedPath(level) {
  if (!level) return null;
  let cur = SUNG[0];
  return SUNG.map((v, i) => {
    const target = v + level.amount * (Math.round(v) - v);   // pull toward the nearest note
    cur = level.glide ? cur + (target - cur) * (1 - level.glide) : target;   // glide = slower, natural slides
    return `${i ? "L" : "M"}${(i / (N - 1)) * 300} ${Y(cur)}`;
  }).join(" ");
}
const SUNG_PATH = SUNG.map((v, i) => `${i ? "L" : "M"}${(i / (N - 1)) * 300} ${Y(v)}`).join(" ");

function PitchDemo({ level }) {
  const tuned = tunedPath(level);
  return (
    <svg viewBox="0 0 300 76" className="h-20 w-full" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((l) => <line key={l} x1="0" x2="300" y1={Y(l)} y2={Y(l)} stroke="var(--line)" strokeDasharray="2 4" />)}
      <path d={SUNG_PATH} fill="none" stroke="var(--mist)" strokeOpacity={tuned ? 0.35 : 0.9} strokeWidth="2" className="transition-[stroke-opacity] duration-500" />
      {tuned && <path d={tuned} fill="none" stroke="var(--ember)" strokeWidth="2.5" strokeLinejoin="round"
        className="tune-path" style={{ filter: "drop-shadow(0 0 4px var(--ember))" }} />}
    </svg>
  );
}

function Piano({ keyString, loading }) {
  const [root, scale] = (keyString || "C major").split(" ");
  const pcs = SCALE[scale]?.map((s) => (NOTE_NAMES.indexOf(root) + s) % 12) ?? [];
  const whites = [0, 2, 4, 5, 7, 9, 11];
  const lit = (pc) => !loading && pcs.includes(pc);
  const order = (pc) => pcs.indexOf(pc);
  return (
    <div className="relative mt-3 h-16 select-none" aria-hidden="true">
      <div className="flex h-full gap-0.5">
        {whites.map((pc) => (
          <div key={pc} className={`piano-key flex-1 rounded-b-md border border-line ${loading ? "shimmer" : ""}`}
            data-on={lit(pc)} style={{ "--i": order(pc) }} />
        ))}
      </div>
      {[1, 3, 6, 8, 10].map((pc) => {
        const left = { 1: 1, 3: 2, 6: 4, 8: 5, 10: 6 }[pc];
        return <div key={pc} className="piano-key piano-black absolute top-0 h-[62%] w-[8%] -translate-x-1/2 rounded-b-md"
          data-on={lit(pc)} style={{ left: `${(left / 7) * 100}%`, "--i": order(pc) }} />;
      })}
    </div>
  );
}

/** Auto-tune toggle + strength, with the detected key explained on a piano. */
// conventional spelling for a sharp-spelled key ("A# major" -> "Bb major")
const FLAT = { major: { "C#": "Db", "D#": "Eb", "G#": "Ab", "A#": "Bb" }, minor: { "D#": "Eb", "A#": "Bb" } };
const spell = (k) => { const [r, m] = k.split(" "); return `${FLAT[m]?.[r] ?? r} ${m}`; };

export default function Autotune({ on, onToggle, level, onLevel, keyInfo, keyLoading, keyError, chosenKey, onKey, beat, onBeat }) {
  const lv = LEVELS.find((l) => l.id === level) ?? LEVELS[1];
  const idx = LEVELS.indexOf(lv);
  const shownKey = chosenKey || keyInfo?.key_string;
  const display = keyInfo && chosenKey === keyInfo.key_string ? keyInfo.display_key : shownKey;
  return (
    <div className="slot rounded-2xl p-4">
      <button type="button" role="switch" aria-checked={on} onClick={() => onToggle(!on)}
        className="flex w-full items-center justify-between gap-3 text-left">
        <div>
          <div className="font-semibold">Auto-tune</div>
          <div className="text-sm text-mist">Pulls off-key notes onto the right notes of your song's key.</div>
        </div>
        <span className={`relative h-7 w-12 shrink-0 rounded-full transition-colors duration-300 ${on ? "bg-ember" : "bg-fg/15"}`}>
          <span className={`absolute top-1 size-5 rounded-full bg-white shadow transition-transform duration-300 ease-[cubic-bezier(.3,1.4,.5,1)] ${on ? "translate-x-6" : "translate-x-1"}`} />
        </span>
      </button>

      <PitchDemo level={on ? lv : null} />
      <div className="-mt-1 flex justify-between text-[11px] text-mist">
        <span><span className="mr-1 inline-block h-0.5 w-3 bg-mist align-middle" />how you sang it</span>
        {on && <span className="chip-in"><span className="mr-1 inline-block h-0.5 w-3 bg-ember align-middle" />after auto-tune</span>}
      </div>

      {on && (
        <div className="chip-in mt-3 space-y-3">
          <div className="relative grid grid-cols-3 rounded-xl bg-fg/[.05] p-1" role="radiogroup" aria-label="Auto-tune strength">
            <div className="absolute inset-y-1 left-1 w-[calc((100%-0.5rem)/3)] rounded-lg bg-gradient-to-b from-[var(--ember-hi)] to-ember shadow-[0_6px_18px_-6px_color-mix(in_srgb,var(--ember)_70%,transparent)] transition-transform duration-300 ease-[cubic-bezier(.3,1.3,.5,1)]"
              style={{ transform: `translateX(${idx * 100}%)` }} />
            {LEVELS.map((l) => (
              <button key={l.id} role="radio" aria-checked={l.id === lv.id} onClick={() => onLevel(l.id)}
                className={`relative z-10 rounded-lg py-2 text-sm font-semibold transition active:scale-95 ${l.id === lv.id ? "text-white" : "text-mist hover:text-fg"}`}>
                {l.label}
              </button>
            ))}
          </div>
          <p key={lv.id} className="chip-in text-sm text-mist">{lv.hint}</p>

          <div className="rounded-xl bg-fg/[.04] p-3">
            {keyLoading ? <div className="text-sm text-mist">Listening for your song's key…</div>
              : keyError ? <div className="text-sm text-ember">{keyError}</div>
                : keyInfo && (
                  <div className="chip-in">
                    <div className="flex items-center gap-2 text-sm text-mist">Your take is in
                      {keyInfo.source === "beat" && <span className="rounded-full bg-ember/15 px-2 py-0.5 text-[11px] font-medium text-ember">from your beat</span>}
                    </div>
                    <div className="text-xl font-bold tracking-tight" style={{ fontStretch: "108%" }}>{display}</div>
                    <div className="text-xs text-mist">
                      Auto-tune will only use these {SCALE[(shownKey || "").split(" ")[1]]?.length ?? 7} notes, lit up below.
                    </div>
                  </div>
                )}
            <Piano keyString={shownKey} loading={keyLoading} />
            {keyInfo && !keyLoading && (
              <div className="mt-3">
                {keyInfo.low_confidence && (
                  <p className="mb-2 text-sm"><span className="font-medium text-amber">Not 100% sure.</span>{" "}
                    <span className="text-mist">{keyInfo.warnings?.[0] ?? "If you know the key, pick it here."}</span></p>
                )}
                {keyInfo.alternatives?.length > 1 && (
                  <div className="mb-3">
                    <div className="mb-1 text-xs text-mist">Closest keys, tap to switch:</div>
                    <div className="flex flex-wrap gap-1.5">
                      {keyInfo.alternatives.slice(0, 4).map((k) => (
                        <button key={k} onClick={() => onKey(k)} aria-pressed={k === shownKey}
                          className={`chip-in rounded-full px-3 py-1 text-sm font-semibold transition active:scale-95 ${k === shownKey ? "bg-ember text-white" : "bg-fg/[.07] text-fg hover:bg-fg/[.12]"}`}>
                          {spell(k)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <KeyPicker value={shownKey} onChange={onKey} keys={KEY_OPTIONS} hint="Or pick any key" />
                {keyInfo.source !== "beat" && onBeat && (
                  <div className="mt-3">
                    <Dropzone compact label="Add your beat for the exact key" hint="We read the key from its chords (not mixed in)"
                      file={beat} onFile={onBeat} accent="violet" optional />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
