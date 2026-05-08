from __future__ import annotations

from pathlib import Path
from typing import Union


PathLike = Union[str, Path]

WORKFLOW_DIRNAME = "workflow"
STEP1_DIRNAME = "step1_extract_scene"
STEP2_DIRNAME = "step2_traverse_hierarchy"


def _as_path(value: PathLike) -> Path:
    return value if isinstance(value, Path) else Path(value)


def get_workflow_dir(results_dir: PathLike) -> Path:
    return _as_path(results_dir) / WORKFLOW_DIRNAME


def get_step1_results_dir(results_dir: PathLike) -> Path:
    return get_workflow_dir(results_dir) / STEP1_DIRNAME


def get_step2_results_dir(results_dir: PathLike) -> Path:
    return get_workflow_dir(results_dir) / STEP2_DIRNAME


def get_step1_build_asset_dir(results_dir: PathLike) -> Path:
    return get_step1_results_dir(results_dir) / "BuildAsset_info"


def get_step1_tag_manager_dir(results_dir: PathLike) -> Path:
    return get_step1_results_dir(results_dir) / "TagManager_info"


def get_step1_scene_data_dir(results_dir: PathLike) -> Path:
    return get_step1_results_dir(results_dir) / "scene_detailed_info"


def get_step1_scene_meta_dir(results_dir: PathLike) -> Path:
    return get_step1_scene_data_dir(results_dir) / "mainResults"


def get_step1_prefab_dir(results_dir: PathLike) -> Path:
    return get_step1_scene_data_dir(results_dir) / "prefabResults"


def get_step1_script_data_dir(results_dir: PathLike) -> Path:
    return get_step1_results_dir(results_dir) / "script_detailed_info"


def get_step1_gobj_tag_path(results_dir: PathLike, scene_name: str) -> Path:
    return get_step1_results_dir(results_dir) / f"{scene_name}_gobj_tag.json"


def get_step1_gobj_layer_path(results_dir: PathLike, scene_name: str) -> Path:
    return get_step1_results_dir(results_dir) / f"{scene_name}_gobj_layer.json"


def get_step2_gobj_hierarchy_path(results_dir: PathLike, scene_name: str) -> Path:
    return get_step2_results_dir(results_dir) / f"{scene_name}_gobj_hierarchy.json"


def get_step2_source_code_files_path(results_dir: PathLike, scene_name: str) -> Path:
    return get_step2_results_dir(results_dir) / f"coreTP_{scene_name}_source_code_files.json"


def _legacy_scene_data_dir(results_dir: PathLike) -> Path:
    return _as_path(results_dir) / "scene_detailed_info"


def _legacy_scene_meta_dir(results_dir: PathLike) -> Path:
    return _legacy_scene_data_dir(results_dir) / "mainResults"


def _legacy_script_data_dir(results_dir: PathLike) -> Path:
    return _as_path(results_dir) / "script_detailed_info"


def _legacy_gobj_tag_path(results_dir: PathLike, scene_name: str) -> Path:
    return _as_path(results_dir) / f"{scene_name}_gobj_tag.json"


def _legacy_gobj_layer_path(results_dir: PathLike, scene_name: str) -> Path:
    return _as_path(results_dir) / f"{scene_name}_gobj_layer.json"


def _legacy_gobj_hierarchy_path(results_dir: PathLike, scene_name: str) -> Path:
    return _as_path(results_dir) / f"{scene_name}_gobj_hierarchy.json"


def _legacy_source_code_files_path(results_dir: PathLike, scene_name: str) -> Path:
    return _as_path(results_dir) / f"coreTP_{scene_name}_source_code_files.json"


def _prefer_existing(preferred: Path, legacy: Path) -> Path:
    return preferred if preferred.exists() else legacy


def resolve_scene_data_dir(results_dir: PathLike) -> Path:
    return _prefer_existing(get_step1_scene_data_dir(results_dir), _legacy_scene_data_dir(results_dir))


def resolve_scene_meta_dir(results_dir: PathLike) -> Path:
    return _prefer_existing(get_step1_scene_meta_dir(results_dir), _legacy_scene_meta_dir(results_dir))


def resolve_script_data_dir(results_dir: PathLike) -> Path:
    return _prefer_existing(get_step1_script_data_dir(results_dir), _legacy_script_data_dir(results_dir))


def resolve_gobj_tag_path(results_dir: PathLike, scene_name: str) -> Path:
    return _prefer_existing(get_step1_gobj_tag_path(results_dir, scene_name), _legacy_gobj_tag_path(results_dir, scene_name))


def resolve_gobj_layer_path(results_dir: PathLike, scene_name: str) -> Path:
    return _prefer_existing(get_step1_gobj_layer_path(results_dir, scene_name), _legacy_gobj_layer_path(results_dir, scene_name))


def resolve_gobj_hierarchy_path(results_dir: PathLike, scene_name: str) -> Path:
    return _prefer_existing(get_step2_gobj_hierarchy_path(results_dir, scene_name), _legacy_gobj_hierarchy_path(results_dir, scene_name))


def resolve_source_code_files_path(results_dir: PathLike, scene_name: str) -> Path:
    return _prefer_existing(get_step2_source_code_files_path(results_dir, scene_name), _legacy_source_code_files_path(results_dir, scene_name))