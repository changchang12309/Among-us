#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
游戏地图定义
"""
from typing import Dict, List, Set


class GameMap:
    """游戏地图类"""
    
    def __init__(self):
        self.locations = self._initialize_locations()
        self.connections = self._initialize_connections()
    
    def _initialize_locations(self) -> List[str]:
        """初始化地图位置"""
        return [
            "飞船大厅",
            "电力室",
            "上升引擎室",
            "下降引擎室",
            "反应堆",
            "氧气室",
            "医疗室",
            "通讯室",
            "监控室",
            "燃料室",
            "主控室"
        ]
    
    def _initialize_connections(self) -> Dict[str, List[str]]:
        """初始化位置连接关系"""
        return {
            "飞船大厅": ["上升引擎室", "氧气室", "主控室", "燃料室"],
            "上升引擎室": ["飞船大厅", "反应堆", "医疗室", "下降引擎室"],
            "下降引擎室": ["医疗室", "上升引擎室", "电力室", "反应堆"],
            "电力室": ["燃料室", "下降引擎室"],
            "反应堆": ["医疗室", "下降引擎室", "上升引擎室"],
            "氧气室": ["飞船大厅", "监控室"],
            "医疗室": ["反应堆", "下降引擎室", "上升引擎室"],
            "通讯室": ["燃料室", "监控室"],
            "监控室": ["通讯室", "氧气室" ,"燃料室"],
            "燃料室": ["电力室", "飞船大厅", "通讯室", "主控室", "监控室"],
            "主控室": ["燃料室", "飞船大厅"]
        }
    
    def get_available_moves(self, current_location: str) -> List[str]:
        """获取当前位置可移动的位置列表"""
        if current_location in self.connections:
            return self.connections[current_location]
        return []
    
    def is_connected(self, location1: str, location2: str) -> bool:
        """检查两个位置是否相连"""
        if location1 in self.connections:
            return location2 in self.connections[location1]
        return False
    
    def get_all_locations(self) -> List[str]:
        """获取所有位置"""
        return self.locations