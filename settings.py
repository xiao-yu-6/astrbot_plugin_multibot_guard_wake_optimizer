"""Validate edits from the sole authenticated management View.

Settings live in the plugin data folder. There is no native config editor.
"""
from __future__ import annotations

import copy
import re

from .core import parse_roster, _compiled_regex, timed_regex, REGEX_MATCH_TIMEOUT
from .wake_flow import FLOW_DEFAULTS
from .semantic_judge import semantic_mode

PLATFORM = re.compile(r"[\w.-]{1,80}\Z")
QQ = re.compile(r"[1-9]\d{4,15}\Z")


class InvalidSettings(ValueError):
    pass


def _text(value, label, max_len=90):
    if not isinstance(value, str) or len(value) > max_len or any(ord(c) < 32 for c in value):
        raise InvalidSettings(f"{label} 格式错误或过长")
    return value.strip()


def _bool(value, label):
    if not isinstance(value, bool):
        raise InvalidSettings(f"{label} 只能为开启或关闭")
    return value


def _multiline_text(value, label, max_len):
    if (not isinstance(value, str) or len(value) > max_len
            or any(ord(c) < 32 and c not in "\r\n\t" for c in value)):
        raise InvalidSettings(f"{label} 格式错误或过长")
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _number(value, label, minimum, maximum, default):
    # The View intentionally preserves an empty number input as an empty
    # string. Only an absent/blank field means "use the documented default".
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidSettings(f"{label} 必须在 {minimum} ~ {maximum} 范围内")
    return value


def _regex(value):
    text = _text(value, "唤醒正则", 240)
    if text:
        try:
            if _compiled_regex(text).search("", timeout=REGEX_MATCH_TIMEOUT) is not None:
                raise InvalidSettings("唤醒正则不可匹配空消息")
        except (re.error, timed_regex.error, TimeoutError) as e:
            raise InvalidSettings(f"唤醒正则格式错误：{e}") from e
    return text


def _validated_roster(raw, label: str, self_id: str = "") -> list[str]:
    """Discard *fully blank* editor rows; refuse partial rows and duplicates.

    Alias is optional, and both ``QQ|代号`` and ``QQ|代号|`` work.
    Names and aliases cannot contain extra pipes, line breaks or control chars.
    """
    if not isinstance(raw, list) or len(raw) > 100:
        raise InvalidSettings(f"{label} 机器人列表格式错误或数量超限（最多100）")
    normalized: list[str] = []
    ids: set[str] = set()
    for i, item in enumerate(raw, 1):
        if not isinstance(item, str) or len(item) > 200:
            raise InvalidSettings(f"{label} 第{i}行格式错误或过长")
        if not item.strip(" |\t\r\n"):
            continue  # '添加机器人'以后尚未填写的空白行，可安全保存。
        fields = item.split("|")
        if len(fields) not in (2, 3):
            raise InvalidSettings(f"{label} 第{i}行格式须为 QQ号|代号|可选别名")
        qq = _text(fields[0], f"{label} 第{i}行QQ号", 16)
        name = _text(fields[1], f"{label} 第{i}行机器人代号", 48)
        if not QQ.fullmatch(qq):
            raise InvalidSettings(f"{label} 第{i}行机器人QQ号必填且必须为有效数字")
        if not name:
            raise InvalidSettings(f"{label} 第{i}行机器人代号不能为空")
        if qq in ids:
            raise InvalidSettings(f"{label} 第{i}行机器人QQ号重复：{qq}")
        if self_id and qq == self_id:
            raise InvalidSettings(f"{label} 第{i}行登记了本实例自己的QQ号：{qq}；请只登记其他机器人")
        ids.add(qq)
        aliases: list[str] = []
        if len(fields) == 3 and fields[2].strip():
            for candidate in re.split(r"[,，;；]", fields[2]):
                alias = _text(candidate, f"{label} 第{i}行别名", 48)
                if alias and alias != name and alias not in aliases:
                    aliases.append(alias)
                if len(aliases) > 12:
                    raise InvalidSettings(f"{label} 第{i}行别名最多12个")
        normalized.append(f"{qq}|{name}" + ("|" + ",".join(aliases) if aliases else ""))
    if len(parse_roster(normalized)) != len(normalized):
        raise InvalidSettings(f"{label} 存在无效QQ号、代号或别名")
    return normalized


