#!/usr/bin/env python3
"""
Transform: rotates a grid inside a saved SS14 map/grid .yml by quarter turns.

Coordinate conventions of the engine (RobustToolbox):
  * grid-local +Y is North, +X is East;
  * Angle 0 is South, positive angles turn counter-clockwise (East = +pi/2, North = pi, West = -pi/2);
  * "left" = counter-clockwise = +90 degrees.

What gets rotated for every target grid:
  * MapGrid tiles (chunk base64, the per-tile RotationMirroring byte of tiles with allowRotationMirror);
  * Transform pos/rot of every entity parented directly to the grid (contained items follow their holder);
  * DecalGrid decals (position and angle);
  * GridAtmosphere tile air;
  * Roof per-tile flags.
The grid entity itself keeps its own position and rotation, so the ship turns in place around --pivot.

Things that must look the same on screen afterwards:
  * tiles and decals whose direction is part of the prototype id (PlatingCornerNE, BrickTileWhiteLineN,
    CatwalkVertical, ...) are swapped for the turned prototype instead of being rotated;
  * decals with snapCardinals or an "upright" tag (flora, rock, dirty, burnt) and items (Item component)
    are moved but keep their angle, otherwise their side-view sprites would lie on their side.

Usage:
  python Tools/transform_grid.py <map.yml> [-o out.yml] [--turn left|right|180] [--grid UID]
                                 [--pivot X,Y|center] [--show]
"""

from __future__ import annotations

import argparse
import base64
import math
import re
import struct
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

PROTO_RE = re.compile(r"^- proto:\s*['\"]?(.*?)['\"]?\s*$")
ENTITY_RE = re.compile(r"^  - uid: (\d+)\s*$")
COMPONENT_RE = re.compile(r"^    - type: (\S+)\s*$")
TRANSFORM_FIELD_RE = re.compile(r"^      (\w+):\s*(.*?)\s*$")
KEY_VALUE_RE = re.compile(r"^(\s*)([^:\s][^:]*?):\s*(.*?)\s*$")

TURNS = {"left": 1, "ccw": 1, "180": 2, "right": 3, "cw": 3}

UPRIGHT_DECAL_TAGS = {"flora", "rock", "dirty", "burnt"}

DIR_TOKEN_RE = re.compile(
    r"(NorthEast|NorthWest|SouthEast|SouthWest|North|South|East|West|Vertical|Horizontal"
    r"|NE|NW|SE|SW|Ne|Nw|Se|Sw|N|S|E|W)(?=[A-Z0-9_]|$)")
DIR_VECTORS = {"n": (0, 1), "s": (0, -1), "e": (1, 0), "w": (-1, 0)}
DIR_WORDS = {"n": "North", "s": "South", "e": "East", "w": "West"}


# ---------------------------------------------------------------- formatting

