#!/usr/bin/env python3
"""
Rotate entire MapGrid 90 degrees counter-clockwise inside a YAML map file.

Features:
- Rotates MapGrid chunk tiles (version 7 format: 7 bytes per tile)
- Recomputes chunk indices and re-serializes tiles preserving stored yaml ids
- Rotates Transform.pos values and other X,Y coordinate strings (e.g. decals, ind)

Usage:
  python Tools/rotate_grid.py input.yml [output.yml]

If output omitted, input is overwritten (make a backup!).

Note: This modifies chunks and common coordinate fields. Review output before use.
"""
import io
import sys
import argparse
import yaml
import base64
import struct
import math
import re


COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def add_type_multi_constructor():
    def _type_multi_constructor(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    yaml.SafeLoader.add_multi_constructor('!type:', _type_multi_constructor)


def load_yaml(path):
    add_type_multi_constructor()
    with io.open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_yaml(obj, path):
    with io.open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(obj, f, sort_keys=False, allow_unicode=True)


def parse_chunk_tiles(b64, chunk_size):
    data = base64.b64decode(b64)
    # each tile: int32 (yaml id) + byte flags + byte variant + byte rotationMirroring
    entry_size = 7
    expected = chunk_size * chunk_size * entry_size
    if len(data) != expected:
        raise ValueError(f"Unexpected chunk byte length {len(data)} != {expected}")
    tiles = [[None for _ in range(chunk_size)] for _ in range(chunk_size)]
    off = 0
    for y in range(chunk_size):
        for x in range(chunk_size):
            (tid,) = struct.unpack_from('<i', data, off)
            off += 4
            flags = data[off]; off += 1
            variant = data[off]; off += 1
            rot = data[off]; off += 1
            tiles[x][y] = (tid, flags, variant, rot)
    return tiles


def serialize_chunk_tiles(tiles, chunk_size):
    buf = bytearray()
    for y in range(chunk_size):
        for x in range(chunk_size):
            tid, flags, variant, rot = tiles[x][y]
            buf += struct.pack('<i', int(tid))
            buf.append(int(flags) & 0xFF)
            buf.append(int(variant) & 0xFF)
            buf.append(int(rot) & 0xFF)
    return base64.b64encode(bytes(buf)).decode('ascii')


def rotate_rotation_ccw(r):
    r = int(r) & 0xFF
    mirrored = r >= 4
    base = r % 4
    new_base = (base + 3) % 4
    return new_base + (4 if mirrored else 0)


def rotate_xy_ccw(x, y):
    # (x,y) -> (-y, x)
    return -y, x


def divmod_floor(a, b):
    # return (q, r) where r in [0,b-1]
    q = a // b
    r = a - q * b
    return q, r


def rotate_mapgrid(data):
    # find MapGrid component
    mapgrid = None
    entities = data.get('entities') if isinstance(data, dict) else None
    if entities:
        for ent in entities:
            comps = ent.get('components') or []
            for c in comps:
                if isinstance(c, dict) and c.get('type') == 'MapGrid':
                    mapgrid = c
                    break
            if mapgrid:
                break

    if not mapgrid:
        # recursive search
        def walk(o):
            if isinstance(o, dict):
                if 'chunks' in o and isinstance(o['chunks'], dict):
                    return o
                for v in o.values():
                    r = walk(v)
                    if r:
                        return r
            if isinstance(o, list):
                for it in o:
                    r = walk(it)
                    if r:
                        return r
            return None
        mapgrid = walk(data)

    if not mapgrid:
        raise RuntimeError('MapGrid not found')

    chunk_size = int(mapgrid.get('size', 16))
    chunks = mapgrid.get('chunks') or {}

    # Parse all tiles into global map
    global_tiles = {}
    for key, info in list(chunks.items()):
        ind = info.get('ind')
        if isinstance(ind, str):
            cx, cy = map(int, ind.split(','))
        elif isinstance(ind, (list, tuple)):
            cx, cy = int(ind[0]), int(ind[1])
        else:
            # try parse key
            cx, cy = map(int, key.split(','))

        tiles_b64 = info.get('tiles')
        if tiles_b64 is None:
            continue
        tiles = parse_chunk_tiles(tiles_b64, chunk_size)
        for x in range(chunk_size):
            for y in range(chunk_size):
                gid_x = cx * chunk_size + x
                gid_y = cy * chunk_size + y
                global_tiles[(gid_x, gid_y)] = tiles[x][y]

    if not global_tiles:
        raise RuntimeError('No tiles parsed from chunks')

    # Rotate all global tiles and gather into new chunks
    new_chunks = {}
    for (gx, gy), tile in list(global_tiles.items()):
        nx, ny = rotate_xy_ccw(gx, gy)
        # get new chunk index and local indices with floor div
        ncx, lx = divmod_floor(nx, chunk_size)
        ncy, ly = divmod_floor(ny, chunk_size)
        # adjust rotation byte
        tid, flags, variant, rot = tile
        new_rot = rotate_rotation_ccw(rot)
        new_tile = (tid, flags, variant, new_rot)
        chunk_key = f"{ncx},{ncy}"
        if chunk_key not in new_chunks:
            # initialize empty tile grid
            arr = [[(0,0,0,0) for _ in range(chunk_size)] for _ in range(chunk_size)]
            new_chunks[chunk_key] = {'ind': f"{ncx},{ncy}", 'tiles_arr': arr}
        new_chunks[chunk_key]['tiles_arr'][lx][ly] = new_tile

    # serialize new chunks into base64 and replace mapgrid chunks
    out_chunks = {}
    for k, v in new_chunks.items():
        arr = v['tiles_arr']
        b64 = serialize_chunk_tiles(arr, chunk_size)
        out_chunks[k] = {'ind': v['ind'], 'tiles': b64, 'version': 7}

    mapgrid['chunks'] = out_chunks

    # Rotate coordinate-like strings across the whole YAML: pos, ind, decals etc.
    def rotate_coords_in_obj(obj):
        if isinstance(obj, dict):
            for key, val in list(obj.items()):
                # skip tiles content we already handled
                if key == 'tiles':
                    continue
                if isinstance(val, str):
                    m = COORD_RE.match(val)
                    if m:
                        a = m.group(1); b = m.group(2)
                        # preserve int vs float
                        na, nb = None, None
                        if '.' in a or '.' in b:
                            x = float(a); y = float(b)
                            rx, ry = rotate_xy_ccw(x, y)
                            obj[key] = f"{rx},{ry}"
                        else:
                            x = int(a); y = int(b)
                            rx, ry = rotate_xy_ccw(x, y)
                            obj[key] = f"{rx},{ry}"
                else:
                    rotate_coords_in_obj(val)
        elif isinstance(obj, list):
            for item in obj:
                rotate_coords_in_obj(item)

    rotate_coords_in_obj(data)

    # Additionally rotate Transform.pos floats that may be stored as scalars without comma
    # Find Transform components and rotate their pos if present as 'pos': 'x,y' or as two floats in a string.
    if entities:
        for ent in entities:
            comps = ent.get('components') or []
            for c in comps:
                if isinstance(c, dict) and c.get('type') == 'Transform':
                    pos = c.get('pos')
                    if isinstance(pos, str):
                        m = COORD_RE.match(pos)
                        if m:
                            a = m.group(1); b = m.group(2)
                            if '.' in a or '.' in b:
                                x = float(a); y = float(b)
                                rx, ry = rotate_xy_ccw(x, y)
                                c['pos'] = f"{rx},{ry}"
                            else:
                                x = int(a); y = int(b)
                                rx, ry = rotate_xy_ccw(x, y)
                                c['pos'] = f"{rx},{ry}"

    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output', nargs='?')
    args = p.parse_args()

    data = load_yaml(args.input)
    out = rotate_mapgrid(data)
    out_path = args.output if args.output else args.input
    save_yaml(out, out_path)
    print('Saved:', out_path)


if __name__ == '__main__':
    main()
