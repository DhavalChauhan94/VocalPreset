// The three vocal sounds (mirrors fixer.STYLES; autotune = the level we switch on when you pick it).
export const VOCAL_STYLES = [
  { id: "rap", label: "Rap", tag: "Dry & punchy", autotune: "off",
    tip: "Bone-dry and upfront, the way mainstream rap vocals hit: heavy compression, grit and no reverb wash. Most rap stays un-tuned. Turn on Light auto-tune to just centre the pitch." },
  { id: "melodic", label: "Melodic rap", tag: "Wavy & spacey", autotune: "heavy",
    tip: "Hard-tuned and floating: heavy auto-tune, quarter-note echoes, a long dark hall and a wobbling double. Auto-tune is set to Heavy." },
  { id: "pop", label: "Singer / Pop", tag: "Smooth & sung", autotune: "medium",
    tip: "Polished and sung: smooth compression, a bright plate and gentle echo. Made for pop, R&B and lo-fi. Auto-tune is set to Medium." },
];

// a sine sampled every 2 units across 150, period 50: sliding it 50 left loops seamlessly
const wave = (amp, y0 = 20) =>
  Array.from({ length: 76 }, (_, i) => `${i ? "L" : "M"}${i * 2} ${(y0 + amp * Math.sin((i * 2 * Math.PI) / 25)).toFixed(2)}`).join(" ");
const BARS = [0.55, 0.9, 0.7, 1, 0.6, 0.95, 0.75, 0.85, 0.5];

function Visual({ id }) {
  if (id === "rap")       // transients that slam and stop: no tails
    return BARS.map((h, i) => <rect key={i} className="sp-bar" x={6 + i * 10.5} y="4" width="6" height="32" rx="1" style={{ "--h": h, "--i": i }} />);
  if (id === "melodic")   // the line plus fading echoes, all wobbling
    return (
      <g className="sp-wobble">
        {[0.12, 0.25, 0.45, 1].map((o, i) => (   // the offset lives on a <g>: the CSS slide would replace it on the path
          <g key={i} transform={`translate(${(3 - i) * 7} 0)`}>
            <path className="sp-wave" d={wave(9 - i)} strokeOpacity={o} fill="none" strokeWidth={i === 3 ? 2.2 : 1.6}
              style={{ animationDuration: "2.6s" }} />
          </g>
        ))}
      </g>
    );
  return (                // one smooth sung line, with a little air sparkling on top
    <>
      <path className="sp-wave" d={wave(8, 23)} fill="none" strokeWidth="2.6" style={{ animationDuration: "3.6s" }} />
      {[[18, 8], [44, 5], [67, 9], [88, 6]].map(([x, y], i) => <circle key={i} className="sp-spark" cx={x} cy={y} r="1.6" style={{ "--i": i }} />)}
    </>
  );
}

/** Pick the sound before the fix: each card moves the way that vocal sounds (on hover, or once picked). */
export default function StylePicker({ value, onChange }) {
  const picked = VOCAL_STYLES.find((s) => s.id === value);
  return (
    <div className="pt-1">
      <div className="flex items-center gap-2 px-1 pb-2 text-sm font-medium text-mist">
        <span className="led" data-on={!!picked} style={{ width: 5, height: 5 }} />Pick your sound
      </div>
      <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Vocal sound">
        {VOCAL_STYLES.map((s) => (
          <button key={s.id} role="radio" aria-checked={value === s.id} onClick={() => onChange(s.id)}
            className="sp slot group rounded-2xl px-2.5 pt-2 pb-2.5 text-left transition duration-200 hover:-translate-y-0.5 active:scale-[.97]">
            <svg viewBox="0 0 100 40" className="h-10 w-full" aria-hidden="true"><Visual id={s.id} /></svg>
            <div className="mt-1.5 text-sm leading-tight font-bold tracking-tight" style={{ fontStretch: "108%" }}>{s.label}</div>
            <div className="text-[11px] text-mist">{s.tag}</div>
          </button>
        ))}
      </div>
      {picked && <p key={picked.id} className="chip-in px-1 pt-2 text-xs leading-relaxed text-mist">{picked.tip}</p>}
    </div>
  );
}
