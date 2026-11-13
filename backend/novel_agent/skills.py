"""Skills 系统：可安装的写作技巧扩展。

格式：目录/SKILL.md，YAML frontmatter（name/description/stages）+ Markdown 正文。
安装渠道：内置、本地文件夹、zip 包、GitHub 仓库。
生效方式：按 stages 注入对应阶段（draft/review/revise）的系统提示词。
"""
import json
import re
import shutil
import zipfile
from pathlib import Path

import httpx

from . import db
from .paths import SKILLS_DIR, builtin_skills_src

ALL_STAGES = ("draft", "review", "revise", "wizard")
CONTENT_CAP = 6000  # 单个技能正文注入上限（字符）


class SkillError(Exception):
    pass


# ---------------------------------------------------------------- 解析

def parse_skill_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        meta = _parse_frontmatter(m.group(1))
        body = m.group(2)
    stages = meta.get("stages") or ["draft", "review", "revise"]
    if isinstance(stages, str):
        stages = [s.strip() for s in re.split(r"[,\s]+", stages.strip("[]")) if s.strip()]
    stages = [s for s in stages if s in ALL_STAGES] or ["draft", "review", "revise"]
    name = meta.get("name") or path.parent.name
    return {
        "name": str(name).strip(),
        "description": str(meta.get("description", "")).strip(),
        "stages": stages,
        "always": str(meta.get("always", "false")).lower() in ("true", "1", "yes"),
        "content": body.strip(),
    }


def _parse_frontmatter(block: str) -> dict:
    meta = {}
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip().strip("'\"")
    return meta


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")
    return s or "skill"


# ---------------------------------------------------------------- 安装

def _find_skill_root(extract_dir: Path) -> Path:
    """在解压目录中定位包含 SKILL.md 的目录（深度 <= 2）。"""
    if (extract_dir / "SKILL.md").exists():
        return extract_dir
    for child in sorted(extract_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            return child
    raise SkillError("包内未找到 SKILL.md（应位于根目录或一级子目录）")


def _install_from_dir(src: Path, source: str, enabled: int = 1) -> dict:
    if not (src / "SKILL.md").exists():
        raise SkillError(f"{src} 中未找到 SKILL.md")
    parsed = parse_skill_md(src / "SKILL.md")
    dir_name = _slug(parsed["name"])
    dest = SKILLS_DIR / dir_name
    n = 1
    while dest.exists():
        n += 1
        dest = SKILLS_DIR / f"{dir_name}_{n}"
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return _register(dest.name, parsed, source, enabled)


def _register(dir_name: str, parsed: dict, source: str, enabled: int) -> dict:
    existing = db.query_one("SELECT id FROM skills WHERE dir_name=?", (dir_name,))
    if existing:
        db.execute(
            "UPDATE skills SET name=?, description=?, stages=?, source=? WHERE id=?",
            (parsed["name"], parsed["description"],
             json.dumps(parsed["stages"], ensure_ascii=False), source, existing["id"]),
        )
        sid = existing["id"]
    else:
        sid = db.execute(
            "INSERT INTO skills(dir_name, name, description, stages, enabled, source, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (dir_name, parsed["name"], parsed["description"],
             json.dumps(parsed["stages"], ensure_ascii=False), enabled, source, db.now()),
        )
    return {"id": sid, "name": parsed["name"], "dir_name": dir_name, "source": source}


def install_from_folder(path: str) -> dict:
    src = Path(path)
    if not src.is_dir():
        raise SkillError(f"文件夹不存在：{path}")
    return _install_from_dir(src, "folder")


def install_from_zip(zip_path: Path) -> dict:
    if not zipfile.is_zipfile(zip_path):
        raise SkillError("不是有效的 zip 包")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(zip_path) as zf:
            members = [m for m in zf.namelist()
                       if not m.endswith("/") and not _is_zip_slip(m)]
            zf.extractall(tmp_dir, members=members)
        root = _find_skill_root(tmp_dir)
        return _install_from_dir(root, "zip")


