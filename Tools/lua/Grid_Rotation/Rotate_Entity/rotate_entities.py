#!/usr/bin/env python3
"""
Rotate entities in a map .yml whose prototypes (including parents) contain a given component.

Interactive flow:
 1) select map file
 2) specify component name (e.g. "Storage" or "Transform")
 3) choose turn: left/right/180
 4) confirm

Writes <input>_rotated.yml by default.
"""
from __future__ import annotations

import math
import re
import struct
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


PROTO_RE = re.compile(r"^- proto:\s*['\"]?(.*?)['\"]?\s*$")
ENTITY_RE = re.compile(r"^  - uid: (\d+)\s*$")
COMPONENT_RE = re.compile(r"^\s*- type: (\S+)\s*$")
KEY_VALUE_RE = re.compile(r"^(\s*)([^:\s][^:]*?):\s*(.*?)\s*$")

TURNS = {"left": 1, "ccw": 1, "180": 2, "right": 3, "cw": 3}


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def fmt_float32(value: float) -> str:
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


def parse_angle(text: str) -> float:
    text = text.strip().strip("'\"")
    if text.endswith("rad"):
        return float(text[:-3])
    if text.endswith("deg"):
        return math.radians(float(text[:-3]))
    return float(text)


def fmt_angle(theta: float) -> str:
    return f"{repr(float(theta))} rad"


def rotate_offset(dx: float, dy: float, turns: int) -> tuple[float, float]:
    if turns == 1:
        return -dy, dx
    if turns == 2:
        return -dx, -dy
    if turns == 3:
        return dy, -dx
    return dx, dy


def rotate_point(x: float, y: float, pivot: tuple[float, float], turns: int) -> tuple[float, float]:
    rx, ry = rotate_offset(x - pivot[0], y - pivot[1], turns)
    return pivot[0] + rx, pivot[1] + ry


