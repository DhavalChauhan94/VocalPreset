import { useCallback, useEffect, useRef, useState } from "react";
import Orb from "./components/Orb.jsx";
import DotWaves from "./components/DotWaves.jsx";
import { KeyPicker, PartPicker, SoundPicker } from "./components/Pickers.jsx";
import { Dropzone, Pipeline, Waveform } from "./components/Parts.jsx";

const STAGE_PALETTES = [
  ["#ff5a36", "#6d28d9"], ["#ffb347", "#be185d"], ["#22d3ee", "#4f46e5"],
  ["#a78bfa", "#0e7490"], ["#f472b6", "#7c2d12"], ["#34d399", "#1e3a8a"], ["#fde047", "#9d174d"],
];
// light theme: same stage changes, in blues
const LIGHT_STAGE_PALETTES = [
  ["#3b8bf6", "#0b3a8c"], ["#7cc8ff", "#1d4ed8"], ["#38bdf8", "#1e3a8a"],
  ["#93c5fd", "#0e7490"], ["#60a5fa", "#312e81"], ["#5eead4", "#1e40af"], ["#a5d8ff", "#1e3a8a"],
];
const fmt = (s) => (isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00");

const THEME_KEY = "vp-theme";
function useTheme() {
  const [choice, setChoice] = useState(() => {
    try { return localStorage.getItem(THEME_KEY) || "system"; } catch { return "system"; }
  });
  const [sysLight, setSysLight] = useState(() => matchMedia("(prefers-color-scheme: light)").matches);
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: light)");
    const on = (e) => setSysLight(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const theme = choice === "system" ? (sysLight ? "light" : "dark") : choice;
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#f4f8fd" : "#07060b");
    try { localStorage.setItem(THEME_KEY, choice); } catch { /* private mode */ }
  }, [theme, choice]);
  return [theme, choice, setChoice];
}

