# -*- coding: utf-8 -*-
"""
MCP 按需加载元工具。

AI 的 tools 列表中只注册这一个轻量工具（~100 token），
当用户需要操作小红书/麦当劳时，AI 调用此工具动态加载对应平台的完整工具集。
"""

import logging
from typing import Any, Dict, Set

from tools.base import Tool

logger = logging.getLogger(__name__)


class LoadMCPToolsTool(Tool):
    """元工具：按需加载 MCP Server 的工具集"""

    def __init__(self, tool_registry, mcp_configs: dict):
        """
        Args:
            tool_registry: ToolRegistry 实例，用于动态注册工具
            mcp_configs: MCP 配置字典，格式:
                {
                    "xiaohongshu": {"url": "...", "token": "", "prefix": "xhs_"},
                    "mcdonald":   {"url": "...", "token": "...", "prefix": "mcd_"},
                }
        """
        self._tool_registry = tool_registry
        self._mcp_configs = mcp_configs
        self._loaded: Set[str] = set()

    @property
    def name(self) -> str:
        return "load_mcp_tools"

    @property
    def description(self) -> str:
        return (
            "按需加载外部平台工具。可用平台："
            "xiaohongshu（小红书：搜索/发帖/评论/点赞/收藏等）、"
            "mcdonald（麦当劳：点餐/领券/积分/门店等）。"
            "调用后该平台的所有工具会出现在你的可用工具列表中。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": list(self._mcp_configs.keys()),
                    "description": "要加载的平台名称",
                }
            },
            "required": ["platform"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        platform = kwargs.get("platform", "")

        if platform in self._loaded:
            return {
                "success": True,
                "result": f"{platform} 的工具已经加载过了，可以直接使用。",
            }

        if platform not in self._mcp_configs:
            available = ", ".join(self._mcp_configs.keys())
            return {
                "success": False,
                "error": f"不支持的平台: {platform}，可用: {available}",
            }

        cfg = self._mcp_configs[platform]

        try:
            from tools.mcp_bridge import MCPBridge

            bridge = MCPBridge(
                server_url=cfg["url"],
                token=cfg.get("token", ""),
                name_prefix=cfg.get("prefix", ""),
            )

            if not bridge.connect():
                return {
                    "success": False,
                    "error": f"连接 {platform} MCP 服务失败，请检查服务是否启动。",
                }

            tools = bridge.get_tools()
            for tool in tools:
                self._tool_registry.register(tool)

            self._loaded.add(platform)
            tool_names = [t.name for t in tools]

            logger.info(f"MCP 按需加载: {platform} ({len(tools)} 个工具)")
            return {
                "success": True,
                "result": (
                    f"已加载 {platform} 的 {len(tools)} 个工具: "
                    f"{', '.join(tool_names)}。现在可以使用这些工具了。"
                ),
            }

        except Exception as e:
            logger.error(f"加载 {platform} MCP 工具失败: {e}")
            return {"success": False, "error": f"加载失败: {str(e)}"}
