# -*- coding: utf-8 -*-
"""高德地图 Tool — POI搜索、周边搜索、地理编码、路线规划"""

import logging
import requests
import urllib.parse
from typing import Any, Dict
from tools.base import Tool

logger = logging.getLogger(__name__)

AMAP_KEY = "cc3f32d36404453d7dadf6cf1cdae10f"
BASE_URL = "https://restapi.amap.com/v3"


def _amap_get(endpoint: str, params: dict) -> dict:
    """发送高德 API 请求。"""
    params["key"] = AMAP_KEY
    params["output"] = "JSON"
    url = f"{BASE_URL}{endpoint}?{urllib.parse.urlencode(params)}"
    resp = requests.get(url, timeout=10, headers={"User-Agent": "yuan-bot/1.0"})
    resp.raise_for_status()
    return resp.json()


def _format_pois(pois: list, max_items: int = 8) -> str:
    """格式化 POI 列表为可读文本。"""
    if not pois:
        return "未找到相关结果。"
    lines = []
    for i, p in enumerate(pois[:max_items], 1):
        name = p.get("name", "")
        address = p.get("address", "") or ""
        tel = p.get("tel", "") or ""
        distance = p.get("distance", "")
        biz = p.get("biz_ext", {}) if isinstance(p.get("biz_ext"), dict) else {}
        rating = biz.get("rating", "")
        cost = biz.get("cost", "")

        line = f"{i}. {name}"
        if address:
            line += f"\n   📍 {address}"
        if distance:
            line += f"（{distance}m）"
        if tel:
            line += f"\n   📞 {tel}"
        extras = []
        if rating and rating != "[]":
            extras.append(f"⭐{rating}")
        if cost and cost != "[]":
            extras.append(f"💰人均¥{cost}")
        if extras:
            line += f"  {'  '.join(extras)}"
        lines.append(line)
    return "\n".join(lines)


def _format_route(data: dict, mode: str) -> str:
    """格式化路线规划结果。"""
    route = data.get("route", {})
    if not route:
        return "未找到路线。"

    origin_addr = route.get("origin", "起点")
    dest_addr = route.get("destination", "终点")

    if mode == "driving":
        paths = route.get("paths", [])
        if not paths:
            return "未找到驾车路线。"
        p = paths[0]
        dist_km = round(int(p.get("distance", 0)) / 1000, 1)
        duration_min = round(int(p.get("duration", 0)) / 60)
        tolls = p.get("tolls", "0")
        steps = p.get("steps", [])
        road_names = []
        for s in steps[:8]:
            road = s.get("road", "")
            if road and road not in road_names:
                road_names.append(road)
        result = f"🚗 驾车路线：{dist_km}公里，约{duration_min}分钟"
        if tolls and tolls != "0":
            result += f"，过路费约¥{tolls}"
        if road_names:
            result += f"\n   途经：{'→'.join(road_names)}"
        return result

    elif mode == "walking":
        paths = route.get("paths", [])
        if not paths:
            return "未找到步行路线。"
        p = paths[0]
        dist_m = int(p.get("distance", 0))
        duration_min = round(int(p.get("duration", 0)) / 60)
        if dist_m >= 1000:
            dist_str = f"{round(dist_m / 1000, 1)}公里"
        else:
            dist_str = f"{dist_m}米"
        return f"🚶 步行路线：{dist_str}，约{duration_min}分钟"

    elif mode == "transit":
        transits = route.get("transits", [])
        if not transits:
            return "未找到公交路线。"
        results = []
        for j, t in enumerate(transits[:3], 1):
            dist_km = round(int(t.get("distance", 0)) / 1000, 1)
            duration_min = round(int(t.get("duration", 0)) / 60)
            cost = t.get("cost", "")
            segments = t.get("segments", [])
            transit_names = []
            for seg in segments:
                bus = seg.get("bus", {})
                bus_lines = bus.get("buslines", [])
                for bl in bus_lines[:1]:
                    line_name = bl.get("name", "")
                    if line_name:
                        transit_names.append(line_name)
            line_text = f"方案{j}：{dist_km}公里，约{duration_min}分钟"
            if cost:
                line_text += f"，约¥{cost}"
            if transit_names:
                line_text += f"\n   乘坐：{'→'.join(transit_names)}"
            results.append(line_text)
        return "🚌 公交路线：\n" + "\n".join(results)

    elif mode == "bicycling":
        paths = data.get("data", {}).get("paths", [])
        if not paths:
            return "未找到骑行路线。"
        p = paths[0]
        dist_m = int(p.get("distance", 0))
        duration_min = round(int(p.get("duration", 0)) / 60)
        if dist_m >= 1000:
            dist_str = f"{round(dist_m / 1000, 1)}公里"
        else:
            dist_str = f"{dist_m}米"
        return f"🚲 骑行路线：{dist_str}，约{duration_min}分钟"

    return "路线信息解析失败。"


