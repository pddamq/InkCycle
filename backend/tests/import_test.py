# -*- coding: utf-8 -*-
"""导入拆章 / 分析 / 仿写 测试。拆章不依赖 LLM；分析需 stub 或真实 Key。"""
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from novel_agent.importer import split_book, persist_import  # noqa: E402
from novel_agent import db  # noqa: E402
from test_util import ensure_llm_ready  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
c = httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=180)
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


SAMPLE = """秤与灰

第一章 雨夜当铺
夜色铺满长街。林岸把铜牌放在柜上，陆停云神色骤变。

第二章 小秤不撒谎
沈青梧当众鉴定铜牌为违规契约残片，两人被迫联手。

第三章 秤坊的价码
黑市开出天价，买主背后是行会上层。
"""

VOL_SAMPLE = """第一卷 入城
第一章 雨夜
当铺起火。
第二章 铜牌
鉴定开始。
第二卷 摊牌
第一章 大会
舆论倒转。
"""


def test_split():
    print("== 规则拆章 ==")
    r = split_book(SAMPLE, "scale.txt")
    check("识别书名", r["title"] in ("秤与灰", "scale"), r["title"])
    check("拆出3章", r["chapter_count"] == 3, str(r["chapter_count"]))
    titles = [ch["title"] for v in r["volumes"] for ch in v["chapters"]]
    check("章标题含雨夜", any("雨夜" in t for t in titles), str(titles))
    check("章内有正文", all(ch["content"].strip() for v in r["volumes"] for ch in v["chapters"]))

    r2 = split_book(VOL_SAMPLE)
    check("拆出2卷", r2["volume_count"] == 2, str(r2["volume_count"]))
    check("共3章", r2["chapter_count"] == 3, str(r2["chapter_count"]))

    r3 = split_book("Chapter 1 Hello\nbody one\n\nChapter 2 Next\nbody two")
    check("英文 Chapter", r3["chapter_count"] == 2, str(r3["chapter_count"]))

    long = "\n\n".join(f"段落{i}。" + "字" * 400 for i in range(20))
    r4 = split_book(long)
    check("无标题按时长切块", r4["chapter_count"] >= 2, str(r4["chapter_count"]))


def test_persist():
    print("== 落库 ==")
    db.init_db()
    parsed = split_book(SAMPLE)
    pid = persist_import(parsed["title"], "玄幻", parsed["volumes"], "t.txt")
    chs = db.query("SELECT * FROM chapters WHERE project_id=? ORDER BY idx", (pid,))
    check("章节入库", len(chs) == 3, str(len(chs)))
    check("导入章已标记完成", all(ch["book_done"] == 1 for ch in chs))
    ver = db.query_one(
        "SELECT content FROM chapter_versions WHERE id=?", (chs[0]["current_version_id"],))
    check("正文已存版本", ver and "铜牌" in ver["content"])
    proj = db.query_one("SELECT brief FROM projects WHERE id=?", (pid,))
    brief = db.jload(proj["brief"], {})
    check("brief.source=imported", brief.get("source") == "imported")


def test_http():
    print("== HTTP ==")
    ensure_llm_ready(c, PORT)
    prev = c.post("/api/import/preview", json={"text": SAMPLE, "filename": "scale.txt"}).json()
    check("preview 章数", prev.get("chapter_count") == 3, str(prev.get("chapter_count")))
    comm = c.post("/api/import/commit", json={
        "title": prev["title"], "genre": "玄幻", "volumes": prev["volumes"],
    }).json()
    pid = comm.get("id")
    check("commit 成功", isinstance(pid, int) and pid > 0, str(pid))

    evs = []
    with c.stream("POST", f"/api/projects/{pid}/import/analyze") as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                evs.append(__import__("json").loads(line[5:]))
    types = [e.get("type") for e in evs]
    check("analyze 完成", "done" in types and "error" not in types, str(types))
    check("analyze 有文风", "style" in types)
    got = c.get(f"/api/projects/{pid}").json()
    check("项目写入 style", bool(got.get("style")), str(got.get("style"))[:40])
    check("brief 有 style_profile", bool((got.get("brief") or {}).get("style_profile")))
    graph = c.get(f"/api/projects/{pid}/plot-graph").json()
    check("流程图有节点", len(graph.get("nodes") or []) >= 3, str(len(graph.get("nodes") or [])))

    im_evs = []
    with c.stream("POST", f"/api/projects/{pid}/imitate",
                  json={"title": "仿写测试", "premise": "原创仿写", "start": False}) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                im_evs.append(__import__("json").loads(line[5:]))
    im_types = [e.get("type") for e in im_evs]
    im_done = next((e for e in im_evs if e.get("type") == "done"), {})
    nid = im_done.get("id")
    check("仿写 SSE 完成", "done" in im_types and "error" not in im_types, str(im_types))
    check("仿写建书", isinstance(nid, int) and nid != pid, str(im_done))
    np = c.get(f"/api/projects/{nid}").json()
    check("仿写 brief.source", (np.get("brief") or {}).get("source") == "imitated")
    nchs = c.get(f"/api/projects/{nid}/outline").json()
    ncount = sum(len(v["chapters"]) for v in nchs)
    check("仿写带章节骨架", ncount == 3, str(ncount))
    first = nchs[0]["chapters"][0]
    detail = c.get(f"/api/projects/{nid}/chapters/{first['id']}").json()
    check("仿写章无原文", not (detail.get("content") or "").strip())
    src_chars = c.get(f"/api/projects/{pid}/characters").json()
    new_chars = c.get(f"/api/projects/{nid}/characters").json()
    src_names = {sc.get("name") for sc in src_chars}
    check("仿写不复制原书角色", not any(nc.get("name") in src_names for nc in new_chars), str(new_chars))
    check("仿写章标题重置", first.get("title", "").startswith("第"), first.get("title"))


def main():
    test_split()
    test_persist()
    test_http()
    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
