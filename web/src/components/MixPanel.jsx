import Knob from "./Knob.jsx";

const pct = (v) => `${Math.round(v * 100)}%`;
const signed = (v) => (Math.round(v * 100) === 0 ? "0" : `${v > 0 ? "+" : ""}${Math.round(v * 100)}`);
const KNOBS = [
  { id: "mix", label: "Mix", format: pct, hint: "How much of our studio sound you hear" },
  { id: "reverb", label: "Reverb", format: pct, hint: "The room around your voice" },
  { id: "delay", label: "Echo", format: pct, hint: "Repeats, left and right" },
  { id: "width", label: "Width", format: pct, hint: "A double that sounds bigger" },
  { id: "brightness", label: "Brightness", format: signed, min: -1, hint: "Darker or crisper" },
  { id: "warmth", label: "Warmth", format: signed, min: -1, hint: "Thinner or fuller" },
];
const STYLES = [
  { id: "reverb_style", label: "Reverb", options: [["room", "Room"], ["plate", "Plate"], ["hall", "Hall"]] },
  { id: "delay_style", label: "Echo", options: [["slap", "Slap"], ["eighth", "1/8"], ["quarter", "1/4"]] },
];

/** The mix rack: every control changes the sound you're hearing instantly (mixed live in the browser). */
export default function MixPanel({ settings, defaults, ready, onChange, onReset }) {
  if (!settings) return null;
  return (
    <div className="rack mt-4 rounded-2xl p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-semibold tracking-tight" style={{ fontStretch: "108%" }}>Mix rack</div>
          <div className="text-xs text-mist">Turn a knob while it plays. Double-click a knob to reset it.</div>
        </div>
        <span className="flex items-center gap-2 text-xs text-mist">
          {ready ? "Live" : "Loading…"}<span className="led" data-on={ready} />
        </span>
      </div>

      <div className={`mt-4 grid grid-cols-3 gap-x-2 gap-y-4 transition ${ready ? "" : "pointer-events-none opacity-40"}`}>
        {KNOBS.map((k) => (
          <div key={k.id} className="flex flex-col items-center" title={k.hint}>
            <Knob label={k.label} value={settings[k.id]} min={k.min ?? 0} max={1} def={defaults?.[k.id] ?? 0}
              format={k.format} onChange={(v) => onChange({ [k.id]: v })} />
          </div>
        ))}
      </div>

      <div className={`mt-4 grid grid-cols-2 gap-2 ${ready ? "" : "pointer-events-none opacity-40"}`}>
        {STYLES.map((st) => (
          <div key={st.id}>
            <div className="mb-1 text-[11px] text-mist">{st.label} type</div>
            <div className="grid grid-cols-3 gap-0.5 rounded-lg bg-fg/[.06] p-0.5" role="radiogroup" aria-label={`${st.label} type`}>
              {st.options.map(([v, l]) => (
                <button key={v} role="radio" aria-checked={settings[st.id] === v} onClick={() => onChange({ [st.id]: v })}
                  className={`rounded-md py-1.5 text-xs font-semibold transition active:scale-95 ${settings[st.id] === v ? "bg-ember text-white" : "text-mist hover:text-fg"}`}>
                  {l}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 text-right">
        <button onClick={onReset} className="rounded-lg px-2 py-1 text-xs text-mist transition hover:bg-fg/10 hover:text-fg">Back to our mix</button>
      </div>
    </div>
  );
}
