"""取证：X-Claude-Code-Agent-Id 在真实录制里的覆盖率与稳定性。

回答四个问题：
1. 子代理请求里 agent_id 的覆盖率（全部 / 分天 / 老录制有没有）
2. 同一派生实例（prompt 对齐泳道键）的所有请求是否共享同一个 agent_id（稳定性）
3. 不同派生实例是否会撞同一个 agent_id（唯一性）
4. agent_id 与计费头 cc_is_subagent 的一致率（交叉校验，既有结论复测）
"""
import json, sys, collections
from pathlib import Path

sys.path.insert(0, r"D:\Claude\workshop\cc-wire-analyzer\src")
import classifier  # noqa: E402

CAP = Path.home() / ".cc-wire-analyzer" / "captures"
idx_files = sorted(CAP.glob("*.idx.jsonl"))
print(f"idx files: {len(idx_files)}")

per_day = collections.defaultdict(lambda: [0, 0])   # day -> [subagent reqs, with agent_id]
inst = collections.defaultdict(set)                 # 对齐泳道键 -> {agent_id,...}（"NONE"=缺失）
aid_to_inst = collections.defaultdict(set)          # agent_id -> {对齐泳道键,...}
aid_reqs = collections.Counter()
fp_reqs = 0
mismatch_billing = []

for f in idx_files:
    day = f.name.split(".")[0]
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        kind = classifier.classify_idx(r)
        if kind != "subagent":
            continue
        aid = r.get("agent_id") or ""
        # 重放 build_dag 的 prompt 对齐，拿到该请求的对齐泳道键（对齐不上记 ALIGNED_NONE）
        lane_key = classifier._lane_key(r)
        aligned = "UNALIGNED"
        task = r.get("first_user_task") or ""
        per_day[day][0] += 1
        if aid:
            per_day[day][1] += 1
        # 对齐需要全量 prompts，单日独立重放（与 build_dag 一样按天构建）
        inst_key = None
        recs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        prompts = []
        for rr in recs:
            if classifier.classify_idx(rr) in ("main", "subagent"):
                for p in rr.get("task_prompts") or []:
                    prompts.append((rr.get("id"), p))
        for mid, p in prompts:
            if mid == r.get("id"):
                continue
            probe = p[:classifier.PROMPT_PROBE_LEN]
            if len(p) < classifier.PROMPT_MATCH_MIN or not probe or probe not in task:
                continue
            import hashlib
            inst_key = "agent-" + hashlib.md5(f"{mid}|{p[:classifier.PROMPT_MATCH_LEN]}".encode("utf-8", "replace")).hexdigest()[:8]
            break
        if inst_key is None:
            key = r.get("agent_id") or r.get("agent_fp") or lane_key
            inst_key = "fallback:" + (key[:24] if key else "?")
        inst[inst_key].add(aid or "NONE")
        if aid:
            aid_to_inst[aid].add(inst_key)
            aid_reqs[aid] += 1
        if not aid:
            fp_reqs += 1

print("\n== 1. 覆盖率（分天）==")
for day in sorted(per_day):
    tot, with_aid = per_day[day]
    print(f"  {day}: {with_aid}/{tot} 子代理请求带 agent_id")

print("\n== 2. 实例内稳定性（同一对齐泳道键下的 agent_id 集合）==")
bad = 0
for k, aids in sorted(inst.items()):
    flag = "" if len(aids) == 1 and "NONE" not in aids else "  <-- 注意"
    if flag: bad += 1
    print(f"  {k}: {sorted(aids)}{flag}")
print(f"  异常实例数: {bad}/{len(inst)}")

print("\n== 3. 唯一性（同一 agent_id 被几个实例用）==")
multi = {a: ks for a, ks in aid_to_inst.items() if len(ks) > 1}
print(f"  agent_id 总数 {len(aid_to_inst)}，被多实例复用的: {len(multi)}")
for a, ks in list(multi.items())[:10]:
    print(f"  {a}: {sorted(ks)}")

print(f"\n== 4. 规模 ==  子代理请求共 {sum(v[0] for v in per_day.values())}，无 agent_id 的 {fp_reqs}")