function ThemeSwitch({ choice, onChange }) {
  const opts = [
    { id: "light", label: "Light", icon: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></> },
    { id: "dark", label: "Dark", icon: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" /> },
    { id: "system", label: "System", icon: <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8m-4-4v4" /></> },
  ];
  return (
    <div className="glass flex rounded-full p-0.5" role="radiogroup" aria-label="Theme">
      {opts.map((o) => (
        <button key={o.id} role="radio" aria-checked={choice === o.id} title={o.label} onClick={() => onChange(o.id)}
          className={`grid size-8 place-items-center rounded-full transition ${choice === o.id ? "bg-fg text-bg" : "text-mist hover:text-fg"}`}>
          <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{o.icon}</svg>
        </button>
      ))}
    </div>
  );
}

export default function App() {
  const [theme, themeChoice, setThemeChoice] = useTheme();
  const [sounds, setSounds] = useState([]);
  const [sound, setSound] = useState("studio_air");
  const [part, setPart] = useState("lead");
  const [key, setKey] = useState("auto");
  const [vocal, setVocal] = useState(null);
  const [beat, setBeat] = useState(null);
  const [job, setJob] = useState(null);        // live job state from the server
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch("/api/sounds").then((r) => r.json()).then((d) => setSounds(d.sounds)).catch(() => setErr("Server not reachable"));
  }, []);
  const cur = sounds.find((s) => s.id === sound);

  // ---------- run a job and poll its progress ----------
  const start = async () => {
    setErr(""); stop();
    const fd = new FormData();
    fd.append("vocal", vocal); fd.append("part", part); fd.append("sound", sound); fd.append("key", key);
    if (beat) fd.append("beat", beat);
    setJob({ status: "running", stage: "Uploading", slot: null, elapsed: 0, chain: cur.chain });
    try {
      const r = await fetch("/api/jobs", { method: "POST", body: fd });
      const { id, detail } = await r.json();
      if (!r.ok) throw new Error(detail || "Upload failed");
      for (;;) {
        await new Promise((res) => setTimeout(res, 350));
        const j = await (await fetch(`/api/jobs/${id}`)).json();
        setJob({ ...j, chain: cur.chain });
        if (j.status === "error") throw new Error(j.error);
        if (j.status === "done") break;
      }
    } catch (e) { setErr(e.message); setJob(null); }
  };
  const busy = job?.status === "running";
  const done = job?.status === "done";

  // ---------- A/B audio engine: both files play in sync, we cross-fade gains ----------
  const ctx = useRef(null), an = useRef(null), els = useRef({}), gains = useRef({});
  const [showing, setShowing] = useState("after");
  const [matchLevel, setMatchLevel] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);

  const ensureGraph = () => {
    if (ctx.current) return;
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = ac.createAnalyser();
    analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.78;
    analyser.connect(ac.destination);
    for (const k of ["before", "after"]) {
      const g = ac.createGain();
      ac.createMediaElementSource(els.current[k]).connect(g);
      g.connect(analyser);
      gains.current[k] = g;
    }
    ctx.current = ac; an.current = analyser;
  };
  const beforeGain = done && matchLevel && job.lufs_raw != null ? Math.pow(10, (job.lufs_out - job.lufs_raw) / 20) : 1;
  useEffect(() => {
    if (!ctx.current) return;
    const now = ctx.current.currentTime;
    gains.current.after.gain.setTargetAtTime(showing === "after" ? 1 : 0, now, 0.015);
    gains.current.before.gain.setTargetAtTime(showing === "before" ? beforeGain : 0, now, 0.015);
  }, [showing, beforeGain, playing]);

  const play = async () => {
    ensureGraph();
    await ctx.current.resume();
    const { before, after } = els.current;
    before.currentTime = after.currentTime;
    await Promise.all([after.play(), before.play()]).catch(() => {});
    setPlaying(true);
  };
  const stop = () => {
    Object.values(els.current).forEach((a) => a?.pause());
    setPlaying(false);
  };
  const seek = (f) => {
    const { before, after } = els.current;
    after.currentTime = before.currentTime = f * (after.duration || 0);
    setT(after.currentTime);
  };
  useEffect(() => {      // keep the two players locked together
    if (!playing) return;
    const id = setInterval(() => {
      const { before, after } = els.current;
      setT(after.currentTime);
      if (Math.abs(before.currentTime - after.currentTime) > 0.04) before.currentTime = after.currentTime;
    }, 100);
    return () => clearInterval(id);
  }, [playing]);
  useEffect(() => { stop(); setT(0); setShowing("after"); }, [job?.mp3]);

  const getAnalyser = useCallback(() => (playing ? an.current : null), [playing]);
  const lightMode = theme === "light";
  const stages = lightMode ? LIGHT_STAGE_PALETTES : STAGE_PALETTES;
  const palette = busy ? stages[(job.slot ?? 0) % stages.length]
    : done && showing === "before" ? ["#a78bfa", "#312e81"] : lightMode ? ["#4a9bff", "#103f9a"] : ["#ff5a36", "#6d28d9"];

  const reset = () => { stop(); setJob(null); };

  return (
    <>
      <DotWaves light={theme === "light"} />
      <Orb getAnalyser={getAnalyser} busy={busy ? 1 : 0} palette={palette} light={theme === "light"} />
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,transparent_0%,color-mix(in_srgb,var(--bg)_35%,transparent)_85%)]" />

      <main className="mx-auto flex min-h-full w-full max-w-md flex-col px-4 pt-[max(1.25rem,env(safe-area-inset-top))] pb-10 lg:max-w-6xl lg:px-10">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="size-2.5 rounded-full bg-ember shadow-[0_0_14px_var(--ember)]" />
            <span className="font-semibold tracking-tight">VocalPreset</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="glass hidden rounded-full px-2.5 py-1 font-mono text-[10px] text-mist sm:inline">FL chain · rebuilt</span>
            <ThemeSwitch choice={themeChoice} onChange={setThemeChoice} />
          </div>
        </header>

        <div className="lg:grid lg:flex-1 lg:grid-cols-[1.1fr_1fr] lg:items-center lg:gap-16">
        <section className="rise mt-[18vh] mb-7 sm:mt-[14vh] lg:mt-0 lg:mb-0">
          <h1 className="chrome text-[2.35rem] leading-[1.04] font-extrabold tracking-[-0.02em] sm:text-5xl lg:text-[4.1rem]">
            Bedroom take.<br />Studio finish.
          </h1>
          <p className="lift-text mt-4 max-w-[36ch] text-[1.02rem] leading-relaxed text-fg/80 lg:mt-6 lg:text-lg">
            Drop a dry vocal and pick a sound rebuilt from real FL Studio presets. It comes back EQ'd, tuned, spaced out and mastered.
          </p>
          <div className="mt-8 hidden gap-8 lg:flex">
            {[["2", "FL presets"], ["13", "plugins rebuilt"], ["3–15s", "per song"]].map(([n, l]) => (
              <div key={l} className="lift-text"><div className="text-3xl font-bold">{n}</div><div className="text-sm text-fg/70">{l}</div></div>
            ))}
          </div>
        </section>
        <div className="faceplate rounded-3xl p-4 sm:p-5 lg:p-6">

        {!job && (
          <div className="rise space-y-2.5" style={{ animationDelay: ".08s" }}>
            <div className="flex items-center justify-between px-1 pb-1">
              <span className="text-lg font-bold tracking-tight" style={{ fontStretch: "110%" }}>New mix</span>
              <span className="flex items-center gap-2 text-xs text-mist">
                {vocal ? "Ready to mix" : "Waiting for a vocal"}<span className="led" data-on={!!vocal} />
              </span>
            </div>
            <Dropzone label="Drop your vocal here" hint="Dry take: mp3, wav, m4a, WhatsApp voice note or video" file={vocal} onFile={setVocal} />
            <Label on={!!cur}>Sound</Label>
            <SoundPicker sounds={sounds} value={sound} onChange={setSound} />
            <Label on>Part</Label>
            <PartPicker value={part} onChange={setPart} />
            {cur?.autotune && (<><Label on>Auto-tune key</Label><KeyPicker value={key} onChange={setKey} /></>)}
            <Label on={!!beat}>Beat</Label>
            <Dropzone compact label="Add a beat" hint="We'll mix and master the full song" file={beat} onFile={setBeat} accent="violet" optional />
            <button disabled={!vocal || !cur} onClick={start}
              className="btn-glow btn-sheen mt-3 w-full rounded-2xl bg-gradient-to-b from-[var(--ember-hi)] to-ember py-4 text-lg font-bold tracking-tight text-white transition duration-200 hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
              style={{ fontStretch: "108%" }}>
              {vocal ? "Mix my vocal" : "Add a vocal to start"}
            </button>
            {err && <p className="text-sm text-ember">{err}</p>}
          </div>
        )}

        {job && !done && <Pipeline chain={job.chain} slot={job.slot} stage={job.stage} elapsed={job.elapsed} />}

        {done && (
          <div className="glass rise rounded-3xl p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-lg font-semibold">{job.mixed ? "Your song is ready" : "Your vocal is ready"}</div>
                <div className="text-sm text-mist">{cur?.name} · {part === "adlib" ? "Ad-libs" : part[0].toUpperCase() + part.slice(1)} · {job.seconds}s</div>
              </div>
              <button onClick={reset} className="rounded-xl px-3 py-1.5 text-sm text-mist hover:bg-fg/10 hover:text-fg">New</button>
            </div>

            <div className="mt-4 flex flex-wrap gap-1.5">
              {job.key && <Chip label="Key" value={job.key} />}
              {job.bpm && <Chip label="BPM" value={job.bpm} />}
              {job.lufs_raw != null && <Chip label="Loudness" value={`${job.lufs_raw} → ${job.lufs_out} LUFS`} />}
            </div>

            <div className="mt-4 overflow-hidden rounded-2xl bg-fg/[.05] px-2">
              <Waveform before={job.peaks_before} after={job.peaks_after} showing={showing}
                progress={dur ? t / dur : 0} onSeek={seek} theme={theme} />
            </div>
            <div className="mt-1 flex justify-between font-mono text-[11px] text-mist">
              <span>{fmt(t)}</span><span>{fmt(dur)}</span>
            </div>

            <div className="mt-3 flex items-center gap-3">
              <button onClick={playing ? stop : play}
                className="btn-glow grid size-14 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ember to-amber text-white transition active:scale-95">
                {playing ? (
                  <svg viewBox="0 0 24 24" className="size-6" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
                ) : (
                  <svg viewBox="0 0 24 24" className="ml-0.5 size-6" fill="currentColor"><path d="M7 5.5v13a1 1 0 0 0 1.5.86l11-6.5a1 1 0 0 0 0-1.72l-11-6.5A1 1 0 0 0 7 5.5Z" /></svg>
                )}
              </button>
              <div className="relative grid flex-1 grid-cols-2 rounded-2xl bg-fg/[.05] p-1">
                <div className={`absolute inset-y-1 w-[calc(50%-0.25rem)] rounded-xl transition-all duration-300 ${showing === "after" ? "left-[calc(50%)] bg-ember/90" : "left-1 bg-violet/80"}`} />
                {["before", "after"].map((k) => (
                  <button key={k} onClick={() => setShowing(k)}
                    className={`relative z-10 rounded-xl py-3 text-sm font-semibold capitalize transition ${showing === k ? "text-white" : "text-mist"}`}>
                    {k}
                  </button>
                ))}
              </div>
            </div>

            <label className="mt-3 flex cursor-pointer items-center justify-between rounded-xl px-1 py-1 text-sm text-mist">
              <span>Level-match Before <span className="text-mist/60">(fair A/B: compare tone, not volume)</span></span>
              <input type="checkbox" checked={matchLevel} onChange={(e) => setMatchLevel(e.target.checked)} className="size-4 accent-ember" />
            </label>

            <div className="mt-4 grid grid-cols-2 gap-2">
              <a href={job.mp3} download className="rounded-2xl bg-fg py-3 text-center font-semibold text-bg transition active:scale-[.98]">Download MP3</a>
              <a href={job.wav} download className="rounded-2xl border border-fg/15 py-3 text-center font-semibold transition hover:bg-fg/5 active:scale-[.98]">WAV 24-bit</a>
            </div>

          </div>
        )}

        </div>
        </div>

        {/* always mounted: Web Audio binds to these elements once */}
        <audio ref={(a) => (els.current.after = a)} src={done ? job.mp3 : undefined} preload="auto"
          onLoadedMetadata={(e) => setDur(e.target.duration)} onEnded={stop} />
        <audio ref={(a) => (els.current.before = a)} src={done ? job.raw : undefined} preload="auto" />

        <footer className="mt-auto pt-10 text-center text-xs text-mist/50">
          Processed on our server · nothing is shared
        </footer>
      </main>
    </>
  );
}

const Label = ({ children, on }) => (
  <div className="flex items-center gap-2 px-1 pt-2 text-sm font-medium text-mist">
    <span className="led" data-on={!!on} style={{ width: 5, height: 5 }} />{children}
  </div>
);
const Chip = ({ label, value }) => (
  <span className="rounded-full bg-fg/[.06] px-2.5 py-1 text-xs">
    <span className="text-mist">{label} </span><span className="font-medium">{value}</span>
  </span>
);
