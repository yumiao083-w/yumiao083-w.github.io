# -*- coding: utf-8 -*-
"""
MCP Bridge — 将远程 MCP Server 的工具桥接为本地 Tool

用法:
    from tools.mcp_bridge import MCPBridge
    bridge = MCPBridge(
        server_url="https://mcp.mcd.cn",
        token="YOUR_TOKEN",
        name_prefix="mcd_",  # 给所有工具名加前缀，避免冲突
    )
    tools = bridge.get_tools()  # 返回 Tool 实例列表
    for tool in tools:
        tool_registry.register(tool)
"""

import logging
import json
import requests
from typing import Any, Dict, List, Optional
from tools.base import Tool

logger = logging.getLogger(__name__)


class MCPProxyTool(Tool):
    """动态生成的 MCP 代理 Tool，将调用转发到远程 MCP Server。"""

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_parameters: Dict[str, Any],
        server_url: str,
        token: str,
        display_name: str = "",
        session_id_getter=None,
    ):
        self._name = display_name or tool_name
        self._original_name = tool_name
        self._description = tool_description
        self._parameters = tool_parameters
        self._server_url = server_url
        self._token = token
        self._get_session_id = session_id_getter or (lambda: "")

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """通过 MCP Streamable HTTP 协议调用远程工具"""
        try:
            # 构建 JSON-RPC 请求
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": self._original_name,
                    "arguments": kwargs,
                },
                "id": 1,
            }

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            sid = self._get_session_id()
            if sid:
                headers["Mcp-Session-Id"] = sid

            resp = requests.post(
                self._server_url,
                json=payload,
                headers=headers,
                timeout=300,  # 5分钟，发帖上传图片/视频较慢
                )
            resp.raise_for_status()

            data = resp.json()

            if "error" in data:
                error = data["error"]
                return {
                    "success": False,
                    "error": f"MCP 错误: {error.get('message', str(error))}",
                }

            result = data.get("result", {})

            # MCP 返回的 content 可能是数组格式
            content = result.get("content", [])
            if isinstance(content, list):
                # 提取文本内容
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                result_text = "\n".join(text_parts) if text_parts else json.dumps(result, ensure_ascii=False)
            elif isinstance(content, str):
                result_text = content
            else:
                result_text = json.dumps(result, ensure_ascii=False)

            # 截断过长的结果，避免塞爆 AI 上下文
            try:
                from config import MCP_RESULT_MAX_LENGTH
            except ImportError:
                MCP_RESULT_MAX_LENGTH = 3000
            if len(result_text) > MCP_RESULT_MAX_LENGTH:
                result_text = result_text[:MCP_RESULT_MAX_LENGTH] + f"\n\n... (结果过长，已截断，共{len(result_text)}字符，仅显示前{MCP_RESULT_MAX_LENGTH}字符)"

            return {
                "success": True,
                "result": result_text,
            }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "MCP 调用超时"}
        except Exception as e:
            logger.error(f"MCP 调用失败 ({self._original_name}): {e}")
            return {"success": False, "error": f"MCP 调用失败: {str(e)}"}


class MCPBridge:
    """MCP Server 桥接器，自动发现并生成代理 Tool。"""

    def __init__(
        self,
        server_url: str,
        token: str,
        name_prefix: str = "",
        timeout: int = 15,
    ):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.name_prefix = name_prefix
        self.timeout = timeout
        self._tools: List[MCPProxyTool] = []
        self._server_info: Dict = {}
        self._session_id: str = ""  # MCP Session ID

    def connect(self) -> bool:
        """连接 MCP Server 并获取工具列表"""
        try:
            # 1. Initialize
            init_resp = self._rpc("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "yuan-bot", "version": "1.0"},
            })

            if not init_resp:
                logger.error("MCP Server 初始化失败")
                return False

            self._server_info = init_resp.get("result", {}).get("serverInfo", {})
            logger.info(
                f"MCP Server 已连接: {self._server_info.get('name', '未知')} "
                f"v{self._server_info.get('version', '?')}"
            )

            # 1.5 发送 initialized 通知（MCP 协议要求）
            self._notify("notifications/initialized", {})

            # 2. List tools
            tools_resp = self._rpc("tools/list", {})
            if not tools_resp:
                logger.error("获取 MCP 工具列表失败")
                return False

            tools_data = tools_resp.get("result", {}).get("tools", [])
            logger.info(f"MCP Server 提供 {len(tools_data)} 个工具")

            # 3. 为每个工具创建代理 Tool
            self._tools = []
            for tool_info in tools_data:
                original_name = tool_info.get("name", "")
                display_name = f"{self.name_prefix}{original_name}" if self.name_prefix else original_name

                # 将 inputSchema 转换为 Tool 的 parameters 格式
                input_schema = tool_info.get("inputSchema", {"type": "object", "properties": {}})

                proxy = MCPProxyTool(
                    tool_name=original_name,
                    tool_description=tool_info.get("description", ""),
                    tool_parameters=input_schema,
                    server_url=self.server_url,
                    token=self.token,
                    display_name=display_name,
                    session_id_getter=lambda: self._session_id,
                )
                self._tools.append(proxy)
                logger.info(f"  MCP Tool: {display_name}")

            return True

        except Exception as e:
            logger.error(f"连接 MCP Server 失败: {e}")
            return False

    def get_tools(self) -> List[MCPProxyTool]:
        """返回所有代理 Tool 实例"""
        return self._tools

    def _notify(self, method: str, params: dict) -> None:
        """发送 JSON-RPC 通知（无 id，不期望返回）"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id
            requests.post(
                self.server_url, json=payload, headers=headers, timeout=5,
            )
        except Exception as e:
            logger.debug(f"MCP 通知发送失败 ({method}): {e}")

    def _rpc(self, method: str, params: dict) -> Optional[dict]:
        """发送 JSON-RPC 请求到 MCP Server"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": 1,
            }
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            # 只在有 token 时添加 Authorization
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            # 复用 MCP Session ID
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id

            resp = requests.post(
                self.server_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()

            # 保存 session ID
            sid = resp.headers.get("Mcp-Session-Id", "")
            if sid:
                self._session_id = sid

            return resp.json()
        except Exception as e:
            logger.error(f"MCP RPC 调用失败 ({method}): {e}")
            return None
