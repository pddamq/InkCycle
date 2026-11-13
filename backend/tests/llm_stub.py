# -*- coding: utf-8 -*-
"""测试用 LLM 桩：替换 novel_agent.llm 的 stream_chat/chat，无需真实 API Key。"""
import asyncio
import json
import re

from novel_agent import llm as llm_mod


async def stub_fetch_models(cfg=None):
    return ["deepseek-chat", "glm-4-flash", "gpt-4o-mini"]


def install():
    """在导入应用 / 启动 uvicorn 之前调用一次。"""
    llm_mod.stream_chat = stub_stream_chat
    llm_mod.chat = stub_chat
    llm_mod.fetch_models = stub_fetch_models


def _sys_text(messages) -> str:
    return " ".join(m.get("content", "") for m in messages if m.get("role") == "system")


def infer_kind(messages, tools):
    if len(messages) == 1 and messages[0].get("role") == "user":
        if "连接成功" in (messages[0].get("content") or ""):
            return "ping"
    sys = _sys_text(messages)
    if "结对写作" in sys or "写作 Agent" in sys or "类似 Cursor" in sys:
        return "chat"
    if "盘问式访谈" in sys:
        return "interview_next"
    if "创作蓝图" in sys and "汇编" in sys:
        return "brief"
    if "极简、准确的情节摘要" in sys:
        return "summary"
    if "世界观架构师" in sys:
        return "wizard_settings"
    if "角色设计师" in sys:
        return "wizard_characters"
    if "大纲师" in sys:
        return "wizard_outline"
    if "文体学家" in sys or "文风档案" in sys:
        return "style_analyze"
    if "结构编辑" in sys or "章节剧情" in sys:
        return "plot_extract"
    if "修改医生" in sys:
        return "revise"
    if "严苛、专业" in sys and "主编" in sys:
        return "review"
    if tools:
        return "draft"
    return "draft"


async def stub_stream_chat(messages, tools=None):
    kind = infer_kind(messages, tools)
    async for ev in _mock_stream(messages, tools, kind):
        yield ev


async def stub_chat(messages, *, stream=True) -> str:
    if not stream:
        return _mock_text(messages, infer_kind(messages, None))
    parts = []
    async for ev in stub_stream_chat(messages, tools=None):
        if ev["type"] == "text":
            parts.append(ev["text"])
    return "".join(parts)


def _extract(messages, pattern):
    for m in messages:
        if m.get("role") == "user":
            mm = re.search(pattern, m.get("content", ""), re.S)
            if mm:
                return mm.group(1).strip()
    return ""


def _has_tool_message(messages):
    return any(m.get("role") == "tool" for m in messages)


async def _mock_stream(messages, tools, mock_kind):
    if mock_kind in ("draft", "interview_next", "brief", "review", "revise", "chat"):
        await asyncio.sleep(0.02)
        yield {"type": "reasoning", "text": "梳理上下文与待办…"}
    if mock_kind == "chat":
        last = messages[-1].get("content", "") if messages else ""
        if "审校" in last:
            text = _mock_review(messages)
            for i in range(0, len(text), 18):
                await asyncio.sleep(0.015)
                yield {"type": "text", "text": text[i:i + 18]}
            return
        if tools and not _has_tool_message(messages):
            text = _mock_draft(messages)
            await asyncio.sleep(0.05)
            yield {"type": "tool_calls", "calls": [
                {"id": "mock_write", "name": "update_chapter", "arguments": {"content": text}}
            ]}
            return
        reply = "好的，正文已写入编辑器。如需调整语气、节奏或某段情节，直接告诉我。"
        for i in range(0, len(reply), 12):
            await asyncio.sleep(0.01)
            yield {"type": "text", "text": reply[i:i + 12]}
        return
    if tools and not _has_tool_message(messages) and mock_kind in ("draft", "interview_next", "brief"):
        candidates = [t for t in tools if t["function"]["name"].startswith("mcp__")] or tools
        t = candidates[0]["function"]
        props = (t.get("parameters") or {}).get("properties") or {}
        args = {}
        if mock_kind == "interview_next":
            args = {"notes": "首轮访谈，先查维度清单"}
        elif mock_kind == "brief":
            args = {"notes": "汇编蓝图前核对覆盖度"}
        elif "keyword" in props:
            args["keyword"] = _extract(messages, r"章节标题：(.+)") or "线索"
        elif "name" in props:
            args["name"] = "林岸"
        await asyncio.sleep(0.05)
        yield {"type": "tool_call_delta", "index": 0, "name": t["name"], "arguments": json.dumps(args, ensure_ascii=False)}
        await asyncio.sleep(0.05)
        yield {"type": "tool_calls", "calls": [
            {"id": "mock_call_1", "name": t["name"], "arguments": args}
        ]}
        return

    text = _mock_text(messages, mock_kind)
    for i in range(0, len(text), 18):
        await asyncio.sleep(0.015)
        yield {"type": "text", "text": text[i:i + 18]}


