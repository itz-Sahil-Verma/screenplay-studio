"""Save/load a Project as one JSON file: workspace/<project_id>/project.json."""
from pathlib import Path

from app.config import settings
from app.models import Project


def project_dir(project_id: str) -> Path:
    return settings.workspace / project_id


def save_project(project: Project) -> Path:
    d = project_dir(project.id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".project.tmp"
    tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    path = d / "project.json"
    tmp.replace(path)  # atomic: a crash never leaves a half-written file
    return path


def load_project(project_id: str) -> Project:
    return Project.model_validate_json((project_dir(project_id) / "project.json").read_text(encoding="utf-8"))
