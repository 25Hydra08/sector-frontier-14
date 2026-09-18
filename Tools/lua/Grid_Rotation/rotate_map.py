#!/usr/bin/env python3
"""
Rotate YAML map 90 degrees counter-clockwise.

Usage:
  python Tools/rotate_map.py input.yml [output.yml] [--key KEY]

If output.yml is omitted, input file is overwritten.
If the map is nested under a key in the root mapping, pass --key KEY.

Supports map formats:
- list of strings (each string is a row)
- list of lists (each inner list is a row of cells)

Be sure to backup your file before overwriting.
"""
import argparse
import sys
import io
import yaml


def load_yaml(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(obj, path):
    with io.open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(obj, f, sort_keys=False, allow_unicode=True)


def to_matrix(target):
    # list of strings -> matrix of chars
    if isinstance(target, list) and all(isinstance(r, str) for r in target):
        rows = [list(r) for r in target]
        return rows, "strings"
    # list of lists -> matrix as-is
    if isinstance(target, list) and all(isinstance(r, list) for r in target):
        return [list(r) for r in target], "lists"
    raise ValueError("Неожиданный формат карты: ожидаются список строк или список списков.")


def from_matrix(matrix, fmt):
    if fmt == "strings":
        return ["".join(row) for row in matrix]
    if fmt == "lists":
        return matrix
    raise RuntimeError("Unknown format")


def rotate_ccw(matrix):
    # rotate 90 degrees counter-clockwise
    if not matrix:
        return matrix
    maxw = max(len(r) for r in matrix)
    rect = [r + [None] * (maxw - len(r)) for r in matrix]
    # zip(*rect) produces columns left-to-right; to rotate CCW we take columns and reverse order
    cols = [list(col) for col in zip(*rect)]
    rotated = cols[::-1]
    # trim trailing None values from each row
    for i in range(len(rotated)):
        while rotated[i] and rotated[i][-1] is None:
            rotated[i].pop()
    return rotated


def main():
    parser = argparse.ArgumentParser(description="Поворот YAML-карты на 90° против часовой")
    parser.add_argument("input", help="входной YAML-файл")
    parser.add_argument("output", nargs="?", help="файл вывода (по умолчанию перезаписать входной)")
    parser.add_argument("--key", "-k", help="ключ в корневом словаре, под которым хранится карта")
    args = parser.parse_args()

    data = load_yaml(args.input)

    key = args.key
    if key:
        if not isinstance(data, dict) or key not in data:
            print(f"Ошибка: ключ '{key}' не найден в корне YAML.", file=sys.stderr)
            sys.exit(2)
        target = data[key]
        parent = data
    else:
        target = data
        parent = None

    try:
        matrix, fmt = to_matrix(target)
    except ValueError as e:
        print("Ошибка:", e, file=sys.stderr)
        sys.exit(2)

    rotated = rotate_ccw(matrix)
    new_target = from_matrix(rotated, fmt)

    if parent is not None:
        parent[key] = new_target
        out_obj = data
    else:
        out_obj = new_target

    out_path = args.output if args.output else args.input
    save_yaml(out_obj, out_path)
    print(f"Сохранено: {out_path}")


if __name__ == "__main__":
    main()