def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def fmt_float32(value: float) -> str:
    """Shortest round-trip float32 text, like .NET float.ToString(InvariantCulture)."""
    packed = struct.unpack("<f", struct.pack("<f", value))[0]
    text = repr(packed)
    for digits in range(1, 10):
        candidate = f"{packed:.{digits}g}"
        if struct.unpack("<f", struct.pack("<f", float(candidate)))[0] == packed:
            text = candidate
            break
    text = format(Decimal(text), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def fmt_vec(x: float, y: float) -> str:
    return f"{fmt_float32(x)},{fmt_float32(y)}"


def parse_vec(text: str) -> tuple[float, float]:
    x, y = text.split(",")
    return float(x), float(y)


def parse_ivec(text: str) -> tuple[int, int]:
    x, y = text.split(",")
    return int(x), int(y)


def parse_angle(text: str) -> float:
    text = text.strip().strip("'\"")
    if text.endswith("rad"):
        return float(text[:-3])
    if text.endswith("deg"):
        return math.radians(float(text[:-3]))
    return float(text)


def normalize_angle(theta: float) -> float:
    """Wraps into (-pi, pi] and snaps near-cardinal values to exact multiples of pi/2."""
    quarter = theta / (math.pi / 2)
    nearest = round(quarter)
    if abs(quarter - nearest) < 1e-6:
        nearest %= 4
        return {0: 0.0, 1: math.pi / 2, 2: math.pi, 3: -math.pi / 2}[nearest]
    theta = math.fmod(theta, 2 * math.pi)
    if theta <= -math.pi:
        theta += 2 * math.pi
    elif theta > math.pi:
        theta -= 2 * math.pi
    return theta


def fmt_angle(theta: float) -> str:
    return f"{repr(float(theta))} rad"


# ---------------------------------------------------------------- rotation math

def rotate_offset(dx: float, dy: float, turns: int) -> tuple[float, float]:
    if turns == 1:
        return -dy, dx
    if turns == 2:
        return -dx, -dy
    if turns == 3:
        return dy, -dx
    return dx, dy


def rotate_tile(index: tuple[int, int], pivot: tuple[int, int], turns: int) -> tuple[int, int]:
    """Tile index after turning the tile square around the integer grid point `pivot`."""
    dx, dy = index[0] - pivot[0], index[1] - pivot[1]
    if turns == 1:
        return pivot[0] - dy - 1, pivot[1] + dx
    if turns == 2:
        return pivot[0] - dx - 1, pivot[1] - dy - 1
    if turns == 3:
        return pivot[0] + dy, pivot[1] - dx - 1
    return index


def rotate_point(x: float, y: float, pivot: tuple[float, float], turns: int) -> tuple[float, float]:
    rx, ry = rotate_offset(x - pivot[0], y - pivot[1], turns)
    return pivot[0] + rx, pivot[1] + ry


def rotate_tile_visual(value: int, turns: int) -> int:
    # Clyde mirrors after rotating, so a mirrored tile steps the other way.
    if value >= 4:
        return 4 + (value - 4 - turns) % 4
    return (value + turns) % 4


def rotate_direction_token(token: str, turns: int) -> str:
    if token in ("Vertical", "Horizontal"):
        return token if turns % 2 == 0 else ("Horizontal" if token == "Vertical" else "Vertical")
    words = re.findall(r"North|South|East|West", token)
    letters = [w[0].lower() for w in words] if words else list(token.lower())
    vx = sum(DIR_VECTORS[c][0] for c in letters)
    vy = sum(DIR_VECTORS[c][1] for c in letters)
    vx, vy = rotate_offset(vx, vy, turns)
    out = ([] if vy == 0 else ["n" if vy > 0 else "s"]) + ([] if vx == 0 else ["e" if vx > 0 else "w"])
    if words:
        return "".join(DIR_WORDS[c] for c in out)
    if token.isupper():
        return "".join(out).upper()
    return "".join(out).capitalize()


def rotate_name(name: str, turns: int, known: set[str]) -> str | None:
    """Prototype id with its direction tokens turned (PlatingCornerNE -> PlatingCornerNW), if it exists."""
    matches = list(DIR_TOKEN_RE.finditer(name))
    if not matches:
        return None
    turned = [rotate_direction_token(m.group(1), turns) for m in matches]
    candidates = [turned]
    # A diagonal written as two adjacent directions reads the same both ways: CheckerSWNE == CheckerNESW.
    if len(matches) == 2 and matches[0].end() == matches[1].start():
        candidates.append(turned[::-1])
    for tokens in candidates:
        parts, last = [], 0
        for m, token in zip(matches, tokens):
            parts += [name[last:m.start()], token]
            last = m.end()
        candidate = "".join(parts) + name[last:]
        if candidate != name and candidate in known:
            return candidate
    return None


# ---------------------------------------------------------------- yaml structure

@dataclass
class Component:
    type: str
    start: int
    end: int


@dataclass
class Entity:
    uid: int
    start: int
    end: int
    proto: str = ""
    components: list[Component] = field(default_factory=list)

    def component(self, name: str) -> Component | None:
        return next((c for c in self.components if c.type == name), None)


def parse_entities(lines: list[str]) -> list[Entity]:
    try:
        begin = lines.index("entities:")
    except ValueError:
        raise SystemExit("No top-level 'entities:' section found.")

    entities: list[Entity] = []
    current: Entity | None = None
    comp: Component | None = None
    proto = ""

    def close(at: int):
        nonlocal current, comp
        if comp is not None:
            comp.end = at
            comp = None
        if current is not None:
            current.end = at
            entities.append(current)
            current = None

    for i in range(begin + 1, len(lines)):
        line = lines[i]
        match = PROTO_RE.match(line)
        if match:
            close(i)
            proto = match.group(1)
            continue
        match = ENTITY_RE.match(line)
        if match:
            close(i)
            current = Entity(int(match.group(1)), i, len(lines), proto)
            continue
        if current is None:
            continue
        if line and not line.startswith("    "):
            close(i)
            continue
        match = COMPONENT_RE.match(line)
        if match:
            if comp is not None:
                comp.end = i
            comp = Component(match.group(1), i, len(lines))
            current.components.append(comp)
            continue
        if comp is not None and line.strip() and indent_of(line) <= 4:
            comp.end = i
            comp = None
    close(len(lines))
    return entities


def find_child_block(lines: list[str], start: int, end: int, key: str) -> tuple[int, int, int, int] | None:
    """Locates `key:` within [start, end); returns (key_line, block_start, block_end, key_indent)."""
    pattern = re.compile(rf"^(\s*){re.escape(key)}:\s*(.*?)\s*$")
    for i in range(start, end):
        match = pattern.match(lines[i])
        if not match:
            continue
        ind = len(match.group(1))
        j = i + 1
        while j < end:
            line = lines[j]
            if line.strip() and not (indent_of(line) > ind or
                                     (indent_of(line) == ind and line.lstrip().startswith("- "))):
                break
            j += 1
        return i, i + 1, j, ind
    return None


def parse_tilemap(lines: list[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    try:
        i = lines.index("tilemap:") + 1
    except ValueError:
        return result
    while i < len(lines) and lines[i].startswith("  "):
        key, _, value = lines[i].strip().partition(":")
        result[int(key)] = value.strip()
        i += 1
    return result


# ---------------------------------------------------------------- tile prototypes

def find_prototypes_dir(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        candidate = parent / "Resources" / "Prototypes"
        if candidate.is_dir():
            return candidate
        if parent.name == "Resources" and (parent / "Prototypes").is_dir():
            return parent / "Prototypes"
    return None


@dataclass
class Prototypes:
    tiles: set[str]
    rotatable_tiles: set[str]
    decals: set[str]
    upright_decals: set[str]
    items: set[str]


def parse_list_field(block: str, key: str) -> list[str]:
    """`key: X`, `key: [A, B]` or a block list of `- A` lines."""
    match = re.search(rf"(?m)^  {key}:[ \t]*([^#\n]*)", block)
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw:
        tail = block[match.end():]
        raw = ",".join(re.findall(r"(?m)^\s+- ([^#\s]+)", re.split(r"(?m)^  \w", tail, maxsplit=1)[0]))
    return [p.strip().strip("'\"") for p in raw.strip("[]").split(",") if p.strip()]


def component_types(block: str) -> set[str]:
    match = re.search(r"(?m)^  components:\s*$", block)
    if not match:
        return set()
    types: set[str] = set()
    indent = None
    for line in block[match.end():].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if indent_of(line) <= 2 and not line.lstrip().startswith("- "):
            break
        item = re.match(r"^(\s*)- type:\s*(\S+)", line)
        if item and (indent is None or len(item.group(1)) == indent):
            indent = len(item.group(1))
            types.add(item.group(2))
    return types


def resolve_inherited(own: dict[str, bool | None], parents: dict[str, list[str]]) -> set[str]:
    cache: dict[str, bool] = {}

    def value(proto_id: str, depth: int = 0) -> bool:
        if proto_id in cache:
            return cache[proto_id]
        result = own.get(proto_id)
        if result is None:
            result = depth < 64 and any(value(p, depth + 1) for p in parents.get(proto_id, []))
        cache[proto_id] = result
        return result

    return {proto_id for proto_id in own if value(proto_id)}


def load_prototypes(prototypes: Path) -> Prototypes:
    tile_flags: dict[str, bool | None] = {}
    tile_parents: dict[str, list[str]] = {}
    decals: set[str] = set()
    upright_decals: set[str] = set()
    item_flags: dict[str, bool | None] = {}
    entity_parents: dict[str, list[str]] = {}

    for path in prototypes.rglob("*.yml"):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        for block in re.split(r"(?m)^- (?=type:)", text):
            head = re.match(r"type:\s*(\w+)\s*$", block.splitlines()[0] if block else "")
            if not head or head.group(1) not in ("tile", "decal", "entity"):
                continue
            id_match = re.search(r"(?m)^  id:\s*['\"]?([^'\"\s]+)", block)
            if not id_match:
                continue
            proto_id = id_match.group(1)
            kind = head.group(1)
            if kind == "tile":
                flag = re.search(r"(?m)^  allowRotationMirror:\s*(\S+)", block)
                tile_flags[proto_id] = None if flag is None else flag.group(1).lower() == "true"
                tile_parents[proto_id] = parse_list_field(block, "parent")
            elif kind == "decal":
                decals.add(proto_id)
                tags = set(parse_list_field(block, "tags"))
                snap = re.search(r"(?m)^  snapCardinals:\s*true", block, re.IGNORECASE)
                if snap or tags & UPRIGHT_DECAL_TAGS:
                    upright_decals.add(proto_id)
            else:
                item_flags[proto_id] = True if "Item" in component_types(block) else None
                entity_parents[proto_id] = parse_list_field(block, "parent")

    return Prototypes(
        tiles=set(tile_flags),
        rotatable_tiles=resolve_inherited(tile_flags, tile_parents),
        decals=decals,
        upright_decals=upright_decals,
        items=resolve_inherited(item_flags, entity_parents),
    )


# ---------------------------------------------------------------- grid data

@dataclass
class TileData:
    yaml_id: int
    flags: int
    variant: int
    rotation: int


def decode_chunks(lines: list[str], comp: Component, space_ids: set[int]):
    block = find_child_block(lines, comp.start + 1, comp.end, "chunks")
    chunk_size = 16
    size_match = find_child_block(lines, comp.start + 1, comp.end, "chunkSize")
    if size_match:
        chunk_size = int(lines[size_match[0]].split(":")[1])
    tiles: dict[tuple[int, int], TileData] = {}
    if block is None:
        return tiles, None, chunk_size

    key_line, b_start, b_end, ind = block
    i = b_start
    while i < b_end:
        line = lines[i]
        if not line.strip() or indent_of(line) != ind + 2:
            i += 1
            continue
        j = i + 1
        fields: dict[str, str] = {}
        while j < b_end and (not lines[j].strip() or indent_of(lines[j]) > ind + 2):
            match = KEY_VALUE_RE.match(lines[j])
            if match:
                fields[match.group(2)] = match.group(3)
            j += 1
        cx, cy = parse_ivec(fields["ind"])
        version = int(fields.get("version", "1"))
        size = int(fields.get("size", chunk_size))
        data = base64.b64decode(fields["tiles"])
        stride = 7 if version >= 7 else (6 if version >= 6 else 4)
        for y in range(size):
            for x in range(size):
                off = (y * size + x) * stride
                if version >= 6:
                    yaml_id = struct.unpack_from("<i", data, off)[0]
                    rest = data[off + 4: off + stride]
                else:
                    yaml_id = struct.unpack_from("<H", data, off)[0]
                    rest = data[off + 2: off + stride]
                if yaml_id in space_ids:
                    continue
                tiles[(cx * size + x, cy * size + y)] = TileData(
                    yaml_id, rest[0], rest[1], rest[2] if version >= 7 else 0)
        i = j
    return tiles, block, chunk_size


def encode_chunks(tiles: dict[tuple[int, int], TileData], chunk_size: int, space_id: int, ind: int) -> list[str]:
    chunks: dict[tuple[int, int], dict[tuple[int, int], TileData]] = {}
    for (gx, gy), tile in tiles.items():
        chunks.setdefault((gx // chunk_size, gy // chunk_size), {})[(gx % chunk_size, gy % chunk_size)] = tile

    out: list[str] = []
    pad = " " * ind
    for (cx, cy) in sorted(chunks, key=lambda c: (c[1], c[0])):
        local = chunks[(cx, cy)]
        buf = bytearray()
        for y in range(chunk_size):
            for x in range(chunk_size):
                tile = local.get((x, y))
                if tile is None:
                    buf += struct.pack("<iBBB", space_id, 0, 0, 0)
                else:
                    buf += struct.pack("<iBBB", tile.yaml_id, tile.flags, tile.variant, tile.rotation)
        out.append(f"{pad}  {cx},{cy}:")
        out.append(f"{pad}    ind: {cx},{cy}")
        out.append(f"{pad}    tiles: {base64.b64encode(bytes(buf)).decode('ascii')}")
        out.append(f"{pad}    version: 7")
    return out


def rotate_bit_chunks(lines: list[str], b_start: int, b_end: int, ind: int,
                      chunk_size: int, rotate, nested: bool) -> list[str]:
    """
    Rotates per-tile bitmask chunks. `nested=True` is the atmos layout (chunk -> {mix: mask}),
    `nested=False` the roof layout (chunk -> mask).
    """
    values: dict[tuple[int, int], str] = {}
    chunk: tuple[int, int] | None = None
    for i in range(b_start, b_end):
        match = KEY_VALUE_RE.match(lines[i])
        if not match:
            continue
        depth = len(match.group(1))
        key, value = match.group(2), match.group(3)
        if depth == ind + 2:
            chunk = parse_ivec(key)
            if nested:
                continue
            masks = {"": int(value)}
        elif nested and depth == ind + 4 and chunk is not None:
            masks = {key: int(value)}
        else:
            continue
        for tag, mask in masks.items():
            for bit in range(chunk_size * chunk_size):
                if mask >> bit & 1:
                    tile = (chunk[0] * chunk_size + bit % chunk_size, chunk[1] * chunk_size + bit // chunk_size)
                    values[rotate(tile)] = tag

    grouped: dict[tuple[int, int], dict[str, int]] = {}
    for (tx, ty), tag in values.items():
        origin = (tx // chunk_size, ty // chunk_size)
        bit = (tx % chunk_size) + (ty % chunk_size) * chunk_size
        masks = grouped.setdefault(origin, {})
        masks[tag] = masks.get(tag, 0) | (1 << bit)

    pad = " " * ind
    out: list[str] = []
    for origin in sorted(grouped, key=lambda c: (c[1], c[0])):
        masks = grouped[origin]
        if nested:
            out.append(f"{pad}  {origin[0]},{origin[1]}:")
            for tag in sorted(masks, key=int):
                out.append(f"{pad}    {tag}: {masks[tag]}")
        else:
            out.append(f"{pad}  {origin[0]},{origin[1]}: {masks['']}")
    return out


def rotate_atmos_v1(lines: list[str], b_start: int, b_end: int, ind: int, rotate) -> list[str]:
    values: dict[tuple[int, int], str] = {}
    for i in range(b_start, b_end):
        match = KEY_VALUE_RE.match(lines[i])
        if match and len(match.group(1)) == ind + 2:
            values[rotate(parse_ivec(match.group(2)))] = match.group(3)
    pad = " " * ind
    return [f"{pad}  {x},{y}: {values[(x, y)]}" for (x, y) in sorted(values, key=lambda c: (c[1], c[0]))]


def rotate_decals(lines: list[str], b_start: int, b_end: int, ind: int,
                  pivot: tuple[float, float], turns: int, half: float, decal_rule) -> list[str]:
    """`decal_rule(id) -> (new_id, angle_turns)` decides between swapping the prototype and turning the angle."""
    nodes: list[tuple[dict[str, str], list[tuple[str, str]]]] = []
    state = None
    for i in range(b_start, b_end):
        line = lines[i]
        if not line.strip():
            continue
        if line.startswith(" " * ind + "- node:"):
            nodes.append(({}, []))
            state = "node"
            continue
        if not nodes:
            continue
        stripped = line.strip()
        if indent_of(line) == ind + 2 and stripped.startswith("decals:"):
            state = "decals"
            continue
        match = KEY_VALUE_RE.match(line)
        if not match:
            continue
        if state == "node":
            nodes[-1][0][match.group(2)] = match.group(3)
        elif state == "decals":
            nodes[-1][1].append((match.group(2), match.group(3)))

    regrouped: dict[tuple, list[tuple[int, str]]] = {}
    for data, decals in nodes:
        new_id, angle_turns = decal_rule(data.get("id", ""))
        angle = normalize_angle(parse_angle(data.get("angle", "0")) + angle_turns * math.pi / 2)
        new_data = {k: v for k, v in data.items() if k != "angle"}
        if "id" in new_data:
            new_data["id"] = new_id
        if angle != 0:
            new_data["angle"] = fmt_angle(angle)
        key = tuple(sorted(new_data.items()))
        for decal_id, coords in decals:
            x, y = parse_vec(coords)
            cx, cy = rotate_point(x + half, y + half, pivot, turns)
            regrouped.setdefault(key, []).append((int(decal_id), fmt_vec(cx - half, cy - half)))

    pad = " " * ind
    out: list[str] = []
    for key in sorted(regrouped):
        out.append(f"{pad}- node:")
        for name, value in key:
            out.append(f"{pad}    {name}: {value}")
        out.append(f"{pad}  decals:")
        for decal_id, coords in sorted(regrouped[key]):
            out.append(f"{pad}    {decal_id}: {coords}")
    return out


# ---------------------------------------------------------------- preview

def ascii_map(tiles, marks: dict[tuple[int, int], str] | None = None) -> str:
    if not tiles:
        return "(no tiles)"
    xs = [x for x, _ in tiles]
    ys = [y for _, y in tiles]
    rows = []
    for y in range(max(ys), min(ys) - 1, -1):
        row = []
        for x in range(min(xs), max(xs) + 1):
            if marks and (x, y) in marks:
                row.append(marks[(x, y)])
            else:
                row.append("#" if (x, y) in tiles else ".")
        rows.append("".join(row))
    return "\n".join(rows) + f"\n  x: {min(xs)}..{max(xs)}  y: {min(ys)}..{max(ys)}  (north is up)"


# ---------------------------------------------------------------- main

def transform(text: str, turns: int, grid_filter: set[int] | None, pivot_arg: tuple[int, int] | str,
              protos: Prototypes | None, show: bool, rotate_items: bool = False) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")

    tilemap = parse_tilemap(lines)
    space_ids = {k for k, v in tilemap.items() if v == "Space"}
    if not space_ids:
        space_id = 0
        while space_id in tilemap:
            space_id += 1
        lines.insert(lines.index("tilemap:") + 1, f"  {space_id}: Space")
        tilemap[space_id] = "Space"
        space_ids = {space_id}
    space_id = min(space_ids)
    rotatable_ids = None if protos is None else {k for k, v in tilemap.items() if v in protos.rotatable_tiles}

    name_to_yaml = {name: yaml_id for yaml_id, name in sorted(tilemap.items(), reverse=True)}
    added_tiles: list[str] = []
    tile_remap: dict[int, int] = {}

    def turned_tile_id(yaml_id: int) -> int:
        if yaml_id not in tile_remap:
            new_name = protos and rotate_name(tilemap.get(yaml_id, ""), turns, protos.tiles)
            if not new_name:
                tile_remap[yaml_id] = yaml_id
            else:
                if new_name not in name_to_yaml:
                    new_yaml = max(tilemap) + 1
                    tilemap[new_yaml] = new_name
                    name_to_yaml[new_name] = new_yaml
                    added_tiles.append(f"  {new_yaml}: {new_name}")
                tile_remap[yaml_id] = name_to_yaml[new_name]
        return tile_remap[yaml_id]

    decal_stats = {"swapped": 0, "upright": 0, "turned": 0}

    def decal_rule(decal_id: str) -> tuple[str, int]:
        new_id = protos and rotate_name(decal_id, turns, protos.decals)
        if new_id:
            decal_stats["swapped"] += 1
            return new_id, 0
        if protos and decal_id in protos.upright_decals:
            decal_stats["upright"] += 1
            return decal_id, 0
        decal_stats["turned"] += 1
        return decal_id, turns

    entities = parse_entities(lines)
    grids = [e for e in entities if e.component("MapGrid") and (grid_filter is None or e.uid in grid_filter)]
    if not grids:
        raise SystemExit("No matching grid entity (MapGrid component) found.")

    replacements: list[tuple[int, int, list[str]]] = []

    for grid in grids:
        map_grid = grid.component("MapGrid")
        tile_size = 1.0
        size_block = find_child_block(lines, map_grid.start + 1, map_grid.end, "tileSize")
        if size_block:
            tile_size = float(lines[size_block[0]].split(":")[1])

        tiles, chunk_block, chunk_size = decode_chunks(lines, map_grid, space_ids)
        if pivot_arg != "center":
            pivot = pivot_arg
        elif tiles:
            xs = [x for x, _ in tiles]
            ys = [y for _, y in tiles]
            pivot = (math.floor((min(xs) + max(xs) + 1) / 2 + 0.5), math.floor((min(ys) + max(ys) + 1) / 2 + 0.5))
        else:
            pivot = (0, 0)
        pivot_local = (pivot[0] * tile_size, pivot[1] * tile_size)

        def rotate_index(index, _pivot=pivot):
            return rotate_tile(index, _pivot, turns)

        new_tiles: dict[tuple[int, int], TileData] = {}
        swapped_tiles = 0
        for index, tile in tiles.items():
            rotation = tile.rotation
            yaml_id = turned_tile_id(tile.yaml_id)
            if yaml_id != tile.yaml_id:
                swapped_tiles += 1
            elif rotatable_ids is None or tile.yaml_id in rotatable_ids:
                rotation = rotate_tile_visual(rotation, turns)
            new_tiles[rotate_index(index)] = TileData(yaml_id, tile.flags, tile.variant, rotation)

        print(f"grid uid {grid.uid}: {len(tiles)} tiles, pivot {pivot[0]},{pivot[1]}, turn {turns * 90} deg ccw")
        print(f"  tiles swapped to the turned prototype: {swapped_tiles}")
        if show:
            print("before:\n" + ascii_map(tiles))
            print("after:\n" + ascii_map(new_tiles))

        if chunk_block is not None:
            _, b_start, b_end, ind = chunk_block
            if lines[chunk_block[0]].rstrip().endswith("{}"):
                pass
            else:
                replacements.append((b_start, b_end, encode_chunks(new_tiles, chunk_size, space_id, ind)))

        decal_grid = grid.component("DecalGrid")
        if decal_grid:
            block = find_child_block(lines, decal_grid.start + 1, decal_grid.end, "nodes")
            version_block = find_child_block(lines, decal_grid.start + 1, decal_grid.end, "version")
            version = int(lines[version_block[0]].split(":")[1]) if version_block else 1
            if block and version >= 2:
                _, b_start, b_end, ind = block
                if b_end > b_start:
                    replacements.append((b_start, b_end, rotate_decals(
                        lines, b_start, b_end, ind, pivot_local, turns, tile_size / 2, decal_rule)))
                    print(f"  decal groups: {decal_stats['swapped']} swapped to the turned prototype, "
                          f"{decal_stats['upright']} kept upright, {decal_stats['turned']} rotated")
                    decal_stats.update(swapped=0, upright=0, turned=0)
            elif block or version < 2:
                print(f"  warning: DecalGrid format v{version} is not supported, decals left as is", file=sys.stderr)

        atmos = grid.component("GridAtmosphere")
        if atmos:
            data_block = find_child_block(lines, atmos.start + 1, atmos.end, "data")
            if data_block:
                tiles_block = find_child_block(lines, data_block[1], data_block[2], "tiles")
                size_block = find_child_block(lines, data_block[1], data_block[2], "chunkSize")
                atmos_chunk = int(lines[size_block[0]].split(":")[1]) if size_block else 4
                if tiles_block and tiles_block[2] > tiles_block[1]:
                    _, b_start, b_end, ind = tiles_block
                    replacements.append((b_start, b_end, rotate_bit_chunks(
                        lines, b_start, b_end, ind, atmos_chunk, rotate_index, nested=True)))
            else:
                tiles_block = find_child_block(lines, atmos.start + 1, atmos.end, "tiles")
                if tiles_block and tiles_block[2] > tiles_block[1]:
                    _, b_start, b_end, ind = tiles_block
                    replacements.append((b_start, b_end, rotate_atmos_v1(lines, b_start, b_end, ind, rotate_index)))

        roof = grid.component("Roof")
        if roof:
            data_block = find_child_block(lines, roof.start + 1, roof.end, "data")
            if data_block and data_block[2] > data_block[1]:
                _, b_start, b_end, ind = data_block
                replacements.append((b_start, b_end, rotate_bit_chunks(
                    lines, b_start, b_end, ind, 8, rotate_index, nested=False)))

        moved = 0
        upright = 0
        for entity in entities:
            xform = entity.component("Transform")
            if xform is None:
                continue
            fields: dict[str, tuple[int, str]] = {}
            for i in range(xform.start + 1, xform.end):
                match = TRANSFORM_FIELD_RE.match(lines[i])
                if match:
                    fields[match.group(1)] = (i, match.group(2))
            if fields.get("parent", (0, ""))[1] != str(grid.uid):
                continue

            x, y = parse_vec(fields["pos"][1]) if "pos" in fields else (0.0, 0.0)
            nx, ny = rotate_point(x, y, pivot_local, turns)
            new_fields: list[str] = []
            no_rot = fields.get("noRot", (0, "False"))[1].lower() == "true"
            is_item = not rotate_items and protos is not None and entity.proto in protos.items
            rot = parse_angle(fields["rot"][1]) if "rot" in fields else 0.0
            if is_item:
                upright += 1
            elif not no_rot:
                rot = normalize_angle(rot + turns * math.pi / 2)

            body = [lines[i] for i in range(xform.start + 1, xform.end)
                    if not re.match(r"^      (pos|rot):", lines[i])]
            insert_at = next((k for k, l in enumerate(body) if re.match(r"^      parent:", l)), len(body))
            if rot != 0:
                new_fields.append(f"      rot: {fmt_angle(rot)}")
            if (nx, ny) != (0.0, 0.0):
                new_fields.append(f"      pos: {fmt_vec(nx, ny)}")
            body[insert_at:insert_at] = new_fields
            replacements.append((xform.start + 1, xform.end, body))
            moved += 1
        print(f"  entities moved: {moved} (items keeping their angle: {upright})")

    if added_tiles:
        end = lines.index("tilemap:") + 1
        while end < len(lines) and lines[end].startswith("  "):
            end += 1
        replacements.append((end, end, added_tiles))

    replacements.sort(key=lambda r: r[0])
    for (a_start, a_end, _), (b_start, _, _) in zip(replacements, replacements[1:]):
        if b_start < a_end:
            raise SystemExit("Internal error: overlapping edits, file left untouched.")
    for start, end, new_lines in reversed(replacements):
        lines[start:end] = new_lines

    return newline.join(lines)


def main():
    parser = argparse.ArgumentParser(description="Rotate a grid in an SS14 map .yml by quarter turns.")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="output file (default: <input>_rotated.yml)")
    parser.add_argument("--turn", default="left", choices=sorted(TURNS), help="left = 90 deg ccw (default)")
    parser.add_argument("--grid", type=int, action="append", help="grid entity uid (default: every grid)")
    parser.add_argument("--pivot", default="0,0",
                        help="tile corner X,Y to turn around, or 'center' for the middle of the tiles "
                             "(default: 0,0 = grid origin; repeated turns are exactly reversible)")
    parser.add_argument("--prototypes", type=Path,
                        help="Resources/Prototypes (default: found next to the input file); used for directional "
                             "tile/decal ids, allowRotationMirror tiles, upright decals and items")
    parser.add_argument("--rotate-items", action="store_true", help="turn the angle of items too")
    parser.add_argument("--show", action="store_true", help="print ASCII tile maps before/after")
    parser.add_argument("--in-place", action="store_true", help="overwrite the input file")
    args = parser.parse_args()

    turns = TURNS[args.turn]
    pivot = "center" if args.pivot == "center" else parse_ivec(args.pivot)

    prototypes = args.prototypes or find_prototypes_dir(args.input.resolve().parent)
    protos = load_prototypes(prototypes) if prototypes else None
    if protos is None:
        print("warning: Resources/Prototypes not found, every tile/decal/item is rotated as is", file=sys.stderr)

    text = args.input.read_text(encoding="utf-8-sig")
    result = transform(text, turns, set(args.grid) if args.grid else None, pivot, protos, args.show,
                       args.rotate_items)

    output = args.input if args.in_place else (args.output or args.input.with_name(args.input.stem + "_rotated.yml"))
    output.write_text(result, encoding="utf-8", newline="")
    print(f"written: {output}")


if __name__ == "__main__":
    main()
