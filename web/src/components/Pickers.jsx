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

/** Dropdown of decoded FL presets ("sounds"), each showing its real plugin chain. */
export function SoundPicker({ sounds, value, onChange }) {
  const cur = sounds.find((s) => s.id === value);
  if (!cur) return null;
  return (
    <Listbox value={value} onChange={onChange}>
      <ListboxButton className="group glass flex w-full items-center gap-3 rounded-2xl px-4 py-3.5 text-left transition hover:border-fg/20 focus:outline-none data-[focus]:ring-2 data-[focus]:ring-ember/50">
        <SoundIcon autotune={cur.autotune} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 font-semibold">
            {cur.name}
            {cur.autotune && <Badge>Auto-tune</Badge>}
          </div>
          <div className="truncate text-sm text-mist">{cur.blurb}</div>
        </div>
        <Chevron />
      </ListboxButton>
      <ListboxOptions anchor="bottom" transition className={panel}>
        {sounds.map((s) => (
          <ListboxOption key={s.id} value={s.id}
            className="group flex cursor-pointer gap-3 rounded-xl px-3 py-3 select-none data-[focus]:bg-fg/[.07]">
            <SoundIcon autotune={s.autotune} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 font-semibold">
                {s.name}{s.autotune && <Badge>Auto-tune</Badge>}
              </div>
              <div className="text-sm text-mist">{s.blurb}</div>
              <div className="mt-2 flex flex-wrap gap-1">
                {s.chain.map((p, i) => (
                  <span key={i} className="rounded-md bg-fg/[.06] px-1.5 py-0.5 font-mono text-[10px] text-mist">
                    {p.replace("Fruity ", "")}
                  </span>
                ))}
              </div>
              <div className="mt-1.5 font-mono text-[10px] text-mist/60">from {s.from}</div>
            </div>
            <div className="invisible pt-0.5 group-data-[selected]:visible"><Check /></div>
          </ListboxOption>
        ))}
      </ListboxOptions>
    </Listbox>
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
      <ListboxButton className="group glass flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left transition hover:border-fg/20 focus:outline-none data-[disabled]:opacity-40 data-[focus]:ring-2 data-[focus]:ring-ember/50">
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

function Badge({ children }) {
  return <span className="rounded-full bg-violet/25 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-violet-200">{children}</span>;
}

function SoundIcon({ autotune }) {
  return (
    <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${autotune ? "bg-violet/25" : "bg-ember/20"}`}>
      <svg viewBox="0 0 24 24" className={`size-5 ${autotune ? "text-violet-300" : "text-ember"}`} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        {autotune
          ? <path d="M3 12h3l2-6 4 12 3-9 2 3h4" />
          : <><path d="M12 3v12" /><circle cx="12" cy="17" r="4" /><path d="M8 7h8" /></>}
      </svg>
    </span>
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
    <div className="glass relative grid grid-cols-3 rounded-2xl p-1">
      <div className="absolute inset-y-1 left-1 w-[calc((100%-0.5rem)/3)] rounded-xl bg-gradient-to-br from-ember to-amber transition-transform duration-300 ease-[cubic-bezier(.2,.8,.2,1)]"
        style={{ transform: `translateX(${idx * 100}%)` }} />
      {parts.map((p) => (
        <button key={p.id} onClick={() => onChange(p.id)}
          className={`relative z-10 rounded-xl px-2 py-2.5 text-center transition ${value === p.id ? "text-white" : "text-mist hover:text-fg"}`}>
          <div className="text-sm font-semibold">{p.label}</div>
          <div className={`text-[11px] ${value === p.id ? "text-white/80" : "text-mist/70"}`}>{p.hint}</div>
        </button>
      ))}
    </div>
  );
}
