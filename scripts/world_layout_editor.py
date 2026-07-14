#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import threading
import time
import urllib.parse
import webbrowser
import zlib
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORLD = REPO_ROOT / "tb4_overlay_ws/src/turtlebot4_gz_bringup/worlds/small_house.sdf"
DEFAULT_MAP = REPO_ROOT / "assets/maps/turtlebot3_waffle_pi/map.yaml"
WORLDS_DIR = REPO_ROOT / "tb4_overlay_ws/src/turtlebot4_gz_bringup/worlds"
INSTALLED_WORLDS_DIR = REPO_ROOT / "tb4_overlay_ws/install/turtlebot4_gz_bringup/share/turtlebot4_gz_bringup/worlds"

FIXED_NAME_PARTS = (
    "wall", "floor", "ceiling", "window", "door", "foldingdoor", "handle",
    "light", "chandelier", "airconditioner", "rangehood"
)

APP_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Small House Layout Editor</title>
<style>
:root {
  color-scheme: dark;
  --bg: #14161a;
  --panel: #1d2229;
  --panel-2: #252b34;
  --line: #39414d;
  --text: #edf1f7;
  --muted: #aab4c2;
  --accent: #41b883;
  --warn: #f59e0b;
  --danger: #ef4444;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.35 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.app { display: grid; grid-template-columns: 330px 1fr 300px; height: 100vh; }
.panel { background: var(--panel); border-right: 1px solid var(--line); min-width: 0; overflow: auto; }
.panel.right { border-right: 0; border-left: 1px solid var(--line); }
.section { padding: 14px; border-bottom: 1px solid var(--line); }
h1 { font-size: 16px; margin: 0 0 10px; font-weight: 650; }
h2 { font-size: 13px; margin: 0 0 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
input, select, button {
  width: 100%; border: 1px solid var(--line); background: #111419; color: var(--text);
  border-radius: 6px; padding: 8px 9px; font: inherit; min-height: 36px;
}
input[type="checkbox"] { width: auto; min-height: 0; }
button { cursor: pointer; background: var(--panel-2); }
button.primary { background: var(--accent); border-color: #2fa06e; color: #062115; font-weight: 700; }
button.ghost { background: transparent; }
button.danger { background: #3a171a; border-color: #7f1d1d; color: #fecaca; }
button:disabled { opacity: .55; cursor: default; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.row3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.stack { display: grid; gap: 10px; }
.toolbar { display: flex; gap: 8px; align-items: center; }
.toolbar button { width: auto; min-width: 36px; padding: 7px 10px; }
.canvas-wrap { position: relative; overflow: auto; height: 100vh; background: #0c0e11; }
.canvas-pad { position: relative; padding: 28px; min-width: 100%; min-height: 100%; }
.map-stage {
  position: relative; transform-origin: top left; background: #20252c; border: 1px solid #4b5563;
  box-shadow: 0 10px 30px rgb(0 0 0 / .35); user-select: none;
}
.map-img { position: absolute; inset: 0; width: 100%; height: 100%; image-rendering: pixelated; opacity: .72; }
.grid-line { position: absolute; background: rgb(255 255 255 / .06); pointer-events: none; }
.obj {
  position: absolute; width: 24px; height: 24px; margin: -12px 0 0 -12px;
  border: 2px solid #111827; background: #f9fafb; color: #111827; border-radius: 6px;
  display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 800;
  cursor: grab; box-shadow: 0 2px 8px rgb(0 0 0 / .45); transform-origin: 50% 50%;
}
.obj.fixed { opacity: .42; background: #94a3b8; cursor: pointer; }
.obj.selected { outline: 3px solid var(--accent); z-index: 20; }
.obj.dirty::after { content: ""; position: absolute; right: -4px; top: -4px; width: 8px; height: 8px; border-radius: 99px; background: var(--warn); }
.obj .arrow { position: absolute; width: 12px; height: 2px; background: currentColor; right: -9px; top: 50%; transform: translateY(-50%); }
.obj .arrow::after { content: ""; position: absolute; right: -2px; top: -3px; border-left: 5px solid currentColor; border-top: 4px solid transparent; border-bottom: 4px solid transparent; }
.object-list { display: grid; gap: 4px; }
.object-item { padding: 8px; border: 1px solid transparent; border-radius: 6px; cursor: pointer; display: grid; gap: 2px; }
.object-item:hover { background: var(--panel-2); }
.object-item.selected { border-color: var(--accent); background: #173327; }
.object-item.fixed { color: var(--muted); }
.name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status { min-height: 20px; color: var(--muted); }
.status.ok { color: #86efac; }
.status.err { color: #fca5a5; }
.small { color: var(--muted); font-size: 12px; }
@media (max-width: 1000px) { .app { grid-template-columns: 280px 1fr; } .panel.right { display: none; } }
</style>
</head>
<body>
<div class="app">
  <aside class="panel">
    <div class="section">
      <h1>Small House Layout</h1>
      <div class="stack">
        <div>
          <label for="sourceWorld">Source</label>
          <select id="sourceWorld"></select>
        </div>
        <div class="row">
          <button id="reloadBtn" class="ghost">Reload</button>
          <button id="saveBtn" class="primary">Save</button>
        </div>
        <div>
          <label for="outputName">Output world name</label>
          <input id="outputName" value="small_house_edited">
        </div>
        <div id="status" class="status"></div>
      </div>
    </div>
    <div class="section">
      <h2>View</h2>
      <div class="stack">
        <div class="row">
          <button id="zoomOut">-</button>
          <button id="zoomIn">+</button>
        </div>
        <div class="toolbar">
          <input id="showFixed" type="checkbox" checked>
          <label for="showFixed" style="margin:0">Fixed objects</label>
        </div>
        <input id="filter" placeholder="Filter objects">
      </div>
    </div>
    <div class="section">
      <h2>Objects</h2>
      <div id="objectList" class="object-list"></div>
    </div>
  </aside>

  <main class="canvas-wrap" id="canvasWrap">
    <div class="canvas-pad">
      <div id="mapStage" class="map-stage">
        <img id="mapImg" class="map-img" alt="map">
      </div>
    </div>
  </main>

  <aside class="panel right">
    <div class="section">
      <h2>Selection</h2>
      <div class="stack">
        <div><label>Name</label><input id="selName" disabled></div>
        <div><label>Model</label><input id="selUri" disabled></div>
        <div class="row3">
          <div><label>X</label><input id="xInput" type="number" step="0.01"></div>
          <div><label>Y</label><input id="yInput" type="number" step="0.01"></div>
          <div><label>Z</label><input id="zInput" type="number" step="0.01"></div>
        </div>
        <div class="row3">
          <div><label>Roll</label><input id="rollInput" type="number" step="0.01"></div>
          <div><label>Pitch</label><input id="pitchInput" type="number" step="0.01"></div>
          <div><label>Yaw</label><input id="yawInput" type="number" step="0.01"></div>
        </div>
        <div class="row">
          <button id="rotLeft">Rotate -15</button>
          <button id="rotRight">Rotate +15</button>
        </div>
        <button id="resetObj" class="danger">Reset object</button>
      </div>
    </div>
    <div class="section">
      <h2>World</h2>
      <div class="small" id="worldInfo"></div>
    </div>
  </aside>
</div>

<script>
const state = {
  worlds: [], currentWorld: '', map: null, objects: [], selected: null,
  scale: 42, dragging: null, dirty: new Set()
};
const $ = id => document.getElementById(id);
const els = {
  sourceWorld: $('sourceWorld'), stage: $('mapStage'), mapImg: $('mapImg'), list: $('objectList'),
  status: $('status'), outputName: $('outputName'), filter: $('filter'), showFixed: $('showFixed'),
  selName: $('selName'), selUri: $('selUri'), x: $('xInput'), y: $('yInput'), z: $('zInput'),
  roll: $('rollInput'), pitch: $('pitchInput'), yaw: $('yawInput'), worldInfo: $('worldInfo')
};
function setStatus(msg, kind='') { els.status.textContent = msg; els.status.className = 'status ' + kind; }
function shortModel(uri) { return (uri || '').replace('model://', '').replace(/^aws_robomaker_residential_/, ''); }
function deg(rad) { return rad * 180 / Math.PI; }
function rad(deg) { return deg * Math.PI / 180; }
function round(v, n=3) { return Number(v).toFixed(n); }
function worldToScreen(x, y) {
  const m = state.map;
  return { left: (x - m.min_x) * state.scale, top: (m.max_y - y) * state.scale };
}
function screenToWorld(left, top) {
  const m = state.map;
  return { x: m.min_x + left / state.scale, y: m.max_y - top / state.scale };
}
function objectByName(name) { return state.objects.find(o => o.name === name); }
function isFixed(o) { return o.fixed; }
function setDirty(o, dirty=true) {
  if (dirty) state.dirty.add(o.name); else state.dirty.delete(o.name);
}
async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
async function loadIndex() {
  const data = await api('/api/worlds');
  state.worlds = data.worlds;
  els.sourceWorld.innerHTML = '';
  for (const w of data.worlds) {
    const opt = document.createElement('option'); opt.value = w.path; opt.textContent = w.name;
    els.sourceWorld.appendChild(opt);
  }
  els.sourceWorld.value = data.default_world;
  await loadWorld();
}
async function loadWorld() {
  const source = els.sourceWorld.value;
  const data = await api('/api/world?source=' + encodeURIComponent(source));
  state.currentWorld = source;
  state.map = data.map;
  state.objects = data.objects;
  state.selected = null;
  state.dirty.clear();
  els.outputName.value = data.suggested_output;
  renderMap(); renderObjects(); renderList(); renderSelection();
  setStatus('Loaded ' + data.world_name, 'ok');
}
function renderMap() {
  const m = state.map;
  els.stage.style.width = (m.width_m * state.scale) + 'px';
  els.stage.style.height = (m.height_m * state.scale) + 'px';
  els.mapImg.src = '/map.png?source=' + encodeURIComponent(m.yaml_path) + '&t=' + Date.now();
  els.stage.querySelectorAll('.grid-line').forEach(n => n.remove());
  for (let x = Math.ceil(m.min_x); x <= Math.floor(m.max_x); x++) {
    const line = document.createElement('div'); line.className = 'grid-line';
    const p = worldToScreen(x, m.min_y); line.style.left = p.left + 'px'; line.style.top = 0;
    line.style.width = '1px'; line.style.height = '100%'; els.stage.appendChild(line);
  }
  for (let y = Math.ceil(m.min_y); y <= Math.floor(m.max_y); y++) {
    const line = document.createElement('div'); line.className = 'grid-line';
    const p = worldToScreen(m.min_x, y); line.style.left = 0; line.style.top = p.top + 'px';
    line.style.width = '100%'; line.style.height = '1px'; els.stage.appendChild(line);
  }
  els.worldInfo.textContent = `Map ${round(m.min_x,1)}..${round(m.max_x,1)} x ${round(m.min_y,1)}..${round(m.max_y,1)} m`;
}
function renderObjects() {
  els.stage.querySelectorAll('.obj').forEach(n => n.remove());
  const filter = els.filter.value.trim().toLowerCase();
  for (const o of state.objects) {
    if (!els.showFixed.checked && isFixed(o)) continue;
    if (filter && !(o.name.toLowerCase().includes(filter) || shortModel(o.uri).toLowerCase().includes(filter))) continue;
    const el = document.createElement('div'); el.className = 'obj'; el.dataset.name = o.name;
    if (isFixed(o)) el.classList.add('fixed');
    if (state.selected === o.name) el.classList.add('selected');
    if (state.dirty.has(o.name)) el.classList.add('dirty');
    const p = worldToScreen(o.pose.x, o.pose.y);
    el.style.left = p.left + 'px'; el.style.top = p.top + 'px';
    el.style.transform = `rotate(${-deg(o.pose.yaw)}deg)`;
    el.innerHTML = `<span>${o.index}</span><span class="arrow"></span>`;
    el.title = o.name;
    el.addEventListener('pointerdown', ev => startDrag(ev, o.name));
    el.addEventListener('click', ev => { ev.stopPropagation(); selectObject(o.name); });
    els.stage.appendChild(el);
  }
}
function renderList() {
  els.list.innerHTML = '';
  const filter = els.filter.value.trim().toLowerCase();
  for (const o of state.objects) {
    if (!els.showFixed.checked && isFixed(o)) continue;
    if (filter && !(o.name.toLowerCase().includes(filter) || shortModel(o.uri).toLowerCase().includes(filter))) continue;
    const item = document.createElement('div'); item.className = 'object-item';
    if (state.selected === o.name) item.classList.add('selected');
    if (isFixed(o)) item.classList.add('fixed');
    item.innerHTML = `<div class="name">${o.name}${state.dirty.has(o.name) ? ' *' : ''}</div><div class="meta">${shortModel(o.uri)} | ${round(o.pose.x)}, ${round(o.pose.y)}</div>`;
    item.addEventListener('click', () => selectObject(o.name));
    els.list.appendChild(item);
  }
}
function selectObject(name) { state.selected = name; renderObjects(); renderList(); renderSelection(); }
function renderSelection() {
  const o = objectByName(state.selected);
  const disabled = !o;
  for (const el of [els.x, els.y, els.z, els.roll, els.pitch, els.yaw, $('rotLeft'), $('rotRight'), $('resetObj')]) el.disabled = disabled;
  els.selName.value = o ? o.name : '';
  els.selUri.value = o ? shortModel(o.uri) : '';
  if (!o) return;
  els.x.value = round(o.pose.x); els.y.value = round(o.pose.y); els.z.value = round(o.pose.z);
  els.roll.value = round(o.pose.roll); els.pitch.value = round(o.pose.pitch); els.yaw.value = round(o.pose.yaw);
}
function applyInputs() {
  const o = objectByName(state.selected); if (!o) return;
  const vals = { x:+els.x.value, y:+els.y.value, z:+els.z.value, roll:+els.roll.value, pitch:+els.pitch.value, yaw:+els.yaw.value };
  for (const [k,v] of Object.entries(vals)) if (Number.isFinite(v)) o.pose[k] = v;
  setDirty(o); renderObjects(); renderList();
}
function rotateSelected(deltaDeg) {
  const o = objectByName(state.selected); if (!o) return;
  o.pose.yaw += rad(deltaDeg); setDirty(o); renderObjects(); renderList(); renderSelection();
}
function resetSelected() {
  const o = objectByName(state.selected); if (!o) return;
  Object.assign(o.pose, o.original_pose); setDirty(o, false); renderObjects(); renderList(); renderSelection();
}
function startDrag(ev, name) {
  const o = objectByName(name); selectObject(name);
  if (!o || isFixed(o)) return;
  const rect = els.stage.getBoundingClientRect();
  const p = worldToScreen(o.pose.x, o.pose.y);
  state.dragging = { name, dx: ev.clientX - rect.left - p.left, dy: ev.clientY - rect.top - p.top };
  ev.currentTarget.setPointerCapture(ev.pointerId);
}
window.addEventListener('pointermove', ev => {
  if (!state.dragging) return;
  const rect = els.stage.getBoundingClientRect();
  const left = ev.clientX - rect.left - state.dragging.dx;
  const top = ev.clientY - rect.top - state.dragging.dy;
  const p = screenToWorld(left, top);
  const o = objectByName(state.dragging.name); if (!o) return;
  o.pose.x = p.x; o.pose.y = p.y; setDirty(o); renderObjects(); renderList(); renderSelection();
});
window.addEventListener('pointerup', () => { state.dragging = null; });
els.stage.addEventListener('click', () => selectObject(null));
async function saveWorld() {
  const output = els.outputName.value.trim();
  if (!output) { setStatus('Missing output world name', 'err'); return; }
  const payload = { source: state.currentWorld, output_name: output, objects: state.objects.map(o => ({ name: o.name, pose: o.pose })) };
  $('saveBtn').disabled = true;
  try {
    const data = await api('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    setStatus('Saved ' + data.path, 'ok');
  } catch (err) { setStatus(err.message, 'err'); }
  finally { $('saveBtn').disabled = false; }
}
$('reloadBtn').addEventListener('click', loadWorld);
$('saveBtn').addEventListener('click', saveWorld);
$('zoomIn').addEventListener('click', () => { state.scale = Math.min(95, state.scale * 1.18); renderMap(); renderObjects(); });
$('zoomOut').addEventListener('click', () => { state.scale = Math.max(18, state.scale / 1.18); renderMap(); renderObjects(); });
els.filter.addEventListener('input', () => { renderObjects(); renderList(); });
els.showFixed.addEventListener('change', () => { renderObjects(); renderList(); });
els.sourceWorld.addEventListener('change', loadWorld);
for (const el of [els.x, els.y, els.z, els.roll, els.pitch, els.yaw]) el.addEventListener('change', applyInputs);
$('rotLeft').addEventListener('click', () => rotateSelected(-15));
$('rotRight').addEventListener('click', () => rotateSelected(15));
$('resetObj').addEventListener('click', resetSelected);
loadIndex().catch(err => setStatus(err.message, 'err'));
</script>
</body>
</html>
"""

@dataclass
class MapInfo:
    yaml_path: Path
    image_path: Path
    resolution: float
    origin_x: float
    origin_y: float
    width: int
    height: int

    @property
    def width_m(self) -> float:
        return self.width * self.resolution

    @property
    def height_m(self) -> float:
        return self.height * self.resolution

    def to_json(self) -> dict:
        return {
            "yaml_path": str(self.yaml_path),
            "image_path": str(self.image_path),
            "resolution": self.resolution,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "width": self.width,
            "height": self.height,
            "width_m": self.width_m,
            "height_m": self.height_m,
            "min_x": self.origin_x,
            "max_x": self.origin_x + self.width_m,
            "min_y": self.origin_y,
            "max_y": self.origin_y + self.height_m,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Top-down editor for TurtleBot small_house SDF model poses.")
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD, help="Default source world SDF")
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP, help="Nav2 map YAML used as background")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the editor in the default browser")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def parse_simple_yaml(path: Path) -> dict:
    data: dict[str, object] = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [float(part.strip()) for part in value[1:-1].split(",")]
        elif re.fullmatch(r"[-+0-9.eE]+", value):
            data[key] = float(value)
        else:
            data[key] = value.strip('"\'')
    return data


def read_pgm_header(path: Path) -> tuple[str, int, int, int, bytes]:
    with path.open("rb") as f:
        magic = f.readline().strip().decode("ascii")
        if magic not in {"P5", "P2"}:
            raise ValueError(f"Unsupported PGM format {magic}: {path}")
        tokens: list[bytes] = []
        while len(tokens) < 3:
            line = f.readline()
            if not line:
                break
            line = line.split(b"#", 1)[0]
            tokens.extend(line.split())
        if len(tokens) < 3:
            raise ValueError(f"Invalid PGM header: {path}")
        width, height, maxval = map(int, tokens[:3])
        rest = f.read()
    return magic, width, height, maxval, rest


def load_map_info(yaml_path: Path) -> MapInfo:
    yaml_path = resolve_path(yaml_path)
    data = parse_simple_yaml(yaml_path)
    image_value = str(data.get("image", ""))
    image_path = Path(image_value)
    if not image_path.is_absolute():
        image_path = yaml_path.parent / image_path
    magic, width, height, _maxval, _data = read_pgm_header(image_path)
    if magic != "P5":
        raise ValueError("Only binary P5 PGM maps are supported for preview")
    origin = data.get("origin", [-10.0, -10.0, 0.0])
    return MapInfo(
        yaml_path=yaml_path,
        image_path=image_path.resolve(),
        resolution=float(data.get("resolution", 0.05)),
        origin_x=float(origin[0]),
        origin_y=float(origin[1]),
        width=width,
        height=height,
    )


def pgm_to_png(path: Path) -> bytes:
    magic, width, height, maxval, data = read_pgm_header(path)
    if magic != "P5":
        raise ValueError("Only binary P5 PGM maps can be converted")
    expected = width * height
    if len(data) < expected:
        raise ValueError("PGM data is shorter than expected")
    raw = data[:expected]
    if maxval != 255:
        raw = bytes(int(value * 255 / maxval) for value in raw)
    rgba = bytearray()
    for y in range(height):
        rgba.append(0)
        start = y * width
        row = raw[start:start + width]
        for value in row:
            rgba.extend((value, value, value, 255))
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(rgba), 9)) + chunk(b"IEND", b"")


def parse_pose(text: str | None) -> dict[str, float]:
    values = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if text:
        parts = text.split()
        for i, part in enumerate(parts[:6]):
            try:
                values[i] = float(part)
            except ValueError:
                values[i] = 0.0
    return {"x": values[0], "y": values[1], "z": values[2], "roll": values[3], "pitch": values[4], "yaw": values[5]}


def format_pose(pose: dict[str, float]) -> str:
    ordered = [pose.get("x", 0.0), pose.get("y", 0.0), pose.get("z", 0.0), pose.get("roll", 0.0), pose.get("pitch", 0.0), pose.get("yaw", 0.0)]
    return " ".join(f"{float(value):.6f}" for value in ordered)


def classify_fixed(name: str, uri: str) -> bool:
    text = f"{name} {uri}".lower()
    return any(part in text for part in FIXED_NAME_PARTS)


def load_world(path: Path, map_info: MapInfo) -> dict:
    path = resolve_path(path)
    root = ET.parse(path).getroot()
    world = root.find("world")
    if world is None:
        raise ValueError(f"No <world> in {path}")
    objects = []
    for index, model in enumerate(world.findall("model"), start=1):
        name = model.get("name", f"model_{index}")
        uri = model.findtext("include/uri", default="")
        pose = parse_pose(model.findtext("pose"))
        fixed = classify_fixed(name, uri)
        objects.append({
            "index": index,
            "name": name,
            "uri": uri,
            "pose": pose.copy(),
            "original_pose": pose.copy(),
            "fixed": fixed,
        })
    suggested = path.stem + "_edited"
    return {
        "world_name": world.get("name", path.stem),
        "source_path": str(path),
        "suggested_output": suggested,
        "map": map_info.to_json(),
        "objects": objects,
    }


def safe_world_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip())
    clean = clean.strip("._-")
    if not clean:
        raise ValueError("Output world name is empty")
    if clean in {"small_house", "warehouse", "depot", "maze", "living_room"}:
        raise ValueError("Refusing to overwrite a built-in world name")
    return clean


def replace_world_name(text: str, new_name: str) -> str:
    return re.sub(r"<world\s+name=(['\"])[^'\"]+\1", f"<world name='{new_name}'", text, count=1)


def replace_model_pose(text: str, model_name: str, pose_text: str) -> str:
    escaped = re.escape(model_name)
    pattern = re.compile(
        rf"(<model\s+name=(['\"]){escaped}\2\s*>.*?<pose\b[^>]*>)(.*?)(</pose>)",
        re.DOTALL,
    )
    next_text, count = pattern.subn(lambda m: m.group(1) + pose_text + m.group(4), text, count=1)
    if count == 0:
        raise ValueError(f"Could not find pose for model {model_name}")
    return next_text


def save_world(source: Path, output_name: str, objects: list[dict]) -> tuple[Path, Path | None]:
    source = resolve_path(source)
    name = safe_world_name(output_name)
    output_path = WORLDS_DIR / f"{name}.sdf"
    if output_path.resolve() == source.resolve():
        raise ValueError("Output path must differ from source world")
    text = source.read_text()
    text = replace_world_name(text, name)
    for obj in objects:
        pose = obj.get("pose", {})
        text = replace_model_pose(text, str(obj["name"]), format_pose(pose))
    output_path.write_text(text)

    installed_path = None
    if INSTALLED_WORLDS_DIR.exists():
        installed_path = INSTALLED_WORLDS_DIR / output_path.name
        installed_path.write_text(text)
    return output_path, installed_path


def list_worlds(default_world: Path) -> dict:
    worlds = []
    for path in sorted(WORLDS_DIR.glob("*.sdf")):
        worlds.append({"name": path.stem, "path": str(path.resolve())})
    default_path = resolve_path(default_world)
    return {"worlds": worlds, "default_world": str(default_path)}


class EditorHandler(BaseHTTPRequestHandler):
    map_info: MapInfo
    default_world: Path

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: HTTPStatus, data: dict) -> None:
        self.send_bytes(status, json.dumps(data).encode("utf-8"), "application/json")

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json(status, {"error": message})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/" or parsed.path == "/index.html":
                self.send_bytes(HTTPStatus.OK, APP_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif parsed.path == "/api/worlds":
                self.send_json(HTTPStatus.OK, list_worlds(self.default_world))
            elif parsed.path == "/api/world":
                query = urllib.parse.parse_qs(parsed.query)
                source = Path(query.get("source", [str(self.default_world)])[0])
                self.send_json(HTTPStatus.OK, load_world(source, self.map_info))
            elif parsed.path == "/map.png":
                self.send_bytes(HTTPStatus.OK, pgm_to_png(self.map_info.image_path), "image/png")
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/save":
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            output_path, installed_path = save_world(Path(payload["source"]), str(payload["output_name"]), list(payload["objects"]))
            self.send_json(HTTPStatus.OK, {
                "path": str(output_path),
                "installed_path": str(installed_path) if installed_path else None,
                "world_name": output_path.stem,
            })
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))


def main() -> int:
    args = parse_args()
    map_info = load_map_info(args.map)
    default_world = resolve_path(args.world)
    handler = type("ConfiguredEditorHandler", (EditorHandler,), {"map_info": map_info, "default_world": default_world})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"World layout editor: {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping editor.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
