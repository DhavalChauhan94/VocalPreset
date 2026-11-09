import { Listbox, ListboxButton, ListboxOption, ListboxOptions } from "@headlessui/react";

const Chevron = () => (
  <svg viewBox="0 0 20 20" className="size-5 text-mist transition group-data-[open]:rotate-180">
    <path fill="currentColor" d="M5.2 7.5a1 1 0 0 1 1.4 0L10 10.9l3.4-3.4a1 1 0 1 1 1.4 1.4l-4.1 4.1a1 1 0 0 1-1.4 0L5.2 8.9a1 1 0 0 1 0-1.4Z" />
  </svg>
);
const Check = () => (
  <svg viewBox="0 0 20 20" className="size-5 text-ember"><path fill="currentColor" d="M16.7 5.3a1 1 0 0 1 0 1.4l-8 8a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L8 12.6l7.3-7.3a1 1 0 0 1 1.4 0Z" /></svg>
);

const panel = "z-50 border border-fg/10 bg-pop backdrop-blur-xl w-[var(--button-width)] rounded-2xl p-1.5 shadow-2xl shadow-black/60 [--anchor-gap:8px] focus:outline-none transition duration-150 ease-out data-[closed]:scale-95 data-[closed]:opacity-0 max-h-80 overflow-auto";

/** Decoded FL presets ("sounds") as tiles. Each dot is one plugin in the real chain; they light up in order when picked. */
export function SoundPicker({ sounds, value, onChange }) {
  const cur = sounds.find((s) => s.id === value);
  if (!cur) return null;
  return (
    <div>
      <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Sound">
        {sounds.map((s) => {
          const on = s.id === value;
          return (
            <button key={s.id} role="radio" aria-checked={on} onClick={() => onChange(s.id)}
              className={`group slot relative rounded-2xl p-3.5 text-left text-fg transition duration-200 hover:-translate-y-0.5 active:translate-y-0 active:scale-[.98]
                ${on ? "border-ember/55 bg-ember/[.08] shadow-[0_0_0_1px_rgb(255_90_54/.25),0_12px_30px_-14px_rgb(255_90_54/.55)]" : "hover:border-fg/25 hover:bg-fg/[.06]"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-fg">{s.name}</span>
                <span className="led" data-on={on} />
              </div>
              <div className="mt-0.5 text-sm text-mist">{s.blurb}</div>
              <div className="mt-3 flex h-4 items-center gap-1" aria-hidden="true">
                {s.chain.map((_, i) => (
                  <span key={i} style={{ "--i": i }}
                    className={`chain-dot size-1.5 rounded-full ${on ? "bg-ember shadow-[0_0_6px_#ff5a36]" : "bg-fg/20 group-hover:bg-fg/40"}`} />
                ))}
                {s.autotune && <span className="ml-auto text-xs text-violet-400">auto-tune</span>}
              </div>
            </button>
          );
        })}
      </div>
      <div key={cur.id} className="mt-2 flex flex-wrap items-center gap-x-1 gap-y-1 px-1 text-xs text-mist">
        {cur.chain.map((p, i) => (
          <span key={i} className="chip-in whitespace-nowrap" style={{ "--i": i }}>
            {i > 0 && <span className="mr-1 text-mist/50">→</span>}{p.replace("Fruity ", "")}
          </span>
        ))}
      </div>
    </div>
  );
}

const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const KEYS = [
  { id: "auto", label: "Auto-detect key", hint: "Recommended: listens to your vocal" },
  { id: "preset", label: "Preset's scale", hint: "Use the key saved in the FL preset" },
  ...NOTES.flatMap((n) => [
    { id: `${n} major`, label: `${n} major` },
    { id: `${n} minor`, label: `${n} minor` },
  ]),
];

/** Key dropdown for the auto-tune. */
export function KeyPicker({ value, onChange, disabled }) {
  const cur = KEYS.find((k) => k.id === value) ?? KEYS[0];
  return (
    <Listbox value={value} onChange={onChange} disabled={disabled}>
      <ListboxButton className="group slot flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left transition hover:border-fg/25 hover:bg-fg/[.06] active:scale-[.99] focus:outline-none data-[disabled]:opacity-40 data-[focus]:ring-2 data-[focus]:ring-ember/50">
        <span className="grid size-9 place-items-center rounded-xl bg-violet/20 font-mono text-sm text-violet-300">♯</span>
        <div className="flex-1">
          <div className="font-semibold">{cur.label}</div>
          <div className="text-sm text-mist">{disabled ? "This sound has no auto-tune" : cur.hint ?? "Fixed key"}</div>
        </div>
        <Chevron />
      </ListboxButton>
      <ListboxOptions anchor="bottom" transition className={panel}>
        {KEYS.map((k) => (
          <ListboxOption key={k.id} value={k.id}
            className="group flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 select-none data-[focus]:bg-fg/[.07]">
            <div className="flex-1">
              <div className="font-medium">{k.label}</div>
              {k.hint && <div className="text-xs text-mist">{k.hint}</div>}
            </div>
            <div className="invisible group-data-[selected]:visible"><Check /></div>
          </ListboxOption>
        ))}
      </ListboxOptions>
    </Listbox>
  );
}



/** Lead / Backing / Ad-libs segmented control with a sliding highlight. */
export function PartPicker({ value, onChange }) {
  const parts = [
    { id: "lead", label: "Lead", hint: "Main vocal" },
    { id: "backing", label: "Backing", hint: "Wide & soft" },
    { id: "adlib", label: "Ad-libs", hint: "Bright & echo" },
  ];
  const idx = parts.findIndex((p) => p.id === value);
  return (
    <div className="slot relative grid grid-cols-3 rounded-2xl p-1" role="radiogroup" aria-label="Part">
      <div className="absolute inset-y-1 left-1 w-[calc((100%-0.5rem)/3)] rounded-xl bg-gradient-to-b from-[#ff7a4a] to-ember shadow-[inset_0_1px_0_rgb(255_255_255/.35),0_6px_18px_-6px_rgb(255_90_54/.7)] transition-transform duration-300 ease-[cubic-bezier(.3,1.3,.5,1)]"
        style={{ transform: `translateX(${idx * 100}%)` }} />
      {parts.map((p) => (
        <button key={p.id} role="radio" aria-checked={value === p.id} onClick={() => onChange(p.id)}
          className={`relative z-10 rounded-xl px-2 py-2.5 text-center transition active:scale-95 ${value === p.id ? "text-white" : "text-mist hover:text-fg"}`}>
          <div className="text-sm font-semibold">{p.label}</div>
          <div className={`text-[11px] ${value === p.id ? "text-white/80" : "text-mist/70"}`}>{p.hint}</div>
        </button>
      ))}
    </div>
  );
}
