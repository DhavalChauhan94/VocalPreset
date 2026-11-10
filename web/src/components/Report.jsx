import { useEffect, useState } from "react";

// Phantom problem types -> words a non-producer understands.
const FINDINGS = {
  clipping: ["Distortion (clipping)", "The take was too loud for the mic or interface, so the loudest moments got chopped off and crackle."],
  inter_sample_peak: ["Peaks over the limit", "Some peaks would crackle on phones and streaming apps."],
  hum: ["Electrical hum", "A low, steady buzz, often a charger, fridge or cable near the mic."],
  noise_floor: ["Background noise", "Hiss or room noise you can hear between your words."],
  snr: ["Voice close to the noise", "Your voice isn't much louder than the background noise."],
  sibilance: ["Sharp S sounds", "'S', 'T' and 'SH' sounds stab out and hurt on headphones."],
  mud: ["Muddy, boxy tone", "Too much low-mid makes the voice sound like it's in a cardboard box."],
  harshness: ["Harsh, shouty tone", "Too much upper-mid makes the voice tiring to listen to."],
  resonant_peak: ["Ringing frequencies", "A few narrow tones ring out, usually from the room or the mic."],
  dc_offset: ["Off-centre signal", "The waveform sits slightly off-centre and wastes headroom. Easy fix."],
  lossy_codec: ["Heavily compressed file", "This came from a squashed format (like a voice note), so some detail is gone."],
  sample_rate_mismatch: ["Mixed sample rates", "Parts of the file don't match technically."],
};
const SEVERITY = { dealbreaker: ["Must fix", 4], significant: ["Noticeable", 3], moderate: ["Minor", 2], minor: ["Tiny", 1] };
const BANDS = [["31_hz", "31"], ["62_hz", "62"], ["125_hz", "125"], ["250_hz", "250"], ["500_hz", "500"],
  ["1000_hz", "1k"], ["2000_hz", "2k"], ["4000_hz", "4k"], ["8000_hz", "8k"], ["16000_hz", "16k"]];
const REGIONS = [["Bass", 3], ["Body", 2], ["Presence", 3], ["Air", 2]];   // label, number of bands

const verdict = (s) => (s >= 90 ? "Studio-ready" : s >= 75 ? "Nearly studio-ready" : s >= 50 ? "Getting there" : "Needs work");
const ringColor = (s) => (s >= 75 ? "#3ccf8e" : s >= 50 ? "var(--amber)" : "var(--ember)");
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Counts from `from` to `to` (ease-out), restarting whenever `to` changes. */
function useCount(to, from = 0, ms = 1200) {
  const [v, setV] = useState(from);
  useEffect(() => {
    if (to == null) return;
    if (reduced()) { setV(to); return; }
    let raf; const t0 = performance.now();
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      setV(Math.round(from + (to - from) * (1 - (1 - k) ** 3)));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, from, ms]);
  return v;
}

