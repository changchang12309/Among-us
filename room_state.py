import json
import time
import threading
from typing import Dict, List, Any, Optional

class RoomState:
    """房间状态管理类 - 用于联机模式下的状态同步"""
    
    def __init__(self, is_host: bool = False):
        self.is_host = is_host
        self.lock = threading.Lock()
        
        # 玩家状态
        self.players: Dict[str, Dict[str, Any]] = {}  # {player_name: {location, is_alive, role, ...}}
        
        # 游戏状态
        self.game_started = False
        self.game_over = False
        self.winner = None
        
        # 任务状态
        self.tasks_completed: Dict[str, int] = {}  # {player_name: task_count}
        self.total_tasks_required = 3
        
        # 事件记录
        self.events: List[Dict[str, Any]] = []  # [{type, player_name, target_name, location, timestamp}, ...]
        
        # 炸弹状态
        self.bomb_location: Optional[str] = None
        self.bomb_explode_time: Optional[float] = None
        
        # 尸体位置
        self.dead_bodies: Dict[str, Dict[str, Any]] = {}  # {player_name: {location, cleared, reported}}
        
        # 紧急会议状态
        self.emergency_meetings_used: Dict[str, int] = {}  # {player_name: count}
        self.emergency_ban_rounds = 0
        
        # 破坏状态
        self.oxygen_sabotaged = False
        self.oxygen_timeout: Optional[float] = None  # 氧气耗尽的时间戳
        self.monitor_sabotaged = False
        self.ruined_rooms: Dict[str, bool] = {}
        self.ruin_cleaned: Dict[str, bool] = {}
        
        # 最后更新时间
        self.last_update = time.time()
    
    def update_player_location(self, player_name: str, location: str):
        """更新玩家位置"""
        with self.lock:
            if player_name in self.players:
                self.players[player_name]['location'] = location
                self.last_update = time.time()
    
    def update_player_status(self, player_name: str, is_alive: bool):
        """更新玩家存活状态"""
        with self.lock:
            if player_name in self.players:
                self.players[player_name]['is_alive'] = is_alive
                self.last_update = time.time()
    
    def add_player(self, player_name: str, role: str = "Crewmate", location: str = "飞船大厅"):
        """添加玩家"""
        with self.lock:
            self.players[player_name] = {
                'location': location,
                'is_alive': True,
                'role': role,
                'tasks_completed': 0
            }
            self.tasks_completed[player_name] = 0
            self.emergency_meetings_used[player_name] = 0
            self.last_update = time.time()
    
    def add_event(self, event_type: str, player_name: str, target_name: str = None, location: str = None):
        """添加游戏事件"""
        with self.lock:
            event = {
                'type': event_type,
                'player_name': player_name,
                'target_name': target_name,
                'location': location,
                'timestamp': time.time()
            }
            self.events.append(event)
            self.last_update = time.time()
    
    def set_bomb(self, location: str, explode_time: float):
        """设置炸弹"""
        with self.lock:
            self.bomb_location = location
            self.bomb_explode_time = explode_time
            self.last_update = time.time()
    
    def clear_bomb(self):
        """清除炸弹"""
        with self.lock:
            self.bomb_location = None
            self.bomb_explode_time = None
            self.last_update = time.time()
    
    def add_dead_body(self, player_name: str, location: str):
        """添加尸体"""
        with self.lock:
            self.dead_bodies[player_name] = {
                'location': location,
                'cleared': False,
                'reported': False
            }
            self.last_update = time.time()
    
    def complete_task(self, player_name: str):
        """完成任务"""
        with self.lock:
            if player_name in self.tasks_completed:
                self.tasks_completed[player_name] += 1
                self.players[player_name]['tasks_completed'] = self.tasks_completed[player_name]
                self.last_update = time.time()
    
    def set_sabotage(self, system: str, value: bool):
        """设置系统破坏状态"""
        with self.lock:
            if system == 'oxygen':
                self.oxygen_sabotaged = value
                if value:
                    self.oxygen_timeout = time.time() + 150  # 150秒后氧气耗尽
                else:
                    self.oxygen_timeout = None
            elif system == 'monitor':
                self.monitor_sabotaged = value
            self.last_update = time.time()
    
    def repair_sabotage(self, system: str):
        """修复破坏的系统"""
        with self.lock:
            if system == 'oxygen':
                self.oxygen_sabotaged = False
                self.oxygen_timeout = None
            elif system == 'monitor':
                self.monitor_sabotaged = False
            self.last_update = time.time()
    
    def set_game_over(self, winner: str):
        """设置游戏结束和获胜者"""
        with self.lock:
            self.game_over = True
            self.winner = winner
            self.last_update = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于网络传输）"""
        with self.lock:
            return {
                'type': 'room_state',
                'players': self.players.copy(),
                'game_started': self.game_started,
                'game_over': self.game_over,
                'winner': self.winner,
                'tasks_completed': self.tasks_completed.copy(),
                'total_tasks_required': self.total_tasks_required,
                'events': self.events[-10:],  # 只发送最近10个事件
                'bomb_location': self.bomb_location,
                'bomb_explode_time': self.bomb_explode_time,
                'dead_bodies': self.dead_bodies.copy(),
                'emergency_meetings_used': self.emergency_meetings_used.copy(),
                'emergency_ban_rounds': self.emergency_ban_rounds,
                'oxygen_sabotaged': self.oxygen_sabotaged,
                'oxygen_timeout': self.oxygen_timeout,
                'monitor_sabotaged': self.monitor_sabotaged,
                'ruined_rooms': self.ruined_rooms.copy(),
                'ruin_cleaned': self.ruin_cleaned.copy(),
                'last_update': self.last_update
            }
    
    def from_dict(self, data: Dict[str, Any]):
        """从字典恢复状态"""
        with self.lock:
            if data.get('type') != 'room_state':
                return
            
            self.players = data.get('players', {})
            self.game_started = data.get('game_started', False)
            self.game_over = data.get('game_over', False)
            self.winner = data.get('winner')
            self.tasks_completed = data.get('tasks_completed', {})
            self.total_tasks_required = data.get('total_tasks_required', 3)
            self.events = data.get('events', [])
            self.bomb_location = data.get('bomb_location')
            self.bomb_explode_time = data.get('bomb_explode_time')
            self.dead_bodies = data.get('dead_bodies', {})
            self.emergency_meetings_used = data.get('emergency_meetings_used', {})
            self.emergency_ban_rounds = data.get('emergency_ban_rounds', 0)
            self.oxygen_sabotaged = data.get('oxygen_sabotaged', False)
            self.oxygen_timeout = data.get('oxygen_timeout')
            self.monitor_sabotaged = data.get('monitor_sabotaged', False)
            self.ruined_rooms = data.get('ruined_rooms', {})
            self.ruin_cleaned = data.get('ruin_cleaned', {})
            self.last_update = time.time()
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict())
    
    def from_json(self, json_str: str):
        """从JSON字符串恢复"""
        try:
            data = json.loads(json_str)
            self.from_dict(data)
        except json.JSONDecodeError:
            pass
