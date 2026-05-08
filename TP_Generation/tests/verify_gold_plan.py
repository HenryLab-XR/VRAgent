import json
p = r'D:\--UnityProject\HenryLabXR\VRAgent2.0-PVEO_core\TP_Generation\Results\Kitchen_TestRoom\gold-manual-kitchen-v1\test_plan.json'
d = json.load(open(p, encoding='utf-8'))
print('taskUnits:', len(d['taskUnits']))
for i, u in enumerate(d['taskUnits']):
    a = u['actionUnits'][0]
    print(f"{i+1:2d}. {a.get('source_object_name','?'):28s}  type={a.get('type','?'):8s}  skip={a.get('skip_move', False)}")
