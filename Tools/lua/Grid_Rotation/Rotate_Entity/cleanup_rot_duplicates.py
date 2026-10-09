#!/usr/bin/env python3
import re
from pathlib import Path
p=Path("Resources/Maps/_Lua/Outpost/Horizon_rotated.yml")
if not p.exists():
    print("file not found",p)
    raise SystemExit(1)
lines=p.read_text(encoding='utf-8').splitlines()
i=0
changed=False
while i<len(lines):
    if lines[i].startswith('- proto:'):
        j=i+1
        while j<len(lines) and not lines[j].startswith('- proto:'):
            if lines[j].lstrip().startswith('- uid:'):
                ent_start=j
                ent_indent=len(lines[j])-len(lines[j].lstrip())
                k=j+1
                while k<len(lines) and (lines[k].strip() and len(lines[k])-len(lines[k].lstrip())>ent_indent):
                    k+=1
                # within entity block, find Transform component
                t_idx=None
                for m in range(ent_start,k):
                    if re.match(r"^\s*- type:\s*Transform", lines[m]):
                        t_idx=m
                        break
                if t_idx is not None:
                    t_indent=len(lines[t_idx])-len(lines[t_idx].lstrip())
                    rot_idxs=[]
                    for n in range(t_idx+1,k):
                        if re.match(r"^\s*rot\s*:\s*", lines[n]) or re.match(r"^\s*rotation\s*:\s*", lines[n]):
                            rot_idxs.append(n)
                    if len(rot_idxs)>1:
                        # keep last, delete others
                        keep=rot_idxs[-1]
                        for idx in reversed(rot_idxs[:-1]):
                            del lines[idx]
                        changed=True
                        # adjust k because of deletions
                        k -= (len(rot_idxs)-1)
                j=k
            else:
                j+=1
        i=j
    else:
        i+=1
if changed:
    p.write_text('\n'.join(lines)+"\n",encoding='utf-8')
    print('Cleaned duplicates')
else:
    print('No duplicates found')
