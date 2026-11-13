"""内置访谈 / 蓝图模板。"""

BUILTIN_TEMPLATES = [
    {
        "name": "玄幻升级流",
        "category": "玄幻",
        "blueprint": {
            "genre": "玄幻", "subgenre": "升级流", "audience": "男频",
            "tone": "爽文", "pov": "第三人称", "chapter_words": 2500, "target_words": 1000000,
            "logline": "废柴少年获奇遇，踏上修炼巅峰之路",
        },
        "seed_history": [
            {"role": "ai", "content": "类型：玄幻升级流\n主角：请介绍你的主角起点与金手指"},
            {"role": "user", "content": "（使用模板，请编辑帮我展开）"},
        ],
    },
    {
        "name": "悬疑推理",
        "category": "悬疑",
        "blueprint": {
            "genre": "悬疑", "subgenre": "本格推理", "audience": "全龄",
            "tone": "紧张", "pov": "第一人称或第三人称有限", "chapter_words": 3000, "target_words": 200000,
        },
        "seed_history": [
            {"role": "ai", "content": "核心谜题是什么？读者何时应感到「原来如此」？"},
        ],
    },
    {
        "name": "都市言情",
        "category": "言情",
        "blueprint": {
            "genre": "言情", "subgenre": "都市", "audience": "女频",
            "tone": "甜虐皆可", "pov": "第三人称", "chapter_words": 2000, "target_words": 150000,
        },
        "seed_history": [],
    },
]