def find_prototypes_dir(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        candidate = parent / "Resources" / "Prototypes"
        if candidate.is_dir():
            return candidate
        if parent.name == "Resources" and (parent / "Prototypes").is_dir():
            return parent / "Prototypes"
    return None


def component_types(block: str) -> set[str]:
    # adapted minimal parser: find component types listed in a prototype block
    match = re.search(r"(?m)^  components:\s*$", block)
    if not match:
        return set()
    types: set[str] = set()
    for line in block[match.end():].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*- type:\s*(\S+)", line)
        if m:
            types.add(m.group(1))
        # stop when next top-level entry in prototype reached
        if indent_of(line) <= 2 and not line.lstrip().startswith("- "):
            break
    return types


def load_entity_prototypes(prototypes: Path) -> tuple[dict[str, bool | None], dict[str, list[str]]]:
    own: dict[str, bool | None] = {}
    parents: dict[str, list[str]] = {}
    for path in prototypes.rglob("*.yml"):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        for block in re.split(r"(?m)^- (?=type:)", text):
            head = re.match(r"type:\s*(\w+)\s*$", block.splitlines()[0] if block else "")
            if not head or head.group(1) != "entity":
                continue
            # find id
            id_match = re.search(r"(?m)^  id:\s*([^\n\r#]+)", block)
            if not id_match:
                continue
            proto_id = id_match.group(1).strip().strip("'\"")
            # parents
            parent_list = []
            pm = re.search(r"(?m)^  parents:[ \t]*([^#\n]*)", block)
            if pm:
                raw = pm.group(1).strip()
                if raw:
                    parent_list = [p.strip().strip("'\"") for p in raw.strip("[]").split(",") if p.strip()]
                else:
                    # block style
                    tail = block[pm.end():]
                    parent_list = re.findall(r"(?m)^\s+- ([^#\s]+)", re.split(r"(?m)^  \w", tail, maxsplit=1)[0])
            parents[proto_id] = parent_list
            types = component_types(block)
            own[proto_id] = True if types else None
    return own, parents


def resolve_inherited(own: dict[str, bool | None], parents: dict[str, list[str]]) -> set[str]:
    cache: dict[str, bool] = {}

    def value(proto_id: str, depth: int = 0) -> bool:
        if proto_id in cache:
            return cache[proto_id]
        result = own.get(proto_id)
        if result is None:
            result = depth < 64 and any(value(p, depth + 1) for p in parents.get(proto_id, []))
        cache[proto_id] = bool(result)
        return cache[proto_id]

    return {proto_id for proto_id in own if value(proto_id)}


def find_protos_with_component(prototypes_dir: Path, component: str) -> set[str]:
    own, parents = load_entity_prototypes(prototypes_dir)
    # mark own where component exists explicitly
    for proto in list(own.keys()):
        # we need to re-read block to detect component presence precisely; simple approach: set own[proto]=None and
        # reparse file list to detect components per-proto using component_types
        own[proto] = None
    # reparse to fill own true where component present
    for path in prototypes_dir.rglob("*.yml"):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        for block in re.split(r"(?m)^- (?=type:)", text):
            head = re.match(r"type:\s*(\w+)\s*$", block.splitlines()[0] if block else "")
            if not head or head.group(1) != "entity":
                continue
            id_match = re.search(r"(?m)^  id:\s*([^\n\r#]+)", block)
            if not id_match:
                continue
            proto_id = id_match.group(1).strip().strip("'\"")
            types = component_types(block)
            own[proto_id] = (component in types)

    return resolve_inherited(own, parents)


def rotate_entities_in_map(map_path: Path, protos_to_rotate: set[str], turns: int, pivot: tuple[float, float]) -> tuple[str, list]:
    text = map_path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    i = 0
    changed = 0
    processed: list[dict] = []
    while i < len(lines):
        line = lines[i]
        # top-level proto blocks
        if line.startswith("- proto:"):
            proto_match = PROTO_RE.match(line)
            if proto_match:
                proto_id = proto_match.group(1)
            else:
                proto_id = ""
            # find end of this block (next top-level '- proto:' or EOF)
            j = i + 1
            while j < len(lines) and not lines[j].startswith("- proto:"):
                j += 1
            if proto_id in protos_to_rotate:
                # process entities inside this block
                # find lines starting with two spaces + '- uid:'
                k = i + 1
                while k < j:
                    if lines[k].lstrip().startswith("- uid:"):
                        # entity block start
                        ent_start = k
                        ent_indent = indent_of(lines[k])
                        k2 = k + 1
                        while k2 < j and (lines[k2].strip() and indent_of(lines[k2]) > ent_indent):
                            k2 += 1
                        # inspect entity block lines between ent_start and k2
                        # find Transform component
                        t_idx = None
                        for m in range(ent_start, k2):
                            if re.match(r"^\s*- type:\s*Transform", lines[m]):
                                t_idx = m
                                break
                        if t_idx is not None:
                            # scan following lines for rot only; do not move pos (rotate in place)
                            rot_line = None
                            r_val = None
                            pos_line = None
                            p_val = None
                            m = t_idx + 1
                            while m < k2 and (lines[m].strip() and indent_of(lines[m]) > indent_of(lines[t_idx])):
                                match = KEY_VALUE_RE.match(lines[m])
                                if match:
                                    key = match.group(2)
                                    val = match.group(3)
                                    if key in ("rot", "rotation"):
                                        rot_line = m
                                        r_val = val
                                    if key in ("pos", "position"):
                                        pos_line = m
                                        p_val = val
                                m += 1
                            # compute delta in radians
                            delta = turns * (math.pi / 2)
                            uid = None
                            uid_match = re.search(r"- uid:\s*(\d+)", lines[ent_start])
                            if uid_match:
                                uid = uid_match.group(1)
                            last_new_rot_value = None
                            last_new_rot_line = None
                            if r_val is not None and rot_line is not None:
                                try:
                                    theta = parse_angle(r_val)
                                except Exception:
                                    theta = None
                                if theta is not None:
                                    ntheta = theta + delta
                                    lines[rot_line] = f"{' ' * indent_of(lines[rot_line])}rot: {fmt_angle(ntheta)}"
                                    changed += 1
                                    last_new_rot_value = fmt_angle(ntheta)
                                    last_new_rot_line = rot_line
                                    if uid is not None:
                                        processed.append({
                                            "proto": proto_id,
                                            "uid": uid,
                                            "pos": p_val,
                                            "old_rot": fmt_angle(theta),
                                            "new_rot": fmt_angle(ntheta),
                                        })
                            else:
                                # before inserting, re-scan the Transform component block for any rot/rotation line
                                found_rot = False
                                rot_line = None
                                r_val = None
                                t_indent = indent_of(lines[t_idx])
                                for n in range(t_idx + 1, k2):
                                    # consider only lines that belong to this Transform block
                                    if not lines[n].strip() or indent_of(lines[n]) <= t_indent:
                                        continue
                                    # match key at line start robustly
                                    if re.match(r"^\s*rot\s*:\s*", lines[n]) or re.match(r"^\s*rotation\s*:\s*", lines[n]):
                                        found_rot = True
                                        rot_line = n
                                        # extract value after ':'
                                        parts = lines[n].split(":", 1)
                                        r_val = parts[1].strip() if len(parts) > 1 else ""
                                        break
                                if found_rot and rot_line is not None:
                                    try:
                                        theta = parse_angle(r_val)
                                    except Exception:
                                        theta = None
                                    if theta is not None:
                                        ntheta = theta + delta
                                        lines[rot_line] = f"{' ' * indent_of(lines[rot_line])}rot: {fmt_angle(ntheta)}"
                                        changed += 1
                                        last_new_rot_value = fmt_angle(ntheta)
                                        last_new_rot_line = rot_line
                                        if uid is not None:
                                            processed.append({
                                                "proto": proto_id,
                                                "uid": uid,
                                                "pos": p_val,
                                                "old_rot": fmt_angle(theta),
                                                "new_rot": fmt_angle(ntheta),
                                            })
                                else:
                                    # no rot present anywhere in Transform: insert rot field with delta
                                    theta = 0.0
                                    ntheta = theta + delta
                                    insert_at = t_idx + 1
                                    # place after existing Transform fields if any
                                    m2 = t_idx + 1
                                    while m2 < k2 and (lines[m2].strip() and indent_of(lines[m2]) > indent_of(lines[t_idx])):
                                        m2 += 1
                                    insert_at = m2
                                    indent = indent_of(lines[t_idx]) + 2
                                    lines.insert(insert_at, f"{' ' * indent}rot: {fmt_angle(ntheta)}")
                                    changed += 1
                                    last_new_rot_value = fmt_angle(ntheta)
                                    last_new_rot_line = insert_at
                                    if uid is not None:
                                        processed.append({
                                            "proto": proto_id,
                                            "uid": uid,
                                            "pos": p_val,
                                            "old_rot": 'implicit 0',
                                            "new_rot": fmt_angle(ntheta),
                                        })
                            # cleanup: remove duplicate rot/rotation lines inside this Transform block
                            if last_new_rot_value is not None:
                                # recompute block end because we may have inserted a line
                                end = ent_start + 1
                                while end < j and (lines[end].strip() and indent_of(lines[end]) > ent_indent):
                                    end += 1
                                # find all rot lines in transform block
                                rot_indices = []
                                for n in range(t_idx + 1, end):
                                    if re.match(r"^\s*rot\s*:\s*", lines[n]) or re.match(r"^\s*rotation\s*:\s*", lines[n]):
                                        rot_indices.append(n)
                                if len(rot_indices) > 1:
                                    # prefer index that matches last_new_rot_value
                                    keep = None
                                    for idx in rot_indices:
                                        if last_new_rot_value in lines[idx]:
                                            keep = idx
                                            break
                                    if keep is None:
                                        keep = rot_indices[-1]
                                    for idx in reversed(rot_indices):
                                        if idx == keep:
                                            continue
                                        del lines[idx]
                                # adjust k2 to new end
                                k2 = end - (len(rot_indices) - 1) if len(rot_indices) > 1 else end
                        k = k2
                    else:
                        k += 1
            i = j
        else:
            i += 1

    if changed:
        return "\n".join(lines) + "\n", processed
    return text, processed


def interactive():
    print("Rotate entities by prototype component (90deg steps)")
    path = input("Map file path: ").strip()
    if not path:
        print("no file")
        return
    map_path = Path(path)
    if not map_path.exists():
        print("file not found")
        return
    comp = input("Component name to match prototypes (e.g. Storage, Transform)\nor comma-separated prototype ids (e.g. BaseGasCondenser,PipeJoint): ").strip()
    if not comp:
        print("no component or prototypes")
        return
    choice = input("Turn (left/right/180) [left]: ").strip() or "left"
    if choice not in TURNS:
        print("invalid turn")
        return
    turns = TURNS[choice]
    # entities rotate in place (around their own axis); pivot is unused
    pivot = (0.0, 0.0)
    # Determine prototypes list: either user supplied explicit list or lookup by component
    protos = set()
    if "," in comp or comp.startswith("proto:"):
        raw = comp[6:] if comp.startswith("proto:") else comp
        protos = {p.strip() for p in raw.split(",") if p.strip()}
        print(f"Using {len(protos)} manually specified prototypes")
    else:
        protos_dir = find_prototypes_dir(map_path.resolve().parent)
        if protos_dir is None:
            print("Resources/Prototypes not found; cannot resolve inheritance. Aborting.")
            return
        print(f"Scanning prototypes in: {protos_dir}")
        protos = find_protos_with_component(protos_dir, comp)
        print(f"Found {len(protos)} prototypes with component '{comp}' (including inherited)")
    proceed = input("Proceed to rotate matching entities in map? (y/N): ").strip().lower()
    if proceed != "y":
        print("aborted")
        return
    new_text, entries = rotate_entities_in_map(map_path, protos, turns, pivot)
    # create backup and overwrite original
    backup = map_path.with_name(map_path.stem + "_backup" + map_path.suffix)
    backup.write_bytes(map_path.read_bytes())
    map_path.write_text(new_text, encoding="utf-8", newline="")
    print(f"backup written: {backup}")
    print(f"overwritten: {map_path}")
    if entries:
        print(f"Processed {len(entries)} entities:")
        for e in entries:
            print(f" uid={e['uid']} proto={e['proto']} pos={e['pos']} {e['old_rot']} -> {e['new_rot']}")


def main():
    if len(sys.argv) > 1:
        # non-interactive usage: rotate_entities.py <map.yml> <Component> [left|right|180] [pivot]
        map_path = Path(sys.argv[1])
        comp = sys.argv[2] if len(sys.argv) > 2 else input("Component or prototypes: ")
        choice = sys.argv[3] if len(sys.argv) > 3 else "left"
        turns = TURNS.get(choice, 1)
        pivot = (0.0, 0.0)
        if len(sys.argv) > 4:
            if sys.argv[4] != "center":
                try:
                    px, py = sys.argv[4].split(",")
                    pivot = (float(px), float(py))
                except Exception:
                    pass
        # determine prototypes set: comma-separated list or lookup by component
        if "," in comp or comp.startswith("proto:"):
            raw = comp[6:] if comp.startswith("proto:") else comp
            protos = {p.strip() for p in raw.split(",") if p.strip()}
        else:
            protos_dir = find_prototypes_dir(map_path.resolve().parent)
            if protos_dir is None:
                print("Resources/Prototypes not found; cannot resolve inheritance.")
                return
            protos = find_protos_with_component(protos_dir, comp)
        new_text, entries = rotate_entities_in_map(map_path, protos, turns, pivot)
        # create backup and overwrite original
        backup = map_path.with_name(map_path.stem + "_backup" + map_path.suffix)
        backup.write_bytes(map_path.read_bytes())
        map_path.write_text(new_text, encoding="utf-8", newline="")
        print(f"backup written: {backup}")
        print(f"overwritten: {map_path}")
        if entries:
            print(f"Processed {len(entries)} entities:")
            for e in entries:
                print(f" uid={e['uid']} proto={e['proto']} pos={e['pos']} {e['old_rot']} -> {e['new_rot']}")
    else:
        interactive()


if __name__ == "__main__":
    main()

