// Wall-mounted AC unit with an animated airflow: a soft plume of additive puffs that follows the
// unit's real louvre angles (up–down and left–right), their swings, the fan speed and the mode.
import * as THREE from 'three';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { box, mat, at } from './kit.js';

export const MODE_COLORS = {
  cool: '#5db2ff',
  heat: '#ff8c3a',
  dry: '#62e0cf',
  fan: '#cfdcff',
  auto: '#9bd28a',
};

const FAN_SPEED = { auto: 0.42, low: 0.26, medium: 0.42, high: 0.62, turbo: 0.9 };
const SWING_ANGLE = { l1: 12, l2: 24, l3: 38, l4: 52, l5: 66, off: 38 };
// Fixed louvre positions 1…5 of a unit with separate axes: degrees below horizontal, and degrees to the side
// (negative = the user's left when facing the unit).
const V_POS = [8, 28, 48, 68, 86];
const H_POS = [-52, -26, 0, 26, 52];
const WALL_ROT = { north: 0, south: Math.PI, west: Math.PI / 2, east: -Math.PI / 2 };

const PUFFS = 70;       // faint mist behind the streamlines
const STREAMS = 34;     // air currents
const SEGS = 9;         // segments per current (fading tail)

export class ACUnit {
  constructor(cfg) {
    this.cfg = cfg;
    this.id = cfg.id;

    this.group = new THREE.Group();
    this.group.position.set(cfg.pos[0], cfg.y, cfg.pos[1]);
    this.group.rotation.y = WALL_ROT[cfg.wall];

    const body = new THREE.Group();
    body.position.z = 0.1 + 0.105; // sit on the inner face of the wall
    const shell = mat('#f3f4f6', { rough: 0.35 });
    this.led = new THREE.MeshStandardMaterial({ color: '#30343c', emissive: '#000000', roughness: 0.4 });
    this.flap = box(0.8, 0.012, 0.075, mat('#e3e5e9', { rough: 0.35 }), { r: 0.004 });
    this.flapPivot = new THREE.Group();
    this.flapPivot.position.set(0, -0.145, 0.03);
    this.flap.position.set(0, -0.006, 0.0375);
    this.flapPivot.add(this.flap);
    body.add(
      at(box(0.94, 0.29, 0.21, shell, { r: 0.05 }), 0, -0.145, 0),
      at(box(0.82, 0.03, 0.09, mat('#17191d', { rough: 0.6 }), { r: 0.006 }), 0, -0.16, 0.055),
      at(box(0.9, 0.004, 0.006, mat('#c9ccd2'), { r: 0 }), 0, 0.02, 0.105),
      at(box(0.085, 0.022, 0.006, this.led, { r: 0.003 }), 0.34, -0.06, 0.105),
      this.flapPivot,
    );
    body.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    this.group.add(body);
    this.body = body;

    // Soft coloured wash so the mode reads on the wall and floor.
    this.wash = new THREE.PointLight(0xffffff, 0, 3.4, 2);
    this.wash.position.set(0, -0.5, 0.75);
    this.group.add(this.wash);

    // The plume: soft round puffs that drift out along the louvre direction, spreading and fading.
    const geo = new THREE.BufferGeometry();
    this.puffPos = new THREE.BufferAttribute(new Float32Array(PUFFS * 3), 3).setUsage(THREE.DynamicDrawUsage);
    this.puffSize = new THREE.BufferAttribute(new Float32Array(PUFFS), 1).setUsage(THREE.DynamicDrawUsage);
    this.puffAlpha = new THREE.BufferAttribute(new Float32Array(PUFFS), 1).setUsage(THREE.DynamicDrawUsage);
    geo.setAttribute('position', this.puffPos);
    geo.setAttribute('aSize', this.puffSize);
    geo.setAttribute('aAlpha', this.puffAlpha);
    this.plumeMat = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color() }, uViewH: { value: ACUnit.viewH } },
      vertexShader: `
        attribute float aSize; attribute float aAlpha; uniform float uViewH; varying float vAlpha;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_Position = projectionMatrix * mv;
          gl_PointSize = aSize * uViewH * 0.5 * projectionMatrix[1][1] / -mv.z;
          vAlpha = aAlpha;
        }`,
      fragmentShader: `
        uniform vec3 uColor; varying float vAlpha;
        void main() {
          vec2 c = gl_PointCoord - 0.5;
          float a = smoothstep(1.0, 0.0, dot(c, c) * 4.0);
          gl_FragColor = vec4(uColor, a * a * vAlpha);
        }`,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    this.flow = new THREE.Points(geo, this.plumeMat);
    this.flow.frustumCulled = false;
    this.flow.position.set(0, -0.17, 0.1 + 0.2);
    this.flow.visible = false;
    this.group.add(this.flow);

    // The air currents: curved streamlines fanning out from the outlet, each a short bright head with a fading tail.
    const sgeo = new LineSegmentsGeometry();
    sgeo.setPositions(new Float32Array(STREAMS * SEGS * 6));
    sgeo.setColors(new Float32Array(STREAMS * SEGS * 6));
    this.streamPos = sgeo.attributes.instanceStart.data;
    this.streamCol = sgeo.attributes.instanceColorStart.data;
    this.streamPos.setUsage(THREE.DynamicDrawUsage);
    this.streamCol.setUsage(THREE.DynamicDrawUsage);
    this.streams = new LineSegments2(sgeo, new LineMaterial({
      linewidth: 2.6, vertexColors: true, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, toneMapped: false,
    }));
    this.streams.frustumCulled = false;
    this.streams.position.copy(this.flow.position);
    this.streams.visible = false;
    this.group.add(this.streams);
    this.lines = Array.from({ length: STREAMS }, (_, i) => {
      const u = ((i * 0.618034) % 1) * 2 - 1;      // across the outlet, -1…1
      const v = ((i * 0.381966 + 0.2) % 1) * 2 - 1; // up/down spread, -1…1
      return { u, v, phase: (i * 0.7548) % 1, speed: 0.8 + ((i * 0.3819) % 1) * 0.5, wobble: i * 2.399 };
    });

    this.seeds = Array.from({ length: PUFFS }, (_, i) => {
      const r = Math.sqrt(((i * 0.7548) % 1));
      const th = (i * 2.399) % (Math.PI * 2);
      return { phase: (i * 0.618034) % 1, u: Math.cos(th) * r, v: Math.sin(th) * r, speed: 0.85 + ((i * 0.3819) % 1) * 0.35, wobble: th };
    });

    this.hit = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.6, 0.6), new THREE.MeshBasicMaterial());
    this.hit.position.set(0, -0.15, 0.25);
    this.hit.visible = false;
    this.hit.userData = { kind: 'ac', id: cfg.id };
    this.group.add(this.hit);

    this.power = 0;
    this.goal = 0;
    this.color = new THREE.Color(MODE_COLORS.cool);
    this.goalColor = this.color.clone();
    this.speed = FAN_SPEED.auto;
    this.swingV = true; this.swingH = false; this.posV = 0; this.posH = 0; this.legacy = 'swing';
    this.angle = 38;
    this.yaw = 0;
    this.clock = 0;
    this.hover = 0;
    this.hoverGoal = 0;
  }

  anchor(out) {
    return out.set(0, 0.12, 0.2).applyMatrix4(this.group.matrixWorld);
  }

  apply(state, { instant = false } = {}) {
    this.goal = state.on ? 1 : 0;
    this.goalColor.set(MODE_COLORS[state.mode] || MODE_COLORS.cool);
    this.speed = FAN_SPEED[state.fan] ?? FAN_SPEED.auto;
    if (state.sleep) this.speed *= 0.6;
    if (state.turbo) this.speed *= 1.3;
    // A unit with separate axes reports swingV / swingH and positions; others have one swing setting.
    const split = 'swingV' in state || 'swingH' in state;
    this.legacy = state.swing;
    this.swingV = split ? Boolean(state.swingV) : state.swing === 'swing';
    this.swingH = split ? Boolean(state.swingH) : false;
    this.posV = split ? (state.angleV || 0) : 0;
    this.posH = split ? (state.angleH || 0) : 0;
    if (instant) { this.power = this.goal; this.color.copy(this.goalColor); }
  }

  update(dt) {
    this.power += (this.goal - this.power) * (1 - Math.exp(-dt * 3.5));
    if (Math.abs(this.goal - this.power) < 0.002) this.power = this.goal;
    this.color.lerp(this.goalColor, 1 - Math.exp(-dt * 5));
    this.hover += (this.hoverGoal - this.hover) * (1 - Math.exp(-dt * 14));
    this.clock += dt;

    const fixedV = this.posV ? V_POS[this.posV - 1] : (SWING_ANGLE[this.legacy] ?? 38);
    const pitch = this.swingV ? 47 + Math.sin(this.clock * 0.9) * 38 : fixedV;
    const fixedH = this.posH ? H_POS[this.posH - 1] : 0;
    const yaw = this.swingH ? Math.sin(this.clock * 0.7 + 1) * 52 : fixedH;
    this.angle += (pitch - this.angle) * (1 - Math.exp(-dt * 4));
    this.yaw += (yaw - this.yaw) * (1 - Math.exp(-dt * 4));

    this.flapPivot.rotation.x = THREE.MathUtils.degToRad(this.angle * 0.9 + 10) * this.power;
    this.led.emissive.copy(this.color);
    this.led.emissiveIntensity = this.power * 3;
    this.wash.color.copy(this.color);
    this.wash.intensity = this.power * 1.4;
    this.body.scale.setScalar(1 + this.hover * 0.06);

    const running = this.power > 0.004;
    this.flow.visible = running;
    this.streams.visible = running;
    if (running) this.writeFlow();
    return running || Math.abs(this.hoverGoal - this.hover) > 0.004 || this.goal !== this.power;
  }

  writeFlow() {
    const pitch = THREE.MathUtils.degToRad(this.angle);
    const yaw = THREE.MathUtils.degToRad(this.yaw);
    const cp = Math.cos(pitch), sp = Math.sin(pitch), sy = Math.sin(yaw), cy = Math.cos(yaw);
    // Direction of the air, the side axis (perpendicular, horizontal) and the third axis.
    const dx = cp * sy, dy = -sp, dz = cp * cy;
    const rx = cy, rz = -sy;                               // side axis (y = 0)
    const ux = -dy * rz, uy = dz * rx - dx * rz, uz = dy * rx; // cross(right, dir)
    const reach = 1.5 + this.speed * 1.7;
    const sink = this.color.r > this.color.b ? -0.3 : 0.5; // cold air sinks, warm air rises
    const pos = this.puffPos.array, size = this.puffSize.array, alpha = this.puffAlpha.array;
    const strength = 0.05 + this.speed * 0.07; // the mist is only a hint; the currents carry the motion

    for (let i = 0; i < PUFFS; i++) {
      const seed = this.seeds[i];
      const t = (seed.phase + this.clock * this.speed * 0.55 * seed.speed) % 1;
      const d = reach * t;
      const spread = 0.05 + 0.5 * t;
      const sway = Math.sin(this.clock * 1.4 + seed.wobble + t * 4) * 0.03 * t;
      const su = (seed.u + sway) * spread, sv = seed.v * spread * 0.85;
      pos[i * 3] = dx * d + rx * su + ux * sv;
      pos[i * 3 + 1] = dy * d + uy * sv - sink * t * t;
      pos[i * 3 + 2] = dz * d + rz * su + uz * sv;
      size[i] = (0.1 + 0.5 * t) * (0.8 + 0.4 * ((i * 0.37) % 1));
      alpha[i] = Math.pow(Math.sin(Math.PI * t), 0.6) * this.power * strength;
    }
    this.puffPos.needsUpdate = true;
    this.puffSize.needsUpdate = true;
    this.puffAlpha.needsUpdate = true;
    this.plumeMat.uniforms.uColor.value.copy(this.color);
    this.plumeMat.uniforms.uViewH.value = ACUnit.viewH;
    this.writeStreams(pitch, yaw, reach, sink);
  }

  writeStreams(pitch, yaw, reach, sink) {
    const pos = this.streamPos.array, col = this.streamCol.array;
    const { r, g, b } = this.color;
    const TAIL = 0.34;                                   // length of a current, as a share of the reach
    const point = (line, t, out, o) => {
      // Each current leaves the outlet at its own angle: the fan widens with distance.
      const yk = yaw + line.u * 0.3 * (0.35 + t);          // radians
      const pk = pitch + line.v * 0.14;
      const cp = Math.cos(pk), sp = Math.sin(pk), sy = Math.sin(yk), cy = Math.cos(yk);
      const d = reach * t;
      const side = line.u * 0.42 * (1 + 0.5 * t) + Math.sin(this.clock * 1.3 + line.wobble + t * 5) * 0.035 * t;
      out[o] = cp * sy * d + Math.cos(yaw) * side;
      out[o + 1] = -sp * d - sink * 0.55 * t * t * reach * 0.5;
      out[o + 2] = cp * cy * d - Math.sin(yaw) * side;
    };
    let k = 0;
    for (const line of this.lines) {
      const head = (line.phase + this.clock * this.speed * 0.5 * line.speed) % 1;
      const fade = Math.pow(Math.sin(Math.PI * head), 0.7) * this.power;
      for (let j = 0; j < SEGS; j++) {
        const t1 = Math.max(0, head - (j / SEGS) * TAIL);
        const t0 = Math.max(0, head - ((j + 1) / SEGS) * TAIL);
        point(line, t0, pos, k * 6);
        point(line, t1, pos, k * 6 + 3);
        const a1 = fade * Math.pow(1 - j / SEGS, 1.4) * 0.8;
        const a0 = fade * Math.pow(1 - (j + 1) / SEGS, 1.4) * 0.8;
        col[k * 6] = r * a0; col[k * 6 + 1] = g * a0; col[k * 6 + 2] = b * a0;
        col[k * 6 + 3] = r * a1; col[k * 6 + 4] = g * a1; col[k * 6 + 5] = b * a1;
        k++;
      }
    }
    this.streamPos.needsUpdate = true;
    this.streamCol.needsUpdate = true;
  }
}

/** Drawing-buffer height in pixels; the world updates it so puff sizes match the view. */
ACUnit.viewH = 900;
