#!/usr/bin/env python3
"""
Inspect MapGrid chunk tile payloads inside a YAML map file.

Usage:
  python Tools/inspect_chunk.py path/to/Horizon.yml --sample 3

The script finds the first MapGrid component in the YAML, lists chunk keys
and for the first N chunks prints info: base64 length, first bytes (hex),
and attempts common decompressions (zlib, gzip). This helps determine the
serialization/compression used for chunk tiles so a correct rotation tool
can be implemented.

Run this and paste the output here so I can implement full rotation.
"""
import argparse
import base64
import io
import sys
import yaml
import binascii
import zlib
import gzip


def try_decompress(data):
    out = {}
    # try zlib
    try:
        d = zlib.decompress(data)
        out['zlib_len'] = len(d)
    except Exception as e:
        out['zlib_err'] = str(e)
    # try gzip
    try:
        d = gzip.decompress(data)
        out['gzip_len'] = len(d)
    except Exception as e:
        out['gzip_err'] = str(e)
    return out


def load_yaml(path):
    # Register a multi-constructor to ignore custom '!type:...' tags used in these maps.
    # This constructor will unwrap the tagged node and return its underlying value
    # (scalar, sequence or mapping) so PyYAML doesn't fail on unknown tags.
    def _type_multi_constructor(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    yaml.SafeLoader.add_multi_constructor('!type:', _type_multi_constructor)
    with io.open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def find_mapgrid(data):
    # Walk entities list and find MapGrid components
    if not isinstance(data, dict):
        return None
    entlist = data.get('entities') or []
    for e in entlist:
        comps = e.get('components') or []
        for c in comps:
            if isinstance(c, dict) and c.get('type') == 'MapGrid':
                return c
    # fallback: search nested structures
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('path')
    p.add_argument('--sample', '-n', type=int, default=3, help='number of chunks to inspect')
    args = p.parse_args()

    data = load_yaml(args.path)
    # find MapGrid component
    mapgrid = None
    # some maps store entities under 'entities' top-level key
    top_entities = data.get('entities') if isinstance(data, dict) else None
    if top_entities:
        for ent in top_entities:
            comps = ent.get('components') or []
            for c in comps:
                if isinstance(c, dict) and c.get('type') == 'MapGrid':
                    mapgrid = c
                    break
            if mapgrid:
                break

    if not mapgrid:
        print('MapGrid component not found under top-level entities. Searching recursively...')
        # deep search: look for any dict with key 'chunks'
        def walk(obj):
            if isinstance(obj, dict):
                if 'chunks' in obj and isinstance(obj['chunks'], dict):
                    return obj
                for v in obj.values():
                    r = walk(v)
                    if r:
                        return r
            if isinstance(obj, list):
                for item in obj:
                    r = walk(item)
                    if r:
                        return r
            return None
        mapgrid = walk(data)

    if not mapgrid:
        print('MapGrid/chunks not found in file.')
        sys.exit(2)

    chunks = mapgrid.get('chunks') or {}
    if not chunks:
        print('No chunks found inside MapGrid.')
        sys.exit(2)

    print(f'Found {len(chunks)} chunks. Showing up to {args.sample} samples.')
    count = 0
    for coord, info in chunks.items():
        if count >= args.sample:
            break
        print('\nChunk key:', coord)
        tiles = info.get('tiles')
        if tiles is None:
            print('  no tiles field')
            continue
        try:
            raw = base64.b64decode(tiles)
        except Exception as e:
            print('  base64 decode failed:', e)
            continue
        print('  raw_len:', len(raw))
        preview = binascii.hexlify(raw[:64]).decode('ascii')
        print('  first64_hex:', preview)
        dec = try_decompress(raw)
        for k, v in dec.items():
            print(f'  {k}: {v}')
        # also print first 64 bytes as ints
        print('  first_bytes_ints:', list(raw[:32]))
        count += 1


if __name__ == '__main__':
    main()
