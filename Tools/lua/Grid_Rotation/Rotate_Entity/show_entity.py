#!/usr/bin/env python3
import re
from pathlib import Path
f=Path("Resources/Maps/_Lua/Outpost/Horizon_rotated.yml")
if not f.exists():
    print(f"File not found: {f}")
    raise SystemExit(1)
s=f.read_text(encoding='utf-8').splitlines()
uid_to='4551'
for i,line in enumerate(s):
    if line.lstrip().startswith(f"- uid: {uid_to}"):
        start=i
        # find end
        j=i+1
        ind=len(line)-len(line.lstrip())
        while j<len(s) and (s[j].strip() and len(s[j])-len(s[j].lstrip())>ind):
            j+=1
        print('\n'.join(s[start:j]))
        break
else:
    print('uid not found')