def _mock_text(messages, kind) -> str:
    if kind == "ping":
        return "连接成功"
    if kind == "review":
        return _mock_review(messages)
    if kind == "interview_next":
        return _mock_interview(messages)
    if kind == "brief":
        return _mock_brief(messages)
    if kind == "summary":
        brief = _extract(messages, r"【章节梗概】\n(.*)") or ""
        content = _extract(messages, r"【章节正文】\n(.*)") or ""
        src = brief or content
        return f"本章推进主线：{src[:100]}。主要人物完成一次关键抉择，未回收伏笔仍保持悬念。"[:150]
    if kind == "wizard_settings":
        return _mock_wizard_settings(messages)
    if kind == "wizard_characters":
        return _mock_wizard_characters(messages)
    if kind == "wizard_outline":
        return _mock_wizard_outline(messages)
    if kind == "revise":
        return _mock_revise(messages)
    if kind == "style_analyze":
        return _mock_style(messages)
    if kind == "plot_extract":
        return _mock_plot(messages)
    return _mock_draft(messages)


def _mock_interview(messages) -> str:
    text = messages[-1].get("content", "") if messages else ""
    turns = text.count("user:")
    if turns <= 0:
        return json.dumps({
            "phase": "asking",
            "intro": "太好了，我们先把这本书的骨架聊清楚，从最核心的开始：",
            "questions": [
                {"key": "logline", "label": "核心创意",
                 "text": "用一句话讲讲你想写的故事：谁、想要什么、遇到什么阻碍？"},
                {"key": "genre", "label": "类型", "text": "想写哪个类型/流派？"},
                {"key": "theme", "label": "主题内核", "text": "你最想借这本书表达什么？"},
            ],
            "covered": [], "missing": ["核心创意", "类型", "主题内核", "主角", "核心冲突"],
        }, ensure_ascii=False)
    if turns == 1:
        return json.dumps({
            "phase": "asking",
            "intro": "很清晰。接着把主角和冲突立起来：",
            "questions": [
                {"key": "protagonist", "label": "主角", "text": "主角是谁？性格、目标、弱点？"},
                {"key": "antagonist", "label": "对手", "text": "主要对手或阻力是谁/什么？"},
                {"key": "conflict", "label": "核心冲突与开篇", "text": "全书核心冲突是什么？"},
            ],
            "covered": ["核心创意", "类型", "主题内核"],
            "missing": ["主角", "对手", "核心冲突", "世界规则", "基调"],
        }, ensure_ascii=False)
    if turns == 2:
        return json.dumps({
            "phase": "asking",
            "intro": "骨架差不多了，再补世界与风格：",
            "questions": [
                {"key": "world", "label": "故事世界", "text": "故事发生在什么时代/世界？"},
                {"key": "tone_style", "label": "基调与文风", "text": "想要的基调与文风？"},
                {"key": "length", "label": "篇幅与结局", "text": "目标总字数、单章字数、结局类型？"},
            ],
            "covered": ["核心创意", "类型", "主题内核", "主角", "对手", "核心冲突"],
            "missing": ["故事世界", "基调文风", "篇幅结局"],
        }, ensure_ascii=False)
    return json.dumps({
        "phase": "ready",
        "intro": "信息已经足够全面了，我这就把它汇编成创作蓝图。",
        "questions": [],
        "covered": ["核心创意", "类型", "主题内核", "主角", "对手", "核心冲突", "故事世界", "基调文风", "篇幅结局"],
        "missing": [],
    }, ensure_ascii=False)


