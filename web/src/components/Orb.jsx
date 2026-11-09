import { useEffect, useRef } from "react";
import * as THREE from "three";

// Simplex noise (Ashima / Stefan Gustavson, MIT)
export const NOISE = `
vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1./6.,1./3.); const vec4 D=vec4(0.,.5,1.,2.);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
  float n_=.142857142857; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.+1.; vec4 s1=floor(b1)*2.+1.; vec4 sh=-step(h,vec4(0.));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
  vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.); m=m*m;
  return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

const VERT = `
uniform float uTime, uLow, uMid, uHigh, uBusy;
varying float vDisp; varying vec3 vNormal; varying vec3 vView;
${NOISE}
void main(){
  vec3 p = position;
  float slow = snoise(p*0.9 + uTime*0.18);
  float mid  = snoise(p*2.2 + vec3(uTime*0.6));
  float fine = snoise(p*5.0 - uTime*1.2);
  float d = slow*(0.10 + uLow*0.22) + mid*(0.04 + uMid*0.10) + fine*(0.008 + uHigh*0.025);
  d += uBusy * 0.08 * sin(uTime*6.0 + p.y*8.0);
  vDisp = d;
  vec3 np = p + normal * d;
  vec4 mv = modelViewMatrix * vec4(np, 1.0);
  vNormal = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;

const FRAG = `
uniform vec3 uA, uB; uniform float uTime, uHigh, uAlpha;
varying float vDisp; varying vec3 vNormal; varying vec3 vView;
void main(){
  float fres = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.2);
  vec3 col = mix(uB, uA, smoothstep(-0.15, 0.25, vDisp));
  col += fres * mix(uA, vec3(1.0, 0.85, 0.7), 0.4) * (0.9 + uHigh);
  float alpha = 0.18 + fres * 0.9;
  gl_FragColor = vec4(col * uAlpha, alpha * uAlpha);
}`;

/**
 * Full-screen audio-reactive orb.
 * getAnalyser(): returns an AnalyserNode or null. busy: 0..1 processing pulse.
 * palette: [hexA, hexB] tweened smoothly.
 */
export default function Orb({ getAnalyser, busy = 0, palette = ["#ff5a36", "#6d28d9"], light = false }) {
  const mount = useRef(null);
  const state = useRef({ busy, palette, light });
  state.current.busy = busy;
  state.current.palette = palette;
  state.current.light = light;

  useEffect(() => {
    const el = mount.current;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    camera.position.set(0, 0, 6);

    const uniforms = {
      uTime: { value: 0 }, uLow: { value: 0 }, uMid: { value: 0 }, uHigh: { value: 0 },
      uBusy: { value: 0 }, uA: { value: new THREE.Color(state.current.palette[0]) },
      uB: { value: new THREE.Color(state.current.palette[1]) }, uAlpha: { value: 0.85 },
    };
    const wireUniforms = { ...uniforms, uAlpha: { value: 0.14 } };
    const orb = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.35, 40),
      new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms,
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }),
    );
    scene.add(orb);
    const wire = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.36, 40),
      new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms: wireUniforms,
        transparent: true, wireframe: true, depthWrite: false, blending: THREE.AdditiveBlending }),
    );
    wire.scale.setScalar(1.002);
    scene.add(wire);

    // particle halo: frequency ring
    const N = 1400;
    const pos = new Float32Array(N * 3), base = new Float32Array(N * 3), seed = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const a = Math.random() * Math.PI * 2, r = 2.1 + Math.random() * 1.6;
      const y = (Math.random() - 0.5) * 0.5 * (r - 1.8);
      base.set([Math.cos(a) * r, y, Math.sin(a) * r], i * 3);
      seed[i] = Math.random();
    }
    pos.set(base);
    const pgeo = new THREE.BufferGeometry();
    pgeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const pmat = new THREE.PointsMaterial({ size: 0.022, color: state.current.palette[0], transparent: true,
      opacity: 0.7, depthWrite: false, blending: THREE.AdditiveBlending });
    const halo = new THREE.Points(pgeo, pmat);
    halo.rotation.x = 0.42;
    scene.add(halo);

    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // keep the orb comfortably in frame on narrow phones
      camera.position.z = w < h ? 8.2 : 6;
      // sit the orb behind the headline on phones, centred-right on desktop
      const y = w < h ? 1.25 : 0.1, x = w < h ? 0.25 : -1.9;
      [orb, wire, halo].forEach((m) => m.position.set(x, y, 0));
      camera.updateProjectionMatrix();
    };
    resize();
    window.addEventListener("resize", resize);

    let freq = null, raf, t0 = performance.now(), wasLight = null;
    const mats = [orb.material, wire.material, pmat];
    const applyTheme = (lt) => {
      // additive glow vanishes on a light page: switch to normal blending + stronger alpha
      mats.forEach((m) => { m.blending = lt ? THREE.NormalBlending : THREE.AdditiveBlending; m.needsUpdate = true; });
      uniforms.uAlpha.value = lt ? 0.95 : 0.85;
      wireUniforms.uAlpha.value = lt ? 0.3 : 0.14;
      pmat.opacity = lt ? 0.55 : 0.7;
    };
    const ca = new THREE.Color(), cb = new THREE.Color();
    const band = (lo, hi) => {
      let s = 0;
      for (let i = lo; i < hi; i++) s += freq[i];
      return s / ((hi - lo) * 255);
    };
    const loop = () => {
      if (state.current.light !== wasLight) { wasLight = state.current.light; applyTheme(wasLight); }
      const t = (performance.now() - t0) / 1000;
      uniforms.uTime.value = t;
      const an = getAnalyser?.();
      let low = 0, mid = 0, high = 0;
      if (an) {
        if (!freq || freq.length !== an.frequencyBinCount) freq = new Uint8Array(an.frequencyBinCount);
        an.getByteFrequencyData(freq);
        low = band(1, 12); mid = band(12, 90); high = band(90, 300);
      }
      const k = 0.18;
      // soft-knee so loud mastered audio breathes instead of spiking
      const soft = (v) => Math.min(1, v) ** 1.4;
      uniforms.uLow.value += (soft(low * 1.1) - uniforms.uLow.value) * k;
      uniforms.uMid.value += (soft(mid * 1.3) - uniforms.uMid.value) * k;
      uniforms.uHigh.value += (soft(high * 1.8) - uniforms.uHigh.value) * k;
      uniforms.uBusy.value += (state.current.busy - uniforms.uBusy.value) * 0.05;
      ca.set(state.current.palette[0]); cb.set(state.current.palette[1]);
      uniforms.uA.value.lerp(ca, 0.04); uniforms.uB.value.lerp(cb, 0.04);
      pmat.color.lerp(ca, 0.03);

      const spin = 0.08 + uniforms.uBusy.value * 0.6;
      orb.rotation.y = wire.rotation.y = t * spin;
      orb.rotation.z = wire.rotation.z = Math.sin(t * 0.2) * 0.2;
      halo.rotation.y = -t * (0.05 + uniforms.uBusy.value * 0.4);
      const kick = 1 + uniforms.uLow.value * 0.15;
      for (let i = 0; i < N; i++) {
        const j = i * 3, w = 1 + Math.sin(t * 2 + seed[i] * 40) * 0.02 * (1 + uniforms.uHigh.value * 6);
        pos[j] = base[j] * w * kick; pos[j + 1] = base[j + 1] * (1 + uniforms.uMid.value);
        pos[j + 2] = base[j + 2] * w * kick;
      }
      pgeo.attributes.position.needsUpdate = true;
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [getAnalyser]);

  return <div ref={mount} className="fixed inset-0 -z-10 [&>canvas]:h-full [&>canvas]:w-full" />;
}
