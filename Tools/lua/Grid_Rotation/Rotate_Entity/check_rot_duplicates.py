#!/usr/bin/env python3
import re
from pathlib import Path
f=Path("Resources/Maps/_Lua/Outpost/Horizon_rotated.yml")
if not f.exists():
    print(f"File not found: {f}")
    raise SystemExit(1)
s=f.read_text(encoding='utf-8').splitlines()
i=0
bad=[]
while i<len(s):
    if s[i].startswith('- proto:'):
        j=i+1
        while j<len(s) and not s[j].startswith('- proto:'):
            if s[j].lstrip().startswith('- uid:'):
                uid_match=re.match(r"\s*- uid:\s*(\d+)",s[j])
                uid=uid_match.group(1) if uid_match else ''
                k=j+1
                cnt=0
                while k<len(s) and not s[k].lstrip().startswith('- uid:') and not s[k].startswith('- proto:'):
                    if re.match(r"^\s*rot\s*:\s*",s[k]) or re.match(r"^\s*rotation\s*:\s*",s[k]):
                        cnt+=1
                    k+=1
                if cnt>1:
                    bad.append((uid,cnt))
                j=k
            else:
                j+=1
        i=j
    else:
        i+=1
if not bad:
    print('No duplicate rot lines found')
else:
    print('Duplicates found:')
    for u,c in bad:
        print(u,c)
