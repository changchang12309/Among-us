#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
玩家类定义
"""
from typing import Optional, List
from roles import Role


class Player:
    """玩家类"""
    
    def __init__(self, name: str, role: Optional[Role] = None):
        self.name = name
        self.role = role
        self.is_alive = True
        self.completed_tasks = 0
        self.current_location = "飞船大厅"
        self.tasks = []  # 添加任务列表
    
    def complete_task(self) -> bool:
        """完成一个任务"""
        if self.is_alive and hasattr(self.role, 'complete_task'):
            # 检查当前位置是否有可完成的任务
            for task in self.tasks:
                if not task.is_completed and task.location == self.current_location:
                    task.complete()
                    if self.role.complete_task():
                        self.completed_tasks += 1
                        return True
        return False
    
    def assign_role(self, role: Role):
        """分配角色"""
        self.role = role
        self.role.assign_to_player(self)
    
    def move(self, location: str):
        """移动到指定位置"""
        if self.is_alive:
            self.current_location = location
    
    def kill(self, target: 'Player') -> bool:
        """击杀目标玩家"""
        if (self.is_alive and target.is_alive and 
            self.current_location == target.current_location and
            hasattr(self.role, 'kill') and self.role.kill()):
            target.is_alive = False
            return True
        return False
    
    def report_dead_body(self) -> bool:
        """报告发现的尸体"""
        if self.is_alive:
            return True
        return False
    
    def vote(self, suspect: Optional['Player']) -> Optional[str]:
        """投票"""
        if self.is_alive:
            if suspect:
                return suspect.name
            else:
                return None
        return None
    
    def get_role_name(self) -> str:
        """获取角色名称"""
        return self.role.__class__.__name__ if self.role else "未知"
    
    def __str__(self) -> str:
        status = "存活" if self.is_alive else "死亡"
        role_name = self.role.__class__.__name__ if self.role else "未知"
        return f"{self.name} ({role_name}, {status}, 完成任务数: {self.completed_tasks})"