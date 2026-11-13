"""路径解析：区分开发环境与 PyInstaller 打包环境。"""
import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


# 项目根目录（开发环境）
ROOT = Path(__file__).resolve().parent.parent.parent

# 前端静态资源目录（打包后位于 _MEIPASS/frontend_dist）
def resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend_dist"
    return ROOT / "frontend" / "dist"


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_probe"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "NovelAgent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _maybe_migrate_legacy_data(primary: Path, legacy: Path) -> None:
    """首次改用 AppData 时，把 exe 同级旧 data/ 拷过来（仅 primary 尚无库时）。"""
    if not legacy.is_dir():
        return
    if (primary / "data.db").exists():
        return
    try:
        for item in legacy.iterdir():
            dest = primary / item.name
            if dest.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    except OSError:
        pass


# 数据目录：
# - 打包版默认 %APPDATA%/NovelAgent（重装/换 exe 位置不丢配置）
# - 设 NOVEL_AGENT_DATA 可指定便携目录（如 exe 同级 data）
# - 开发环境用项目 backend/data
def _resolve_data_dir() -> Path:
    custom = os.environ.get("NOVEL_AGENT_DATA", "").strip()
    if custom:
        d = Path(custom)
        d.mkdir(parents=True, exist_ok=True)
        return d

    if is_frozen():
        primary = _app_data_dir()
        legacy = Path(sys.executable).parent / "data"
        _maybe_migrate_legacy_data(primary, legacy)
        return primary

    d = ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA_DIR = _resolve_data_dir()
SKILLS_DIR = DATA_DIR / "skills"

# 内置技能源（打包后位于 _MEIPASS/builtin_skills）
def builtin_skills_src() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", "")) / "builtin_skills"
    return Path(__file__).resolve().parent / "builtin_skills"
