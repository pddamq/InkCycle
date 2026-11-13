# -*- coding: utf-8 -*-
"""工具层单元测试：直接调用 handler，验证查询类与写入类工具行为（无需起服务）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from novel_agent import db
from novel_agent.tools import collect_tools

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def main():
    db.init_db()
    # 准备一个临时项目 + 卷 + 章
    pid = db.execute(
        "INSERT INTO projects(title, genre, premise, target_words, created_at, updated_at) "
        "VALUES('工具测试书','悬疑','测试',50000,?,?)", (db.now(), db.now()))
    db.execute("INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?)",
               (pid, '[]', db.now()))
    vid = db.execute("INSERT INTO volumes(project_id, idx, title, summary) VALUES(?,?,?,?)",
                     (pid, 0, "第一卷", ""))
    chid = db.execute(
        "INSERT INTO chapters(project_id, volume_id, idx, title, brief, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)", (pid, vid, 0, "测试章", "主角发现线索", db.now(), db.now()))
    # 一个角色 + 一条设定 + 一条已有伏笔
    db.execute("INSERT INTO characters(project_id, name, role, profile, created_at, updated_at) "
               "VALUES(?,?,?,?,?,?)",
               (pid, "林岸", "主角",
                '{"personality":"外冷内热","goal":"查清真相","recent":"本章受伤"}',
                db.now(), db.now()))
    db.execute("INSERT INTO world(project_id, sections, updated_at) VALUES(?,?,?) "
               "ON CONFLICT(project_id) DO UPDATE SET sections=excluded.sections",
               (pid, '[{"title":"力量体系","content":"九阶修行，启灵为第一阶"}]', db.now()))

    tools, handlers = collect_tools(pid, chid, write=True)
    names = [t["function"]["name"] for t in tools]
    check("工具总数=10（7读+3写）", len(tools) == 10, str(len(names)))
    for expect in ["list_characters", "get_character_details", "get_world_setting",
                   "list_open_foreshadowing", "search_previous_chapters", "get_recent_timeline",
                   "get_nearby_chapters", "register_foreshadowing", "resolve_foreshadowing",
                   "add_timeline_event"]:
        check(f"含工具 {expect}", expect in names)

    # ---- 查询类 ----
    r = handlers["list_characters"]({})
    check("list_characters 返回角色", "林岸" in r, r[:40])
    r = handlers["get_character_details"]({"name": "林岸"})
    check("get_character_details 含档案字段", "性格" in r and "近况" in r, r[:60])
    r = handlers["get_character_details"]({"name": "不存在的人"})
    check("get_character_details 未找到给提示", "未找到" in r)
    r = handlers["get_world_setting"]({"keyword": "力量"})
    check("get_world_setting 关键词命中", "九阶修行" in r)
    r = handlers["get_world_setting"]({})
    check("get_world_setting 空词列小节", "力量体系" in r)
    r = handlers["get_nearby_chapters"]({})
    check("get_nearby_chapters 标记当前章", "当前章" in r and "测试章" in r)

    # ---- 写入类：登记伏笔 ----
    r = handlers["register_foreshadowing"]({"description": "铜牌裂痕的来历", "payoff_hint": "第三卷揭晓"})
    check("register_foreshadowing 成功", "已登记伏笔" in r, r)
    fo = db.query("SELECT * FROM foreshadowing WHERE project_id=? AND status='open'", (pid,))
    check("伏笔已入库且关联本章", len(fo) == 1 and fo[0]["planted_chapter_id"] == chid)
    # 去重
    r = handlers["register_foreshadowing"]({"description": "铜牌裂痕的来历"})
    check("register_foreshadowing 去重", "无需重复登记" in r or "已在台账" in r, r)
    check("去重后仍只有1条", len(db.query("SELECT * FROM foreshadowing WHERE project_id=?", (pid,))) == 1)

    # ---- 写入类：回收伏笔 ----
    r = handlers["resolve_foreshadowing"]({"description": "铜牌裂痕"})
    check("resolve_foreshadowing 成功", "已标记伏笔" in r and "已回收" in r, r)
    fo = db.query_one("SELECT * FROM foreshadowing WHERE project_id=?", (pid,))
    check("伏笔状态=paid 且关联回收章", fo["status"] == "paid" and fo["payoff_chapter_id"] == chid)
    r = handlers["resolve_foreshadowing"]({"description": "不存在的伏笔xyz"})
    check("resolve 未匹配给提示", "未找到" in r)

    # ---- 写入类：时间线 ----
    r = handlers["add_timeline_event"]({"time_label": "第1夜", "description": "当铺纵火"})
    check("add_timeline_event 成功", "已记录时间线事件" in r, r)
    tl = db.query("SELECT * FROM timeline_events WHERE project_id=?", (pid,))
    check("时间线已入库且关联本章", len(tl) == 1 and tl[0]["chapter_id"] == chid)
    r = handlers["get_recent_timeline"]({})
    check("get_recent_timeline 读到新事件", "当铺纵火" in r)

    # ---- 只读模式不含写入工具 ----
    tools_ro, handlers_ro = collect_tools(pid, chid, write=False)
    check("write=False 时只有7个读工具", len(tools_ro) == 7, str(len(tools_ro)))
    check("write=False 不含 register_foreshadowing", "register_foreshadowing" not in handlers_ro)

    # 清理
    for sql in ["DELETE FROM timeline_events WHERE project_id=?", "DELETE FROM foreshadowing WHERE project_id=?",
                "DELETE FROM chapters WHERE project_id=?", "DELETE FROM volumes WHERE project_id=?",
                "DELETE FROM characters WHERE project_id=?", "DELETE FROM world WHERE project_id=?",
                "DELETE FROM projects WHERE id=?"]:
        db.execute(sql, (pid,))

    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