def validate_all(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise InvalidSettings("提交内容必须为配置对象")
    setup = raw.get("robot_setup")
    guard = raw.get("guard_options")
    semantic = raw.get("semantic_options")
    if not all(isinstance(v, dict) for v in (setup, guard, semantic)):
        raise InvalidSettings("配置缺少三个主区块")
    result = {"robot_setup": {}, "guard_options": {}, "semantic_options": {}}
    root = result["robot_setup"]
    root["_linked_active"] = True
    root["enabled"] = _bool(setup.get("enabled", False), "插件开关")
    root["wake_enabled"] = _bool(setup.get("wake_enabled", True), "关键词唤醒开关")
    instances = setup.get("instances")
    groups = setup.get("groups")
    sessions = setup.get("group_sessions")
    if not isinstance(instances, list) or len(instances)>100 or not isinstance(groups, list) or len(groups)>500 or not isinstance(sessions, list) or len(sessions)>1000:
        raise InvalidSettings("实例、群聊或会话列表类型错误或数量超限")
    platform_ids = set()
    qq_self_ids = set()
    normalized_instances = []
    for i, item in enumerate(instances):
        if not isinstance(item, dict):
            raise InvalidSettings(f"实例 {i+1} 不是有效条目")
        platform = _text(item.get("platform_id", ""), "平台实例 ID", 80)
        if not PLATFORM.fullmatch(platform) or platform in platform_ids:
            raise InvalidSettings(f"重复或无效的平台实例 ID：{platform}")
        platform_ids.add(platform)
        self_qq = _text(item.get("self_qq", ""), "实例QQ", 16)
        if self_qq and (not QQ.fullmatch(self_qq) or self_qq in qq_self_ids):
            raise InvalidSettings(f"机器人 QQ 号无效或重复：{self_qq}")
        if self_qq: qq_self_ids.add(self_qq)
        mode = item.get("wake_mode", "shared")
        if mode not in ("shared", "per_group"):
            raise InvalidSettings("群聊唤醒词模式错误")
        flow = item.get("wake_flow", {})
        if not isinstance(flow, dict):
            raise InvalidSettings("唤醒接话设置格式错误")
        action = flow.get("empty_action", FLOW_DEFAULTS["empty_action"])
        if action not in ("original", "respond", "wait"):
            raise InvalidSettings("空唤醒处理方式错误")
        clean_flow = {
            "enabled": _bool(flow.get("enabled", False), "唤醒接话开关"),
            "empty_action": action,
            "followup_enabled": _bool(flow.get("followup_enabled", False), "同人接话开关"),
        }
        for key, label, minimum, maximum in (
            ("context_count", "附带群聊条数", 0, 50),
            ("context_max_chars", "群聊上下文字符数", 512, 12000),
            ("wait_seconds", "等待秒数", 1, 300),
        ):
            clean_flow[key] = _number(flow.get(key), label, minimum, maximum, FLOW_DEFAULTS[key])
        normalized_instances.append({
            "__template_key":"instance",
            "instance_label":_text(item.get("instance_label", ""), "实例备注", 64) or platform,
            "platform_id":platform,
            "bot_name":_text(item.get("bot_name", ""), "机器人名称", 64) or platform,
            "self_qq":self_qq,
            "keyword_enabled":_bool(item.get("keyword_enabled",True),"实例唤醒开关"),
            "wake_mode":mode,
            "wake_regex":_regex(item.get("wake_regex", "")),
            "semantic_aliases":_text(item.get("semantic_aliases", ""), "目标机器人语义别名", 240),
            "semantic_persona":_multiline_text(item.get("semantic_persona", ""), "机器人参与判断人格", 1200),
            "wake_flow": clean_flow,
        })
    root["instances"] = normalized_instances
    group_ids = set()
    normalized_groups = []
    for i, item in enumerate(groups):
        if not isinstance(item, dict):
            raise InvalidSettings(f"群聊 {i+1} 不是有效条目")
        group_id = _text(item.get("group_id", ""), "群号", 16)
        if not QQ.fullmatch(group_id) or group_id in group_ids:
            raise InvalidSettings(f"群号无效或重复：{group_id}")
        group_ids.add(group_id)
        normalized_groups.append({"__template_key":"group", "group_id":group_id,
                                  "group_label":_text(item.get("group_label", ""), "群聊备注", 64) or group_id})
    root["groups"] = normalized_groups
    seen = set()
    normalized_sessions = []
    for i, item in enumerate(sessions):
        if not isinstance(item, dict):
            raise InvalidSettings(f"会话 {i+1} 不是有效条目")
        platform = _text(item.get("platform_id", ""), "会话实例",80)
        group_id = _text(item.get("group_id", ""), "会话群号",16)
        if platform not in platform_ids or group_id not in group_ids:
            raise InvalidSettings(f"会话 {i+1} 必须选择基础参数表中已有的实例和群聊")
        key=(platform,group_id)
        if key in seen:
            raise InvalidSettings(f"同一个实例与群号不可配置重复会话：{platform} / {group_id}")
        seen.add(key)
        instance = next(x for x in normalized_instances if x["platform_id"] == platform)
        bots = _validated_roster(item.get("bots", []), f"会话 {i+1}", instance["self_qq"])
        custom_enabled = _bool(item.get("use_custom_wake_regex",False), "群专用正则开关")
        custom_regex = _regex(item.get("wake_regex", ""))
        if custom_enabled and instance["wake_mode"] == "per_group" and not custom_regex:
            raise InvalidSettings(f"会话 {i+1} 已开启独立唤醒正则，但正则为空；请填写正则或关闭独立开关")
        normalized_sessions.append({
            "__template_key":"group",
            "platform_id":platform,"group_id":group_id,
            "keyword_enabled":_bool(item.get("keyword_enabled",True),"群聊关键词开关"),
            "use_custom_wake_regex":custom_enabled,
            "wake_regex":custom_regex,
            "bots":bots,
            "block_bot_replies":_bool(item.get("block_bot_replies", True), "防互聊开关"),
        })
    root["group_sessions"] = normalized_sessions
    for field in ("wake_groups",):
        scope=setup.get(field, [])
        if not isinstance(scope, list) or len(scope)>500:
            raise InvalidSettings("关键词群范围列表错误")
        normalized=[]
        for item in scope:
            if isinstance(item, str) and not item.strip():
                continue  # AstrBot native list editor can leave an empty item.
            group_id=_text(item,"关键词群号",16)
            if group_id not in group_ids:
                raise InvalidSettings("关键词群范围须选择已登记的群号")
            if group_id not in normalized: normalized.append(group_id)
        root[field]=normalized

    g=result["guard_options"]
    for key in ("bot_guard_enabled","inject_enabled","verbose_log"):
        g[key]=_bool(guard.get(key, {"bot_guard_enabled":True,"inject_enabled":True,"verbose_log":False}[key]),key)
    scope=guard.get("gate_groups",[])
    if not isinstance(scope,list) or len(scope)>500:
        raise InvalidSettings("防互聊群范围列表错误")
    g["gate_groups"]=[]
    for item in scope:
        if isinstance(item, str) and not item.strip():
            continue
        group_id=_text(item,"防互聊群号",16)
        if group_id not in group_ids:
            raise InvalidSettings("防互聊群范围须选择已登记的群号")
        if group_id not in g["gate_groups"]:g["gate_groups"].append(group_id)
    for k,mn,mx,default in (
       ("recent_count",0,100,6),("related_count",0,100,8),
       ("recall_search_limit",1,10000,5000),("max_inject_chars",512,10000,2400),
       ("max_saved_per_group",1,100000,10000)):
        g[k]=_number(guard.get(k,default),k,mn,mx,default)

    s=result["semantic_options"]
    if "semantic_mode" in semantic:
        mode = semantic.get("semantic_mode")
        if mode not in ("regex_only", "regex_then_semantic", "semantic_only"):
            raise InvalidSettings("语义判断模式必须是仅正则、正则后复核或仅语义")
    else:
        mode = semantic_mode(semantic)
    s["semantic_mode"] = mode
    s["semantic_enabled"] = mode != "regex_only"  # compatible persisted flag
    s["judge_persona"] = _multiline_text(semantic.get("judge_persona", ""), "判断器人格", 2400)
    s["semantic_provider_id"]=_text(semantic.get("semantic_provider_id", ""),"提供商ID",120)
    s["semantic_timeout_seconds"]=_number(semantic.get("semantic_timeout_seconds",20),"语义超时",3,120,20)
    s["semantic_context_count"]=_number(semantic.get("semantic_context_count",4),"语义判断参考消息条数",0,8,4)
    s["patrol_interval_seconds"]=_number(semantic.get("patrol_interval_seconds",15),"巡检窗口秒数",2,120,15)
    s["patrol_cooldown_seconds"]=_number(semantic.get("patrol_cooldown_seconds",45),"巡检冷却秒数",0,3600,45)
    s["patrol_min_messages"]=_number(semantic.get("patrol_min_messages",1),"巡检窗口最少真人消息",1,20,1)
    return result


def migrate_old_config(config: dict, sections: dict) -> dict:
    """Present v0.4 session_rules in the linked editor for a one-time save.

    Exact group entries migrate losslessly. Legacy wildcard rosters are
    copied to known groups only; the old config remains intact as backup.
    """
    legacy = config.get("session_rules")
    setup = sections["robot_setup"]
    if not isinstance(legacy, list) or not legacy or setup.get("_linked_active"):
        return sections
    inst = {}
    for row in setup.get("instances", []):
        if isinstance(row, dict) and row.get("platform_id"):
            inst[row["platform_id"]] = row
    groups = {}
    for g in setup.get("groups", []):
        if isinstance(g,dict) and g.get("group_id"):
            groups[g["group_id"]] = g
    for row in legacy:
        if not isinstance(row, dict):
            continue
        p = str(row.get("platform_id", "")).strip()
        g = str(row.get("group_id", "*")).strip()
        if not PLATFORM.fullmatch(p):
            continue
        if p not in inst:
            inst[p] = {"__template_key":"instance", "instance_label":p,
                       "platform_id":p,"bot_name":row.get("bot_name") or p,
                       "self_qq":"","keyword_enabled":True,
                       "wake_mode":"per_group","wake_regex":""}
        if g == "*":
            inst[p]["bot_name"] = row.get("bot_name") or inst[p]["bot_name"]
            inst[p]["wake_regex"] = row.get("wake_regex","")
            inst[p]["keyword_enabled"] = row.get("keyword_enabled",True)
        elif QQ.fullmatch(g):
            groups.setdefault(g,{"__template_key":"group","group_label":g,"group_id":g})
    setup["instances"] = list(inst.values())
    setup["groups"] = list(groups.values())
    session_map = {}
    wildcards = {}
    for row in legacy:
        if not isinstance(row,dict):
            continue
        p = str(row.get("platform_id", "")).strip()
        g = str(row.get("group_id", "*")).strip()
        if p not in inst:
            continue
        if g == "*":
            wildcards[p] = list(row.get("bots",[]) or [])
            continue
        if g not in groups:
            continue
        mode = inst[p]
        if row.get("wake_regex","") != mode.get("wake_regex",""):
            mode["wake_mode"]="per_group"
        session_map[(p,g)] = {
            "__template_key":"group",
            "platform_id":p,"group_id":g,
            "keyword_enabled":row.get("keyword_enabled", True),
            "use_custom_wake_regex":row.get("wake_regex","") != mode.get("wake_regex",""),
            "wake_regex":row.get("wake_regex", ""),
            "bots":list(row.get("bots",[]) or []),
            "block_bot_replies":row.get("block_bot_replies",True),
        }
    # The legacy wildcard roster applied across all groups. The linked UI
    # allows group-specific rosters only: copy to explicitly listed groups.
    for p, bots in wildcards.items():
        for g in groups:
            if not bots:
                continue
            key=(p,g)
            if key not in session_map:
                session_map[key]={"__template_key":"group",
                    "platform_id":p,"group_id":g,"keyword_enabled":True,
                    "use_custom_wake_regex":False,"wake_regex":"","bots":list(bots),
                    "block_bot_replies":True}
            else:
                current=session_map[key]["bots"]
                existing={str(x).split('|')[0] for x in current if isinstance(x,str)}
                session_map[key]["bots"] = [x for x in bots if isinstance(x,str) and x.split('|')[0] not in existing] + current
    setup["group_sessions"] = list(session_map.values())
    # Mark as unsaved; the old runtime rules continue applying until the user
    # validates and saves this migrated linked layout.
    return sections


def get_current_sections(config: dict) -> dict:
    """Copy from the live AstrBot config without leaking unrelated secrets."""
    sections = copy.deepcopy({
       "robot_setup":dict(config.get("robot_setup", {}) or {}),
       "guard_options":dict(config.get("guard_options", {}) or {}),
       "semantic_options":dict(config.get("semantic_options", {}) or {}),
    })
    return migrate_old_config(config, sections)