class MapSearchTool(Tool):
    """高德地图搜索工具"""

    @property
    def name(self) -> str:
        return "map_search"

    @property
    def description(self) -> str:
        return (
            "地图搜索工具，基于高德地图。支持以下功能：\n"
            "1. POI搜索：按关键词搜索某城市的商家/地点（如餐厅、酒店、景点）\n"
            "2. 周边搜索：搜索某地址/坐标附近的商家/地点\n"
            "3. 地理编码：将地址转换为经纬度坐标\n"
            "4. 路线规划：查询两地之间的驾车/步行/公交/骑行路线\n"
            "当用户询问"附近有什么""搜一下XX""怎么去""多远""找一家"等问题时使用。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["poi_search", "nearby_search", "geocode", "route"],
                    "description": (
                        "操作类型：\n"
                        "- poi_search: 关键词搜索（需要keywords和city）\n"
                        "- nearby_search: 周边搜索（需要location或address + keywords）\n"
                        "- geocode: 地址转坐标（需要address）\n"
                        "- route: 路线规划（需要origin和destination）"
                    ),
                },
                "keywords": {
                    "type": "string",
                    "description": "搜索关键词，如"火锅""咖啡店""超市"",
                },
                "city": {
                    "type": "string",
                    "description": "城市名称，如"北京""杭州"，用于POI搜索",
                },
                "address": {
                    "type": "string",
                    "description": "地址文本，用于地理编码或作为周边搜索的中心点",
                },
                "location": {
                    "type": "string",
                    "description": "经纬度坐标，格式'经度,纬度'（如'116.397,39.909'）",
                },
                "radius": {
                    "type": "integer",
                    "description": "周边搜索半径（米），默认1000",
                },
                "origin": {
                    "type": "string",
                    "description": "路线规划起点（地址文本）",
                },
                "destination": {
                    "type": "string",
                    "description": "路线规划终点（地址文本）",
                },
                "travel_mode": {
                    "type": "string",
                    "enum": ["driving", "walking", "transit", "bicycling"],
                    "description": "出行方式，默认driving",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")

        try:
            if action == "poi_search":
                return await self._poi_search(kwargs)
            elif action == "nearby_search":
                return await self._nearby_search(kwargs)
            elif action == "geocode":
                return await self._geocode(kwargs)
            elif action == "route":
                return await self._route(kwargs)
            else:
                return {"success": False, "error": f"未知操作: {action}"}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "地图查询超时，请稍后再试"}
        except Exception as e:
            logger.error(f"地图查询失败: {e}", exc_info=True)
            return {"success": False, "error": f"地图查询失败: {str(e)}"}

    async def _poi_search(self, kwargs: dict) -> Dict[str, Any]:
        keywords = kwargs.get("keywords", "")
        city = kwargs.get("city", "")
        if not keywords:
            return {"success": False, "error": "POI搜索需要提供 keywords 参数"}

        params = {"keywords": keywords, "extensions": "all", "offset": "10"}
        if city:
            params["city"] = city
            params["citylimit"] = "true"

        data = _amap_get("/place/text", params)
        if data.get("status") != "1":
            return {"success": False, "error": data.get("info", "查询失败")}

        pois = data.get("pois", [])
        total = data.get("count", 0)
        result_text = _format_pois(pois)
        return {
            "success": True,
            "result": f"在{city or '全国'}搜索「{keywords}」，共{total}个结果：\n{result_text}",
            "total": total,
        }

    async def _nearby_search(self, kwargs: dict) -> Dict[str, Any]:
        keywords = kwargs.get("keywords", "")
        location = kwargs.get("location", "")
        address = kwargs.get("address", "")
        radius = kwargs.get("radius", 1000)

        # 如果提供了地址但没坐标，先做地理编码
        if address and not location:
            geo_result = await self._geocode({"address": address, "city": kwargs.get("city", "")})
            if not geo_result.get("success"):
                return geo_result
            location = geo_result.get("location", "")

        if not location:
            return {"success": False, "error": "周边搜索需要提供 location 或 address 参数"}

        params = {
            "location": location,
            "radius": str(radius),
            "extensions": "all",
            "offset": "10",
        }
        if keywords:
            params["keywords"] = keywords

        data = _amap_get("/place/around", params)
        if data.get("status") != "1":
            return {"success": False, "error": data.get("info", "查询失败")}

        pois = data.get("pois", [])
        total = data.get("count", 0)
        result_text = _format_pois(pois)
        center = address or location
        return {
            "success": True,
            "result": f"在{center}附近{radius}米内搜索「{keywords or '所有'}」，共{total}个结果：\n{result_text}",
            "total": total,
        }

    async def _geocode(self, kwargs: dict) -> Dict[str, Any]:
        address = kwargs.get("address", "")
        city = kwargs.get("city", "")
        if not address:
            return {"success": False, "error": "地理编码需要提供 address 参数"}

        params = {"address": address}
        if city:
            params["city"] = city

        data = _amap_get("/geocode/geo", params)
        if data.get("status") != "1":
            return {"success": False, "error": data.get("info", "编码失败")}

        geocodes = data.get("geocodes", [])
        if not geocodes:
            return {"success": False, "error": f"无法解析地址: {address}"}

        geo = geocodes[0]
        location = geo.get("location", "")
        formatted = geo.get("formatted_address", "")
        return {
            "success": True,
            "result": f"📍 {address} → {formatted}\n坐标: {location}",
            "location": location,
            "formatted_address": formatted,
        }

    async def _route(self, kwargs: dict) -> Dict[str, Any]:
        origin_text = kwargs.get("origin", "")
        dest_text = kwargs.get("destination", "")
        mode = kwargs.get("travel_mode", "driving")

        if not origin_text or not dest_text:
            return {"success": False, "error": "路线规划需要提供 origin 和 destination 参数"}

        # 如果不是坐标格式，先地理编码
        origin_loc = origin_text
        if not self._is_coord(origin_text):
            geo = await self._geocode({"address": origin_text})
            if not geo.get("success"):
                return {"success": False, "error": f"无法解析起点: {origin_text}"}
            origin_loc = geo["location"]

        dest_loc = dest_text
        if not self._is_coord(dest_text):
            geo = await self._geocode({"address": dest_text})
            if not geo.get("success"):
                return {"success": False, "error": f"无法解析终点: {dest_text}"}
            dest_loc = geo["location"]

        params = {
            "origin": origin_loc,
            "destination": dest_loc,
            "extensions": "all",
        }

        if mode == "bicycling":
            params["key"] = AMAP_KEY
            params["output"] = "JSON"
            url = f"https://restapi.amap.com/v4/direction/bicycling?{urllib.parse.urlencode(params)}"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "yuan-bot/1.0"})
            resp.raise_for_status()
            data = resp.json()
        else:
            endpoint_map = {
                "driving": "/direction/driving",
                "walking": "/direction/walking",
                "transit": "/direction/transit/integrated",
            }
            endpoint = endpoint_map.get(mode, "/direction/driving")
            if mode == "transit":
                params["city"] = "auto"
            data = _amap_get(endpoint, params)

        if mode != "bicycling" and data.get("status") != "1":
            return {"success": False, "error": data.get("info", "路线规划失败")}

        result_text = _format_route(data, mode)
        return {
            "success": True,
            "result": f"从 {origin_text} → {dest_text}：\n{result_text}",
        }

    @staticmethod
    def _is_coord(text: str) -> bool:
        """检查是否为坐标格式 '经度,纬度'"""
        parts = text.split(",")
        if len(parts) != 2:
            return False
        try:
            float(parts[0])
            float(parts[1])
            return True
        except ValueError:
            return False
