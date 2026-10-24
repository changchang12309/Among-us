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
        # 监控冷却（联机模式实时冷却）：约0.45个任务周期，补偿船员应对击杀
        self.monitor_cooldown_seconds = 45
        self.current_monitor_cooldown_seconds = 0
    
    def update_cooldowns_real_time(self):
        """更新所有冷却时间（实时计时，每秒调用一次）- 基类方法"""
        if self.current_monitor_cooldown_seconds > 0:
            self.current_monitor_cooldown_seconds = max(0, self.current_monitor_cooldown_seconds - 1)
    
    def start_cooldowns(self):
        """开始所有冷却（联机模式开局调用）- 基类方法"""
        self.current_monitor_cooldown_seconds = 0
    
    def can_use_monitor(self) -> bool:
        """检查是否可以使用监控"""
        return self.current_monitor_cooldown_seconds == 0
    
    def use_monitor(self):
        """使用监控"""
        self.current_monitor_cooldown_seconds = self.monitor_cooldown_seconds
    
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
        # 单机模式使用回合制冷却
        self.kill_cooldown = 2  # 回合数
        self.current_kill_cooldown = 0
        self.bomb_cooldown = 5  # 回合数
        self.current_bomb_cooldown = 0
        self.bomb_explode_time = None
        
        # 联机模式使用实时计时（秒）
        # 平衡基准：每名船员完成 1星+2星+3星 任务+跑图的全周期 T≈100 秒
        self.kill_cooldown_seconds = 45  # 击杀：约0.45T，每个任务周期约2次击杀窗口
        self.current_kill_cooldown_seconds = 0  # 初始为0，开局后设置为冷却时间
        self.shuttle_cooldown_seconds = 60  # 穿梭：约0.6T
        self.current_shuttle_cooldown_seconds = 0  # 初始为0，开局后设置为冷却时间
        self.bomb_cooldown_seconds = 150  # 炸弹：约1.5T
        self.current_bomb_cooldown_seconds = 0  # 初始为0，开局后设置为冷却时间
        self.bomb_explode_time_seconds = 60  # 炸弹引爆时间1分钟（拆弹任务约10-30秒）
        self.sabotage_cooldown_seconds = 90  # 破坏：约0.9T（修复氧气需分流30-50秒）
        self.current_sabotage_cooldown_seconds = 0  # 初始为0
    
    def set_kill_cooldown(self, cooldown: int):
        """设置击杀冷却时间（回合数，单机模式用）"""
        self.kill_cooldown = cooldown
        self.current_kill_cooldown = 0
    
    def update_cooldowns(self):
        """更新所有冷却时间（回合制）"""
        if self.current_kill_cooldown > 0:
            self.current_kill_cooldown -= 1
        if self.current_bomb_cooldown > 0:
            self.current_bomb_cooldown -= 1
    
    def update_cooldowns_real_time(self):
        """更新所有冷却时间（实时计时，每秒调用一次）"""
        # 调用基类方法更新监控冷却
        super().update_cooldowns_real_time()
        # 更新内鬼专属冷却
        if self.current_kill_cooldown_seconds > 0:
            self.current_kill_cooldown_seconds = max(0, self.current_kill_cooldown_seconds - 1)
        if self.current_shuttle_cooldown_seconds > 0:
            self.current_shuttle_cooldown_seconds = max(0, self.current_shuttle_cooldown_seconds - 1)
        if self.current_bomb_cooldown_seconds > 0:
            self.current_bomb_cooldown_seconds = max(0, self.current_bomb_cooldown_seconds - 1)
        if self.current_sabotage_cooldown_seconds > 0:
            self.current_sabotage_cooldown_seconds = max(0, self.current_sabotage_cooldown_seconds - 1)
    
    def can_sabotage(self) -> bool:
        """检查是否可以破坏系统（联机模式）"""
        return self.current_sabotage_cooldown_seconds == 0
    
    def use_sabotage(self):
        """使用破坏系统技能（联机模式）"""
        self.current_sabotage_cooldown_seconds = self.sabotage_cooldown_seconds
    
    def start_cooldowns(self):
        """开始所有冷却（联机模式开局调用）"""
        # 调用基类方法
        super().start_cooldowns()
        # 设置内鬼专属冷却
        self.current_kill_cooldown_seconds = self.kill_cooldown_seconds
        self.current_shuttle_cooldown_seconds = self.shuttle_cooldown_seconds
        self.current_bomb_cooldown_seconds = self.bomb_cooldown_seconds
        self.current_sabotage_cooldown_seconds = 0  # 开局破坏系统没有冷却
    
    def kill(self, multiplayer=False) -> bool:
        """内鬼击杀技能"""
        if multiplayer:
            # 联机模式：使用实时计时
            if self.current_kill_cooldown_seconds == 0:
                self.current_kill_cooldown_seconds = self.kill_cooldown_seconds
                return True
            print(f"❌ 击杀冷却中，还剩{self.current_kill_cooldown_seconds}秒")
            return False
        else:
            # 单机模式：使用回合制
            if self.current_kill_cooldown == 0:
                self.current_kill_cooldown = self.kill_cooldown
                return True
            print(f"❌ 击杀冷却中，还剩{self.current_kill_cooldown}回合")
            return False
    
    def can_shuttle(self) -> bool:
        """检查是否可以穿梭（联机模式）"""
        return self.current_shuttle_cooldown_seconds == 0
    
    def use_shuttle(self):
        """使用穿梭技能（联机模式）"""
        self.current_shuttle_cooldown_seconds = self.shuttle_cooldown_seconds
    
    def place_bomb(self, multiplayer=False) -> bool:
        """放置炸弹技能"""
        if multiplayer:
            # 联机模式：使用实时计时
            if self.current_bomb_cooldown_seconds == 0:
                self.current_bomb_cooldown_seconds = self.bomb_cooldown_seconds
                self.bomb_explode_time = time.time() + self.bomb_explode_time_seconds  # 1分钟
                return True
            print(f"❌ 炸弹冷却中，还剩{self.current_bomb_cooldown_seconds}秒")
            return False
        else:
            # 单机模式：使用回合制
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