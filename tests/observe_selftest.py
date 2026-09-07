"""外环观测状态自测：幂等 / 事务 / 冲突 / 引用 / 改判留痕 / id 形状。

跑法：`uv run python tests/observe_selftest.py`

**走临时目录**（`CCWA_HOME` 指到 tmp），不碰真实数据目录——同开发约定第八节那条。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认 GBK
TMP = tempfile.mkdtemp(prefix="ccwa-obs-")
os.environ["CCWA_HOME"] = TMP
os.environ["CCWA_CLAUDE_SETTINGS"] = str(Path(TMP) / "claude-settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import observe_store as OB          # noqa: E402  —— 必须在设好 CCWA_HOME 之后导入

FAILED: list[str] = []


def ok(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILED.append(msg)


def raises(code, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except OB.ObserveError as e:
        return e.code == code
    except Exception:
        return False
    return False


print("== 观测状态：建 / 读 / 列 ==")
st = OB.create({"date": "2026-09-06", "lane": "s-751cdf31"}, "第一次观测")
oid = st["id"]
ok(oid.startswith("obs_") and len(oid) == 11, f"id 形状对：{oid}")
ok(st["revision"] == 0 and st["items"] == [], "新建是空的、revision 从 0 起")
ok(OB.read(oid)["scope"]["lane"] == "s-751cdf31", "范围存下来了")
ok(len(OB.listing()) == 1 and OB.listing()[0]["n_items"] == 0, "列表能列出来")
ok(OB.read("obs_0000000") is None, "读不存在的合法 id 返回 None")
ok(raises("bad_id", OB.read, "../../etc/passwd"), "路径穿越形状的 id 被拒")
ok(raises("bad_id", OB.read, "obs_XYZ"), "非法字符的 id 被拒")

print("\n== 新增 / client_ref 省一轮往返 ==")
r = OB.apply(oid, "sub-1", 0, [
    {"op": "add_item", "kind": "phase", "text": "阶段一：收尾文档编辑",
     "evidence": ["req_7ee737e"], "client_ref": "p1"},
    {"op": "add_item", "kind": "finding", "text": "seq151 换了模型",
     "evidence": ["req_aaa1111"], "client_ref": "f1"},
    {"op": "link_items", "from": "f1", "to": "p1", "type": "belongs_to"},
    {"op": "set_cursor", "cursor": 153},
])
st = r["state"]
ok(len(st["items"]) == 2, "两条都建上了")
ok(set(r["refs"]) == {"p1", "f1"}, "client_ref 映射回来了")
ok(st["items"][1]["links"][0]["to"] == st["items"][0]["id"], "同一批内用 client_ref 关联成功")
ok(st["revision"] == 1 and st["cursor"] == 153, "revision 前移 + 水位记下")

print("\n== 幂等：同一个 submission 重放 ==")
r2 = OB.apply(oid, "sub-1", None, [{"op": "add_item", "kind": "finding", "text": "不该出现"}])
ok(r2["replayed"] is True, "认出是重放")
ok(len(r2["state"]["items"]) == 2, "重放不重复建条目")
ok(r2["state"]["revision"] == 1, "重放不推进 revision")
ok(r2["refs"] == r["refs"], "重放退回原来的 refs")
ok(raises("no_submission", OB.apply, oid, "", 1, [{"op": "add_item", "text": "x"}]),
   "不给 submission_id 直接拒（幂等靠它）")

print("\n== 冲突：base_revision 对不上不静默覆盖 ==")
ok(raises("conflict", OB.apply, oid, "sub-x", 0, [{"op": "add_item", "text": "旧版本写的"}]),
   "拿过期的 base_revision 提交被拒")
ok(len(OB.read(oid)["items"]) == 2, "被拒之后状态没被改动")
ok(OB.apply(oid, "sub-2", None, [{"op": "set_cursor", "cursor": 1}])["state"]["revision"] == 2,
   "不给 base_revision 则跳过版本检查（首版单写者的便利口子）")

print("\n== 事务：一批里有非法操作则整批不生效 ==")
before = OB.read(oid)
ok(raises("bad_kind", OB.apply, oid, "sub-3", None, [
    {"op": "add_item", "kind": "finding", "text": "合法的一条"},
    {"op": "add_item", "kind": "不存在的类型", "text": "非法的一条"},
]), "非法 kind 让整批失败")
after = OB.read(oid)
ok(len(after["items"]) == len(before["items"]), "失败批次里合法的那条也没写进去")
ok(after["revision"] == before["revision"], "失败批次不推进 revision")
ok(raises("no_item", OB.apply, oid, "sub-4", None,
          [{"op": "link_items", "from": "i_nope00", "to": "i_nope01"}]),
   "关联不存在的条目被拒")
ok(raises("empty_text", OB.apply, oid, "sub-5", None,
          [{"op": "add_item", "kind": "finding", "text": "   "}]), "空正文被拒")
ok(raises("empty_ops", OB.apply, oid, "sub-6", None, []), "空批次被拒")

print("\n== 改判：回改原条目并留痕 ==")
iid = OB.read(oid)["items"][1]["id"]
OB.apply(oid, "sub-7", None, [{"op": "update_item", "id": iid,
                               "patch": {"text": "seq151 换到 glm-5.3（已核对）",
                                         "status": "supported"}}])
it = [i for i in OB.read(oid)["items"] if i["id"] == iid][0]
ok(it["text"].startswith("seq151 换到 glm-5.3"), "正文被改判（不是追加一条新的）")
ok(it["status"] == "supported" and it["rev"] == 3, "关联与改判各推进条目版本")
ok(it["history"] and it["history"][-1]["text"] == "seq151 换了模型", "旧版进了 history")
OB.apply(oid, "sub-8", None, [{"op": "retract_item", "id": iid, "reason": "证据不足"}])
it = [i for i in OB.read(oid)["items"] if i["id"] == iid][0]
ok(it["status"] == "retracted" and it["reason"] == "证据不足", "撤回带原因")
ok(len(it["history"]) == 3, "关联、改判与撤回均留痕")
ok(OB.listing()[0]["n_items"] == 1 and OB.listing()[0]["n_retracted"] == 1,
   "列表把撤回的与在册的分开数")

print("\n== 落盘是原子替换，不留半截文件 ==")
ok(not list(OB.OBS_DIR.glob(".*.writing")), "没有残留的 .writing 临时文件")
ok((OB.OBS_DIR / f"{oid}.json").exists(), "状态文件在")

print("\n== 历史与提交流水有界 ==")
for n in range(OB.HISTORY_MAX + 5):
    OB.apply(oid, f"bulk-{n}", None, [{"op": "update_item", "id": iid,
                                       "patch": {"text": f"第 {n} 次改判"}}])
it = [i for i in OB.read(oid)["items"] if i["id"] == iid][0]
ok(len(it["history"]) == OB.HISTORY_MAX, f"history 封顶在 {OB.HISTORY_MAX}")
ok(len(OB.read(oid)["submits"]) <= OB.SUBMITS_MAX, f"提交流水封顶在 {OB.SUBMITS_MAX}")

print("\n== 删除 ==")
ok(OB.delete(oid)["deleted"] is True, "删得掉")
ok(OB.read(oid) is None, "删完读不到")
ok(raises("not_found", OB.delete, oid), "重复删明确报不存在")


print("\n== 语义轨迹字段：兼容、覆盖集合和完整历史 ==")
graph = OB.create({"date": "2026-09-08", "lane": "s-test"})
gid = graph["id"]
r = OB.apply(gid, "graph-1", 0, [
    {"op": "add_item", "kind": "goal", "text": "完成用户目标", "client_ref": "goal"},
    {"op": "add_item", "kind": "phase", "text": "验证代码", "title": " 验证 ",
     "progress": "active", "covers": ["req_a", "req_b", "req_a"], "client_ref": "phase"},
    {"op": "add_item", "kind": "artifact", "text": "补丁文件", "client_ref": "artifact"},
    {"op": "add_item", "kind": "check", "text": "回归测试", "client_ref": "check"},
])
phase_id = r["refs"]["phase"]
phase = next(x for x in r["state"]["items"] if x["id"] == phase_id)
ok(phase["title"] == "验证" and phase["covers"] == ["req_a", "req_b"], "短标题归一、覆盖去重保序")
legacy = r["state"]["items"][0]
ok("covers" not in legacy and "progress" not in legacy, "旧条目形状不被强行填默认字段")
OB.apply(gid, "graph-2", 1, [{"op": "update_item", "id": phase_id, "patch": {
    "title": "", "progress": "done", "covers": [], "evidence": ["req_c"]}}])
phase = next(x for x in OB.read(gid)["items"] if x["id"] == phase_id)
old = phase["history"][-1]
ok(phase["status"] == "tentative" and phase["progress"] == "done", "执行完成不自动改变判断可信状态")
ok(old["title"] == "验证" and old["covers"] == ["req_a", "req_b"] and old["progress"] == "active",
   "覆盖、进度、标题的旧版完整保留")
ok(old["evidence"] == [] and "links" in old and "history" not in old, "旧证据与关系也保留，历史不递归膨胀")

def reject_patch(code, patch, label):
    before_bytes = OB._file(gid).read_bytes()
    rejected = raises(code, OB.apply, gid, "reject-" + label, None, [
        {"op": "set_cursor", "cursor": 888},
        {"op": "update_item", "id": phase_id, "patch": patch},
    ])
    ok(rejected and OB._file(gid).read_bytes() == before_bytes, label + "拒绝且状态/水位/历史/流水均未变化")

for value in [None, 12, [], "x" * 201]:
    reject_patch("bad_title", {"title": value}, "非法标题 " + repr(value)[:30])
for value in [None, True, "supported", "DONE", []]:
    reject_patch("bad_progress", {"progress": value}, "非法执行进度 " + repr(value))
for value in [None, "req_a", [4], [""], ["req_../x"], ["req_a\n"], ["req_a"] * 2001]:
    reject_patch("bad_covers", {"covers": value}, "非法覆盖 " + repr(value)[:30])
full_covers = [f"req_{i}" for i in range(2000)]
rr = OB.apply(gid, "max-covers", None, [{"op": "update_item", "id": phase_id,
                                         "patch": {"covers": full_covers}}])
ok(next(x for x in rr["state"]["items"] if x["id"] == phase_id)["covers"] == full_covers,
   "2000 个显式请求全部保存，不静默截断")

print("\n== 预测：结构、原版冻结与撤回后仍不可改写 ==")
forecast = {"after_rid": "req_b", "horizon_steps": 5, "criterion": "执行回归测试"}
pr = OB.apply(gid, "forecast-1", None, [{"op": "add_item", "kind": "prediction",
    "text": "下一步运行测试", "title": "测试候选", "forecast": forecast, "client_ref": "p"}])
pid = pr["refs"]["p"]
for patch in [{"text": "下一步提交"}, {"kind": "finding"},
              {"forecast": dict(forecast, horizon_steps=10)}]:
    before_bytes = OB._file(gid).read_bytes()
    ok(raises("forecast_locked", OB.apply, gid, "locked", None, [
        {"op": "set_cursor", "cursor": 999}, {"op": "update_item", "id": pid, "patch": patch}])
       and OB._file(gid).read_bytes() == before_bytes, "不能覆盖预测正文/类型/窗口，整批回滚")
for bad in [None, {}, dict(forecast, extra=True), dict(forecast, after_rid="../x"),
            dict(forecast, horizon_steps=True), dict(forecast, horizon_steps="5"),
            dict(forecast, horizon_steps=0), dict(forecast, horizon_steps=5001),
            dict(forecast, criterion=" "), dict(forecast, criterion="x" * 2001)]:
    before_bytes = OB._file(gid).read_bytes()
    ok(raises("bad_forecast", OB.apply, gid, "bad-forecast", None, [
        {"op": "add_item", "kind": "prediction", "text": "测试", "forecast": bad}])
       and OB._file(gid).read_bytes() == before_bytes, "非法预测结构被拒: " + repr(bad)[:70])
reject_patch("bad_forecast", {"forecast": forecast}, "非预测不能携带 forecast")
OB.apply(gid, "forecast-review", None, [{"op": "update_item", "id": pid,
    "patch": {"status": "supported", "evidence": ["req_c"], "forecast": forecast,
              "text": "下一步运行测试"}}])
p = next(x for x in OB.read(gid)["items"] if x["id"] == pid)
ok(p["history"][-1]["forecast"] == forecast, "核对状态可更新，原预测结构进入完整历史")
OB.apply(gid, "forecast-retract", None, [{"op": "retract_item", "id": pid, "reason": "新线索改变判断"}])
ok(raises("forecast_locked", OB.apply, gid, "rewrite-withdrawn", None, [
    {"op": "update_item", "id": pid, "patch": {"text": "改成已经发生的事"}}]), "撤回后仍不能改写原预测")
replacement = OB.apply(gid, "forecast-replacement", None, [{"op": "add_item", "kind": "prediction",
    "text": "先检查依赖", "forecast": dict(forecast, after_rid="req_c")}])
ok(len([i for i in replacement["state"]["items"] if i["kind"] == "prediction"]) == 2,
   "改判新建候选，旧预测与撤回理由仍在")

print("\n== 原子替换实际失败：不前移水位或保存半份新字段 ==")
from unittest.mock import patch as mock_patch
before_bytes = OB._file(gid).read_bytes()
with mock_patch.object(Path, "replace", side_effect=OSError("simulated replace failure")):
    failed_write = raises("write_failed", OB.apply, gid, "disk-failure", None, [
        {"op": "update_item", "id": phase_id, "patch": {"progress": "blocked", "covers": ["req_z"]}},
        {"op": "set_cursor", "cursor": 9999},
    ])
ok(failed_write and OB._file(gid).read_bytes() == before_bytes, "替换失败后磁盘上的整个状态逐字节不变")
retry = OB.apply(gid, "disk-failure", None, [{"op": "set_cursor", "cursor": 55}])
ok(not retry["replayed"] and retry["state"]["cursor"] == 55, "失败提交未占用幂等键，恢复后可正常写入")

print()
if FAILED:
    print(f"[FAILED] {len(FAILED)} 条：")
    for m in FAILED:
        print("  -", m)
    sys.exit(1)
print("[ALL PASSED] 外环观测状态：幂等 / 事务 / 冲突 / 引用 / 改判留痕 / id 形状 全部通过 ✓")
