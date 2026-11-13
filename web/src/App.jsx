import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import Autotune from "./components/Autotune.jsx";
import Report from "./components/Report.jsx";
import MixPanel from "./components/MixPanel.jsx";
import StylePicker, { VOCAL_STYLES } from "./components/StylePicker.jsx";
import { createMixEngine } from "./mixEngine.js";
import { Dropzone, Pipeline, Waveform } from "./components/Parts.jsx";

// three.js is ~80% of the JS and only draws the backdrop: load it after the page shows
const Orb = lazy(() => import("./components/Orb.jsx"));
const DotWaves = lazy(() => import("./components/DotWaves.jsx"));

const STAGE_PALETTES = [
  ["#ff5a36", "#6d28d9"], ["#ffb347", "#be185d"], ["#22d3ee", "#4f46e5"],
  ["#a78bfa", "#0e7490"], ["#f472b6", "#7c2d12"], ["#34d399", "#1e3a8a"], ["#fde047", "#9d174d"],
];
// light theme: same stage changes, in blues
const LIGHT_STAGE_PALETTES = [
  ["#3b8bf6", "#0b3a8c"], ["#7cc8ff", "#1d4ed8"], ["#38bdf8", "#1e3a8a"],
  ["#93c5fd", "#0e7490"], ["#60a5fa", "#312e81"], ["#5eead4", "#1e40af"], ["#a5d8ff", "#1e3a8a"],
];
// Web Share with files (phones, Windows/macOS share sheets): send the MP3 straight to WhatsApp & co
const CAN_SHARE = (() => {
  try { return !!navigator.canShare?.({ files: [new File([""], "a.mp3", { type: "audio/mpeg" })] }); } catch { return false; }
})();
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
  const [vocal, setVocal] = useState(null);
  const [job, setJob] = useState(null);        // the take as the server sees it (polled)
  const [err, setErr] = useState("");
  const [tune, setTune] = useState(false);
  const [level, setLevel] = useState("medium");
  const [keyInfo, setKeyInfo] = useState(null);
  const [keyLoading, setKeyLoading] = useState(false);
  const [keyError, setKeyError] = useState("");
  const [chosenKey, setChosenKey] = useState(null);
  const [style, setStyle] = useState(null);     // rap / melodic / pop: kept across takes
  const pickStyle = (id) => {                   // each sound comes with its usual auto-tune
    const at = VOCAL_STYLES.find((s) => s.id === id).autotune;
    setStyle(id); setTune(at !== "off"); setLevel(at === "off" ? "light" : at);
  };
  const takeNo = useRef(0);                    // bumps per new take so stale polls stop

  const poll = async (id, until) => {
    const me = takeNo.current;
    for (let misses = 0; ;) {
      await new Promise((res) => setTimeout(res, 400));
      if (me !== takeNo.current) return null;
      let r;
      try { r = await fetch(`/api/jobs/${id}`); misses = 0; } catch (e) {
        if (++misses < 15) continue;   // ~6 s of retries rides out a server restart
        throw e;
      }
      if (r.status === 404) throw new Error("The server restarted and lost this take. Drop the file again.");
      const j = await r.json();
      setJob(j);
      if (j.status === "error") throw new Error(j.error);
      if (until.includes(j.status)) return j;
    }
  };
  // fetch() rejects with a bare "Failed to fetch" when the server is unreachable; say what to do instead
  const explain = (e) => (e instanceof TypeError
    ? "Can't reach the VocalPreset server. Make sure it's running (start.bat), then try again." : e.message);

  // ---------- 1. drop a vocal -> analysis starts straight away ----------
  const onVocal = async (file) => {
    stop(); takeNo.current += 1;
    setVocal(file); setErr(""); setKeyInfo(null); setChosenKey(null); setKeyError(""); setBeat(null);
    if (!file) { setJob(null); return; }
    setJob({ status: "analysing", stage: "Uploading" });
    try {
      const fd = new FormData();
      fd.append("vocal", file);
      const r = await fetch("/api/takes", { method: "POST", body: fd });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Upload failed");
      await poll(d.id, ["analysed"]);
    } catch (e) { setErr(explain(e)); setJob(null); }
  };

  // ---------- 2. auto-tune on -> detect the key (once per take) ----------
  const [beat, setBeat] = useState(null);
  const detectKey = async (id, beatFile) => {
    setKeyLoading(true); setKeyError("");
    try {
      const fd = new FormData();
      if (beatFile) fd.append("beat", beatFile);
      const r = await fetch(`/api/takes/${id}/key`, { method: "POST", body: fd });
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Couldn't find the key");
      setKeyInfo(d); setChosenKey(d.key_string);
    } catch (e) { setKeyError(explain(e)); } finally { setKeyLoading(false); }
  };
  useEffect(() => {
    if (tune && job?.id && ["analysed", "done"].includes(job.status) && !keyInfo && !keyLoading && !keyError) detectKey(job.id);
  }, [tune, job?.id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- 3. fix it ----------
  const fix = async () => {
    stop(); setErr("");
    try {
      const r = await fetch(`/api/takes/${job.id}/fix`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ autotune: tune ? level : "off", key: tune ? chosenKey : null, style }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Couldn't start the fix");
      setJob((j) => ({ ...j, status: "fixing", stage: "Planning the fix", slot: 0 }));
      await poll(job.id, ["done"]);
    } catch (e) { setErr(explain(e)); setJob((j) => j && { ...j, status: "analysed" }); }
  };
  const busy = job?.status === "analysing" || job?.status === "fixing";
  const done = job?.status === "done" || job?.status === "mixing";
  const nProblems = job?.analysis?.problems?.problems?.length ?? 0;

  // ---------- 4. live mix engine: stems mixed in the browser, every knob instant ----------
  const ctx = useRef(null), engine = useRef(null);
  const [engineReady, setEngineReady] = useState(false);
  const [mixS, setMixS] = useState(null);           // the rack's current settings
  const [defaults, setDefaults] = useState(null);   // the one-click mix (for reset / double-click)
  const [showing, setShowing] = useState("after");
  const [matchLevel, setMatchLevel] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [exporting, setExporting] = useState("");
  const [mixError, setMixError] = useState("");

  const audioCtx = () => (ctx.current ??= new (window.AudioContext || window.webkitAudioContext)());
  useEffect(() => {                                   // a finished fix: load its stems into a fresh engine
    if (job?.status !== "done" || !job.stems) return;
    if (engine.current?.key === job.stems[1]) return;
    let cancelled = false;
    setEngineReady(false);
    engine.current?.dispose(); engine.current = null;
    setPlaying(false); setT(0); setShowing("after");
    setMixS(job.settings); setDefaults(job.settings);
    createMixEngine(audioCtx(), { raw: job.raw, stems: job.stems, duck: job.duck, fx: job.fx, settings: job.settings })
      .then((e) => {
        if (cancelled) { e.dispose(); return; }
        e.key = job.stems[1];
        engine.current = e; setDur(e.duration); setEngineReady(true);
      })
      .catch(() => !cancelled && setMixError("Couldn't load the live mixer. Downloads still work."));
    return () => { cancelled = true; };
  }, [job?.status, job?.stems?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps

  const beforeGain = done && matchLevel && job.lufs_raw != null ? Math.pow(10, (job.lufs_out - job.lufs_raw) / 20) : 1;
  useEffect(() => { engine.current?.showing(showing, beforeGain); }, [showing, beforeGain, engineReady]);

  const play = async () => {
    if (!engine.current) return;
    await audioCtx().resume();
    engine.current.play(engine.current.time() >= dur - 0.05 ? 0 : engine.current.time());
    setPlaying(true);
  };
  const stop = () => { engine.current?.pause(); setPlaying(false); };
  const seek = (f) => { engine.current?.seek(f * dur); setT(f * dur); };
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const now = engine.current?.time() ?? 0;
      setT(now);
      if (now >= dur - 0.02) stop();
    }, 100);
    return () => clearInterval(id);
  }, [playing, dur]); // eslint-disable-line react-hooks/exhaustive-deps

  const knob = (patch) => {                           // instant: straight into the audio graph
    setMixS((m) => ({ ...m, ...patch }));
    engine.current?.set(patch);
  };
  const resetMix = () => { setMixS(defaults); engine.current?.set(defaults); };

  // Download = export exactly what you hear: the server renders the rack settings (unchanged = instant).
  const exported = async (kind) => {
    setMixError("");
    const same = JSON.stringify(mixS) === JSON.stringify(job.settings);
    let j = job;
    if (!same) {
      setExporting(kind);
      try {
        const r = await fetch(`/api/takes/${job.id}/mix`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mixS),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Couldn't export the mix");
        j = await poll(job.id, ["done"]);
        if (j?.mix_error) throw new Error(j.mix_error);
      } catch (e) { setMixError(explain(e)); setExporting(""); return null; }
      setExporting("");
    }
    return j;
  };
  const download = async (kind) => {
    const j = await exported(kind);
    if (!j) return;
    const a = document.createElement("a");
    a.href = j[kind]; a.download = j.names?.[kind] ?? ""; document.body.appendChild(a); a.click(); a.remove();
  };
  const share = async () => {
    const j = await exported("share");
    if (!j) return;
    try {
      const blob = await (await fetch(j.mp3)).blob();
      await navigator.share({ files: [new File([blob], j.names.mp3, { type: "audio/mpeg" })], title: j.names.mp3.slice(0, -4) });
    } catch (e) {
      // a long export uses up the click's permission to share: the file is ready now, so a second tap works
      if (e.name === "NotAllowedError") setMixError("Your mix is ready. Tap Share again to send it.");
      else if (e.name !== "AbortError") setMixError("Couldn't open sharing here. Download the MP3 and send that instead.");
    }
  };

  const getAnalyser = useCallback(() => (playing ? engine.current?.analyser ?? null : null), [playing]);
  const lightMode = theme === "light";
  const stages = lightMode ? LIGHT_STAGE_PALETTES : STAGE_PALETTES;
  const palette = busy ? stages[(job.slot ?? 0) % stages.length]
    : done && showing === "before" ? ["#a78bfa", "#312e81"] : lightMode ? ["#4a9bff", "#103f9a"] : ["#ff5a36", "#6d28d9"];

  const reset = () => { stop(); takeNo.current += 1; setVocal(null); setJob(null); setErr(""); };

  return (
    <>
      <Suspense fallback={null}>
        <DotWaves light={theme === "light"} />
        <Orb getAnalyser={getAnalyser} busy={busy ? 1 : 0} palette={palette} light={theme === "light"} />
      </Suspense>
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,transparent_0%,color-mix(in_srgb,var(--bg)_35%,transparent)_85%)]" />

      <main className="mx-auto flex min-h-full w-full max-w-md flex-col px-4 pt-[max(1.25rem,env(safe-area-inset-top))] pb-10 lg:max-w-6xl lg:px-10">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="size-2.5 rounded-full bg-ember shadow-[0_0_14px_var(--ember)]" />
            <span className="font-semibold tracking-tight">VocalPreset</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="glass hidden rounded-full px-2.5 py-1 font-mono text-[10px] text-mist sm:inline">analyse, tune, fix</span>
            <ThemeSwitch choice={themeChoice} onChange={setThemeChoice} />
          </div>
        </header>

        <div className="lg:grid lg:flex-1 lg:grid-cols-[1.1fr_1fr] lg:items-center lg:gap-16">
        <section className="rise mt-[18vh] mb-7 sm:mt-[14vh] lg:mt-0 lg:mb-0">
          <h1 className="chrome text-[2.35rem] leading-[1.04] font-extrabold tracking-[-0.02em] sm:text-5xl lg:text-[4.1rem]">
            Bedroom take.<br />Studio finish.
          </h1>
          <p className="lift-text mt-4 max-w-[36ch] text-[1.02rem] leading-relaxed text-fg/80 lg:mt-6 lg:text-lg">
            Drop a dry vocal. We check it like an engineer would, tell you what's off in plain words, and fix it, with optional auto-tune.
          </p>
          <div className="mt-8 hidden gap-8 lg:flex">
            {[["20", "checks on every take"], ["24", "keys for auto-tune"], ["-12", "LUFS, loud and clean"]].map(([n, l]) => (
              <div key={l} className="lift-text"><div className="text-3xl font-bold">{n}</div><div className="text-sm text-fg/70">{l}</div></div>
            ))}
          </div>
        </section>
        <div className="faceplate rounded-3xl p-4 sm:p-5 lg:p-6">

        {(!job || job.status === "analysing" || job.status === "analysed") && (
          <div className="rise space-y-2.5" style={{ animationDelay: ".08s" }}>
            <div className="flex items-center justify-between px-1 pb-1">
              <span className="text-lg font-bold tracking-tight" style={{ fontStretch: "110%" }}>Your vocal</span>
              <span className="flex items-center gap-2 text-xs text-mist">
                {!job ? "Waiting for a vocal" : job.status === "analysing" ? "Listening…" : "Ready to fix"}
                <span className="led" data-on={job?.status === "analysed"} />
              </span>
            </div>
            <Dropzone label="Drop your vocal here" hint="Dry take: mp3, wav, m4a, WhatsApp voice note or video"
              file={vocal} onFile={onVocal} scanning={job?.status === "analysing"} />
            {job && <StylePicker value={style} onChange={pickStyle} />}
            {job?.status === "analysing" && (
              <p className="chip-in px-1 text-sm text-mist">Listening to your take like an engineer would: noise, hum, harsh spots, loudness and more.</p>
            )}
            {job?.status === "analysed" && (<>
              <a href="#report" className="chip-in slot flex items-center justify-between gap-3 rounded-2xl px-4 py-3 transition hover:bg-fg/[.06]">
                <span className="text-sm">
                  {job.score != null ? <>Studio readiness <span className="font-bold">{job.score}/100</span></> : "Report ready"}
                  <span className="text-mist">{nProblems ? `, ${nProblems} thing${nProblems > 1 ? "s" : ""} to fix` : ", nothing major"}</span>
                </span>
                <span className="text-sm font-medium text-ember">See report ↓</span>
              </a>
              <Autotune on={tune} onToggle={setTune} level={level} onLevel={setLevel} keyInfo={keyInfo}
                keyLoading={keyLoading} keyError={keyError} chosenKey={chosenKey} onKey={setChosenKey}
                beat={beat} onBeat={(f) => { setBeat(f); if (f) detectKey(job.id, f); }} />
            </>)}
            <button disabled={job?.status !== "analysed" || !style || (tune && (keyLoading || !chosenKey))} onClick={fix}
              className="btn-glow btn-sheen mt-3 w-full rounded-2xl bg-gradient-to-b from-[var(--ember-hi)] to-ember py-4 text-lg font-bold tracking-tight text-white transition duration-200 hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
              style={{ fontStretch: "108%" }}>
              {!job ? "Drop a vocal to start" : job.status === "analysing" ? "Analysing…" : !style ? "Pick your sound" : tune && keyLoading ? "Finding the key…" : "Fix my vocal"}
            </button>
            {err && <p className="text-sm text-ember">{err}</p>}
          </div>
        )}

        {job?.status === "fixing" && <Pipeline chain={job.chain ?? job.plan?.map((st) => st.label) ?? []} slot={job.slot} stage={job.stage} elapsed={job.elapsed} />}

        {done && (
          <div className="glass rise rounded-3xl p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-lg font-semibold">Your vocal is fixed</div>
                <div className="text-sm text-mist">{job.style_label ? `${job.style_label} · ` : ""}{job.autotune && job.autotune !== "off" ? `Auto-tune ${job.autotune}` : "No auto-tune"}, done in {job.seconds}s</div>
              </div>
              <div className="flex gap-1">
                <button onClick={() => setJob((j) => ({ ...j, status: "analysed" }))} className="rounded-xl px-3 py-1.5 text-sm text-mist hover:bg-fg/10 hover:text-fg">Tweak</button>
                <button onClick={reset} className="rounded-xl px-3 py-1.5 text-sm text-mist hover:bg-fg/10 hover:text-fg">New</button>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-1.5">
              {job.score_after != null && <Chip label="Readiness" value={`${job.score} → ${job.score_after}`} />}
              {job.key && <Chip label="Key" value={job.key} />}
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

            <MixPanel settings={mixS} defaults={defaults} ready={engineReady} onChange={knob} onReset={resetMix} />
            {mixError && <p className="mt-2 text-sm text-ember">{mixError}</p>}

            <div className="mt-4 grid grid-cols-2 gap-2">
              <button onClick={() => download("mp3")} disabled={!!exporting}
                className="rounded-2xl bg-fg py-3 text-center font-semibold text-bg transition active:scale-[.98] disabled:opacity-60">
                {exporting === "mp3" ? "Exporting…" : "Download MP3"}</button>
              <button onClick={() => download("wav")} disabled={!!exporting}
                className="rounded-2xl border border-fg/15 py-3 text-center font-semibold transition hover:bg-fg/5 active:scale-[.98] disabled:opacity-60">
                {exporting === "wav" ? "Exporting…" : "WAV 16-bit"}</button>
            </div>
            {CAN_SHARE && (
              <button onClick={share} disabled={!!exporting}
                className="mt-2 flex w-full items-center justify-center gap-2 rounded-2xl border border-fg/15 py-3 font-semibold transition hover:bg-fg/5 active:scale-[.98] disabled:opacity-60">
                <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4" />
                </svg>
                {exporting === "share" ? "Exporting…" : "Share MP3"}
              </button>
            )}
            <p className="mt-2 px-1 text-xs leading-relaxed text-mist">
              Sending on WhatsApp? The MP3 goes as audio. WhatsApp caps audio at 16 MB, so send a long WAV as a Document.
            </p>

          </div>
        )}

        </div>
        </div>

        {job && job.status !== "analysing" && (job.analysis || job.analysis_error) && <Report take={job} />}

        <footer className="mt-auto pt-10 text-center text-xs text-mist/50">
          Processed on our server · nothing is shared
        </footer>
      </main>
    </>
  );
}

const Chip = ({ label, value }) => (
  <span className="rounded-full bg-fg/[.06] px-2.5 py-1 text-xs">
    <span className="text-mist">{label} </span><span className="font-medium">{value}</span>
  </span>
);
