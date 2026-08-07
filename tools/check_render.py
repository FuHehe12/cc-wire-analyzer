#!/usr/bin/env python3
"""前端固定高度卡裁切审计（260803）。

根因：v0.4.8 聚合卡固定高度（DGX.NH）+ overflow:hidden 把内容行裁掉了，而 6 条自测全是后端
e2e、前端视觉零系统自测——固定高度卡塞太多行 / overflow 裁内容这类 bug 一直没有自动化防线。
本脚本静态审计所有「固定高度卡」的内容行数是否塞得下它声明的高度常量，抓 v0.4.8 同型。

为什么是静态而不是跑浏览器：项目无 playwright/selenium（单 exe 轻量哲学），运行时 DOM 扫描
无法自动化。静态审计维护一张「卡片 → 内容行数 → padding → 高度常量」清单，断言
`行数 × ROW_H + padding ≤ 常量值`。常量值从 index.html 的 `const DGX={}` 解析，不硬编码——
改常量不用改本脚本。

判据：ROW_H=18（最大内容行高，dn-r1 / dn-badges 实测）。padding 按卡——.dag-node 默认
8px 10px（上下 16），.dag-node.mid 是 4px 10px（上下 8）。
flex 列里固定高度的卡，内容先被 flex-shrink 压扁（scrollHeight==clientHeight，纯 overflow
判据测不出）、再被 overflow:hidden 裁——所以这里是「声明高度 vs 内容需要」的事前审计。

用法：
    uv run python tools/check_render.py            # 审计
    uv run python tools/check_render.py --self-test # 造反例（NH_AGG→62）验证它真会报
"""
import re
import sys
from pathlib import Path

# Windows 默认控制台是 GBK，编不出 ✓ 之类的字符 → print 抛 UnicodeEncodeError，脚本以非零码
# 退出，**检查全过也会被读成失败**（260808 撞到：check_render 全 OK 却崩在最后那句 ALL PASSED）。
# src/ 的自测脚本一直有这段，tools/ 四个漏了；中文输出在 GBK 下也只是乱码不可读。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


INDEX = Path(__file__).resolve().parent.parent / "src" / "templates" / "index.html"
ROW_H = 18   # 最大内容行高（dn-r1 / dn-badges，实测）

# 固定高度卡清单：(卡片名, 内容行数, 上下padding之和, 高度常量名)
# 行数 = 该卡 HTML 模板里纵向并排的顶层内容块数（dn-r1 / dn-meta / dn-badges / dn-you / dn-sum）。
# padding 是卡片级的：.dag-node 默认 8px 10px（上下 16），.dag-node.mid 是 4px 10px（上下 8）。
# 新增固定高度卡时加一行；改某卡内容行数时改这里——这就是审计要保护的契约。
CARDS = [
    ("dagNodeHtml 普通节点（非 mid）", 2, 16, "NH"),        # dn-r1 + dn-meta/sum
    ("dagNodeHtml 中间步 mid",         1, 8,  "NH_MID"),   # dn-r1 单行；.mid padding 4+4
    ("dagTurnCardHtml 轮卡",           4, 16, "NH_TURN"),  # dn-r1 + dn-you + dn-badges + 余量
    ("dagAuxAggHtml 辅助聚合卡",       3, 16, "NH_AGG"),   # dn-r1 + dn-meta + dn-badges
    ("dagRunCardHtml 错误 run",        2, 16, "NH"),        # dn-r1 + dn-sum
]


def parse_dgx(html: str) -> dict:
    """从 index.html 的 `const DGX = { ... }` 提取所有数值常量。"""
    m = re.search(r"const\s+DGX\s*=\s*\{([^}]*)\}", html)
    if not m:
        raise SystemExit("找不到 const DGX={...}——index.html 结构变了，本脚本要更新")
    return {k: int(v) for k, v in re.findall(r"(\w+)\s*:\s*(\d+)", m.group(1))}


def audit(html: str) -> list:
    """返回违规列表 [(卡片名, 行数, 常量名, 常量值或None, 需要高度)]。空 = 全过。"""
    dgx = parse_dgx(html)
    bad = []
    for name, rows, pad, const in CARDS:
        h = dgx.get(const)
        need = rows * ROW_H + pad
        if h is None or need > h:
            bad.append((name, rows, const, h, need))
    return bad


def self_test() -> int:
    """造反例：把 NH_AGG 改回 v0.4.8 的 bug 值 62，验证审计会报。"""
    html = INDEX.read_text(encoding="utf-8")
    if "NH_AGG: 76" not in html:
        print("[SELF-TEST FAIL] index.html 里没有 'NH_AGG: 76'，常量改了？本脚本要更新")
        return 1
    html = html.replace("NH_AGG: 76", "NH_AGG: 62")
    bad = [b for b in audit(html) if b[2] == "NH_AGG"]
    if not bad:
        print("[SELF-TEST FAIL] NH_AGG=62 应触发 OVERFLOW 但审计没报——脚本失效了")
        return 1
    print(f"[SELF-TEST OK] NH_AGG=62 触发 OVERFLOW：{bad[0][0]} 需要 {bad[0][4]}px > 62px")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    html = INDEX.read_text(encoding="utf-8")
    dgx = parse_dgx(html)
    nh = {k: v for k, v in dgx.items() if k.startswith("NH")}
    print(f"固定高度卡裁切审计（内容行数 × {ROW_H} + 上下padding ≤ 高度常量）")
    print("  高度常量:", "  ".join(f"{k}={v}" for k, v in nh.items()))
    print()
    bad = []
    for name, rows, pad, const in CARDS:
        h = dgx.get(const)
        need = rows * ROW_H + pad
        if h is None:
            print(f"  NO_CONST  {name}：常量 {const} 不在 DGX（index.html 改了？）")
            bad.append((name, rows, const, h, need))
        elif need > h:
            print(f"  OVERFLOW  {name}：{rows} 行 → {need}px > {const}={h}（差 {need - h}px）")
            bad.append((name, rows, const, h, need))
        else:
            print(f"  OK        {name}：{rows} 行 → {need}px ≤ {const}={h}")
    print()
    if bad:
        print(f"[FAIL] {len(bad)} 张固定高度卡装不下内容，会被 overflow:hidden 裁切")
        print("       增大对应 DGX 常量，或减少该卡的内容行数")
        sys.exit(1)
    print("[ALL PASSED] 所有固定高度卡都装得下内容 ✓")


if __name__ == "__main__":
    main()
