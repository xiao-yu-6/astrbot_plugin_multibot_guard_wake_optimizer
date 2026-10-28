# 贡献指南

## 提交修改

- 问题反馈应包含 AstrBot 版本、适配器、相关设置和最小复现步骤，示例中的账号与群号须替换为虚构值。
- 功能或行为变更应同步更新使用文档和更新记录。
- 保持修改范围明确，避免混入无关格式调整或运行环境文件。

## 开发与检查

内部 Python 包名为 `astrbot_plugin_peer_context_guard`，开发时使用该目录名：

```bash
git clone https://github.com/xiao-yu-6/astrbot_plugin_multibot_guard_wake_optimizer.git astrbot_plugin_peer_context_guard
cd astrbot_plugin_peer_context_guard
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node --check views/settings/app.js
node tests/frontend_lifecycle.cjs
```

上述测试使用模拟事件与模型接口。它们用于回归检查，不能替代实际适配器环境中的兼容性验证。涉及事件优先级、唤醒或调度的修改，应补充相应的框架集成检查；不要向公共群聊发送自动化测试流量。

文档修改检查链接、配置默认值、格式及与实现的一致性即可。

## 兼容性要求

- 保留内部插件标识、配置接口及数据目录。需要改变存储格式时，应提供迁移与回退说明。
- 升级不得擅自扩大群范围、开启语义巡检或清空已有设置及历史。
- 发送者过滤以 QQ 号为依据，不以昵称或自称判断机器人身份。
- 保留 @、命令与发送者门禁的处理边界，避免重复响应。
- 等待窗口按实例、群聊和发送者隔离；巡检任务应能取消并释放占用。
- 群专用正则的继承与覆盖应保持可预测；配置删除后保存、重载不应恢复已删除的条目。
- 配置删除与历史数据清理应分别处理，不得隐式擦除数据库内容。

## 格式与隐私

- 文本文件使用 UTF-8 和 LF；Python 使用 4 空格缩进，前端沿用现有风格。
- 提交前检查完整差异，不只依赖 `.gitignore`。勿提交凭据、实际账号与群聊数据、私有配置、数据库、日志或备份。
- 保留许可证与贡献者版权；引入外部代码前核对其许可条件。
- 安全问题按 [SECURITY.md](SECURITY.md) 处理。

## 分发方式

通过仓库源码安装和更新；不维护 GitHub Release 或预打包安装文件。
