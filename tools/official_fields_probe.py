"""对账探针：录制里 CC 给了哪些官方标识字段，我们在哪些地方还在用启发式推断。

两部分：
1. 枚举全部录制记录的 request headers_safe 键（含出现率），找还没被利用的官方字段
2. 枚举 idx 已有字段，对照 build_dag 的推断点（trigger 边/泳道键/near 边/turn_start），
   看每个推断点是否有更权威的原料
"""
import json, sys, collections
from pathlib import Path

sys.path.insert(0, r"D:\Claude\workshop\cc-wire-analyzer\src")

CAP = Path.home() / ".cc-wire-analyzer" / "captures"
header_keys = collections.Counter()
per_day_version = collections.defaultdict(collections.Counter)
body_keys = collections.Counter()
meta_keys = collections.Counter()
total = 0

for f in sorted(CAP.glob("*.jsonl")):
    if ".idx." in f.name:
        continue
    day = f.name.split(".")[0]
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        req = r.get("request") or {}
        hs = req.get("headers_safe") or {}
        for k in hs:
            header_keys[k] += 1
        ua = hs.get("user-agent", "")
        per_day_version[day][ua] += 1
        body = req.get("body") or {}
        for k in body:
            body_keys[k] += 1
        meta = body.get("metadata") or {}
        for k in meta:
            meta_keys[k] += 1
        total += 1

print(f"records: {total}")
print("\n== request headers_safe 键（出现次数）==")
for k, n in header_keys.most_common():
    print(f"  {n:6d}  {k}")
print("\n== body 顶层键 ==")
for k, n in body_keys.most_common(30):
    print(f"  {n:6d}  {k}")
print("\n== metadata 键 ==")
for k, n in meta_keys.most_common():
    print(f"  {n:6d}  {k}")
print("\n== user-agent（分天版本线）==")
for day in sorted(per_day_version):
    uas = ", ".join(f"{ua}×{n}" for ua, n in per_day_version[day].most_common(3))
    print(f"  {day}: {uas}")
