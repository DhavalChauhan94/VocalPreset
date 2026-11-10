import { useRef } from "react";

const START = -135, SWEEP = 270;   // degrees: a 7-to-5 o'clock sweep, like hardware

function arc(r, a0, a1) {
  const p = (a) => [50 + r * Math.sin((a * Math.PI) / 180), 50 - r * Math.cos((a * Math.PI) / 180)];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${x0} ${y0} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
}

/** Rotary knob. Drag up/down (Shift = fine), scroll, arrow keys; double-click resets. */
export default function Knob({ label, value, min = 0, max = 1, def = 0, format, onChange, size = 64 }) {
  const drag = useRef(null);
  const frac = (value - min) / (max - min);
  const clamp = (v) => Math.min(max, Math.max(min, v));
  const nudge = (delta) => onChange(clamp(Math.round((value + delta) * 1000) / 1000));
  const angle = START + frac * SWEEP;
  const zero = min < 0 ? START + ((0 - min) / (max - min)) * SWEEP : START;   // bipolar knobs fill from centre

  const down = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { y: e.clientY, v: value };
  };
  const move = (e) => {
    if (!drag.current) return;
    const span = (max - min) * (e.shiftKey ? 0.25 : 1);
    onChange(clamp(drag.current.v + ((drag.current.y - e.clientY) / 180) * span));
  };
  const key = (e) => {
    const step = (max - min) * (e.shiftKey ? 0.01 : 0.05);
    const k = { ArrowUp: step, ArrowRight: step, ArrowDown: -step, ArrowLeft: -step }[e.key];
    if (k) { e.preventDefault(); nudge(k); }
    if (e.key === "Home") onChange(min);
    if (e.key === "End") onChange(max);
  };

  return (
    <div className="flex select-none flex-col items-center gap-1">
      <div role="slider" tabIndex={0} aria-label={label} aria-valuemin={min} aria-valuemax={max}
        aria-valuenow={Number(value.toFixed(2))} aria-valuetext={format(value)}
        onPointerDown={down} onPointerMove={move} onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)} onDoubleClick={() => onChange(def)}
        onWheel={(e) => nudge((e.deltaY < 0 ? 1 : -1) * (max - min) * 0.02)} onKeyDown={key}
        className="knob relative cursor-ns-resize touch-none rounded-full" style={{ width: size, height: size }}>
        <svg viewBox="0 0 100 100" className="size-full">
          <path d={arc(44, START, START + SWEEP)} fill="none" stroke="var(--line)" strokeWidth="7" strokeLinecap="round" />
          {Math.abs(angle - zero) > 0.5 && (
            <path d={arc(44, Math.min(zero, angle), Math.max(zero, angle))} fill="none" stroke="var(--ember)"
              strokeWidth="7" strokeLinecap="round" style={{ filter: "drop-shadow(0 0 4px var(--ember))" }} />
          )}
          <circle cx="50" cy="50" r="32" className="knob-cap" />
          <line x1="50" y1="50" x2="50" y2="24" stroke="var(--fg)" strokeWidth="4" strokeLinecap="round"
            transform={`rotate(${angle} 50 50)`} />
        </svg>
      </div>
      <div className="text-center leading-tight">
        <div className="text-[13px] font-semibold">{label}</div>
        <div className="font-mono text-[11px] text-mist tabular-nums">{format(value)}</div>
      </div>
    </div>
  );
}