function ScoreRing({ before, after }) {
  const shown = useCount(after ?? before, after != null ? before : 0);
  const r = 52, c = 2 * Math.PI * r;
  return (
    <div className="flex items-center gap-5">
      <div className="relative size-36 shrink-0">
        <svg viewBox="0 0 120 120" className="size-full -rotate-90">
          <circle cx="60" cy="60" r={r} fill="none" stroke="var(--line)" strokeWidth="10" />
          <circle cx="60" cy="60" r={r} fill="none" stroke={ringColor(shown)} strokeWidth="10" strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={c * (1 - shown / 100)}
            style={{ filter: `drop-shadow(0 0 6px ${ringColor(shown)})` }} />
        </svg>
        <div className="absolute inset-0 grid place-items-center text-center">
          <div><div className="text-4xl font-extrabold tabular-nums" style={{ fontStretch: "110%" }}>{shown}</div>
            <div className="-mt-0.5 text-[11px] text-mist">out of 100</div></div>
        </div>
      </div>
      <div>
        <div className="text-sm text-mist">{after != null ? "Studio readiness, after the fix" : "Studio readiness"}</div>
        <div className="text-2xl font-bold tracking-tight">{verdict(shown)}</div>
        {after != null && (
          <div className="chip-in mt-1 text-sm text-mist">
            Was <span className="font-semibold text-fg">{before}</span>, now <span className="font-semibold text-fg">{after}</span>
            <span className="ml-1.5 font-semibold" style={{ color: ringColor(after) }}>{after >= before ? `+${after - before}` : after - before}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function Finding({ p, step, state, i }) {
  const [title, meaning] = FINDINGS[p.type] ?? [p.type.replace(/_/g, " "), p.message];
  const [sev, level] = SEVERITY[p.severity] ?? ["Note", 1];
  return (
    <div className={`chip-in slot rounded-2xl p-4 transition ${state === "fixed" ? "opacity-70" : ""}`} style={{ "--i": i }}>
      <div className="flex items-start justify-between gap-3">
        <div className={`font-semibold ${state === "fixed" ? "line-through decoration-2 decoration-[#3ccf8e]" : ""}`}>{title}</div>
        {state === "fixed" ? (
          <span className="flex shrink-0 items-center gap-1 text-xs font-semibold text-[#3ccf8e]">
            <svg viewBox="0 0 20 20" className="size-4"><path fill="currentColor" d="M16.7 5.3a1 1 0 0 1 0 1.4l-8 8a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L8 12.6l7.3-7.3a1 1 0 0 1 1.4 0Z" /></svg>Fixed
          </span>
        ) : (
          <span className="flex shrink-0 items-center gap-1.5 text-xs text-mist" title={p.message}>
            {state === "left" ? "Still there" : state === "softened" ? "Softened" : sev}
            <span className="flex gap-0.5">{[1, 2, 3, 4].map((n) => <span key={n} className="led" data-on={n <= level} style={{ width: 5, height: 5 }} />)}</span>
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-mist">{meaning}</p>
      {step && state === "open" && (
        <p className="mt-2 text-sm"><span className="font-medium text-ember">We'll fix it:</span> {step.why}</p>
      )}
      {state === "softened" && (
        <p className="mt-2 text-sm"><span className="font-medium text-amber">Softened, not removed.</span> The crackly peaks are
          smoothed, but distortion recorded into the take stays. Recording a little quieter will sound best.</p>
      )}
      {state === "left" && (
        <p className="mt-2 text-sm"><span className="font-medium text-amber">We reduced it,</span> but some is still there.
          {p.severity === "dealbreaker" ? " Re-recording will sound best." : ""}</p>
      )}
    </div>
  );
}

function Meter({ label, value, verdict: v, pos }) {
  return (
    <div className="slot rounded-2xl p-4">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm text-mist">{label}</span><span className="font-semibold tabular-nums">{value}</span>
      </div>
      <div className="relative mt-3 h-2 rounded-full bg-fg/10">
        <div className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-ember to-amber transition-[width] duration-1000 ease-out"
          style={{ width: `${Math.max(3, Math.min(100, pos * 100))}%` }} />
      </div>
      <div className="mt-2 text-xs text-mist">{v}</div>
    </div>
  );
}

function Tone({ bands }) {
  const vals = BANDS.map(([k]) => bands?.[k] ?? -90);
  const top = Math.max(...vals), floor = top - 60;
  const [grown, setGrown] = useState(false);
  useEffect(() => { const id = requestAnimationFrame(() => setGrown(true)); return () => cancelAnimationFrame(id); }, []);
  return (
    <div className="slot rounded-2xl p-4">
      <div className="flex items-baseline justify-between"><span className="text-sm text-mist">Tone balance</span>
        <span className="text-xs text-mist">how much of each range is in your voice</span></div>
      <div className="mt-3 flex h-28 items-end gap-1.5">
        {vals.map((v, i) => (
          <div key={i} className="flex h-full flex-1 flex-col justify-end">
            <div className="origin-bottom rounded-t-md bg-gradient-to-t from-ember to-amber transition-transform duration-700 ease-out"
              style={{ height: `${Math.max(4, ((v - floor) / 60) * 100)}%`, transform: `scaleY(${grown ? 1 : 0})`, transitionDelay: `${i * 50}ms` }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1.5 text-[10px] text-mist/80">{BANDS.map(([, l]) => <span key={l} className="flex-1 text-center">{l}</span>)}</div>
      <div className="mt-1.5 flex gap-1.5 text-xs">
        {REGIONS.map(([name, n]) => <span key={name} className="border-t border-line pt-1 text-center text-mist" style={{ flex: n }}>{name}</span>)}
      </div>
    </div>
  );
}

/** The analysis, explained: score, findings with what we'll do, and simple meters. */
export default function Report({ take }) {
  const a = take.analysis;
  if (!a) {
    return (
      <section className="rise faceplate mt-8 rounded-3xl p-6">
        <div className="text-lg font-bold">We couldn't analyse this take</div>
        <p className="mt-1 text-sm text-mist">The fix still works, using a safe all-round studio chain. ({take.analysis_error})</p>
      </section>
    );
  }
  const done = (take.status === "done" || take.status === "mixing") && take.score_after != null;
  const problems = a.problems?.problems ?? [];
  const leftTypes = new Set((take.analysis_after?.problems?.problems ?? []).map((p) => p.type));
  const steps = take.steps ?? take.plan ?? [];
  const stepFor = (type) => steps.find((s) => s.fixes.includes(type));
  const m = (done && take.analysis_after) || a;   // meters show the result once it's fixed
  // loudness range (LRA), not crest factor: crest rises once the gaps are silenced, LRA tracks how far apart words are
  const lufs = m.loudness?.integrated_lufs, tp = m.loudness?.true_peak_dbtp, lra = m.loudness?.loudness_range_lu;
  return (
    <section className="rise faceplate mt-8 rounded-3xl p-5 sm:p-6" id="report">
      <div className="grid gap-6 lg:grid-cols-[auto_1fr] lg:items-center">
        <ScoreRing before={take.score} after={done ? take.score_after : null} />
        <p className="max-w-[60ch] text-mist">
          {problems.length === 0 ? "No problems found. We'll still balance, compress and master it so it sounds finished."
            : done ? `We fixed ${take.fixed?.length ?? 0} of ${problems.length} problem${problems.length > 1 ? "s" : ""}. Here's what changed.`
              : `We listened like an engineer would and found ${problems.length} thing${problems.length > 1 ? "s" : ""} to fix. Here's what each one means.`}
        </p>
      </div>

      {problems.length > 0 && (
        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          {problems.map((p, i) => (
            <Finding key={p.type} p={p} step={stepFor(p.type)} i={i}
              state={!done ? "open" : leftTypes.has(p.type) ? "left" : (take.fixed ?? []).includes(p.type) ? "fixed" : "softened"} />
          ))}
        </div>
      )}

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {lufs != null && <Meter label="Loudness" value={`${lufs.toFixed(1)} LUFS`} pos={(lufs + 40) / 34}
          verdict={done ? (Math.abs(lufs + 12) < 1.5 ? "Loud and punchy, like a released track." : "Set for streaming.")
            : lufs < -16 ? "Quiet. We'll make it loud and punchy (-12)." : "Loud, but uncontrolled. We'll make it loud and clean (-12)."} />}
        {tp != null && <Meter label="Peak headroom" value={`${tp.toFixed(1)} dB`} pos={(tp + 30) / 31}
          verdict={tp > -1 ? "Peaks hit the ceiling and may crackle." : "Peaks are safely below the ceiling."} />}
        {lra != null && <Meter label="Volume swings" value={`${lra.toFixed(1)} LU`} pos={lra / 20}
          verdict={lra > 10 ? (done ? "Still a wide range between words." : "Loud and quiet words are far apart. We'll even them out.")
            : lra < 3 ? "Very even, almost flat." : done ? "Even and controlled, words sit up front." : "Nicely controlled already."} />}
      </div>
      {m.spectral?.octave_band_energy_db && <div className="mt-3"><Tone key={done ? "after" : "before"} bands={m.spectral.octave_band_energy_db} /></div>}
    </section>
  );
}
