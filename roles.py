#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
角色定义类
"""
import time
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

# 使用TYPE_CHECKING避免循环导入
if TYPE_CHECKING:
    from player import Player


class Role(ABC):
    """角色抽象基类"""
    
    def __init__(self):
        # 使用字符串类型注解避免运行时导入错误
        self.player: Optional['Player'] = None
    
    def assign_to_player(self, player: 'Player'):
        """将角色分配给玩家"""
        self.player = player
    
    @abstractmethod
    def get_role_info(self) -> str:
        """获取角色信息"""
        pass


class Crewmate(Role):
    """船员角色"""
    
    def __init__(self, num_tasks: int = 5):
        super().__init__()
        self.num_tasks = num_tasks
        self.tasks_completed = 0
    
    def complete_task(self) -> bool:
        """船员完成任务"""
        if self.tasks_completed < self.num_tasks:
            self.tasks_completed += 1
            print(f"✅ {self.player.name}完成了一个任务！({self.tasks_completed}/{self.num_tasks})")
            return True
        return False
    
    def get_role_info(self) -> str:
        """获取船员角色信息"""
        return "你是船员！你需要在太空飞船中完成各种任务，同时找出伪装成船员的内鬼。\n\n【胜利条件】\n① 完成所有常规任务（每名船员需完成3个任务）\n② 通过紧急会议投票出局所有内鬼\n\n【温馨提示】\n- 完成3个常规任务即可获胜\n- 破坏的氧气系统需要在2回合内修复，否则内鬼获胜\n- 发现尸体后可以发起紧急会议报告尸体\n- 紧急会议仅在飞船大厅可发起，每人可发起2次"


class Impostor(Role):
    """内鬼角色"""
    
    def __init__(self):
        super().__init__()
        self.kill_cooldown = 2
        self.current_kill_cooldown = 0
        self.bomb_cooldown = 5
        self.current_bomb_cooldown = 0
        self.bomb_explode_time = None
    
    def set_kill_cooldown(self, cooldown: int):
        """设置击杀冷却时间"""
        self.kill_cooldown = 2
        self.current_kill_cooldown = 0
    
    def update_cooldowns(self):
        """更新所有冷却时间"""
        if self.current_kill_cooldown > 0:
            self.current_kill_cooldown -= 1
        if self.current_bomb_cooldown > 0:
            self.current_bomb_cooldown -= 1
    
    def kill(self) -> bool:
        """内鬼击杀技能"""
        if self.current_kill_cooldown == 0:
            self.current_kill_cooldown = self.kill_cooldown
            return True
        print(f"❌ 击杀冷却中，还剩{self.current_kill_cooldown}回合")
        return False
    
    def place_bomb(self) -> bool:
        """放置炸弹技能（3分钟后爆炸）"""
        if self.current_bomb_cooldown == 0:
            self.current_bomb_cooldown = self.bomb_cooldown
            self.bomb_explode_time = time.time() + 180  # 3分钟  
            return True
        print(f"❌ 炸弹冷却中，还剩{self.current_bomb_cooldown}回合")
        return False
    
    def is_bomb_exploded(self) -> bool:
        """检查炸弹是否已爆炸"""
        if self.bomb_explode_time is None:
            return False
        return time.time() >= self.bomb_explode_time
    
    def get_bomb_time_remaining(self) -> int:
        """获取炸弹爆炸剩余时间（秒）"""
        if self.bomb_explode_time is None:
            return 0
        remaining = max(0, int(self.bomb_explode_time - time.time()))
        return remaining
    
    def sabotage(self, system: str) -> bool:
        """破坏系统"""
        print(f"🔧 {system}系统被破坏了！")
        return True
    
    def get_role_info(self) -> str:
        """获取内鬼角色信息"""
        return """你是内鬼！你可以潜入飞船、击杀船员、放置炸弹、破坏系统，在暗中消灭所有船员！

【胜利条件】
① 内鬼数量与船员数量相等
② 氧气系统被破坏后船员未在2回合内修复

【内鬼技能】
- 击杀：悄悄杀害船员（2回合冷却，第一回合禁用）
- 穿梭：传送到任意房间（3回合冷却，第一回合禁用）
- 炸弹：在当前位置放置炸弹，3分钟后爆炸（5回合冷却）
- 破坏：破坏氧气或监控系统（2回合冷却）

【温馨提示】
- 第一回合禁止击杀和穿梭
- 破坏氧气后船员有2回合修复时间，超时则你获胜"""