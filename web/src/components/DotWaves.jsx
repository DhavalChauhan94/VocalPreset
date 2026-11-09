import { useEffect, useRef } from "react";
import * as THREE from "three";
import { NOISE } from "./Orb.jsx";

// Full-screen LED dot-matrix background: a fixed grid of round dots whose size and
// colour follow slow flowing wave ribbons (red → orange → amber on black).
// One fragment shader draws every dot, so the CPU does no per-dot work.
// Reacts to the pointer: dots light up around the cursor, a click/tap sends a ripple.

const VERT = `void main(){ gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const FRAG = `
precision highp float;
uniform vec2 uRes; uniform float uTime, uSpacing, uDpr, uLight, uMouseAmt;
uniform vec2 uMouse; uniform vec3 uRip[4];
${NOISE}
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

void main(){
  vec2 frag = gl_FragCoord.xy;
  vec2 cell = floor(frag / uSpacing);
  vec2 cpx = (cell + 0.5) * uSpacing;          // dot centre, device px
  vec2 p = cpx / uRes.y;                       // aspect-correct, 0..1 tall
  float t = uTime;

  // pointer glow (CSS px distances so it feels the same on every screen)
  float md = distance(cpx, uMouse) / uDpr;
  float glow = uMouseAmt * exp(-md * md / (2.0 * 140.0 * 140.0));

  // two diagonal ribbons, warped by slow noise; where they overlap it runs hot (yellow)
  float n1 = snoise(vec3(p * 1.15, t * 0.045));
  float n2 = sin(p.x * 3.1 + p.y * 1.7 + t * 0.21) * 0.5 + sin(p.y * 4.3 - t * 0.17) * 0.5;
  float a = p.y + p.x * 0.55 + n1 * 0.24 + n2 * 0.05 + glow * 0.06;
  float b = p.y - p.x * 0.22 + n1 * 0.16 - n2 * 0.06 - glow * 0.04;
  float r1 = smoothstep(0.42, 1.0, 0.5 + 0.5 * sin(a * 5.4 - t * 0.42));
  float r2 = smoothstep(0.50, 1.0, 0.5 + 0.5 * sin(b * 4.0 + t * 0.29 + 1.3));
  // ribbons sit at red; only where both fold together does it run orange -> yellow
  // a wide, low third wave paints the brown/maroon bands that sit in the dark areas
  float c = p.y * 0.9 + p.x * 0.30 + n1 * 0.30;
  float r3 = smoothstep(0.35, 1.0, 0.5 + 0.5 * sin(c * 7.5 - t * 0.33 + 2.4));
  // ribbons sit at red; patches inside them (slow noise) heat up to orange, then yellow at the hottest folds
  float hot = smoothstep(0.10, 0.80, n1);
  float v = r1 * 0.55 + r2 * 0.30 + hot * r1 * 0.14 + hot * r1 * r2 * 0.40;
  v = max(v, r3 * 0.30);

  // electronic feel: slow scan sweep + faint per-dot flicker
  float sweep = p.y * 0.85 + p.x * 0.35 - mod(t * 0.11, 3.2) + 0.6;
  v += exp(-sweep * sweep * 90.0) * 0.10;
  v += (hash(cell + floor(t * 9.0)) - 0.5) * 0.035;

  // pointer + ripples (also tracked as "lift": the field rests dimmed and lights up where you touch it)
  v += glow * 0.42;
  float lift = glow;
  for (int i = 0; i < 4; i++) {
    float age = t - uRip[i].z;
    if (age > 0.0 && age < 2.2) {
      float d = distance(cpx, uRip[i].xy) / uDpr;
      float ring = (d - age * 380.0) / 34.0;
      float rv = exp(-ring * ring) * (1.0 - age / 2.2);
      v += rv * 0.55; lift += rv;
    }
  }
  v = clamp(v, 0.0, 1.0);
  v = floor(v * 28.0 + 0.5) / 28.0;            // LED brightness steps

  // round dot, nearly touching when bright, small + dim in the dark areas
  float r = uSpacing * mix(0.34, 0.47, v);
  float dist = length(frag - cpx);
  float px = max(uDpr * 0.6, 0.6);
  float dotA = 1.0 - smoothstep(r - px, r + px, dist);
  float bead = mix(1.0, 0.8, smoothstep(0.0, r, dist));   // slight LED bead shading

  // dark ramp: dim dot -> maroon -> red -> orange -> amber
  vec3 col = mix(vec3(0.085, 0.052, 0.058), vec3(0.29, 0.165, 0.173), smoothstep(0.02, 0.30, v));
  col = mix(col, vec3(0.878, 0.125, 0.059), smoothstep(0.30, 0.56, v));
  col = mix(col, vec3(0.973, 0.408, 0.102), smoothstep(0.66, 0.86, v));
  col = mix(col, vec3(1.0, 0.80, 0.42), smoothstep(0.90, 1.05, v));
  float aDark = dotA;

  // light ramp: faint warm dots on the cream page
  vec3 colL = mix(vec3(0.91, 0.78, 0.72), vec3(0.94, 0.27, 0.12), smoothstep(0.2, 0.62, v));
  colL = mix(colL, vec3(0.97, 0.56, 0.16), smoothstep(0.65, 0.95, v));
  float aLight = dotA * mix(0.22, 0.62, v);

  float bright = mix(0.46, 1.0, clamp(lift * 1.4, 0.0, 1.0));
  aLight *= mix(0.62, 1.0, clamp(lift * 1.4, 0.0, 1.0));
  vec3 outC = mix(col * bead * bright, colL, uLight);
  float outA = mix(aDark, aLight, uLight);
  gl_FragColor = vec4(outC * outA, outA);       // premultiplied
}`;

export default function DotWaves({ light = false }) {
  const mount = useRef(null);
  const lightRef = useRef(light);
  lightRef.current = light;

  useEffect(() => {
    const el = mount.current;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false, premultipliedAlpha: true });
    } catch {
      return; // no WebGL: the page keeps its plain --bg background
    }
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(dpr);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const uniforms = {
      uRes: { value: new THREE.Vector2(1, 1) }, uTime: { value: 0 }, uSpacing: { value: 10 },
      uDpr: { value: dpr }, uLight: { value: lightRef.current ? 1 : 0 },
      uMouse: { value: new THREE.Vector2(-1e4, -1e4) }, uMouseAmt: { value: 0 },
      uRip: { value: Array.from({ length: 4 }, () => new THREE.Vector3(0, 0, -99)) },
    };
    const geo = new THREE.PlaneGeometry(2, 2);
    const mat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms,
      transparent: true, blending: THREE.NoBlending, depthWrite: false, depthTest: false });
    scene.add(new THREE.Mesh(geo, mat));

    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h, false);
      uniforms.uRes.value.set(w * dpr, h * dpr);
      // ~75–90 dots across like the reference, clamped so desktop dots stay fine
      uniforms.uSpacing.value = Math.round(Math.min(12, Math.max(6, w / 90)) * dpr);
    };
    resize();
    window.addEventListener("resize", resize);

    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const target = { x: -1e4, y: -1e4, amt: 0 };
    let rip = 0, t = 0, last = performance.now(), raf;
    const toPx = (e) => [e.clientX * dpr, (el.clientHeight - e.clientY) * dpr];
    const onMove = (e) => {
      [target.x, target.y] = toPx(e);
      target.amt = 1;
      if (uniforms.uMouse.value.x < -1e3) uniforms.uMouse.value.set(target.x, target.y);
    };
    const onDown = (e) => {
      onMove(e);
      if (reduced) return;
      const [x, y] = toPx(e);
      uniforms.uRip.value[rip++ % 4].set(x, y, t);
    };
    const onUp = (e) => { if (e.pointerType !== "mouse") target.amt = 0; };
    const onLeave = () => { target.amt = 0; };
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerdown", onDown, { passive: true });
    window.addEventListener("pointerup", onUp, { passive: true });
    window.addEventListener("pointercancel", onLeave);
    document.addEventListener("pointerleave", onLeave);
    window.addEventListener("blur", onLeave);

    const loop = () => {
      const now = performance.now();
      t += Math.min(0.1, (now - last) / 1000) * (reduced ? 0.15 : 1);
      last = now;
      uniforms.uTime.value = t;
      const m = uniforms.uMouse.value;
      m.x += (target.x - m.x) * 0.14; m.y += (target.y - m.y) * 0.14;
      uniforms.uMouseAmt.value += (target.amt - uniforms.uMouseAmt.value) * 0.06;
      uniforms.uLight.value += ((lightRef.current ? 1 : 0) - uniforms.uLight.value) * 0.08;
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onLeave);
      document.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("blur", onLeave);
      geo.dispose(); mat.dispose(); renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={mount} aria-hidden="true" className="pointer-events-none fixed inset-0 -z-20 [&>canvas]:h-full [&>canvas]:w-full" />;
}
