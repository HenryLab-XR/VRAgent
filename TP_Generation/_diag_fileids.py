import json, sys
d = json.load(open('Results/Apartment/Apartment_gobj_hierarchy.json', encoding='utf-8'))
items = d if isinstance(d, list) else (list(d.values()) if isinstance(d, dict) else [])

def walk(node, depth=0):
    if not isinstance(node, dict):
        return
    n = node.get('gameobject_name', '')
    gid = node.get('gameobject_id', '')
    grid = node.get('gameobject_id_replace', '')
    pinst = node.get('m_PrefabInstance_fileID') or node.get('prefab_instance_fileID') or ''
    if 'Switch' in n or gid == '574134354' or grid == '574134354' or 'Hall' in n:
        diff = '  *DIFF*' if (gid != grid and grid) else ''
        print(f"{'  '*depth}{n}  id={gid}  id_replace={grid}  prefab_inst={pinst}{diff}")
    for c in node.get('child_relations', []) or []:
        walk(c, depth + 1)

for it in items:
    walk(it)

# Show all top-level keys of a representative node
print("\n--- Top-level keys of first interactable ---")
def first(node):
    if isinstance(node, dict) and 'Switch' in node.get('gameobject_name', ''):
        return node
    for c in (node.get('child_relations') or []) if isinstance(node, dict) else []:
        r = first(c)
        if r: return r
    return None
for it in items:
    n = first(it)
    if n:
        print(json.dumps({k: v for k, v in n.items() if k != 'child_relations'}, indent=2, default=str)[:1200])
        break