def _mock_brief(messages) -> str:
    text = messages[-1].get("content", "") if messages else ""
    m = re.search(r"user:\s*(.+)", text)
    logline = (m.group(1).strip()[:60] if m else "少年在契约失衡的世界中追查父辈真相")
    return json.dumps({
        "title": "秤与灰", "genre": "玄幻", "subgenre": "悬疑流·契约设定",
        "logline": logline,
        "theme": "真相与代价：知道得越多，越要付出等价交换",
        "audience": "男频为主", "tone": "冷峻克制 + 高浓度悬疑反转",
        "era_setting": "架空旧王朝崩塌百年后的城邦联盟时代",
        "world_rules": "万物可与灵源缔结契约、等价交换",
        "main_scenes": "雾都当铺街、契约师行会",
        "factions": "契约师行会与地下秤坊明争暗斗",
        "protagonist": "林岸，外冷内热，追查父亲契约案真相",
        "antagonist": "裴照，行会上层，极端秩序崇拜者",
        "supporting": "沈青梧为女主与盟友；陆停云为导师",
        "relationships": "林岸与沈青梧互相试探又互相托付",
        "core_conflict": "个人真相 vs 体制秩序",
        "opening_hook": "雨夜当铺，家传铜牌被鉴定为违规契约残片",
        "plot_direction": "入城卷入鉴定案→发现父亲旧案拼图→终局等价交换",
        "ending": "HE：旧案平反、铜牌归位",
        "emotional_beats": "每章一钩、压抑后释放",
        "pov": "第三人称限知", "style": "冷峻白描 + 强画面感",
        "pacing": "快节奏", "chapter_words": 2500, "target_words": 300000,
        "taboos": "不要无脑后宫", "must_have": "契约等价交换硬设定",
        "references": "《诡秘之主》", "extra": "",
    }, ensure_ascii=False)


def _mock_draft(messages) -> str:
    title = _extract(messages, r"章节标题：(.+)") or "无题"
    brief = _extract(messages, r"本章梗概：(.+)") or "主角推进关键事件。"
    names_line = ""
    for m in messages:
        if m.get("role") == "user":
            mm = re.search(r"【人物卡】\n(.+?)\n\n", m.get("content", ""), re.S)
            if mm:
                names_line = mm.group(1)
                break
    names = re.findall(r"^(.{1,8}?)（", names_line, re.M)
    if not names:
        names = ["林岸", "沈青梧"]
    a, b = names[0], (names[1] if len(names) > 1 else "沈青梧")
    brief_sent = re.split(r"[。！？]", brief)[0] or brief
    return (
        f"夜色像浸了墨的宣纸，缓缓铺满长街。风卷起碎纸，打着旋儿贴上斑驳的墙根。\n\n"
        f"{brief_sent}。此刻街口空无一人，只有檐角灯笼在风里摇晃，把{a}的影子拉得很长。\n\n"
        f"“你来了。”{b}的声音从暗处传来，平静得像在陈述天气。\n\n"
        f"{a}没有立刻回答。他想起白天得到的消息，指节因握紧而微微发白。\n\n"
        f"“东西带了吗？”{a}终于开口，嗓音低哑。\n\n"
        f"{b}从袖中取出一枚半旧的铜牌，牌面上刻着模糊的云纹。"
        f"“我只提醒你一次，”{b}说，“今晚之后，有些路就回不了头了。”\n\n"
        f"{a}接过铜牌，指尖抚过裂痕，忽然觉得掌心一凉。远处更鼓敲了三下，"
        f"可他分明感觉到，暗处有不止一双眼睛正在醒来。\n\n"
        f"他抬步走入巷子深处。灯笼的光在身后一盏盏熄灭，仿佛整条街都在为他让路——"
        f"又或者，在替什么人关上门。"
    )


