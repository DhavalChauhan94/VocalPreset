import { useEffect, useRef, useState } from "react";

const SLIDERS = [
  { id: "mix", label: "Mix", hint: "How much of our studio processing you hear. 0% is your own cleaned-up voice.", min: 0 },
  { id: "reverb", label: "Reverb", hint: "The room around your voice. More = bigger, dreamier.", min: 0 },
  { id: "delay", label: "Echo", hint: "Repeats the ends of your words, left and right.", min: 0 },
  { id: "width", label: "Width", hint: "A subtle double that makes the vocal sound wider and richer.", min: 0 },
  { id: "brightness", label: "Brightness", hint: "Darker and smoother, or brighter and crisper.", min: -1 },
  { id: "warmth", label: "Warmth", hint: "Thinner, or fuller with tape-style warmth.", min: -1 },
];
const STYLES = {
  reverb_style: { label: "Reverb type", options: [["room", "Room"], ["plate", "Plate"], ["hall", "Hall"]] },
  delay_style: { label: "Echo timing", options: [["slap", "Slap"], ["eighth", "1/8"], ["quarter", "1/4"]] },
};
const pct = (v, min) => (min < 0 ? `${v > 0 ? "+" : ""}${Math.round(v * 100)}` : `${Math.round(v * 100)}%`);

/** Post-mix tweaks. Sliders move instantly; the server re-renders ~0.5 s after you let go. */
export default function MixPanel({ settings, busy, error, onChange, onReset }) {
  const [local, setLocal] = useState(settings);
  const timer = useRef(null), pending = useRef({});
  useEffect(() => { if (!Object.keys(pending.current).length) setLocal(settings); }, [settings]);
  const send = (patch, now) => {
    setLocal((s) => ({ ...s, ...patch }));
    pending.current = { ...pending.current, ...patch };   // several quick moves go out together
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { const p = pending.current; pending.current = {}; onChange(p); }, now ? 0 : 450);
  };
  if (!local) return null;
  return (
    <div className="slot mt-4 rounded-2xl p-4">
      <div className="flex items-center justify-between">
        <div className="font-semibold">Shape your mix</div>
        <span className="flex items-center gap-2 text-xs text-mist">
          {busy ? "Updating…" : "Live"}<span className="led" data-on={!busy} />
        </span>
      </div>
      <div className="mt-3 space-y-3.5">
        {SLIDERS.map((sl) => (
          <label key={sl.id} className="block">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium">{sl.label}</span>
              <span className="font-mono text-xs text-mist tabular-nums">{pct(local[sl.id], sl.min)}</span>
            </div>
            <input type="range" min={sl.min} max={1} step={0.01} value={local[sl.id]}
              onChange={(e) => send({ [sl.id]: Number(e.target.value) })}
              className="mt-1 w-full" aria-label={sl.label} />
            <div className="text-xs text-mist">{sl.hint}</div>
          </label>
        ))}
        {Object.entries(STYLES).map(([key, st]) => (
          <div key={key}>
            <div className="text-sm font-medium">{st.label}</div>
            <div className="mt-1 grid grid-cols-3 gap-1 rounded-xl bg-fg/[.05] p-1" role="radiogroup" aria-label={st.label}>
              {st.options.map(([v, l]) => (
                <button key={v} role="radio" aria-checked={local[key] === v} onClick={() => send({ [key]: v }, true)}
                  className={`rounded-lg py-1.5 text-sm font-semibold transition active:scale-95 ${local[key] === v ? "bg-ember text-white" : "text-mist hover:text-fg"}`}>
                  {l}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between">
        <span className="text-xs text-ember">{error}</span>
        <button onClick={onReset} className="rounded-lg px-2 py-1 text-xs text-mist transition hover:bg-fg/10 hover:text-fg">Back to our mix</button>
      </div>
    </div>
  );
}
