"""Durable settings for the plugin's single management View.

With no `_conf_schema.json` AstrBot's duplicate native config UI is not
registered. Config is stored atomically in plugin_data and imported once from
pre-v0.6 AstrBotConfig for upgrades. The legacy file is never modified.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile


def empty_defaults() -> dict:
    # Fail closed: without a registered instance there are no automatic wake
    # rules and no peer-account blocking. Users configure them in the View.
    return {
        "robot_setup": {
            "_linked_active": True, "enabled": False,
            "wake_enabled": True, "wake_groups": [],
            "instances": [], "groups": [], "group_sessions": [],
        },
        "guard_options": {
            "bot_guard_enabled": True, "gate_groups": [],
            "inject_enabled": True, "recent_count": 6,
            "related_count": 8, "recall_search_limit": 5000,
            "max_inject_chars": 2400, "max_saved_per_group": 10000,
            "verbose_log": False,
        },
        "semantic_options": {
            "semantic_enabled": False, "semantic_provider_id": "",
            "semantic_timeout_seconds": 20,
        },
    }


class ManagedConfig(dict):
    def __init__(self, plugin_name: str, *, data_root=None, legacy_config_root=None):
        from astrbot.core.utils.astrbot_path import (
            get_astrbot_plugin_data_path, get_astrbot_config_path,
        )
        super().__init__()
        self.store_dir = Path(data_root if data_root is not None else get_astrbot_plugin_data_path()) / plugin_name
        self.path = self.store_dir / "settings.json"
        self.legacy_path = Path(legacy_config_root if legacy_config_root is not None else get_astrbot_config_path()) / (plugin_name + "_config.json")
        self._lock = asyncio.Lock()
        if self.path.is_file():
            # The new file is authoritative after the first successful save.
            # Corrupted files cause loud startup failure, NOT silent reset.
            incoming = self._load_json(self.path)
        elif self.legacy_path.is_file():
            # Import legacy fields for manual review, never auto-activate.
            # The old file remains untouched as an upgrade/recovery copy.
            incoming = self._load_json(self.legacy_path)
            if not isinstance(incoming, dict):
                raise ValueError("旧配置文件不是 JSON 对象，已停止加载")
            setup = incoming.get("robot_setup")
            if not isinstance(setup, dict):
                setup = {}
                incoming["robot_setup"] = setup
            setup["enabled"] = False
        else:
            incoming = empty_defaults()
        if not isinstance(incoming, dict):
            raise ValueError("配置文件不是 JSON 对象，已停止加载以保护现有设置")
        self.update(copy.deepcopy(incoming))

    @staticmethod
    def _load_json(path: Path) -> dict:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)

    async def save_config_async(self, replace_config: dict | None = None, *, indent: int = 2) -> bool:
        if not isinstance(replace_config, dict):
            raise ValueError("需要已验证的完整配置对象")
        # Serialize saves without exposing partially written state to other
        # message handlers. The replace contains only the three validated
        # top-level sections, so obsolete native/legacy fields disappear.
        async with self._lock:
            snapshot = copy.deepcopy(replace_config)
            self.store_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            # QQ IDs and directory mappings are local personal data.
            if os.name == "posix":
                os.chmod(self.store_dir, 0o700)
            fd, temporary = tempfile.mkstemp(dir=self.store_dir, prefix=".settings-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump(snapshot, out, ensure_ascii=False, indent=indent)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.clear()
            self.update(snapshot)
            return True