def _mock_revise(messages) -> str:
    content = _extract(messages, r"【原稿】\n(.*)") or ""
    return content.strip() + "\n\n（修订版：已按审校意见收紧节奏、统一人物口吻，并补足伏笔衔接。）"


def _mock_review(messages) -> str:
    content = _extract(messages, r"正文】\n(.*)") or ""
    score = 88 if "修订版" in content else 61
    names = re.findall(r"^(.{1,8}?)（", _extract(messages, r"【人物卡（要点）】\n(.*)"), re.M)
    n1 = names[0] if names else "主角"
    if score >= 85:
        return json.dumps({
            "score": score,
            "summary": "修订稿问题已基本消除，一致性、节奏达标，可进入下一章。",
            "issues": [{"type": "节奏", "severity": "低", "location": "中段",
                        "description": "过渡段稍缓", "suggestion": "可压缩两句环境描写"}],
        }, ensure_ascii=False)
    return json.dumps({
        "score": score,
        "summary": "初稿骨架成立，但存在人物动机薄弱与伏笔缺位两类问题，建议修订。",
        "issues": [
            {"type": "一致性", "severity": "高", "location": "对话段落",
             "description": f"{n1}得知关键消息后的反应过于平静，与其人物卡中的冲动性格不符",
             "suggestion": "增加一处失态细节再回归克制"},
            {"type": "伏笔", "severity": "中", "location": "铜牌道具",
             "description": "铜牌裂痕是新出现的未登记伏笔",
             "suggestion": "在伏笔台账登记，或在后续章节明确其来历"},
            {"type": "文风", "severity": "低", "location": "第2段",
             "description": "带有说明腔", "suggestion": "改为动作呈现"},
        ],
    }, ensure_ascii=False)


def _mock_wizard_settings(messages) -> str:
    premise = _extract(messages, r"核心创意：(.+)") or "少年逆袭"
    genre = _extract(messages, r"类型：(.+)") or "玄幻"
    return json.dumps({
        "sections": [
            {"title": "世界规则", "content": f"世界以契约为最高法则。{premise}的故事就发生在契约失衡的边缘地带。"},
            {"title": "力量体系", "content": "修行分为九阶：启灵、凝纹、铸台、映月、渡厄、归一、窥道、执契、无咎。"},
            {"title": "时代与社会", "content": "旧王朝崩塌百年，城邦联盟松散自治。"},
            {"title": "核心冲突", "content": "主角意外卷入一场跨越两代人的契约骗局。"},
            {"title": "风格基调", "content": f"{genre}底色，冷峻克制的叙述 + 高浓度悬疑反转。"},
        ]
    }, ensure_ascii=False)