def _is_zip_slip(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return normalized.startswith(("/", "..")) or ":" in normalized.split("/")[0]


def install_from_github(url: str) -> dict:
    m = re.match(r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url.strip())
    if not m:
        raise SkillError("请输入形如 https://github.com/用户名/仓库 的地址")
    owner, repo = m.group(1), m.group(2)
    for branch in ("main", "master"):
        dl = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"
        try:
            resp = httpx.get(dl, follow_redirects=True, timeout=60)
            if resp.status_code == 200:
                import tempfile
                import os
                with tempfile.TemporaryDirectory() as tmp:
                    zip_path = Path(tmp) / "skill.zip"
                    zip_path.write_bytes(resp.content)
                    skill = install_from_zip(zip_path)
                    db.execute("UPDATE skills SET source=? WHERE id=?", (f"github:{owner}/{repo}", skill["id"]))
                    skill["source"] = f"github:{owner}/{repo}"
                    return skill
        except httpx.HTTPError as e:
            raise SkillError(f"下载失败：{e}") from e
    raise SkillError("无法下载仓库（尝试 main/master 分支均失败）")


def uninstall(skill_id: int) -> bool:
    row = db.query_one("SELECT * FROM skills WHERE id=?", (skill_id,))
    if not row:
        return False
    d = SKILLS_DIR / row["dir_name"]
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    db.execute("DELETE FROM skills WHERE id=?", (skill_id,))
    return True


def toggle(skill_id: int, enabled: bool) -> bool:
    row = db.query_one("SELECT id FROM skills WHERE id=?", (skill_id,))
    if not row:
        return False
    db.execute("UPDATE skills SET enabled=? WHERE id=?", (1 if enabled else 0, skill_id))
    return True


# ---------------------------------------------------------------- 同步与注入

def ensure_builtin_skills():
    """首次运行时把内置技能复制到数据目录。"""
    src = builtin_skills_src()
    if not src.exists():
        return
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    for child in sorted(src.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            dest = SKILLS_DIR / child.name
            if not dest.exists():
                shutil.copytree(child, dest)


def rescan():
    """数据目录与 DB 双向同步（新增收录、缺失移除、内容更新）。"""
    ensure_builtin_skills()
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    on_disk = set()
    for child in sorted(SKILLS_DIR.iterdir()):
        if not (child / "SKILL.md").exists():
            continue
        on_disk.add(child.name)
        try:
            parsed = parse_skill_md(child / "SKILL.md")
        except Exception:
            continue
        _register_existing(child.name, parsed)
    for row in db.query("SELECT id, dir_name FROM skills"):
        if row["dir_name"] not in on_disk:
            db.execute("DELETE FROM skills WHERE id=?", (row["id"],))


def _register_existing(dir_name: str, parsed: dict):
    existing = db.query_one("SELECT id, source FROM skills WHERE dir_name=?", (dir_name,))
    if existing:
        db.execute(
            "UPDATE skills SET name=?, description=?, stages=? WHERE id=?",
            (parsed["name"], parsed["description"],
             json.dumps(parsed["stages"], ensure_ascii=False), existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO skills(dir_name, name, description, stages, enabled, source, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (dir_name, parsed["name"], parsed["description"],
             json.dumps(parsed["stages"], ensure_ascii=False), 1, "folder", db.now()),
        )


def list_skills() -> list:
    rows = db.query("SELECT * FROM skills ORDER BY id")
    out = []
    for r in rows:
        stages = db.jload(r["stages"], [])
        out.append({
            "id": r["id"], "name": r["name"], "description": r["description"],
            "stages": stages, "enabled": bool(r["enabled"]),
            "source": r["source"], "dir_name": r["dir_name"],
        })
    return out


def get_skill_content(skill_id: int) -> "dict | None":
    row = db.query_one("SELECT * FROM skills WHERE id=?", (skill_id,))
    if not row:
        return None
    path = SKILLS_DIR / row["dir_name"] / "SKILL.md"
    if not path.exists():
        return None
    parsed = parse_skill_md(path)
    return {"id": row["id"], **{k: parsed[k] for k in ("name", "description", "stages", "content")}}


def build_skills_block(stage: str, cap_total: int = 20000) -> str:
    """为指定阶段拼装启用技能的注入文本。"""
    blocks = []
    total = 0
    for r in db.query("SELECT * FROM skills WHERE enabled=1"):
        stages = db.jload(r["stages"], [])
        if stage not in stages:
            continue
        path = SKILLS_DIR / r["dir_name"] / "SKILL.md"
        if not path.exists():
            continue
        content = parse_skill_md(path)["content"][:CONTENT_CAP]
        if not content:
            continue
        total += len(content)
        if total > cap_total:
            break
        blocks.append(f"【写作技巧 · {r['name']}】\n{content}")
    if not blocks:
        return ""
    return "\n\n---\n\n" + "\n\n".join(blocks) + "\n"
