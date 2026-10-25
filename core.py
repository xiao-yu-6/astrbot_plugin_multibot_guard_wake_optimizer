"""AstrBot-independent session configuration, regex policy and persistent read-only peer log.

Only numerical QQ sender IDs determine registered bot identity; nicknames are
labels and must never be used to decide whether an event comes from a bot.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
import re
import os
import sqlite3

# Third-party regex engine supports per-match timeouts, unlike Python re.
import regex as timed_regex

REGEX_MATCH_TIMEOUT = 0.03  # seconds; untrusted group messages must not hang the event loop


_QQ_ID = re.compile(r"[1-9]\d{4,15}\Z")
_PLATFORM = re.compile(r"[\w.-]{1,80}\Z")


def id_set(raw: Any) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str):
        raw = re.split(r"[,，\n;；]+", raw)
    if not isinstance(raw, (list, set, tuple)):
        return set()
    return {str(x).strip() for x in raw if str(x).strip()}


def _name(value: Any) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 48 or any(ord(c) < 32 for c in value):
        return ""
    return value


def parse_roster(raw: Any) -> dict[str, dict[str, Any]]:
    """User-supplied rows are 'QQ|name|alias1,alias2'. Invalid rows ignored.

    String rows are intentionally used because AstrBot's template-list editor
    supports editing a list of plain strings inside each session template.
    """
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, (list, tuple)):
        return result
    for row in raw[:500]:
        if not isinstance(row, str):
            continue
        parts = [s.strip() for s in row.split("|", 2)]
        if len(parts) < 2 or not _QQ_ID.fullmatch(parts[0]):
            continue
        qq, name = parts[:2]
        name = _name(name)
        if not name or qq in result:
            continue
        aliases: list[str] = []
        if len(parts) > 2:
            for alias in re.split(r"[,，;；]+", parts[2]):
                alias = _name(alias)
                if alias and alias != name and alias not in aliases:
                    aliases.append(alias)
                if len(aliases) >= 12:
                    break
        result[qq] = {"qq_id": qq, "name": name, "aliases": aliases}
    return result


def parse_session_rules(raw: Any) -> list[dict]:
    """Normalize AstrBot template_list. Exact group rules override '*' rules."""
    if not isinstance(raw, (list, tuple)):
        return []
    rules: list[dict] = []
    keys: set[tuple[str, str]] = set()
    for row in raw[:200]:
        if not isinstance(row, dict):
            continue
        platform = str(row.get("platform_id") or "").strip()
        group = str(row.get("group_id") or "*").strip()
        if not _PLATFORM.fullmatch(platform) or (group != "*" and not _QQ_ID.fullmatch(group)):
            continue
        key = (platform, group)
        if key in keys:
            continue
        keys.add(key)
        name = _name(row.get("bot_name")) or platform
        expression = str(row.get("wake_regex") or "").strip()
        if len(expression) > 240:
            expression = ""
        if expression:
            try:
                # A regex capable of matching empty text causes accidental
                # unconditional awakening: treat it as disabled.
                compiled = _compiled_regex(expression)
                if compiled.search("", timeout=REGEX_MATCH_TIMEOUT) is not None:
                    expression = ""
            except (re.error, timed_regex.error, TimeoutError):
                expression = ""
        rules.append({
            "platform_id": platform,
            "group_id": group,
            "bot_name": name,
            "wake_regex": expression,
            "keyword_enabled": row.get("keyword_enabled", True) is not False,
            "block_bot_replies": row.get("block_bot_replies", True) is not False,
            "bots": parse_roster(row.get("bots", [])),
        })
    return rules


def session_config(rules: list[dict], platform_id: str, group_id: str) -> dict | None:
    """Overlay group-specific data on optional platform-wide ('*') default."""
    default = exact = None
    for rule in rules:
        if rule["platform_id"] != platform_id:
            continue
        if rule["group_id"] == "*":
            default = rule
        if rule["group_id"] == group_id:
            exact = rule
    if not default and not exact:
        return None
    if not exact:
        return {**default, "bots": dict(default["bots"])}
    if not default:
        return {**exact, "bots": dict(exact["bots"])}
    # Exact session can choose its own wake settings; wildcard roster is
    # explicitly intended for all groups and is extended/overridden here.
    merged = dict(default["bots"])
    merged.update(exact["bots"])
    return {**exact, "bots": merged}


@lru_cache(maxsize=256)
def _compiled_regex(expr: str):
    return timed_regex.compile(expr, timed_regex.IGNORECASE)


def has_keyword(session: dict | None, text: str) -> bool:
    if not session or not session.get("keyword_enabled", True):
        return False
    expr = session.get("wake_regex") or ""
    if not expr or not isinstance(text, str):
        return False
    try:
        return _compiled_regex(expr).search(text[:1000], timeout=REGEX_MATCH_TIMEOUT) is not None
    except (re.error, timed_regex.error, TimeoutError):
        return False


def format_directory(bot_roster: dict[str, dict], self_id: str) -> list[dict]:
    return [
        {"qq": qq, "name": row["name"], "aliases": row.get("aliases", [])}
        for qq, row in list(bot_roster.items())[:200]
        if qq != str(self_id)
    ]


def tokenize(s: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z0-9]{2,}", s.lower()))
    for span in re.findall(r"[\u4e00-\u9fff]+", s):
        words.update(span[i:i + 2] for i in range(max(len(span) - 1, 0)))
        words.update(span[i:i + 3] for i in range(max(len(span) - 2, 0)))
    return words


class PeerStore:
    """Local SQLite log; keyed by instance+group; no remote or cross-group sync."""
    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(path.parent, 0o700)
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=2)
        if os.name == "posix":
            os.chmod(path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=1500")
        self.db.execute('''CREATE TABLE IF NOT EXISTS peer_message (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          platform_id TEXT NOT NULL,
          group_id TEXT NOT NULL,
          sender_id TEXT NOT NULL,
          sender_name TEXT NOT NULL,
          msg_id TEXT,
          content TEXT NOT NULL,
          created_at TEXT NOT NULL
        )''')
        self.db.execute('''CREATE INDEX IF NOT EXISTS ix_peer_scope
          ON peer_message(platform_id,group_id,id DESC)''')
        self.db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS ux_peer_dedup
          ON peer_message(platform_id,group_id,sender_id,msg_id)
          WHERE msg_id IS NOT NULL''')

    def append(self, platform_id: str, group_id: str, sender_id: str,
               sender_name: str, content: str, msg_id: str | None = None,
               max_per_scope: int = 10000) -> bool:
        if not content.strip():
            return False
        limit = max(1, min(int(max_per_scope), 100000))
        cur = self.db.execute('''INSERT OR IGNORE INTO peer_message
          (platform_id,group_id,sender_id,sender_name,msg_id,content,created_at)
          VALUES (?,?,?,?,?,?,?)''', (
            platform_id, group_id, sender_id, sender_name, msg_id,
            content[:1500], datetime.now(timezone.utc).isoformat(timespec="seconds")))
        if cur.rowcount:
            self.db.execute('''DELETE FROM peer_message WHERE id IN (
              SELECT id FROM peer_message WHERE platform_id=? AND group_id=?
              ORDER BY id DESC LIMIT -1 OFFSET ?
            )''', (platform_id, group_id, limit))
        return bool(cur.rowcount)

    def recall(self, platform_id: str, group_id: str, query: str,
               recent_count: int = 6, relevant_count: int = 8,
               candidate_limit: int = 5000, max_chars: int = 2400,
               bot_directory: dict[str, dict] | None = None) -> list[dict]:
        limit = max(1, min(int(candidate_limit), 10000))
        rows = self.db.execute('''SELECT id,sender_name,created_at,content,sender_id
          FROM peer_message WHERE platform_id=? AND group_id=?
          ORDER BY id DESC LIMIT ?''', (platform_id, group_id, limit)).fetchall()
        if not rows:
            return []
        # A user removing a bot from the per-group directory revokes its
        # future visibility to this bot's model, including older records.
        # Archived records remain local for explicit user-initiated recovery.
        allowed_senders = set(bot_directory or {})
        if bot_directory is not None:
            if not allowed_senders:
                return []
            rows = [r for r in rows if r[4] in allowed_senders]
            if not rows:
                return []
        mentioned_ids: set[str] = set()
        if bot_directory:
            for sender, meta in bot_directory.items():
                names = [meta.get("name", ""), *meta.get("aliases", [])]
                if any(isinstance(n, str) and len(n) >= 2 and n in query for n in names):
                    mentioned_ids.add(sender)
        pool = [r for r in rows if r[4] in mentioned_ids] if mentioned_ids else rows
        latest = pool[:max(0, min(int(recent_count), 100))]
        picked = {r[0] for r in latest}
        qtokens = tokenize(query)
        remaining = [r for r in rows if r[0] not in picked]
        def score(r):
            return len(tokenize(r[3]) & qtokens) + (20 if r[4] in mentioned_ids else 0)
        relevant = sorted(((score(r), -i, r) for i, r in enumerate(remaining)), reverse=True)
        chosen = latest + [r for score_, _, r in relevant if score_ > 0][:max(0, min(int(relevant_count), 100))]
        chosen.sort(key=lambda r: r[0])
        output, used = [], 0
        for msgid, saved_name, timestamp, content, sender_id in chosen:
            name = (bot_directory or {}).get(sender_id, {}).get("name") or saved_name
            snippet = content.replace("\r", " ").replace("\n", " ")[:600]
            cost = len(snippet) + len(name) + len(timestamp) + 60
            if used + cost > int(max_chars):
                continue
            output.append({"id": msgid, "sender": name, "sender_id": sender_id,
                           "at": timestamp, "text": snippet})
            used += cost
        return output

    def count(self, platform_id: str, group_id: str) -> int:
        return self.db.execute('''SELECT COUNT(*) FROM peer_message
          WHERE platform_id=? AND group_id=?''', (platform_id, group_id)).fetchone()[0]

    def close(self):
        self.db.close()


def build_rules_from_setup(setup: dict | None) -> list[dict]:
    """Build platform defaults and exact-group overrides from linked UI tables.

    Unregistered groups inherit the corresponding instance-wide default.
    Identifying a peer bot always requires exact sender QQ, not nickname.
    """
    if not isinstance(setup, dict):
        return []
    instances = setup.get("instances", [])
    groups = setup.get("group_sessions", [])
    if not isinstance(instances, list) or not isinstance(groups, list):
        return []
    ids = {}
    raw = []
    for instance in instances[:100]:
        if not isinstance(instance, dict):
            continue
        platform = str(instance.get("platform_id", "")).strip()
        if not _PLATFORM.fullmatch(platform) or platform in ids:
            continue
        ids[platform] = instance
        raw.append({
            "platform_id": platform, "group_id": "*",
            "bot_name": instance.get("bot_name") or instance.get("instance_label") or platform,
            "wake_regex": instance.get("wake_regex", ""),
            "keyword_enabled": instance.get("keyword_enabled", True),
            "block_bot_replies": True,
            "bots": [],
        })
    seen = set()
    for group in groups[:500]:
        if not isinstance(group, dict):
            continue
        platform = str(group.get("platform_id", "")).strip()
        group_id = str(group.get("group_id", "")).strip()
        if platform not in ids or not _QQ_ID.fullmatch(group_id):
            continue
        if (platform, group_id) in seen:
            continue
        seen.add((platform, group_id))
        inst = ids[platform]
        use_group = (inst.get("wake_mode", "shared") == "per_group"
                     and group.get("use_custom_wake_regex") is True)
        raw.append({
            "platform_id": platform, "group_id": group_id,
            "bot_name": inst.get("bot_name") or inst.get("instance_label") or platform,
            "wake_regex": group.get("wake_regex", "") if use_group else inst.get("wake_regex", ""),
            "keyword_enabled": inst.get("keyword_enabled", True) is not False
                 and group.get("keyword_enabled", True) is not False,
            "block_bot_replies": group.get("block_bot_replies", True) is not False,
            "bots": group.get("bots", []),
        })
    return parse_session_rules(raw)


def explicit_local_bot_ids(setup: dict | None) -> set[str]:
    """Only QQ IDs explicitly declared as local bot accounts count globally."""
    result = set()
    if not isinstance(setup, dict):
        return result
    for row in setup.get("instances", []):
        if isinstance(row, dict):
            value = str(row.get("self_qq", "")).strip()
            if _QQ_ID.fullmatch(value):
                result.add(value)
    return result