def _mock_wizard_characters(messages) -> str:
    return json.dumps([
        {"name": "林岸", "role": "主角", "appearance": "瘦高，左手腕有旧烧伤疤",
         "personality": "外冷内热，关键时刻冲动", "goal": "查清父亲契约案真相",
         "secret": "他能听见灵源的低语", "relationships": "与沈青梧互相试探又互相托付"},
        {"name": "沈青梧", "role": "女主", "appearance": "银灰瞳，随身带一杆黄铜小秤",
         "personality": "表面冷静，私下护短", "goal": "证明师父的死不是意外",
         "secret": "她的黄铜秤封着半份原始契约", "relationships": "与林岸因案结缘"},
        {"name": "陆停云", "role": "导师", "appearance": "跛脚老当铺掌柜",
         "personality": "惜字如金，看似市侩实则通透", "goal": "守完故人托付的最后一年",
         "secret": "他是当年契约骗局的经手人", "relationships": "林岸父亲旧友"},
        {"name": "裴照", "role": "对手", "appearance": "白面无须，永远整洁",
         "personality": "极端秩序崇拜者", "goal": "回收所有违规契约",
         "secret": "他的右眼是契约灵源伪装的", "relationships": "沈青梧名义上的顶头上司"},
    ], ensure_ascii=False)


def _mock_wizard_outline(messages) -> str:
    return json.dumps({
        "volumes": [
            {"title": "第一卷 · 秤与灰", "summary": "林岸入城卷入鉴定案。",
             "chapters": [
                 {"title": "雨夜当铺", "brief": "林岸带家传铜牌进城典当，当铺遭纵火，铜牌易主。"},
                 {"title": "小秤不撒谎", "brief": "林岸追查铜牌，与沈青梧正面相遇。"},
                 {"title": "秤坊的价码", "brief": "黑市秤坊开出天价线索，买主背后是行会上层。"},
                 {"title": "第一枚裂痕", "brief": "找到父亲契约副本，遭裴照拦截。"},
             ]},
            {"title": "第二卷 · 契约之殇", "summary": "旧案全貌逐步揭开。",
             "chapters": [
                 {"title": "低语", "brief": "林岸开始听见灵源低语，沈青梧帮他过关。"},
                 {"title": "两代人的债", "brief": "陆停云坦白当年经手真相。"},
                 {"title": "城邦大会", "brief": "林岸公开违规契约，舆论倒转。"},
                 {"title": "天平倾斜", "brief": "裴照发动清算，卷末大战一触即发。"},
             ]},
            {"title": "第三卷 · 归还", "summary": "终局之战，所有伏笔回收。",
             "chapters": [
                 {"title": "等价", "brief": "林岸以能力为代价换取裴照秘密公开。"},
                 {"title": "无咎", "brief": "裴照被自己的秩序反噬。"},
                 {"title": "九阶之上", "brief": "终战：旧案平反，铜牌归位。"},
             ]},
        ]
    }, ensure_ascii=False)


def _mock_style(messages) -> str:
    return json.dumps({
        "style_summary": "冷峻白描，短句推进，对话有潜台词，少用说明腔。",
        "genre": "玄幻悬疑", "pov": "第三人称限知", "pacing": "快节奏，章末留钩",
        "tone": "克制、阴冷", "sentence": "短句为主，偶有长句铺环境",
        "dialogue": "对白简短，信息藏在潜台词", "vocabulary": "书面白话，少网络词",
        "rhetoric": "意象集中在铜牌、雨、秤",
        "avoid": "排比三连、不禁/微微、说明腔对话、模板式景物首尾",
        "chapter_words": 2200,
    }, ensure_ascii=False)


def _mock_plot(messages) -> str:
    text = messages[-1].get("content", "") if messages else ""
    titles = re.findall(r"【(.+?)】", text)
    if not titles:
        titles = ["未命名"]
    chapters = []
    for i, t in enumerate(titles):
        chapters.append({
            "title": t,
            "summary": f"{t}推进主线，出现关键抉择。",
            "brief": f"{t}的核心事件",
            "characters": [{"name": "林岸", "role": "主角", "note": "追查真相"}] if i == 0 else [],
            "foreshadows": [{"action": "plant" if i == 0 else "resolve",
                             "description": "铜牌裂痕的来历"}],
            "timeline": [{"time_label": f"第{i + 1}夜", "description": f"{t}发生"}],
        })
    return json.dumps({"chapters": chapters}, ensure_ascii=False)
