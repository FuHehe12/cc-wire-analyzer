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
ok(it["status"] == "supported" and it["rev"] == 2, "状态与条目版本都前移")
ok(it["history"] and it["history"][-1]["text"] == "seq151 换了模型", "旧版进了 history")
OB.apply(oid, "sub-8", None, [{"op": "retract_item", "id": iid, "reason": "证据不足"}])
it = [i for i in OB.read(oid)["items"] if i["id"] == iid][0]
ok(it["status"] == "retracted" and it["reason"] == "证据不足", "撤回带原因")
ok(len(it["history"]) == 2, "撤回同样留痕")
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

print()
if FAILED:
    print(f"[FAILED] {len(FAILED)} 条：")
    for m in FAILED:
        print("  -", m)
    sys.exit(1)
print("[ALL PASSED] 外环观测状态：幂等 / 事务 / 冲突 / 引用 / 改判留痕 / id 形状 全部通过 ✓")
