// Live mix engine: the server's space()/mixdown() rebuilt in Web Audio, so every knob is instant.
// Stems: s0 = your cleaned/tuned voice, s1 = the polished voice (both mono, level-matched).
// The numbers come from the server (job.fx = fixer.FX) and the reverb IRs are the server's own,
// so the preview matches the downloaded render (which the server makes with the same settings).

const decode = async (ctx, url) => ctx.decodeAudioData(await (await fetch(url)).arrayBuffer());

export async function createMixEngine(ctx, { raw, stems, duck, fx, settings }) {
  const [rawBuf, b0, b1, ...irs] = await Promise.all([
    decode(ctx, raw), decode(ctx, stems[0]), decode(ctx, stems[1]),
    ...["room", "plate", "hall"].map((s) => decode(ctx, `/api/ir/${s}.wav`)),
  ]);
  const IR = { room: irs[0], plate: irs[1], hall: irs[2] };
  const curve = Float32Array.from(duck);
  const now = () => ctx.currentTime;
  const set = (param, v) => param.setTargetAtTime(v, now(), 0.015);          // click-free, ~instant
  const node = (Ctor, opts) => new Ctor(ctx, opts);
  const bq = (type, frequency, extra = {}) => node(BiquadFilterNode, { type, frequency, Q: Math.SQRT1_2, ...extra });
  const stereo = { channelCount: 2, channelCountMode: "explicit", channelInterpretation: "speakers" };

  // ----- vocal: mix crossfade -> warmth / brightness shelves -----
  const g0 = node(GainNode), g1 = node(GainNode), vocal = node(GainNode);
  const warm = bq("lowshelf", fx.warm_hz), bright = bq("highshelf", fx.bright_hz);
  g0.connect(vocal); g1.connect(vocal); vocal.connect(warm).connect(bright);
  const st = node(GainNode, stereo);                                          // "st" in fixer.space()
  bright.connect(st);

  // ----- doubler: two LFO-wobbled delays, hard left / right -----
  const dblMerge = node(ChannelMergerNode, { numberOfInputs: 2 });
  const lfos = fx.doubler.map(([base, depth, rate], ch) => {
    const d = node(DelayNode, { maxDelayTime: 0.1, delayTime: base });
    const lfo = node(OscillatorNode, { frequency: rate });
    const amt = node(GainNode, { gain: depth });
    lfo.connect(amt).connect(d.delayTime); lfo.start();
    bright.connect(d).connect(dblMerge, 0, ch);
    return lfo;
  });
  const widthGain = node(GainNode, { gain: 0 });
  dblMerge.connect(bq("highpass", fx.doubler_hp)).connect(bq("lowpass", fx.doubler_lp)).connect(widthGain).connect(st);

  // ----- send (dry + double) -> ducked convolution reverb / ducked ping-pong echo -----
  const send = bq("lowpass", fx.send_lp);
  st.connect(bq("highpass", fx.send_hp)).connect(send);
  const conv = node(ConvolverNode, { disableNormalization: true });
  conv.buffer = IR[settings.reverb_style];
  const duckR = node(GainNode), reverbGain = node(GainNode, { gain: 0 });
  send.connect(conv).connect(duckR).connect(reverbGain);

  const split = node(ChannelSplitterNode, { numberOfOutputs: 2 }), echoMerge = node(ChannelMergerNode, { numberOfInputs: 2 });
  send.connect(split);
  const feedbackDelay = () => {                                              // y[n] = x[n-D] + fb*y[n-D]
    const d = node(DelayNode, { maxDelayTime: 2 });
    const fb = node(GainNode, { gain: fx.delay_fb });
    d.connect(fb).connect(d);
    return d;
  };
  const echoL = feedbackDelay(), pre = node(DelayNode, { maxDelayTime: 1 }), echoR = feedbackDelay();
  split.connect(echoL, 0).connect(echoMerge, 0, 0);                          // L: 2t, 4t, ...
  split.connect(pre, 1).connect(echoR).connect(echoMerge, 0, 1);             // R: t, 3t, ...
  const duckD = node(GainNode), delayGain = node(GainNode, { gain: 0 });
  echoMerge.connect(bq("lowpass", fx.delay_lp)).connect(duckD).connect(delayGain);

  // ----- master: after / before, preview limiter, analyser for the orb -----
  const after = node(GainNode), before = node(GainNode, { gain: 0 });
  st.connect(after); reverbGain.connect(after); delayGain.connect(after);
  const makeup = node(GainNode, { gain: 10 ** (4 / 20) });                    // stems sit at -16 LUFS; master is -12
  const limiter = node(DynamicsCompressorNode, { threshold: -1.5, knee: 0, ratio: 20, attack: 0.002, release: 0.08 });
  const analyser = node(AnalyserNode, { fftSize: 1024, smoothingTimeConstant: 0.78 });
  after.connect(makeup); before.connect(limiter); makeup.connect(limiter).connect(analyser).connect(ctx.destination);

  let s = { ...settings }, sources = [], startedAt = 0, offset = 0, playing = false;

  const apply = (patch) => {
    s = { ...s, ...patch };
    const m = s.mix;
    set(g0.gain, 1 - m); set(g1.gain, m);
    set(warm.gain, fx.warm_db * s.warmth); set(bright.gain, fx.bright_db * s.brightness);
    set(widthGain.gain, s.width * m * 10 ** (fx.doubler_db / 20));
    set(reverbGain.gain, fx.reverb_gain * s.reverb * m);
    set(delayGain.gain, fx.delay_gain * s.delay * m);
    if (patch.reverb_style) conv.buffer = IR[s.reverb_style];
    const t = fx.delays[s.delay_style];
    set(echoL.delayTime, 2 * t); set(pre.delayTime, t); set(echoR.delayTime, 2 * t);
  };
  apply({});

  const scheduleDuck = (when, from) => {                                     // the server's exact ducking curve
    const i = Math.min(curve.length - 2, Math.floor(from * fx.duck_rate));
    const part = curve.subarray(i);
    for (const g of [duckR.gain, duckD.gain]) {
      g.cancelScheduledValues(0);
      g.setValueCurveAtTime(part, when, Math.max(0.05, part.length / fx.duck_rate));
    }
  };

  const stopSources = () => { sources.forEach((src) => { try { src.stop(); } catch { /* already stopped */ } }); sources = []; };

  return {
    duration: b1.duration,
    analyser,
    settings: () => s,
    set: apply,
    time: () => (playing ? Math.min(b1.duration, offset + now() - startedAt) : offset),
    play(from = offset) {
      stopSources();
      const when = now() + 0.03;
      sources = [[rawBuf, before], [b0, g0], [b1, g1]].map(([buf, dest]) => {
        const src = node(AudioBufferSourceNode, { buffer: buf });
        src.connect(dest); src.start(when, Math.min(from, buf.duration));
        return src;
      });
      scheduleDuck(when, from);
      offset = from; startedAt = when; playing = true;
    },
    pause() { if (playing) { offset = this.time(); stopSources(); playing = false; } },
    seek(to) { offset = Math.max(0, Math.min(to, b1.duration)); if (playing) this.play(offset); },
    showing(which, beforeGain) {
      set(after.gain, which === "after" ? 1 : 0);
      set(before.gain, which === "before" ? beforeGain : 0);
    },
    dispose() { stopSources(); lfos.forEach((l) => l.stop()); analyser.disconnect(); },
  };
}
