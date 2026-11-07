import { useEffect, useRef, useState } from "react";

/** Drag-and-drop or tap-to-pick file slot. */
export function Dropzone({ label, hint, file, onFile, accent = "ember", optional }) {
  const [over, setOver] = useState(false);
  const input = useRef(null);
  const ring = accent === "ember" ? "border-ember/70 bg-ember/[.06]" : "border-violet/70 bg-violet/[.07]";
  return (
    <button type="button" onClick={() => input.current.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); e.dataTransfer.files[0] && onFile(e.dataTransfer.files[0]); }}
      className={`group relative w-full overflow-hidden rounded-2xl border border-dashed px-4 py-4 text-left transition
        ${file ? `border-solid ${ring}` : over ? ring : "border-fg/15 bg-fg/[.02] hover:border-fg/30"}`}>
      <input ref={input} type="file" hidden accept="audio/*,video/*,.mpeg,.opus,.m4a,.wav,.mp3"
        onChange={(e) => e.target.files[0] && onFile(e.target.files[0])} />
      <div className="flex items-center gap-3">
        <span className={`grid size-10 shrink-0 place-items-center rounded-xl transition ${file ? (accent === "ember" ? "bg-ember text-white" : "bg-violet text-white") : "bg-fg/[.06] text-mist group-hover:text-fg"}`}>
          {file ? (
            <svg viewBox="0 0 20 20" className="size-5"><path fill="currentColor" d="M16.7 5.3a1 1 0 0 1 0 1.4l-8 8a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L8 12.6l7.3-7.3a1 1 0 0 1 1.4 0Z" /></svg>
          ) : (
            <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 20h16" /></svg>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 font-semibold">
            <span className="truncate">{file ? file.name : label}</span>
            {optional && !file && <span className="text-[10px] font-medium uppercase tracking-wider text-mist/70">optional</span>}
          </div>
          <div className="truncate text-sm text-mist">
            {file ? `${(file.size / 1048576).toFixed(1)} MB · tap to change` : hint}
          </div>
        </div>
        {file && optional && (
          <span role="button" onClick={(e) => { e.stopPropagation(); onFile(null); }}
            className="rounded-lg px-2 py-1 text-xs text-mist hover:bg-fg/10 hover:text-fg">Remove</span>
        )}
      </div>
    </button>
  );
}

/** The FL plugin chain, lighting up live as the server works through it. */
export function Pipeline({ chain, slot, stage, elapsed, done }) {
  return (
    <div className="glass rise rounded-3xl p-5">
      <div className="flex items-center justify-between">
        <div className="font-semibold">{done ? "Finished" : "Processing"}</div>
        <div className="font-mono text-xs text-mist">{elapsed?.toFixed?.(1) ?? "0.0"}s</div>
      </div>
      <div className="mt-1 h-5 text-sm text-mist">{stage}</div>
      <ol className="mt-4 space-y-1.5">
        {chain.map((p, i) => {
          const state = done || (slot != null && i < slot) ? "done" : slot === i ? "live" : "wait";
          return (
            <li key={i} className={`relative flex items-center gap-3 overflow-hidden rounded-xl px-3 py-2.5 transition duration-500
              ${state === "live" ? "bg-ember/15 text-fg" : state === "done" ? "text-fg/80" : "text-mist/50"}`}>
              {state === "live" && <div className="shimmer absolute inset-0" />}
              <span className={`relative grid size-6 place-items-center rounded-full font-mono text-[11px] transition
                ${state === "done" ? "bg-ember text-white" : state === "live" ? "bg-fg text-bg" : "bg-fg/[.06]"}`}>
                {state === "done" ? "✓" : i + 1}
              </span>
              <span className="relative flex-1 text-sm font-medium">{p}</span>
              {state === "live" && <span className="relative size-2 animate-ping rounded-full bg-ember" />}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Waveform of before + after, with playhead, click/drag to seek. */
export function Waveform({ before, after, showing, progress, onSeek, theme }) {
  const cv = useRef(null);
  useEffect(() => {
    const c = cv.current, dpr = Math.min(devicePixelRatio, 2);
    const w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d");
    g.scale(dpr, dpr);
    const draw = (peaks, color, alpha) => {
      if (!peaks) return;
      const n = peaks.length, bw = w / n;
      g.fillStyle = color; g.globalAlpha = alpha;
      for (let i = 0; i < n; i++) {
        const v = Math.max(0.02, peaks[i]) * h * 0.46;
        g.fillRect(i * bw, h / 2 - v, Math.max(1, bw - 0.6), v * 2);
      }
    };
    const css = getComputedStyle(document.documentElement);
    const fg = css.getPropertyValue("--fg").trim() || "#fff", bg = css.getPropertyValue("--bg").trim() || "#07060b";
    g.clearRect(0, 0, w, h);
    const grad = g.createLinearGradient(0, 0, w, 0);
    grad.addColorStop(0, "#ff5a36"); grad.addColorStop(1, "#ffb347");
    if (showing === "after") { draw(before, fg, 0.12); draw(after, grad, 0.95); }
    else { draw(after, "#ff5a36", 0.12); draw(before, theme === "light" ? "#7c3aed" : "#c4b5fd", 0.9); }
    // dim the unplayed part
    g.globalAlpha = 0.55; g.fillStyle = bg;
    g.fillRect(w * progress, 0, w * (1 - progress), h);
    g.globalAlpha = 1; g.fillStyle = fg;
    g.fillRect(w * progress - 1, 0, 2, h);
  }, [before, after, showing, progress, theme]);
  const seek = (e) => {
    const r = cv.current.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
    onSeek(Math.min(1, Math.max(0, x / r.width)));
  };
  return <canvas ref={cv} onClick={seek} onTouchMove={seek} className="h-24 w-full cursor-pointer touch-none" />;
}
