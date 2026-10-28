"""Regression tests for v0.7.5: shared vs per-group wake, history/guard independent."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from test_linked import example
from astrbot_plugin_peer_context_guard.settings import validate_all
from astrbot_plugin_peer_context_guard.core import build_rules_from_setup, session_config, has_keyword


class WakeOverridePolicyTests(unittest.TestCase):
    def config(self):
        cfg=example()
        cfg["robot_setup"]["group_sessions"][0]["use_custom_wake_regex"]=False
        cfg["robot_setup"]["group_sessions"][0]["wake_regex"]=""
        return cfg

    def test_new_group_defaults_to_shared_wake(self):
        cfg=self.config()
        cfg["robot_setup"]["group_sessions"].append({
            "platform_id":"bot-a","group_id":"234567890",
            "keyword_enabled":True,"use_custom_wake_regex":False,"wake_regex":"",
            "block_bot_replies":True,"bots":[],
        })
        setup=validate_all(cfg)["robot_setup"]
        group=session_config(build_rules_from_setup(setup),"bot-a","234567890")
        self.assertTrue(has_keyword(group,"小A你好"))
        self.assertFalse(has_keyword(group,"阿A你好"))

    def test_inherited_rule_tracks_instance_change(self):
        cfg=self.config()
        cfg["robot_setup"]["instances"][0]["wake_regex"]="(机器人A|新称呼)"
        setup=validate_all(cfg)["robot_setup"]
        group=session_config(build_rules_from_setup(setup),"bot-a","123456789")
        self.assertTrue(has_keyword(group,"新称呼，在吗"))

    def test_custom_only_active_when_enabled_both_levels(self):
        cfg=self.config()
        inst=cfg["robot_setup"]["instances"][0]
        row=cfg["robot_setup"]["group_sessions"][0]
        row["wake_regex"]="(阿A|小A)"
        for mode,custom,expected in [("shared",True,False),("per_group",False,False),("per_group",True,True)]:
            inst["wake_mode"]=mode;row["use_custom_wake_regex"]=custom
            rules=build_rules_from_setup(validate_all(cfg)["robot_setup"])
            self.assertEqual(has_keyword(session_config(rules,"bot-a","123456789"),"阿A你好"),expected)

    def test_custom_reverts_to_common_without_discarding_value(self):
        cfg=self.config()
        row=cfg["robot_setup"]["group_sessions"][0]
        row["wake_regex"]="阿A";row["use_custom_wake_regex"]=True
        cfg["robot_setup"]["instances"][0]["wake_mode"]="shared"
        setup=validate_all(cfg)["robot_setup"]
        self.assertEqual(setup["group_sessions"][0]["wake_regex"],"阿A")
        self.assertTrue(has_keyword(session_config(build_rules_from_setup(setup),"bot-a","123456789"),"小A"))

    def test_guard_and_bots_not_touched_by_group_override(self):
        cfg=self.config();row=cfg["robot_setup"]["group_sessions"][0]
        row["wake_regex"]="阿A";row["use_custom_wake_regex"]=True
        setup=validate_all(cfg)["robot_setup"]
        rule=session_config(build_rules_from_setup(setup),"bot-a","123456789")
        self.assertTrue(rule["block_bot_replies"])
        self.assertIn("1000000003",rule["bots"])

if __name__ == "__main__":unittest.main()
