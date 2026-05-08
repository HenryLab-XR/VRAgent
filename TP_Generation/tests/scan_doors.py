"""Scan Kitchen_TestRoom.unity for DoorNode instances and extract fileIDs/positions."""
import re
import sys

SCENE = r'D:\--UnityProject\HenryLabXR\VRAgent2.0-PVEO_core\VRAgent\Assets\SampleScene\Kitchen_TestRoom\Kitchen_TestRoom.unity'
DOOR_GUID = '35b2592b8cc0b5b44ad2b30d36f27d85'
DOOR_ROOT_TRANS = '4044343915653978979'
DOOR_ROOT_GO = '4044343915653978978'
DOOR_CTRL = '4570469119082599206'  # DoorController on root GO

content = open(SCENE, encoding='utf-8').read()
docs = re.split(r'--- !u!', content)

print(f'Total docs: {len(docs)}')
print('=== DoorNode PrefabInstance overrides ===')
prefab_insts = []
for d in docs:
    if d.startswith('1001 ') and DOOR_GUID in d and 'm_SourcePrefab' in d:
        m = re.search(r'1001 &(\d+)', d)
        pid = m.group(1) if m else '?'
        name_m = re.search(r'propertyPath: m_Name\s*\n\s*value: (\S[^\n]*)', d)
        name = name_m.group(1).strip() if name_m else '(default DoorNode)'
        x = re.search(r'm_LocalPosition\.x\s*\n\s*value: (\S+)', d)
        y = re.search(r'm_LocalPosition\.y\s*\n\s*value: (\S+)', d)
        z = re.search(r'm_LocalPosition\.z\s*\n\s*value: (\S+)', d)
        xv = x.group(1) if x else '?'
        yv = y.group(1) if y else '?'
        zv = z.group(1) if z else '?'
        par_m = re.search(r'm_TransformParent: \{fileID: (\d+)', d)
        par = par_m.group(1) if par_m else '?'
        print(f'PrefabInst &{pid}  name={name!r}  pos=({xv}, {yv}, {zv})  parent={par}')
        prefab_insts.append(pid)

print('\n=== Stripped objects pointing to DoorNode root ===')
for d in docs:
    if 'stripped' in d:
        for src_id, label in [(DOOR_ROOT_TRANS, 'Transform-root'),
                              (DOOR_ROOT_GO, 'GameObject-root'),
                              (DOOR_CTRL, 'DoorController')]:
            if src_id in d and DOOR_GUID in d:
                hdr = re.search(r'^(\d+) &(\d+) stripped', d, re.MULTILINE)
                if hdr:
                    inst = re.search(r'm_PrefabInstance: \{fileID: (\d+)', d)
                    inst_id = inst.group(1) if inst else '?'
                    print(f'[{label}] class={hdr.group(1)} stripped &{hdr.group(2)} for prefab_inst={inst_id}')
