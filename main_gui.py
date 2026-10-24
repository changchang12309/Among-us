import os
import sys
import random
import time
import socket
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import List, Dict, Optional
import math
import argparse
import base64
import json
from room_state import RoomState

# ========== 控制台编码兜底 ==========
# Windows 中文环境下 stdout 为 GBK，日志/print 里的 emoji 与 ✓ 会抛
# UnicodeEncodeError，足以打断后台线程（同步、Tk 回调）造成"卡住不弹窗"。
# 只放宽错误处理、不改编码：中文正常显示，非常用符号退化为转义序列。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="backslashreplace")
    except Exception:
        pass

# ========== 全局崩溃捕获：任何未处理异常/硬崩溃都落盘，便于定位闪退 ==========
def _setup_crash_logger():
    import traceback
    import atexit
    import faulthandler
    try:
        _log_dir = os.path.dirname(os.path.abspath(__file__))
        _crash_path = os.path.join(_log_dir, f"crash_{os.getpid()}.log")
        _cf = open(_crash_path, "a", encoding="utf-8", buffering=1)

        def _log(msg):
            try:
                _cf.write(msg + "\n")
                _cf.flush()
            except Exception:
                pass

        _log(f"\n===== main_gui 启动 pid={os.getpid()} platform={sys.platform} argv={sys.argv} =====")

        def _excepthook(exc_type, exc_value, exc_tb):
            _log("!!! sys.excepthook 未捕获异常:\n" + "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)))

        def _thread_excepthook(args):
            _log("!!! 线程未捕获异常:\n" + "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

        sys.excepthook = _excepthook
        if hasattr(threading, "excepthook"):
            threading.excepthook = _thread_excepthook
        # 段错误/致命信号时输出 Python 栈
        try:
            faulthandler.enable(file=_cf)
        except Exception:
            pass
        atexit.register(lambda: _log(f"===== atexit: 进程正常退出 pid={os.getpid()} ====="))
        os.environ["MAIN_GUI_CRASH_LOG"] = _crash_path
    except Exception as _e:
        print(f"崩溃日志初始化失败: {_e}")

_setup_crash_logger()

# 添加平台特定支持
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
else:
    # Linux/WSL：忽略 SIGPIPE，避免向已关闭的管道/套接字写入时进程被直接终止
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    except Exception:
        pass

# 解析命令行参数
parser = argparse.ArgumentParser(description='太空狼人杀')
parser.add_argument('--multiplayer', action='store_true', help='联机模式')
parser.add_argument('--server', action='store_true', help='服务器模式')
parser.add_argument('--player_count', type=int, default=0, help='玩家数量')
parser.add_argument('--roles', type=str, default='', help='角色分配(base64编码)')
parser.add_argument('--names', type=str, default='', help='玩家名称列表(逗号分隔，旧参数)')
parser.add_argument('--names_b64', type=str, default='', help='玩家名称列表(base64编码JSON，可安全含逗号/空格)')
parser.add_argument('--my_role', type=str, default='', help='当前玩家的身份')
parser.add_argument('--my_name', type=str, default='', help='当前玩家的名称')
parser.add_argument('--sync_port', type=int, default=12346, help='位置同步端口')
parser.add_argument('--server_ip', type=str, default='127.0.0.1', help='服务器IP地址')
args = parser.parse_args()


def _decode_names_arg():
    """解析玩家名单：优先 base64 JSON（可安全包含逗号/空格），回退到逗号分隔。"""
    if args.names_b64:
        try:
            return json.loads(base64.b64decode(args.names_b64.encode()).decode("utf-8"))
        except Exception as e:
            print(f"❌ 玩家名单(base64)解析错误: {e}")
            return []
    if args.names:
        return args.names.split(",")
    return []


# 根据命令行参数设置联机模式变量
is_multiplayer = args.multiplayer
is_server = args.server
player_count_from_args = args.player_count
role_assignments_from_args = {}
player_names_from_args = []
my_role_from_args = args.my_role
my_name_from_args = args.my_name
sync_port_from_args = args.sync_port
server_ip_from_args = args.server_ip

# 读取环境变量中的角色设置（由入口文件设置）
env_player_role = os.environ.get('PLAYER_ROLE', '')
print(f"🔍 环境变量 PLAYER_ROLE: '{env_player_role}'")
print(f"📍 同步端口: {sync_port_from_args}, 服务器IP: {server_ip_from_args}")

# 客户端联机模式：直接使用命令行参数，不读取配置文件
# （避免多客户端同时运行时配置文件冲突）
if args.multiplayer:
    print("🎮 联机模式：使用命令行参数启动游戏")
    if args.roles and (args.names or args.names_b64):
        try:
            role_assignments_json = base64.b64decode(args.roles.encode()).decode()
            role_assignments_from_args = json.loads(role_assignments_json)
            player_names_from_args = _decode_names_arg()
            print(f"✅ 已从命令行参数加载角色分配")
        except Exception as e:
            print(f"❌ 角色分配解析错误: {e}")
            role_assignments_from_args = {}
            player_names_from_args = []
    
    # 读取玩家角色和名字
    if args.my_role:
        my_role_from_args = args.my_role
        print(f"✅ 已设置玩家角色: {my_role_from_args}")
    if args.my_name:
        my_name_from_args = args.my_name
        print(f"✅ 已设置玩家名字: {my_name_from_args}")
    
    # 打印所有联机参数
    print(f"📊 联机参数汇总:")
    print(f"   - 玩家数量: {player_count_from_args}")
    print(f"   - 我的角色: {my_role_from_args}")
    print(f"   - 我的名字: {my_name_from_args}")
    print(f"   - 同步端口: {sync_port_from_args}")
    print(f"   - 服务器IP: {server_ip_from_args}")
else:
    # 单机模式：尝试读取配置文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_filename = "player_roles_config.json"
    config_path = os.path.join(script_dir, config_filename)
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_from_file = json.load(f)
            print(f"✅ 成功读取配置文件: {config_path}")
            print(f"📋 配置文件内容: {config_from_file}")
            
            # 从配置文件覆盖参数
            if config_from_file:
                player_count_from_args = config_from_file.get('player_count', player_count_from_args)
                role_assignments_from_args = config_from_file.get('assignments', {})
                player_names_from_args = list(role_assignments_from_args.keys()) if role_assignments_from_args else []
                my_role_from_args = config_from_file.get('my_role', my_role_from_args)
                my_name_from_args = config_from_file.get('my_name', my_name_from_args)
                
                print(f"🔄 从配置文件覆盖参数:")
                print(f"   - 玩家数量: {player_count_from_args}")
                print(f"   - 我的角色: {my_role_from_args}")
                print(f"   - 我的名字: {my_name_from_args}")
        except Exception as e:
            print(f"❌ 配置文件读取错误: {e}")
            config_from_file = None
    else:
        print(f"⚠️ 配置文件不存在: {config_path}")
    
    if args.roles and (args.names or args.names_b64) and not config_from_file:
        try:
            role_assignments_json = base64.b64decode(args.roles.encode()).decode()
            role_assignments_from_args = json.loads(role_assignments_json)
            player_names_from_args = _decode_names_arg()
        except Exception as e:
            print(f"角色分配解析错误: {e}")
            role_assignments_from_args = {}
            player_names_from_args = []
# 字体检测函数
def get_available_font():
    """获取系统可用的字体"""
    try:
        # 确保Tkinter根窗口已创建
        if not tk._default_root:
            # 创建临时根窗口来获取字体
            temp_root = tk.Tk()
            temp_root.withdraw()  # 隐藏窗口
        
        # 直接返回Arial，避免字体检测问题
        return 'Arial'
    except Exception as e:
        # 如果出现任何错误，直接返回Arial
        return 'Arial'

# 导入游戏组件
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from game import Game
from player import Player
from roles import Role, Crewmate, Impostor
from tasks import Task
from map import GameMap
from tasks import (
    WireFixTask, FilterCleanTask, BodyScanTask, DownloadDataTask,
    CalibrateDownEngineTask, CalibrateUpEngineTask, RepairReactorTask,
    RefuelTask, StartSatelliteTask, MorseCodeTask, OxygenRepairTask
)

def assign_tasks_to_crewmates(crewmates):
    """分配任务给所有船员，确保难度均衡且不重复
    
    规则：
    1. 每个船员分配3个任务（1个一星 + 1个两星 + 1个三星）
    2. 所有船员的任务不能重复
    3. 如果船员数量大于可用任务数量，则增加任务类型
    
    Args:
        crewmates: 船员玩家列表
        
    Returns:
        dict: {player_name: [task1, task2, task3]}
    """
    if not crewmates:
        return {}
    
    # 定义各难度任务池
    one_star_tasks = [
        WireFixTask(), FilterCleanTask(), BodyScanTask(), RefuelTask()
    ]
    two_star_tasks = [
        CalibrateDownEngineTask(), CalibrateUpEngineTask(), DownloadDataTask()
    ]
    three_star_tasks = [
        RepairReactorTask(), StartSatelliteTask(), MorseCodeTask()
    ]
    
    num_crewmates = len(crewmates)
    assignments = {}
    
    # 扩展任务池（如果船员数量超过原始任务池大小）
    while len(one_star_tasks) < num_crewmates:
        one_star_tasks.extend([WireFixTask(), FilterCleanTask(), BodyScanTask()])
    while len(two_star_tasks) < num_crewmates:
        two_star_tasks.extend([CalibrateDownEngineTask(), CalibrateUpEngineTask(), DownloadDataTask()])
    while len(three_star_tasks) < num_crewmates:
        three_star_tasks.extend([RepairReactorTask(), StartSatelliteTask(), MorseCodeTask()])
    
    # 随机打乱任务池
    random.shuffle(one_star_tasks)
    random.shuffle(two_star_tasks)
    random.shuffle(three_star_tasks)
    
    # 为每个船员分配任务
    for i, player in enumerate(crewmates):
        # 从各自的池中取一个任务
        task1 = one_star_tasks.pop(0)  # 一星任务
        task2 = two_star_tasks.pop(0)  # 两星任务
        task3 = three_star_tasks.pop(0)  # 三星任务
        
        assignments[player.name] = [task1, task2, task3]
        player.tasks = [task1, task2, task3]
    
    return assignments

# ========== 太空狼人杀图形界面类 ==========
class AmongUsGUI:
    """太空狼人杀图形界面类"""
    
    def __init__(self, root, game):
        self.root = root
        self.root.title("太空狼人杀 - Among Us 简化版")
        self.root.geometry("1920x1080+0+0")
        self.root.configure(bg="#1a1a2e")
        self.game = game
        self.current_player = None
        self.action_steps = 0
        self.max_steps = 4
        # 统一使用Arial字体，避免跨平台字体问题
        self.font_family = 'Arial'
        # 增大字体大小倍数
        self.font_size_multiplier = 1.25
        self.current_player_index = 0
        
        # 全局回合变量
        self.global_round = 1
        self.players_acted_this_round = 0
        self.alive_players_count = 0
        
        # 氧气系统破坏核心变量（2回合超时直接结算）
        self.oxygen_sabotaged = False
        self.oxygen_sabotage_round = 0
        self.oxygen_repaired = False
        self.oxygen_timeout_rounds = 2
        self.oxygen_remaining_rounds = 0
        self.oxygen_timeout = None  # 氧气耗尽的时间戳（联机模式实时倒计时）
        
        # 监控系统破坏核心变量（永久性破坏，需完成任务恢复）
        self.monitor_sabotaged = False
        self.monitor_sabotage_round = 0
        self.monitor_repaired = False
        
        # 监控使用冷却（2回合冷却）
        self.monitor_cooldown = {}  # {player_name: remaining_rounds}
        
        # 内鬼穿梭功能核心变量
        self.impostor_teleport_cooldown = {}
        self.all_rooms = [
            "飞船大厅", "电力室", "上升引擎室", "下降引擎室", "反应堆",
            "氧气室", "医疗室", "通讯室", "监控室", "燃料室", "主控室"
        ]
        
        # 紧急会议核心变量
        self.emergency_meeting_count = {}  # 记录每个玩家剩余紧急会议次数 {player_name: remaining_count}
        self.max_emergency_meetings = 2    # 每人最大紧急会议次数
        self.meeting_room = "飞船大厅"     # 仅飞船大厅可发起紧急会议
        self.emergency_ban_rounds = 0      # 炸弹在飞船大厅爆炸后禁用紧急会议的剩余回合数
        
        # 废墟清理核心变量
        self.ruined_rooms = {}  # 记录房间是否为废墟状态 {room_name: True/False}
        self.ruin_cleaned = {}  # 记录废墟是否已清理 {room_name: True/False}
        
        # 破坏系统冷却
        self.sabotage_cooldown = 0  # 破坏系统冷却剩余回合数
        self.sabotage_cooldown_rounds = 2  # 破坏系统冷却回合数（2回合）
        
        # ========== 旁观模式核心变量 ==========
        self.spectator_players = []  # 处于旁观模式的玩家列表
        self.all_players_list = []   # 保存所有玩家的完整列表（包含死亡/存活）
        self.spectator_view_room = ""  # 旁观视角所在房间（与玩家物理位置分离）
        self.dead_player_locations = {}  # 记录死亡玩家的尸体位置（清理后标记为已移除）
        
        self.reported_bodies = {}  # 已报告的尸体字典 {player_name: "reported" | "voted_out"}

        # 炸弹状态标志（防止重复触发爆炸）
        self.bomb_exploding = False
        self.bomb_location = None  # 炸弹所在房间
        
        # ========== 位置同步核心变量 ==========
        self.sync_socket = None  # 同步连接socket
        self.sync_buffer = ""    # 接收缓冲区
        self.sync_running = True  # 同步线程运行标志
        self.room_state = None   # 房间状态（联机模式）
        self.sync_clients = []   # 房主端同步服务器已接受的客户端连接
        self.sync_server_started = False  # 同步服务器是否已启动（防止重复绑定端口）
        
        # ========== 界面引用保存（用于避免闪烁） ==========
        self.game_frame = None   # 主游戏框架引用
        self.room_mates_label = None  # 房间内玩家显示Label
        self.player_labels = {}  # 玩家状态Label字典
        
        # 创建主界面
        self.create_main_frame()
        
        # 联机模式冷却计时Label引用（用于刷新而不闪烁）
        self.kill_cooldown_label = None
        self.shuttle_cooldown_label = None
        self.bomb_cooldown_label = None
        self.monitor_cooldown_label = None
        self.sabotage_cooldown_label = None
        self.bomb_timer_label = None
        # 跟踪上一次的冷却状态（用于检测冷却结束）
        self.last_kill_cooldown = None
        self.last_shuttle_cooldown = None
        self.last_bomb_cooldown = None
        self.last_monitor_cooldown = None
        self.last_sabotage_cooldown = None

    def add_action_step(self):
        """增加行动步数，校验是否达到上限（联机模式下不限制）"""
        # 联机模式下，不限制行动步数
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
            self.action_steps += 1
            return True
        
        # 单机模式下，原有的限制
        if self.action_steps >= self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法继续执行该操作")
            return False
        self.action_steps += 1
        return True

    def clear_all_bodies(self):
        """
        清除所有尸体（核心新函数）
        - 保留旁观模式玩家列表
        - 标记尸体位置为已清理
        - 游戏日志记录清理操作
        """
        if not self.dead_player_locations:
            # 初始化死亡玩家位置记录
            for player in self.spectator_players:
                self.dead_player_locations[player.name] = {
                    "location": player.current_location,
                    "cleared": False
                }
        
        # 清除所有尸体记录（投票出去的玩家记录保留）
        # 只清除标记为"reported"的尸体，保留"voted_out"的记录
        bodies_to_remove = []
        for player_name, status in self.reported_bodies.items():
            if status == "reported":
                bodies_to_remove.append(player_name)
        
        for player_name in bodies_to_remove:
            del self.reported_bodies[player_name]
        
        # 清理所有尸体
        cleared_count = 0
        for player_name in self.dead_player_locations:
            if not self.dead_player_locations[player_name]["cleared"]:
                self.dead_player_locations[player_name]["cleared"] = True
                cleared_count += 1

       
        # 提示玩家
        messagebox.showinfo("尸体清理", f"🧹 投票结束，所有尸体已被清理！\n旁观玩家仍保持旁观模式，仅尸体消失")


    def switch_to_next_player(self):
        """切换至下一个玩家（包含死亡玩家），死亡玩家自动进入旁观模式"""
        # 使用完整玩家列表（包含死亡/存活）进行轮换，永不跳过任何玩家
        if not self.all_players_list:
            self.all_players_list = self.game.players.copy()
        
        # 获取当前玩家索引
        if self.current_player in self.all_players_list:
            current_idx = self.all_players_list.index(self.current_player)
        else:
            current_idx = 0
        
        # 切换到下一个玩家（循环轮换）
        next_idx = (current_idx + 1) % len(self.all_players_list)
        self.current_player = self.all_players_list[next_idx]
        self.current_player_index = self.game.players.index(self.current_player)
        
        # 重置行动步数（无论是否存活）
        self.action_steps = 0
        
        # 死亡玩家自动加入旁观模式
        if not self.current_player.is_alive and self.current_player not in self.spectator_players:
            self.spectator_players.append(self.current_player)
            # 记录尸体位置
            self.dead_player_locations[self.current_player.name] = {
                "location": self.current_player.current_location,
                "cleared": False
            }
            # 初始化旁观视角为玩家死亡位置
            self.spectator_view_room = self.current_player.current_location
            self.add_log(f"👻 {self.current_player.name}已死亡，进入旁观模式！尸体位置：{self.current_player.current_location}")
        
        # 旁观玩家初始化视角位置
        if self.current_player in self.spectator_players and not self.spectator_view_room:
            self.spectator_view_room = self.current_player.current_location
        
        # 全局回合计数逻辑（仅存活玩家参与回合计数）
        alive_players = [p for p in self.game.players if p.is_alive]
        self.alive_players_count = len(alive_players)
        
        # 仅存活玩家行动后才计数回合
        if self.current_player.is_alive:
            self.players_acted_this_round += 1
            
            if self.players_acted_this_round >= self.alive_players_count:
                # 回合结束，更新氧气剩余回合数
                if self.oxygen_sabotaged and not self.oxygen_repaired:
                    self.oxygen_remaining_rounds -= 1
                    self.add_log(f"⚠️ 氧气系统破坏剩余修复回合：{self.oxygen_remaining_rounds}")
                    
                    # 核心逻辑：剩余回合为0则直接结束游戏跳结算
                    if self.oxygen_remaining_rounds <= 0:
                        self.game.winner = "impostor"
                        self.game.game_over = True
                        self.broadcast_game_over("impostor", "oxygen_exhausted")
                        self.show_game_over()
                        return
                
                # 更新内鬼穿梭冷却时间
                for player_name in list(self.impostor_teleport_cooldown.keys()):
                    if self.impostor_teleport_cooldown[player_name] > 0:
                        self.impostor_teleport_cooldown[player_name] -= 1
                        if self.impostor_teleport_cooldown[player_name] == 0:
                            del self.impostor_teleport_cooldown[player_name]
                
                # 更新监控使用冷却时间
                for player_name in list(self.monitor_cooldown.keys()):
                    if self.monitor_cooldown[player_name] > 0:
                        self.monitor_cooldown[player_name] -= 1
                        if self.monitor_cooldown[player_name] == 0:
                            del self.monitor_cooldown[player_name]
                
                # 更新紧急会议禁用状态（炸弹在飞船大厅爆炸后）
                if self.emergency_ban_rounds > 0:
                    self.emergency_ban_rounds -= 1
                    if self.emergency_ban_rounds == 0:
                        self.add_log(f"✅ 紧急会议功能已恢复！")
                
                # 更新破坏系统冷却时间
                if self.sabotage_cooldown > 0:
                    self.sabotage_cooldown -= 1
                    if self.sabotage_cooldown == 0:
                        self.add_log(f"✅ 破坏系统冷却已结束！")
                            
                # 更新内鬼冷却时间（击杀和炸弹）
                for player in self.game.players:
                    if hasattr(player.role, 'update_cooldowns'):
                        player.role.update_cooldowns()
                            
                
                # 更新全局回合数
                self.global_round += 1
                self.players_acted_this_round = 0
                
                # 仅游戏未结束时显示回合提示
                if not self.game.game_over:
                    messagebox.showinfo("回合结束", f"第{self.global_round-1}回合结束！\n进入第{self.global_round}回合")
        
        # 显示玩家切换提示（区分存活/旁观）
        if not self.game.game_over:
            if self.current_player in self.spectator_players:
                # 检查尸体是否已清理
                body_status = "（尸体已清理）" if self.dead_player_locations.get(self.current_player.name, {}).get("cleared", False) else f"（尸体位置：{self.current_player.current_location}）"
                messagebox.showinfo("玩家切换", f"当前旁观视角：{self.current_player.name}\n{body_status}\n当前查看房间：{self.spectator_view_room}")
            else:
                messagebox.showinfo("玩家切换", f"当前操作玩家：{self.current_player.name}\n全局回合：{self.global_round}")
        
        # 刷新UI
        self.create_game_frame()

    def add_log(self, message):
        """添加日志信息"""
        if hasattr(self, 'log_text'):
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")

    def create_main_frame(self):
        """创建主界面"""
        # 清除所有现有组件
        for widget in self.root.winfo_children():
            widget.destroy()

        if is_multiplayer and player_count_from_args > 0 and role_assignments_from_args and player_names_from_args:
            self.root.after(100, self.start_multiplayer_game_setup)
            return

        # 重置全局变量
        self.global_round = 1
        self.players_acted_this_round = 0
        self.alive_players_count = 0
        
        # 重置氧气系统状态
        self.oxygen_sabotaged = False
        self.oxygen_sabotage_round = 0
        self.oxygen_repaired = False
        self.oxygen_remaining_rounds = 0
        
        # 重置监控系统状态
        self.monitor_sabotaged = False
        self.monitor_sabotage_round = 0
        self.monitor_repaired = False
        
        # 重置监控使用冷却
        self.monitor_cooldown = {}
        
        # 重置内鬼穿梭冷却
        self.impostor_teleport_cooldown = {}
        
        # 重置紧急会议次数
        self.emergency_meeting_count = {}
        self.emergency_ban_rounds = 0  # 重置紧急会议禁用状态
        
        # 重置废墟状态
        self.ruined_rooms = {}
        self.ruin_cleaned = {}
        
        # 重置旁观模式变量
        self.spectator_players = []
        self.all_players_list = []
        self.spectator_view_room = ""
        self.dead_player_locations = {}  # 重置尸体位置记录
        self.reported_bodies = {}  # 重置已报告的尸体列表
        
        # 创建标题
        title_label = tk.Label(
            self.root, 
            text="太空狼人杀", 
            font=(self.font_family, int(48 * self.font_size_multiplier), "bold"),
            fg="#e94560",
            bg="#1a1a2e"
        )
        title_label.pack(pady=40)
        
        # 创建副标题
        subtitle_label = tk.Label(
            self.root, 
            text="Among Us 简化版", 
            font=(self.font_family, int(18 * self.font_size_multiplier)),
            fg="#ffffff",
            bg="#1a1a2e"
        )
        subtitle_label.pack(pady=8)
        
        # 创建玩家数量选择框架
        player_frame = tk.Frame(self.root, bg="#16213e", padx=40, pady=30)
        player_frame.pack(pady=25)
        
        player_label = tk.Label(
            player_frame, 
            text="请选择玩家数量 (4-10):", 
            font=(self.font_family, int(14 * self.font_size_multiplier)),
            fg="#ffffff",
            bg="#16213e"
        )
        player_label.pack(pady=8)
        
        # 创建玩家数量滑块
        self.num_players_var = tk.IntVar(value=10)
        player_scale = tk.Scale(
            player_frame, 
            from_=4, 
            to=10, 
            orient="horizontal",
            variable=self.num_players_var,
            length=int(300 * self.font_size_multiplier),
            bg="#16213e",
            fg="#ffffff",
            troughcolor="#0f3460",
            highlightbackground="#16213e"
        )
        player_scale.pack(pady=10)
        
        # 显示当前选择的玩家数量
        self.num_players_display = tk.Label(
            player_frame, 
            text=f"当前选择: {self.num_players_var.get()} 人", 
            font=(self.font_family, int(12 * self.font_size_multiplier)),
            fg="#00ff00",
            bg="#16213e"
        )
        self.num_players_display.pack(pady=5)
        player_scale.bind("<Motion>", lambda event: self.update_player_count())
        
        # 创建开始按钮
        # 为所有平台创建兼容的按钮
        if sys.platform == 'darwin':
            # Mac上使用ttk按钮
            start_button = ttk.Button(
                player_frame, 
                text="开始游戏", 
                style="Start.TButton",
                command=self.start_game_setup
            )
            style = ttk.Style()
            style.theme_use('alt')
            style.configure("Start.TButton", 
                          font=(self.font_family, int(16 * self.font_size_multiplier), "bold"),
                          padding=(int(30 * self.font_size_multiplier), int(10 * self.font_size_multiplier)),
                          background="#4CAF50",
                          foreground="#FFFFFF")
            style.map("Start.TButton",
                      background=[("active", "#388E3C"),("!active", "#4CAF50")],
                      foreground=[("active", "#E8F5E9"),("!active", "#FFFFFF")])

        else:
            # Windows上使用普通按钮
            start_button = tk.Button(
                player_frame, 
                text="开始游戏", 
                font=(self.font_family, int(16 * self.font_size_multiplier), "bold"),
                bg="#4caf50",
                fg="#ffffff",
                padx=int(30 * self.font_size_multiplier),
                pady=int(10 * self.font_size_multiplier),
                bd=2,
                relief="flat",
                command=self.start_game_setup
            )
        start_button.pack(pady=25)
    
    def update_player_count(self):
        """更新玩家数量显示"""
        self.num_players_display.config(text=f"当前选择: {self.num_players_var.get()} 人")

    def show_final_role_confirmation(self):
        """显示最终角色确认页"""
        # 先清空窗口
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # 找到当前玩家
        current_player = None
        for player in self.game.players:
            if player.name == my_name_from_args:
                current_player = player
                break
        
        if not current_player:
            # 如果找不到，使用第一个玩家
            current_player = self.game.players[0]
        
        role_color = "#e94560" if isinstance(current_player.role, Impostor) else "#4caf50"
        role_name = "内鬼" if isinstance(current_player.role, Impostor) else "船员"
        
        # 创建确认页
        confirm_frame = tk.Frame(self.root, bg="#1a1a2e")
        confirm_frame.pack(fill="both", expand=True)
        
        tk.Label(
            confirm_frame,
            text="🎮 最后确认你的角色",
            font=(self.font_family, 28, "bold"),
            fg="#00d4ff",
            bg="#1a1a2e"
        ).pack(pady=40)
        
        role_info_frame = tk.Frame(confirm_frame, bg="#16213e", padx=50, pady=40)
        role_info_frame.pack(pady=20)
        
        tk.Label(
            role_info_frame,
            text=f"玩家名称: {current_player.name}",
            font=(self.font_family, 20, "bold"),
            fg="#ffffff",
            bg="#16213e"
        ).pack(pady=10)
        
        tk.Label(
            role_info_frame,
            text=f"你的角色: {role_name}",
            font=(self.font_family, 32, "bold"),
            fg=role_color,
            bg="#16213e"
        ).pack(pady=15)
        
        tk.Label(
            role_info_frame,
            text="⚠️ 请确认这是你的角色，进入游戏后无法更改！",
            font=(self.font_family, 14),
            fg="#ffff00",
            bg="#16213e"
        ).pack(pady=10)
        
        tk.Button(
            confirm_frame,
            text="✅ 确认，开始游戏！",
            font=(self.font_family, 20, "bold"),
            bg="#4caf50",
            fg="#ffffff",
            padx=60,
            pady=20,
            relief="flat",
            cursor="hand2",
            command=lambda: self.proceed_to_show_role_info()
        ).pack(pady=40)
    
    def proceed_to_show_role_info(self):
        """从确认页进入角色信息显示"""
        # 显示角色信息
        self.show_role_info()
    
    def cleanup_role_assignment_files(self):
        """角色分配数据确认加载入内存后，清理本次会话的角色分配备份文件。

        安全约束：
        1. 调用方必须先校验所有玩家角色已在运行内存中就绪；
        2. 仅删除固定白名单内的 player_roles_config*.json，不触碰任何其他文件；
        3. 任何删除失败只记录日志，绝不中断游戏主流程。
        """
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))

            # 本次会话待清理文件名（精确白名单，避免误删其他环节的文件）
            target_files = ["player_roles_config.json"]
            if getattr(self, 'is_multiplayer', False):
                # 联机模式：追加本会话每名玩家对应的具名备份文件
                # （各端机器上实际只会存在自己那一个；此处按会话名单做幂等清理）
                for player in self.game.players:
                    safe_name = str(player.name).replace(" ", "_").replace("(", "").replace(")", "")
                    target_files.append(f"player_roles_config_{safe_name}.json")

            for filename in target_files:
                file_path = os.path.join(script_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        print(f"🧹 已清理角色分配备份文件: {filename}", flush=True)
                except Exception as e:
                    # 角色数据已在内存中，删除失败不影响游戏继续运行
                    print(f"⚠️ 清理角色分配文件失败（不影响游戏）: {filename} -> {e}", flush=True)
        except Exception as e:
            print(f"⚠️ 角色分配文件清理流程异常（不影响游戏）: {e}", flush=True)

    def start_multiplayer_game_setup(self):
        """联机模式开始游戏设置（使用配置文件的角色分配）"""
        num_players = player_count_from_args
        player_names = player_names_from_args.copy()

        if not player_names or len(player_names) != num_players:
            messagebox.showerror("错误", "玩家数量不匹配！")
            return

        # 初始化房间状态
        self.room_state = RoomState(is_host=is_server)
        
        # 初始化游戏（内鬼数量不影响，我们会手动设置角色）
        num_impostors = sum(1 for role in role_assignments_from_args.values() if role == "Impostor")
        self.game = Game(player_names, num_impostors)
        
        # 手动创建玩家，避免 Game.initialize_players() 的默认行为
        self.game.players = []
        for name in player_names:
            player = Player(name)
            # 设置初始属性
            player.completed_tasks = 0
            player.current_location = "飞船大厅"
            player.is_alive = True
            player.tasks = []
            
            # 完全从配置文件设置角色
            if name in role_assignments_from_args:
                role_name = role_assignments_from_args[name]
                print(f"🔄 设置 {name} 的角色为: {role_name}")
                if role_name == "Impostor":
                    player.role = Impostor()
                else:
                    player.role = Crewmate()
            else:
                player.role = Crewmate()  # 默认船员
            
            self.game.players.append(player)
            
            # 添加玩家到房间状态
            role_name = "Impostor" if isinstance(player.role, Impostor) else "Crewmate"
            self.room_state.add_player(player.name, role_name)

        # 初始化所有玩家的紧急会议次数（每人2次）
        self.emergency_meeting_count = {p.name: self.max_emergency_meetings for p in self.game.players}

        # 保存完整玩家列表
        self.all_players_list = self.game.players.copy()

        # 核心修改1：船员任务分配，确保难度均衡且不重复
        crewmates = [p for p in self.game.players if isinstance(p.role, Crewmate)]
        for player in crewmates:
            player.role.num_tasks = 3
            player.completed_tasks = 0
            player.tasks = []
        
        # 使用新的任务分配函数（1个一星 + 1个两星 + 1个三星，不重复）
        if crewmates:
            assign_tasks_to_crewmates(crewmates)
            # 打印任务分配情况便于调试
            for player in crewmates:
                task_difficulties = [f"{t.name}({t.difficulty}星)" for t in player.tasks]
                print(f"DEBUG: {player.name} 的任务: {', '.join(task_difficulties)}")
        
        # 初始化回合变量
        self.global_round = 1
        self.players_acted_this_round = 0
        self.alive_players_count = len([p for p in self.game.players if p.is_alive])

        # 初始化内鬼穿梭冷却
        self.impostor_teleport_cooldown = {}

        # 设置联机模式标志
        self.is_multiplayer = True
        
        # current_player_index 会在 show_role_info 中根据 my_name_from_args 准确找到
        self.current_player_index = 0

        # 角色分配环节正式完成：校验所有角色数据已正确加载到运行内存，
        # 校验通过后立即清理本次会话的角色分配备份文件；不通过则保留文件并跳过清理
        roles_in_memory = (
            len(self.game.players) == num_players
            and all(
                isinstance(p.role, (Crewmate, Impostor))
                and role_assignments_from_args.get(p.name) == (
                    "Impostor" if isinstance(p.role, Impostor) else "Crewmate"
                )
                for p in self.game.players
            )
        )
        if roles_in_memory:
            self.cleanup_role_assignment_files()
        else:
            print("⚠️ 联机角色数据未完整加载到内存，跳过角色分配文件清理", flush=True)

        # 显示最终确认页
        self.show_final_role_confirmation()
    
    def start_game_setup(self):
        """开始游戏设置（船员任务数固定为3，临时任务单独处理）"""
        num_players = self.num_players_var.get()
        player_names = []
        
        # 获取玩家名称
        for i in range(1, num_players + 1):
            name = f"玩家{i}"
            player_names.append(name)
        
        # 根据玩家数量确定内鬼数量
        if num_players <= 6:
            num_impostors = 1
        else:
            num_impostors = 2
        
        # 初始化游戏
        self.game = Game(player_names, num_impostors)
        self.game.initialize_players()
        self.game.assign_roles()

        # 角色分配环节正式完成：校验所有角色已写入运行内存，
        # 通过后清理角色分配备份文件（单机仅清理公共备份文件），失败只记日志
        if (len(self.game.players) == num_players
                and all(isinstance(p.role, (Crewmate, Impostor)) for p in self.game.players)):
            self.cleanup_role_assignment_files()
        else:
            print("⚠️ 单机角色数据未完整加载到内存，跳过角色分配文件清理", flush=True)

        # 初始化所有玩家的紧急会议次数（每人2次）
        self.emergency_meeting_count = {p.name: self.max_emergency_meetings for p in self.game.players}
        
        # 保存完整玩家列表
        self.all_players_list = self.game.players.copy()
        
        # 核心修改1：船员任务分配，确保难度均衡且不重复
        crewmates = [p for p in self.game.players if isinstance(p.role, Crewmate)]
        for player in crewmates:
            player.role.num_tasks = 3
            player.completed_tasks = 0
            player.tasks = []
        
        # 使用新的任务分配函数（1个一星 + 1个两星 + 1个三星，不重复）
        if crewmates:
            assign_tasks_to_crewmates(crewmates)
            # 打印任务分配情况便于调试
            for player in crewmates:
                task_difficulties = [f"{t.name}({t.difficulty}星)" for t in player.tasks]
                print(f"DEBUG: {player.name} 的任务: {', '.join(task_difficulties)}")
        
        # 初始化回合变量
        self.global_round = 1
        self.players_acted_this_round = 0
        self.alive_players_count = len([p for p in self.game.players if p.is_alive])
        
        # 初始化内鬼穿梭冷却
        self.impostor_teleport_cooldown = {}
        
        # 初始化所有玩家的冷却（联机模式）
        for player in self.game.players:
            player.role.start_cooldowns()
        
        # 显示角色信息（仅自己可见）
        self.show_role_info()
    
    def show_role_info(self):
        """显示角色信息（联机模式下只显示当前玩家的角色）"""
        # 检查是否是联机模式
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
            # 联机模式：根据 my_name_from_args 找到当前玩家的索引
            self.current_player_index = 0
            for i, player in enumerate(self.game.players):
                if player.name == my_name_from_args:
                    self.current_player_index = i
                    break
            
            # 只显示当前玩家的角色
            player = self.game.players[self.current_player_index]
            
            # 清除界面
            for widget in self.root.winfo_children():
                widget.destroy()
            
            # 创建角色信息界面
            role_frame = tk.Frame(self.root, bg="#16213e", padx=40, pady=30)
            role_frame.pack(fill="both", expand=True, pady=30, padx=50)
            
            # 玩家信息
            player_label = tk.Label(
                role_frame, 
                text=f"玩家: {player.name}", 
                font=(self.font_family, int(24 * self.font_size_multiplier), "bold"),
                fg="#ffffff",
                bg="#16213e"
            )
            player_label.pack(pady=12)
            
            # 角色信息
            role_name = player.role.__class__.__name__
            role_color = "#e94560" if role_name == "Impostor" else "#00ff00"
            
            role_label = tk.Label(
                role_frame, 
                text=f"角色: {role_name}", 
                font=(self.font_family, int(32 * self.font_size_multiplier), "bold"),
                fg=role_color,
                bg="#16213e"
            )
            role_label.pack(pady=15)
            
            # 角色说明
            info_text = player.role.get_role_info()
            info_label = tk.Label(
                role_frame, 
                text=info_text, 
                font=(self.font_family, 10),
                fg="#ffffff",
                bg="#16213e",
                wraplength=800,
                justify="center"
            )
            info_label.pack(pady=10)
            
            # 紧急会议规则提示
            meeting_rule_label = tk.Label(
                role_frame,
                text=f"📢 紧急会议规则：每人可发起{self.max_emergency_meetings}次紧急会议，仅在【飞船大厅】可发起！",
                font=(self.font_family, int(11 * self.font_size_multiplier)),
                fg="#00ffff",
                bg="#16213e"
            )
            meeting_rule_label.pack(pady=3)
            
            # 任务信息（仅船员可见）
            if isinstance(player.role, Crewmate):
                task_label = tk.Label(
                    role_frame, 
                    text=f"你需要完成 3 个常规任务", 
                    font=(self.font_family, int(14 * self.font_size_multiplier)),
                    fg="#4caf50",
                    bg="#16213e"
                )
                task_label.pack(pady=5)
                oxygen_rule_label = tk.Label(
                    role_frame,
                    text="⚠️ 内鬼破坏氧气后会新增临时修复任务，修复后自动移除！\n临时任务不占用3个常规任务数量，2回合内未修复则内鬼胜利！",
                    font=(self.font_family, int(11 * self.font_size_multiplier)),
                    fg="#ff0000",
                    bg="#16213e"
                )
                oxygen_rule_label.pack(pady=3)
            
            # 其他内鬼信息（仅内鬼可见）
            if isinstance(player.role, Impostor):
                other_impostors = [p.name for p in self.game.players 
                                 if p != player and isinstance(p.role, Impostor)]
                if other_impostors:
                    impostor_label = tk.Label(
                        role_frame, 
                        text=f"其他内鬼: {', '.join(other_impostors)}", font=(self.font_family, 10),
                        fg="#e94560",
                        bg="#16213e"
                    )
                    impostor_label.pack(pady=2)
                # 提示内鬼氧气破坏规则
                oxygen_tip_label = tk.Label(
                    role_frame,
                    text="⚠️ 破坏氧气后船员会新增临时修复任务，2回合内未修复你将直接胜利！",
                    font=(self.font_family, 9),
                    fg="#ffcc00",
                    bg="#16213e"
                )
                oxygen_tip_label.pack(pady=2)
                # 提示内鬼穿梭规则
                teleport_rule_label = tk.Label(
                    role_frame,
                    text="🔮 穿梭规则：第一回合禁用，使用后冷却3回合，可跳至任意房间！",
                    font=(self.font_family, 9),
                    fg="#00ffff",
                    bg="#16213e"
                )
                teleport_rule_label.pack(pady=2)
            
            # 提示文本（联机模式下的提示）
            tip_label = tk.Label(
                role_frame, 
                text="请记住你的角色信息，然后点击开始游戏！", 
                font=(self.font_family, 10),
                fg="#ffcc00",
                bg="#16213e"
            )
            tip_label.pack(pady=15)
            
            # 继续按钮（联机模式下直接开始游戏）
            if sys.platform == 'darwin':
                continue_button = ttk.Button(
                    role_frame, 
                    text="开始游戏", 
                    style="Continue.TButton",
                    command=self.start_game_loop
                )
                style = ttk.Style()
                style.configure("Continue.TButton", 
                              font=(self.font_family, 16),
                              padding=(30, 10),
                              background="#4CAF50",
                              foreground="#FFFFFF")
                style.map("Continue.TButton",
                      background=[("active", "#388E3C"),("!active", "#4CAF50")],
                      foreground=[("active", "#E3F2FD"),("!active", "#FFFFFF")])
            else:
                continue_button = tk.Button(
                    role_frame, 
                    text="开始游戏", 
                    font=(self.font_family, 16),
                    bg="#4caf50",
                    fg="#ffffff",
                    padx=30,
                    pady=10,
                    bd=2,
                    relief="flat",
                    command=self.start_game_loop
                )
            continue_button.pack()
        else:
            # 单机模式：原有的逻辑
            if self.current_player_index < len(self.game.players):
                player = self.game.players[self.current_player_index]
                
                # 清除界面
                for widget in self.root.winfo_children():
                    widget.destroy()
                
                # 创建角色信息界面
                role_frame = tk.Frame(self.root, bg="#16213e", padx=40, pady=30)
                role_frame.pack(fill="both", expand=True, pady=30, padx=50)
                
                # 玩家信息
                player_label = tk.Label(
                    role_frame, 
                    text=f"玩家: {player.name}", 
                    font=(self.font_family, int(24 * self.font_size_multiplier), "bold"),
                    fg="#ffffff",
                    bg="#16213e"
                )
                player_label.pack(pady=12)
                
                # 角色信息
                role_name = player.role.__class__.__name__
                role_color = "#e94560" if role_name == "Impostor" else "#00ff00"
                
                role_label = tk.Label(
                    role_frame, 
                    text=f"角色: {role_name}", 
                    font=(self.font_family, int(32 * self.font_size_multiplier), "bold"),
                    fg=role_color,
                    bg="#16213e"
                )
                role_label.pack(pady=15)
                
                # 角色说明
                info_text = player.role.get_role_info()
                info_label = tk.Label(
                    role_frame, 
                    text=info_text, 
                    font=(self.font_family, 10),
                    fg="#ffffff",
                    bg="#16213e",
                    wraplength=800,
                    justify="center"
                )
                info_label.pack(pady=10)
                
                # 紧急会议规则提示
                meeting_rule_label = tk.Label(
                    role_frame,
                    text=f"📢 紧急会议规则：每人可发起{self.max_emergency_meetings}次紧急会议，仅在【飞船大厅】可发起！",
                    font=(self.font_family, int(11 * self.font_size_multiplier)),
                    fg="#00ffff",
                    bg="#16213e"
                )
                meeting_rule_label.pack(pady=3)
                
                # 任务信息（仅船员可见）
                if isinstance(player.role, Crewmate):
                    task_label = tk.Label(
                        role_frame, 
                        text=f"你需要完成 3 个常规任务", 
                        font=(self.font_family, int(14 * self.font_size_multiplier)),
                        fg="#4caf50",
                        bg="#16213e"
                    )
                    task_label.pack(pady=5)
                    oxygen_rule_label = tk.Label(
                        role_frame,
                        text="⚠️ 内鬼破坏氧气后会新增临时修复任务，修复后自动移除！\n临时任务不占用3个常规任务数量，2回合内未修复则内鬼胜利！",
                        font=(self.font_family, int(11 * self.font_size_multiplier)),
                        fg="#ff0000",
                        bg="#16213e"
                    )
                    oxygen_rule_label.pack(pady=3)
                
                # 其他内鬼信息（仅内鬼可见）
                if isinstance(player.role, Impostor):
                    other_impostors = [p.name for p in self.game.players 
                                     if p != player and isinstance(p.role, Impostor)]
                    if other_impostors:
                        impostor_label = tk.Label(
                            role_frame, 
                            text=f"其他内鬼: {', '.join(other_impostors)}", font=(self.font_family, 10),
                            fg="#e94560",
                            bg="#16213e"
                        )
                        impostor_label.pack(pady=2)
                    # 提示内鬼氧气破坏规则
                    oxygen_tip_label = tk.Label(
                        role_frame,
                        text="⚠️ 破坏氧气后船员会新增临时修复任务，2回合内未修复你将直接胜利！",
                        font=(self.font_family, 9),
                        fg="#ffcc00",
                        bg="#16213e"
                    )
                    oxygen_tip_label.pack(pady=2)
                    # 提示内鬼穿梭规则
                    teleport_rule_label = tk.Label(
                        role_frame,
                        text="🔮 穿梭规则：第一回合禁用，使用后冷却3回合，可跳至任意房间！",
                        font=(self.font_family, 9),
                        fg="#00ffff",
                        bg="#16213e"
                    )
                    teleport_rule_label.pack(pady=2)
                
                # 提示文本
                tip_label = tk.Label(
                    role_frame, 
                    text="请记住你的角色信息，然后点击继续按钮", 
                    font=(self.font_family, 10),
                    fg="#ffcc00",
                    bg="#16213e"
                )
                tip_label.pack(pady=15)
                
                # 继续按钮
                if sys.platform == 'darwin':
                    continue_button = ttk.Button(
                        role_frame, 
                        text="继续", 
                        style="Continue.TButton",
                        command=self.next_role_info
                    )
                    style = ttk.Style()
                    style.configure("Continue.TButton", 
                                  font=(self.font_family, 16),
                                  padding=(30, 10),
                                  background="#2196F3",
                                  foreground="#FFFFFF")
                    style.map("Continue.TButton",
                          background=[("active", "#1976D2"),("!active", "#2196F3")],
                          foreground=[("active", "#E3F2FD"),("!active", "#FFFFFF")])
                else:
                    continue_button = tk.Button(
                        role_frame, 
                        text="继续", 
                        font=(self.font_family, 16),
                        bg="#2196f3",
                        fg="#ffffff",
                        padx=30,
                        pady=10,
                        bd=2,
                        relief="flat",
                        command=self.next_role_info
                    )
                continue_button.pack()
            else:
                # 所有玩家都已查看角色，开始游戏
                self.start_game_loop()
    
    def next_role_info(self):
        """显示下一个玩家的角色信息"""
        self.current_player_index += 1
        self.show_role_info()
    
    def start_game_loop(self):
        """开始游戏主循环（联机模式下，每个玩家独立，不限回合和步数）"""
        self.game.game_over = False
        
        # 联机模式：根据 my_name_from_args 找到当前玩家，不进行回合切换
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
            # 找到当前玩家
            self.current_player = None
            for player in self.game.players:
                if player.name == my_name_from_args:
                    self.current_player = player
                    break
            
            if not self.current_player:
                self.current_player = self.game.players[0]
            
            # 移除回合计数和步数限制
            self.global_round = 1
            self.action_steps = 0  # 重置，但不限制
            
            # 启动内鬼技能冷却（开局即冷却）
            if isinstance(self.current_player.role, Impostor):
                self.current_player.role.start_cooldowns()
            
            # 启动实时冷却计时器（每秒更新一次）
            self.start_real_time_cooldown_timer()
        else:
            # 单机模式：原有的回合制逻辑
            self.global_round = 1
            self.players_acted_this_round = 0
            self.alive_players_count = len([p for p in self.game.players if p.is_alive])
            
            if self.all_players_list:
                self.current_player = self.all_players_list[0]
            else:
                self.current_player = self.game.players[0]
        
        # 联机模式下启动位置同步
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
            # 房主（服务器）端：在本进程内启动位置同步服务器。
            # 注意：同步服务器必须运行在整个游戏期间，不能放在房间大厅进程里
            # （大厅进程游戏开始即退出，会导致所有玩家同步连接被拒绝）。
            if is_server:
                self.start_sync_server()
            # 所有玩家（含房主自己）都启动同步客户端；房主回连本机 127.0.0.1。
            # 客户端内置重连循环，即使房主服务器稍晚启动也能自动连上。
            self.start_sync_client()
        
        # 开始游戏
        self.create_game_frame()
    
    def start_real_time_cooldown_timer(self):
        """启动实时冷却计时器（每秒更新一次）"""
        def update_cooldowns():
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer and not self.game.game_over:
                # 更新所有玩家的冷却（包括监控冷却）
                for player in self.game.players:
                    player.role.update_cooldowns_real_time()
                
                # 更新炸弹爆炸倒计时（如果有炸弹）
                if self.bomb_location and isinstance(self.current_player.role, Impostor):
                    remaining = self.current_player.role.get_bomb_time_remaining()
                    if remaining <= 0 and self.bomb_location:
                        # 炸弹爆炸
                        self.execute_bomb_explosion(self.current_player)
                
                # 只更新计时显示，不重新创建整个界面
                self.update_cooldown_labels()
            
            # 每秒更新一次
            self.root.after(1000, update_cooldowns)
        
        # 立即执行一次，然后每秒执行
        update_cooldowns()
    
    def update_cooldown_labels(self):
        """更新冷却计时Label（检测冷却结束时重新创建界面）"""
        if not hasattr(self, 'is_multiplayer') or not self.is_multiplayer:
            return
        
        try:
            need_refresh = False
            
            # 更新监控冷却（所有玩家）
            monitor_cooldown = self.current_player.role.current_monitor_cooldown_seconds
            
            # 检测监控冷却是否结束
            if self.last_monitor_cooldown is not None and self.last_monitor_cooldown > 0 and monitor_cooldown == 0:
                need_refresh = True
            self.last_monitor_cooldown = monitor_cooldown
            
            if self.monitor_cooldown_label and monitor_cooldown > 0:
                try:
                    if self.monitor_cooldown_label.winfo_exists():
                        minutes = monitor_cooldown // 60
                        seconds = monitor_cooldown % 60
                        self.monitor_cooldown_label.config(text=f"⏱️ 监控冷却: {minutes:02d}:{seconds:02d}")
                except tk.TclError:
                    pass
            
            # 更新内鬼其他技能冷却
            if isinstance(self.current_player.role, Impostor):
                # 击杀冷却
                kill_cooldown = self.current_player.role.current_kill_cooldown_seconds
                if self.last_kill_cooldown is not None and self.last_kill_cooldown > 0 and kill_cooldown == 0:
                    need_refresh = True
                self.last_kill_cooldown = kill_cooldown
                
                if self.kill_cooldown_label and kill_cooldown > 0:
                    try:
                        if self.kill_cooldown_label.winfo_exists():
                            minutes = kill_cooldown // 60
                            seconds = kill_cooldown % 60
                            self.kill_cooldown_label.config(text=f"⏱️ 击杀冷却: {minutes:02d}:{seconds:02d}")
                    except tk.TclError:
                        pass
                
                # 穿梭冷却
                shuttle_cooldown = self.current_player.role.current_shuttle_cooldown_seconds
                if self.last_shuttle_cooldown is not None and self.last_shuttle_cooldown > 0 and shuttle_cooldown == 0:
                    need_refresh = True
                self.last_shuttle_cooldown = shuttle_cooldown
                
                if self.shuttle_cooldown_label and shuttle_cooldown > 0:
                    try:
                        if self.shuttle_cooldown_label.winfo_exists():
                            minutes = shuttle_cooldown // 60
                            seconds = shuttle_cooldown % 60
                            self.shuttle_cooldown_label.config(text=f"⏱️ 穿梭冷却: {minutes:02d}:{seconds:02d}")
                    except tk.TclError:
                        pass
                
                # 炸弹冷却
                bomb_cooldown = self.current_player.role.current_bomb_cooldown_seconds
                if self.last_bomb_cooldown is not None and self.last_bomb_cooldown > 0 and bomb_cooldown == 0:
                    need_refresh = True
                self.last_bomb_cooldown = bomb_cooldown
                
                if self.bomb_cooldown_label and bomb_cooldown > 0:
                    try:
                        if self.bomb_cooldown_label.winfo_exists():
                            minutes = bomb_cooldown // 60
                            seconds = bomb_cooldown % 60
                            self.bomb_cooldown_label.config(text=f"⏱️ 炸弹冷却: {minutes:02d}:{seconds:02d}")
                    except tk.TclError:
                        pass
                
                # 破坏系统冷却
                sabotage_cooldown = self.current_player.role.current_sabotage_cooldown_seconds
                if self.last_sabotage_cooldown is not None and self.last_sabotage_cooldown > 0 and sabotage_cooldown == 0:
                    need_refresh = True
                self.last_sabotage_cooldown = sabotage_cooldown
                
                if self.sabotage_cooldown_label and sabotage_cooldown > 0:
                    try:
                        if self.sabotage_cooldown_label.winfo_exists():
                            minutes = sabotage_cooldown // 60
                            seconds = sabotage_cooldown % 60
                            self.sabotage_cooldown_label.config(text=f"⏱️ 破坏冷却: {minutes:02d}:{seconds:02d}")
                    except tk.TclError:
                        pass
            
            # 如果需要刷新界面时重新创建（显示按钮）
            if need_refresh:
                self.create_game_frame()
                return
            
            # 更新炸弹爆炸倒计时
            if self.bomb_timer_label and self.bomb_location and isinstance(self.current_player.role, Impostor):
                remaining = self.current_player.role.get_bomb_time_remaining()
                if remaining > 0:
                    try:
                        if self.bomb_timer_label.winfo_exists():
                            minutes = remaining // 60
                            seconds = remaining % 60
                            self.bomb_timer_label.config(text=f"💣 炸弹倒计时: {minutes:02d}:{seconds:02d}")
                    except tk.TclError:
                        pass
        except Exception as e:
            print(f"更新冷却标签时出错: {e}")

    def handle_emergency_meeting(self, player):
        """处理发起紧急会议的核心逻辑（新增位置校验）"""
        # 旁观玩家无法发起紧急会议
        if player in self.spectator_players:
            messagebox.showwarning("旁观限制", "❌ 旁观模式下无法发起紧急会议！")
            return
        
        # 检查紧急会议是否被禁用（炸弹在飞船大厅爆炸后）
        if self.emergency_ban_rounds > 0:
            messagebox.showwarning("功能禁用", f"❌ 紧急会议功能已被禁用！\n剩余禁用回合：{self.emergency_ban_rounds}回合")
            return
        
        # 检查飞船大厅是否是废墟
        if self.ruined_rooms.get(self.meeting_room, False) and not self.ruin_cleaned.get(self.meeting_room, True):
            messagebox.showwarning("废墟阻挡", f"❌ 飞船大厅是废墟状态！\n请先清理废墟才能发起紧急会议！")
            return
        
        # 1. 检查剩余次数
        remaining = self.emergency_meeting_count.get(player.name, 0)
        if remaining <= 0:
            messagebox.showwarning("次数用尽", "❌ 您发起紧急会议的次数已使用完毕！")
            return
        
        # 2. 新增：检查当前位置是否为飞船大厅
        if player.current_location != self.meeting_room:
            messagebox.showwarning("位置限制", f"❌ 仅在【{self.meeting_room}】可发起紧急会议！\n当前位置：{player.current_location}")
            return
        
        # 3. 确认发起紧急会议
        confirm = messagebox.askyesno(
            "发起紧急会议",
            f"📢 你确定要发起紧急会议吗？\n当前剩余次数：{remaining-1}/{self.max_emergency_meetings}",
            parent=self.root
        )
        if not confirm:
            return
        
        # 4. 消耗紧急会议次数
        self.emergency_meeting_count[player.name] -= 1
        remaining_after = self.emergency_meeting_count[player.name]
        
        # 5. 记录日志
        self.add_log(f"📢 {player.name}在{self.meeting_room}发起了紧急会议！剩余次数：{remaining_after}/{self.max_emergency_meetings}")
        
        # 6. 进入讨论阶段（复用原有讨论逻辑）
        self.discussion_phase(player, None)

    def get_room_mates_text(self):
        """获取当前视角房间的玩家文本（旁观模式显示视角房间的玩家）
        飞船大厅人数超过3人时使用3-3-3布局
        """
        # 旁观模式：显示视角房间的玩家信息
        if self.current_player in self.spectator_players:
            view_room = self.spectator_view_room or self.current_player.current_location
            room_mates = [
                p for p in self.game.players 
                if p.current_location == view_room
            ]
            text_lines = [f"当前查看房间({view_room})玩家及身份："]
            if not room_mates:
                text_lines.append("无其他玩家")
            else:
                # 飞船大厅超过3人时使用3-3-3布局
                if view_room == "飞船大厅" and len(room_mates) > 3:
                    # 分行显示，每行最多3人
                    player_info_lines = []
                    for i, p in enumerate(room_mates):
                        role_name = p.role.__class__.__name__
                        status = "🔴死亡" if not p.is_alive else "🟢存活"
                        if p == self.current_player and not p.is_alive:
                            if self.dead_player_locations.get(p.name, {}).get("cleared", False):
                                status += "（你的尸体已清理）"
                            else:
                                status += "（你的尸体）"
                        player_info_lines.append(f"{p.name}: {role_name} ({status})")
                        # 每3人换一行
                        if (i + 1) % 3 == 0:
                            text_lines.append(" | ".join(player_info_lines))
                            player_info_lines = []
                    # 处理剩余的玩家
                    if player_info_lines:
                        text_lines.append(" | ".join(player_info_lines))
                else:
                    # 普通布局或人数<=3
                    player_info = []
                    for p in room_mates:
                        role_name = p.role.__class__.__name__
                        status = "🔴死亡" if not p.is_alive else "🟢存活"
                        # 标记自己的尸体（如果未清理）
                        if p == self.current_player and not p.is_alive:
                            if self.dead_player_locations.get(p.name, {}).get("cleared", False):
                                status += "（你的尸体已清理）"
                            else:
                                status += "（你的尸体）"
                        player_info.append(f"{p.name}: {role_name} ({status})")
                    line1 = " | ".join(player_info)
                    text_lines.append(line1)
            return "\n".join(text_lines[:4])  # 最多返回4行
        # 正常模式：仅显示当前房间的存活玩家名
        else:
            current_player = self.current_player
            room_mates = [
                p.name for p in self.game.players 
                if p.is_alive and p != current_player and p.current_location == current_player.current_location
            ]
            text_lines = [f"当前房间({current_player.current_location})玩家："]
            if not room_mates:
                text_lines.append("无其他玩家")
            else:
                # 飞船大厅超过3人时使用3-3-3布局
                if current_player.current_location == "飞船大厅" and len(room_mates) > 3:
                    # 分行显示，每行最多3人
                    for i in range(0, len(room_mates), 3):
                        chunk = room_mates[i:i+3]
                        text_lines.append(" | ".join(chunk))
                else:
                    line1 = " | ".join(room_mates[:])
                    text_lines.append(line1)
            return "\n".join(text_lines[:4])  # 最多返回4行
    
    def teleport_to_room(self, player):
        """内鬼穿梭功能：跳转到任意房间"""
        # 旁观玩家无法使用穿梭
        if player in self.spectator_players:
            messagebox.showwarning("旁观限制", "❌ 旁观模式下无法使用穿梭功能！")
            return
        
        # 步数检查（联机模式下不检查）
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
            if self.action_steps > self.max_steps:
                messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法使用穿梭")
                return
        
        # 创建穿梭房间选择窗口
        teleport_window = tk.Toplevel(self.root)
        teleport_window.title("内鬼穿梭 - 选择目标房间")
        teleport_window.geometry("1000x750+460+165")
        teleport_window.configure(bg="#1a1a2e")
        teleport_window.transient(self.root)
        teleport_window.grab_set()
        teleport_window.wm_attributes("-topmost", True)
        
        # 标题
        title_label = tk.Label(
            teleport_window,
            text="🔮 选择要穿梭到的房间",
            font=(self.font_family, 16, "bold"),
            fg="#00ffff",
            bg="#1a1a2e"
        )
        title_label.pack(pady=15)
        
        # 房间列表
        room_var = tk.StringVar()
        room_listbox = tk.Listbox(
            teleport_window,
            listvariable=room_var,
            font=(self.font_family, 12),
            bg="#0f3460",
            fg="#ffffff",
            selectbackground="#00ffff",
            selectforeground="#000000",
            width=25,
            height=12
        )
        room_listbox.pack(pady=10, padx=20)
        
        # 添加所有房间选项
        for room in self.all_rooms:
            room_listbox.insert(tk.END, room)
        
        # 确认穿梭
        def confirm_teleport():
            if room_listbox.curselection():
                selected_idx = room_listbox.curselection()[0]
                target_room = room_listbox.get(selected_idx)
                
                is_multiplayer = hasattr(self, 'is_multiplayer') and self.is_multiplayer
                
                # 检查穿梭冷却（联机模式）
                if is_multiplayer:
                    if not player.role.can_shuttle():
                        remaining = player.role.current_shuttle_cooldown_seconds
                        minutes = remaining // 60
                        seconds = remaining % 60
                        messagebox.showerror("冷却中", f"⚠️ 穿梭技能冷却中！\n剩余时间：{minutes}分{seconds}秒")
                        return
                    # 使用穿梭并启动冷却
                    player.role.use_shuttle()
                else:
                    # 单机模式：使用回合制冷却
                    if self.impostor_teleport_cooldown.get(player.name, 0) > 0:
                        messagebox.showerror("冷却中", f"⚠️ 穿梭技能冷却中！\n剩余：{self.impostor_teleport_cooldown[player.name]}回合")
                        return
                
                # 消耗行动步数
                self.action_steps += 1
                
                # 执行穿梭
                old_room = player.current_location
                player.current_location = target_room
                
                # 设置冷却
                if not is_multiplayer:
                    self.impostor_teleport_cooldown[player.name] = 3
                
                # 发送位置更新
                if is_multiplayer:
                    self.send_position_update(player.name, target_room)
                
                # 关闭窗口
                teleport_window.destroy()
                
                # 提示
                if is_multiplayer:
                    messagebox.showinfo("穿梭成功", f"✅ 已成功穿梭到【{target_room}】！\n穿梭将进入1分钟冷却")
                else:
                    messagebox.showinfo("穿梭成功", f"✅ 已成功穿梭到【{target_room}】！\n穿梭将进入3回合冷却")
                
                # 刷新UI
                self.create_game_frame()
                
                # 检查步数是否超限（联机模式下不检查）
                if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                    if self.action_steps > self.max_steps:
                        messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                        self.switch_to_next_player()
            else:
                messagebox.showwarning("警告", "请选择一个目标房间！")
        
        # 按钮框架
        btn_frame = tk.Frame(teleport_window, bg="#1a1a2e")
        btn_frame.pack(pady=15)
        
        # 确认按钮
        # 为所有平台创建兼容的按钮
        if sys.platform == 'darwin':
            # Mac上使用ttk按钮
            confirm_btn = ttk.Button(
                btn_frame,
                text="确认穿梭", 
                style="Confirm.TButton",
                command=confirm_teleport
            )
            cancel_btn = ttk.Button(
                btn_frame,
                text="取消", 
                style="Cancel.TButton",
                command=teleport_window.destroy
            )
            style = ttk.Style()
            style.configure("Confirm.TButton", 
                          font=(self.font_family, 12),
                          padding=(20, 5),
                          background="#00FFFF",
                          foreground="#000000")
            style.map("Confirm.TButton",
                      background=[("active", "#00CCCC"),("!active", "#00FFFF")],
                      foreground=[("active", "#000000"),("!active", "#000000")])
            style.configure("Cancel.TButton", 
                          font=(self.font_family, 12),
                          padding=(20, 5),
                          background="#F44336",
                          foreground="#FFFFFF")
            style.map("Cancel.TButton",
                      background=[("active", "#D32F2F"),("!active", "#F44336")],
                      foreground=[("active", "#FFEBEE"),("!active", "#FFFFFF")])
            confirm_btn.pack(side="left", padx=10)
        else:
            # Windows上使用普通按钮
            confirm_btn = tk.Button(
                btn_frame,
                text="确认穿梭",
                font=(self.font_family, 12),
                bg="#2196f3",
                fg="#ffffff",
                padx=20,
                pady=5,
                bd=2,
                relief="flat",
                command=confirm_teleport
            )
            cancel_btn = tk.Button(
                btn_frame,
                text="取消",
                font=(self.font_family, 12),
                bg="#f44336",
                fg="#ffffff",
                padx=20,
                pady=5,
                bd=2,
                relief="flat",
                command=teleport_window.destroy
            )
            confirm_btn.pack(side="left", padx=10)
        cancel_btn.pack(side="left", padx=10)
    
    def update_bomb_timer(self):
        """实时更新炸弹倒计时（每秒更新一次）"""
        if self.game.game_over or self.bomb_exploding:
            return
        
        has_bomb = False
        remaining = 0
        
        # 优先从房间状态获取炸弹时间（联机模式）
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer and self.room_state and self.room_state.bomb_explode_time:
            remaining = max(0, int(self.room_state.bomb_explode_time - time.time()))
            has_bomb = remaining > 0
        else:
            # 单机模式：从内鬼角色获取炸弹时间
            for player in self.game.players:
                if isinstance(player.role, Impostor) and player.role.bomb_explode_time:
                    remaining = player.role.get_bomb_time_remaining()
                    has_bomb = True
                    break
        
        if has_bomb:
            if remaining <= 0:
                self.execute_bomb_explosion()
                return
            
            minutes = remaining // 60
            seconds = remaining % 60
            try:
                if self.bomb_timer_label and self.bomb_timer_label.winfo_exists():
                    self.bomb_timer_label.config(text=f"💣 炸弹倒计时：{minutes}:{seconds:02d}")
                    self.bomb_remaining_time = remaining
                    
                    if remaining <= 10:
                        self.bomb_timer_label.config(fg="#ff0000")
                    else:
                        self.bomb_timer_label.config(fg="#ff5722")
            except tk.TclError:
                pass
        else:
            try:
                if self.bomb_timer_label and self.bomb_timer_label.winfo_exists():
                    self.bomb_timer_label.config(text="")
                self.bomb_remaining_time = 0
            except:
                pass
        
        # 检查标签是否仍然存在
        try:
            if self.bomb_timer_label and self.bomb_timer_label.winfo_exists():
                self.root.after(1000, self.update_bomb_timer)
        except:
            pass
    
    def update_oxygen_timer(self):
        """实时更新氧气倒计时（每秒更新一次）"""
        if self.game.game_over:
            return
        
        if self.oxygen_sabotaged and not self.oxygen_repaired and self.oxygen_timeout:
            remaining = max(0, int(self.oxygen_timeout - time.time()))
            
            if remaining <= 0:
                self.execute_oxygen_exhaustion()
                return
            
            minutes = remaining // 60
            seconds = remaining % 60
            try:
                if self.oxygen_timer_label and self.oxygen_timer_label.winfo_exists():
                    self.oxygen_timer_label.config(text=f"⚠️ 氧气倒计时：{minutes}:{seconds:02d}")
                    
                    if remaining <= 30:
                        self.oxygen_timer_label.config(fg="#ff0000")
                    elif remaining <= 60:
                        self.oxygen_timer_label.config(fg="#ff6600")
                    else:
                        self.oxygen_timer_label.config(fg="#ffcc00")
            except tk.TclError:
                pass
        else:
            try:
                if self.oxygen_timer_label and self.oxygen_timer_label.winfo_exists():
                    self.oxygen_timer_label.config(text="")
            except:
                pass
        
        # 检查标签是否仍然存在
        try:
            if self.oxygen_timer_label and self.oxygen_timer_label.winfo_exists():
                self.root.after(1000, self.update_oxygen_timer)
        except:
            pass

    def execute_bomb_explosion(self, player):
        """执行炸弹爆炸"""
        self.bomb_exploding = True
        
        bomb_location = player.current_location
        player.role.bomb_explode_time = None
        
        self.add_log(f"💥 炸弹在{bomb_location}爆炸了！")
        
        damage_msg = ""
        system_msg = ""
        
        # 标记房间为废墟
        self.ruined_rooms[bomb_location] = True
        self.ruin_cleaned[bomb_location] = False
        self.add_log(f"🏚️ {bomb_location}变成废墟！需要清理后才能使用！")
        
        if "氧气" in bomb_location:
            self.oxygen_sabotaged = True
            self.oxygen_repaired = False
            self.oxygen_sabotage_round = self.global_round
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                self.oxygen_timeout = time.time() + 150  # 联机模式：150秒倒计时
                # 更新房间状态
                if self.room_state:
                    self.room_state.set_sabotage("oxygen", True)
                self.add_log(f"⚠️ 氧气系统受损！船员需要在150秒内修复！")
            else:
                self.oxygen_remaining_rounds = 2
                self.add_log(f"⚠️ 氧气系统受损！船员需要在2回合内修复！")
            system_msg = "💥 氧气系统受损！"
        elif "监控" in bomb_location:
            self.monitor_sabotaged = True
            self.add_log(f"⚠️ 监控系统受损！需要完成任务才能恢复！")
            system_msg = "💥 监控系统受损！"
        elif bomb_location == "飞船大厅":
            self.emergency_ban_rounds = 2
            self.add_log(f"⚠️ 飞船大厅被炸！紧急会议功能已被禁用2回合！")
            system_msg = "⚠️ 紧急会议已被禁用2回合！"
        
        dead_players = []
        for target in self.game.players:
            if target.is_alive and target.current_location == bomb_location:
                if not isinstance(target.role, Impostor):
                    dead_players.append(target)
        
        if dead_players:
            dead_names = ", ".join([p.name for p in dead_players])
            self.add_log(f"☠️ 炸弹炸死了：{dead_names}")
            damage_msg = f"☠️ 炸弹造成{len(dead_players)}人死亡：{dead_names}"
            
            for p in dead_players:
                p.is_alive = False
        
        try:
            if self.bomb_timer_label and self.bomb_timer_label.winfo_exists():
                self.bomb_timer_label.config(text="")
        except:
            pass
        self.bomb_remaining_time = 0
        self.bomb_location = None  # 清除炸弹位置
        
        if system_msg or damage_msg:
            final_msg = f"💥 {bomb_location}的炸弹爆炸了！"
            if system_msg:
                final_msg += f"\n{system_msg}"
            if damage_msg:
                final_msg += f"\n{damage_msg}"
            messagebox.showinfo("炸弹爆炸", final_msg)
        
        self.bomb_exploding = False
        
        if self.game.check_game_over():
            # 获取胜利者并广播
            winner = self.game.winner if hasattr(self.game, 'winner') else "unknown"
            self.broadcast_game_over(winner, "bomb_explosion")
            self.show_game_over()
        else:
            self.create_game_frame()
    
    def execute_oxygen_exhaustion(self):
        """执行氧气耗尽（内鬼胜利）"""
        self.add_log("⚠️ 氧气耗尽！船员未能在时间内修复氧气系统！")
        
        # 设置游戏结束状态
        self.game.winner = "impostor"
        self.game.game_over = True
        
        # 广播游戏结束
        self.broadcast_game_over("impostor", "oxygen_exhausted")
        
        # 显示游戏结束界面
        self.show_game_over()

    def check_bomb_explosion(self):
        """检查炸弹是否爆炸（实时检测）"""
        for player in self.game.players:
            if isinstance(player.role, Impostor) and player.role.bomb_explode_time:
                if player.role.is_bomb_exploded():
                    bomb_location = self.bomb_location  # 使用固定的炸弹位置，而不是player.current_location
                    self.add_log(f"💥 炸弹在{bomb_location}爆炸了！")
                    messagebox.showinfo("炸弹爆炸", f"💥 {bomb_location}的炸弹爆炸了！")
                    
                    # 标记房间为废墟
                    self.ruined_rooms[bomb_location] = True
                    self.ruin_cleaned[bomb_location] = False
                    self.add_log(f"🏚️ {bomb_location}变成废墟！需要清理后才能使用！")
                    
                    # 根据爆炸位置触发修复任务
                    if "氧气" in bomb_location:
                        self.oxygen_sabotaged = True
                        self.oxygen_repaired = False
                        self.oxygen_sabotage_round = self.global_round
                        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                            self.oxygen_timeout = time.time() + 150  # 联机模式：150秒倒计时
                            # 更新房间状态
                            if self.room_state:
                                self.room_state.set_sabotage("oxygen", True)
                            self.add_log(f"⚠️ 氧气系统受损！船员需要在150秒内修复！")
                            messagebox.showinfo("系统损坏", "💥 氧气系统受损！\n船员需要在150秒内修复！")
                        else:
                            self.oxygen_remaining_rounds = 2
                            self.add_log(f"⚠️ 氧气系统受损！船员需要在2回合内修复！")
                            messagebox.showinfo("系统损坏", "💥 氧气系统受损！\n船员需要在2回合内修复！")
                    elif "监控" in bomb_location:
                        self.monitor_sabotaged = True
                        self.add_log(f"⚠️ 监控系统受损！需要完成任务才能恢复！")
                        messagebox.showinfo("系统损坏", "💥 监控系统受损！\n需要完成任务才能恢复！")
                    elif bomb_location == "飞船大厅":
                        self.emergency_ban_rounds = 2
                        self.add_log(f"⚠️ 飞船大厅被炸！紧急会议功能已被禁用2回合！")
                        messagebox.showinfo("功能禁用", "⚠️ 飞船大厅被炸！\n紧急会议功能已被禁用2回合！")
                    
                    dead_players = []
                    for target in self.game.players:
                        if target.is_alive and target.current_location == bomb_location:
                            if not isinstance(target.role, Impostor):
                                dead_players.append(target)
                    
                    if dead_players:
                        dead_names = ", ".join([p.name for p in dead_players])
                        self.add_log(f"☠️ 炸弹炸死了：{dead_names}")
                        messagebox.showinfo("伤亡报告", f"☠️ 炸弹造成{len(dead_players)}人死亡：\n{dead_names}")
                        
                        for p in dead_players:
                            p.is_alive = False
                    
                    player.role.bomb_explode_time = None
                    self.bomb_location = None
                    
                    if self.game.check_game_over():
                        # 获取胜利者并广播
                        winner = self.game.winner if hasattr(self.game, 'winner') else "unknown"
                        self.broadcast_game_over(winner, "bomb_explosion")
                        self.show_game_over()
                        return True
        return False

    def create_game_frame(self):
        """创建游戏主界面（死亡玩家保留并进入旁观模式，尸体固定位置）"""
        # 首先检查炸弹是否爆炸
        if self.check_bomb_explosion():
            return
        
        # 清除所有现有组件
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # 初始化冷却跟踪变量（联机模式下）
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer and isinstance(self.current_player.role, Impostor):
            self.last_kill_cooldown = self.current_player.role.current_kill_cooldown_seconds
            self.last_shuttle_cooldown = self.current_player.role.current_shuttle_cooldown_seconds
            self.last_bomb_cooldown = self.current_player.role.current_bomb_cooldown_seconds
        
        # 清空界面引用
        self.player_labels = {}
        self.room_mates_label = None
        
        # 创建游戏主框架
        self.game_frame = tk.Frame(self.root, bg="#16213e")
        self.game_frame.pack(fill="both", expand=True)
        
        # 定义放大后的字体大小（基于 font_size_multiplier）
        fs = self.font_size_multiplier
        title_font = (self.font_family, int(14 * fs), "bold")
        normal_font = (self.font_family, int(12 * fs))
        small_font = (self.font_family, int(10 * fs))
        
        self.create_task_list() 
        # 顶部信息栏
        top_frame = tk.Frame(self.game_frame, bg="#0f3460", height=60)
        top_frame.pack(fill="x")
        
        # 显示游戏信息（联机模式下，无回合和步数限制）
        # 新增：旁观模式标识
        spectator_tag = "【旁观模式】" if self.current_player in self.spectator_players else ""
        
        # 联机模式下，不显示回合和步数
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
            round_text = f"{spectator_tag}联机模式 | 无限行动次数"
        else:
            round_text = f"{spectator_tag}全局回合：{self.global_round} | 当前玩家行动步数：{self.action_steps}/{self.max_steps}"
        
        if self.oxygen_sabotaged and not self.oxygen_repaired:
            round_text += f" | ⚠️ 氧气已破坏！"
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer and self.oxygen_timeout:
                # 联机模式：显示实时倒计时
                remaining_time = max(0, int(self.oxygen_timeout - time.time()))
                minutes = remaining_time // 60
                seconds = remaining_time % 60
                round_text += f"剩余时间：{minutes}分{seconds}秒"
                if remaining_time <= 30:
                    round_text += " ⏰ 紧急！"
            elif not hasattr(self, 'is_multiplayer') or not self.is_multiplayer:
                # 单机模式：显示回合数
                round_text += f"剩余修复回合：{self.oxygen_remaining_rounds} (共2回合)"
                if self.oxygen_remaining_rounds <= 1:
                    round_text += " ⏰ 最后倒计时！"
        
        # 添加内鬼穿梭冷却提示（仅存活内鬼显示，联机模式下改为次数显示）
        if isinstance(self.current_player.role, Impostor) and self.current_player.is_alive:
            if self.current_player.name in self.impostor_teleport_cooldown:
                if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                    round_text += f" | 🔮 穿梭冷却中"
                else:
                    round_text += f" | 🔮 穿梭冷却剩余：{self.impostor_teleport_cooldown[self.current_player.name]}回合"
            elif self.global_round == 1 and not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                round_text += f" | 🔮 第一回合无法使用穿梭"
        
        # 添加监控使用冷却提示（仅存活玩家显示）
        if self.current_player.is_alive and self.current_player not in self.spectator_players:
            if self.current_player.name in self.monitor_cooldown:
                if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                    round_text += f" | 📡 监控冷却中"
                else:
                    round_text += f" | 📡 监控冷却剩余：{self.monitor_cooldown[self.current_player.name]}回合"
        
        # 显示炸弹倒计时（所有玩家可见）
        self.bomb_remaining_time = 0
        for player in self.game.players:
            if isinstance(player.role, Impostor) and player.role.bomb_explode_time:
                self.bomb_remaining_time = player.role.get_bomb_time_remaining()
                break
        
        round_label = tk.Label(
            top_frame, 
            text=round_text, 
            font=(self.font_family, 16),
            fg="#ffffff",
            bg="#0f3460"
        )
        round_label.pack(side="left", padx=20)
        
        # 实时炸弹倒计时标签
        self.bomb_timer_label = tk.Label(
            top_frame,
            text="",
            font=(self.font_family, 16),
            fg="#ff5722",
            bg="#0f3460"
        )
        self.bomb_timer_label.pack(side="left", padx=20)
        
        # 实时氧气倒计时标签
        self.oxygen_timer_label = tk.Label(
            top_frame,
            text="",
            font=(self.font_family, 16),
            fg="#ffcc00",
            bg="#0f3460"
        )
        self.oxygen_timer_label.pack(side="left", padx=20)
        
        # 启动炸弹倒计时更新
        self.update_bomb_timer()
        # 启动氧气倒计时更新
        self.update_oxygen_timer()
        
        # 显示当前玩家剩余紧急会议次数 + 位置限制提示（旁观玩家显示次数但无法使用）
        remaining_meetings = self.emergency_meeting_count.get(self.current_player.name, 0)
        meeting_label = tk.Label(
            top_frame,
            text=f"📢 紧急会议剩余次数：{remaining_meetings}/{self.max_emergency_meetings} | 仅{self.meeting_room}可发起",
            font=(self.font_family, 14),
            fg="#00ffff",
            bg="#0f3460"
        )
        meeting_label.pack(side="left", padx=20)
        
        # 玩家存活状态（显示所有玩家，死亡玩家标记👻）
        status_frame = tk.Frame(top_frame, bg="#0f3460")
        status_frame.pack(side="right", padx=20)
        
        status_label = tk.Label(
            status_frame, 
            text="所有玩家状态:", 
            font=(self.font_family, 12),
            fg="#ffffff",
            bg="#0f3460"
        )
        status_label.pack(side="left")
        
        for player in self.all_players_list:
            status = "🔵" if player.is_alive else "🔴"
            # 旁观玩家额外标记
            if player in self.spectator_players:
                status += "👻"
            player_status = tk.Label(
                status_frame, 
                text=f"{status}{player.name}", 
                font=(self.font_family, 10),
                fg="#ffffff",
                bg="#0f3460"
            )
            player_status.pack(side="left", padx=5)
            # 保存引用
            self.player_labels[player.name] = player_status
        
        # 中间内容区域
        content_frame = tk.Frame(self.game_frame, bg="#16213e")
        content_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # 左侧地图区域
        map_container = tk.Frame(content_frame, bg="#16213e")
        map_container.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        # 核心：固定四行显示当前视角房间的玩家（飞船大厅超过3人时使用3-3-3布局）
        self.room_mates_label = tk.Label(
            map_container,
            text=self.get_room_mates_text(),
            font=(self.font_family, 12),
            fg="#00ffff",
            bg="#16213e",
            justify="left",
            wraplength=780,
            anchor="nw",
            height=4  # 固定4行高度，适应3-3-3布局
        )
        self.room_mates_label.pack(pady=(0, 5), fill="x")
        
        # 原有地图框架
        map_frame = tk.LabelFrame(map_container, text="飞船地图", bg="#1a1a2e", fg="#ffffff", font=(self.font_family, 12))
        map_frame.pack(fill="both", expand=True)
        
        # 绘制简单的地图
        self.draw_map(map_frame)
        
        # 右侧信息区域
        info_frame = tk.LabelFrame(content_frame, text="游戏信息", bg="#1a1a2e", fg="#ffffff", font=(self.font_family, 12))
        info_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        
        # 当前玩家信息
        player_info_frame = tk.Frame(info_frame, bg="#1a1a2e")
        player_info_frame.pack(fill="x", padx=10, pady=10)
        
        player_info_label = tk.Label(
            player_info_frame, 
            text=f"当前玩家: {self.current_player.name}", 
            font=(self.font_family, 14, "bold"),
            fg="#ffffff",
            bg="#1a1a2e"
        )
        player_info_label.pack(pady=5)
        
        # 显示存活状态
        if self.current_player in self.spectator_players:
            # 检查尸体是否已清理
            body_cleared = self.dead_player_locations.get(self.current_player.name, {}).get("cleared", False)
            if body_cleared:
                alive_status = f"🔴 死亡（旁观）| 你的尸体已被清理"
            else:
                alive_status = f"🔴 死亡（旁观）| 尸体位置：{self.current_player.current_location}"
            
            status_label = tk.Label(
                player_info_frame,
                text=alive_status,
                font=(self.font_family, 12),
                fg="#ff0000",
                bg="#1a1a2e"
            )
            status_label.pack(pady=5)
            
            # 显示当前旁观视角位置
            view_status = f"当前查看房间：{self.spectator_view_room or self.current_player.current_location}"
            view_label = tk.Label(
                player_info_frame,
                text=view_status,
                font=(self.font_family, 12),
                fg="#00ffff",
                bg="#1a1a2e"
            )
            view_label.pack(pady=5)
        else:
            alive_status = "🟢 存活" if self.current_player.is_alive else "🔴 死亡"
            status_label = tk.Label(
                player_info_frame,
                text=f"状态: {alive_status}",
                font=(self.font_family, 12),
                fg="#00ff00" if self.current_player.is_alive else "#ff0000",
                bg="#1a1a2e"
            )
            status_label.pack(pady=5)
            
            location_label = tk.Label(
                player_info_frame, 
                text=f"当前位置: {self.current_player.current_location}", 
                font=(self.font_family, 12),
                fg="#4caf50",
                bg="#1a1a2e"
            )
            location_label.pack(pady=5)
        
        # 显示当前玩家剩余步数（死亡玩家也显示，但无法使用，联机模式下不显示）
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
            steps_label = tk.Label(
                player_info_frame, 
                text=f"剩余行动步数: {self.max_steps - self.action_steps + 1}", 
                font=(self.font_family, 12),
                fg="#ffcc00",
                bg="#1a1a2e"
            )
            steps_label.pack(pady=5)
        
        # 显示船员常规任务进度（死亡船员也显示）
        if isinstance(self.current_player.role, Crewmate):
            progress = f"{self.current_player.completed_tasks}/3"
            progress_label = tk.Label(
                player_info_frame,
                text=f"常规任务进度: {progress}",
                font=(self.font_family, 12),
                fg="#00ff00",
                bg="#1a1a2e"
            )
            progress_label.pack(pady=5)
        
        # 行动按钮区域
        action_frame = tk.Frame(info_frame, bg="#1a1a2e")
        action_frame.pack(fill="x", padx=10, pady=10)
        
        # ========== 旁观模式：禁用所有操作按钮，仅视角移动 ==========
        if self.current_player in self.spectator_players:
            # 旁观模式提示
            spectator_label = tk.Label(
                action_frame,
                text="👻 你已死亡，进入旁观模式",
                font=(self.font_family, 14, "bold"),
                fg="#ffcc00",
                bg="#1a1a2e"
            )
            spectator_label.pack(fill="x", pady=10)
            
            # 提示尸体状态
            body_cleared = self.dead_player_locations.get(self.current_player.name, {}).get("cleared", False)
            if body_cleared:
                body_label = tk.Label(
                    action_frame,
                    text=f"⚠️ 你的尸体已被清理！",
                    font=(self.font_family, 12),
                    fg="#ff6666",
                    bg="#1a1a2e"
                )
            else:
                body_label = tk.Label(
                    action_frame,
                    text=f"⚠️ 你的尸体将永久停留在：{self.current_player.current_location}",
                    font=(self.font_family, 12),
                    fg="#ff6666",
                    bg="#1a1a2e"
                )
            body_label.pack(fill="x", pady=5)
            
            # 旁观专用：视角移动（仅改变查看房间，不移动尸体）
            move_label = tk.Label(
                action_frame,
                text="旁观视角移动：可查看任意房间，尸体位置不变（清理后消失）",
                font=(self.font_family, 12),
                fg="#00ffff",
                bg="#1a1a2e"
            )
            move_label.pack(fill="x", pady=5)
            
            # 房间选择下拉框
            room_var = tk.StringVar(value=self.spectator_view_room or self.current_player.current_location)
            room_combobox = ttk.Combobox(
                action_frame,
                textvariable=room_var,
                values=self.all_rooms,
                state="readonly",
                font=(self.font_family, 10),
                width=20
            )
            room_combobox.pack(fill="x", pady=5)
            
            # 视角移动按钮（仅改变视角，不移动玩家本体）
            def spectator_move_view():
                target_room = room_var.get()
                self.spectator_view_room = target_room
                body_status = "（尸体已清理）" if body_cleared else f"（尸体仍在{self.current_player.current_location}）"
                self.add_log(f"👻 {self.current_player.name}(旁观)切换视角到{target_room} {body_status}")
                self.create_game_frame()
            
            # 为所有平台创建兼容的按钮
            if sys.platform == 'darwin':
                # Mac上使用ttk按钮
                move_btn = ttk.Button(
                    action_frame,
                    text="切换到选中房间视角", 
                    style="Move.TButton",
                    command=spectator_move_view
                )
                style = ttk.Style()
                style.configure("Move.TButton", 
                              font=(self.font_family, 10),
                              padding=(5, 3),
                              background="#0F3460",
                              foreground="#FFFFFF")
                style.map("Move.TButton",
                      background=[("active", "#0A2647"),("!active", "#0F3460")],
                      foreground=[("active", "#E3F2FD"),("!active", "#FFFFFF")])
            else:
                # Windows上使用普通按钮
                move_btn = tk.Button(
                    action_frame,
                    text="切换到选中房间视角",
                    font=(self.font_family, 10),
                    bg="#0f3460",
                    fg="#ffffff",
                    bd=2,
                    relief="flat",
                    command=spectator_move_view
                )
            move_btn.pack(fill="x", pady=5)
            
            # 禁用所有操作按钮的提示
            disabled_label = tk.Label(
                action_frame,
                text="⚠️ 旁观模式下无法执行任何游戏操作，仅可查看",
                font=(self.font_family, 12),
                fg="#ff0000",
                bg="#1a1a2e"
            )
            disabled_label.pack(fill="x", pady=10)
        else:
            # ========== 存活玩家：正常显示操作按钮 ==========
            # 紧急会议按钮（仅飞船大厅+剩余次数>0可用）
            remaining_meetings = self.emergency_meeting_count.get(self.current_player.name, 0)
            is_in_meeting_room = self.current_player.current_location == self.meeting_room
            
            # 检查紧急会议是否被禁用（炸弹在飞船大厅爆炸后）
            if self.emergency_ban_rounds > 0:
                # 显示冷却中标签
                emergency_cooldown_label = tk.Label(
                    action_frame,
                    text=f"⚠️ 紧急会议禁用中: {self.emergency_ban_rounds}回合",
                    font=(self.font_family, 12),
                    fg="#ff0000",
                    bg="#1a1a2e"
                )
                emergency_cooldown_label.pack(fill="x", pady=5)
                
                # 创建进度条样式的冷却显示
                cooldown_bar_frame = tk.Frame(action_frame, bg="#1a1a2e")
                cooldown_bar_frame.pack(fill="x", pady=2)
                
                # 冷却进度条背景
                progress_bg = tk.Frame(cooldown_bar_frame, bg="#333333", height=8)
                progress_bg.pack(fill="x", padx=20)
                progress_bg.pack_propagate(False)
                
                # 冷却进度条前景（根据禁用回合数计算进度）
                ban_progress = 1 - (self.emergency_ban_rounds / 2)  # 2回合总禁
                progress_fg = tk.Frame(progress_bg, bg="#ff5722", height=8)
                # 使用place设置进度条宽度，避免pack不支持width参数的问题
                progress_bg.update_idletasks()  # 确保背景已渲染
                bar_width = int(progress_bg.winfo_width() * ban_progress)
                progress_fg.place(x=0, y=0, width=bar_width, height=8)
            elif remaining_meetings > 0 and is_in_meeting_room:
                meeting_btn_state = "normal"
                meeting_btn_bg = "#ff9800"
                meeting_btn_text = f"发起紧急会议（剩余{remaining_meetings}次）"
            else:
                meeting_btn_state = "disabled"
                meeting_btn_bg = "#666666"
                if remaining_meetings <= 0:
                    meeting_btn_text = "发起紧急会议（次数已用尽）"
                else:
                    meeting_btn_text = f"发起紧急会议（仅{self.meeting_room}可发起）"
            
            # 为所有平台创建兼容的按钮（紧急会议未禁用时）
            if self.emergency_ban_rounds > 0:
                # 禁用状态下不创建按钮（已在上方创建冷却显示）
                pass
            elif sys.platform == 'darwin':
                # Mac上使用ttk按钮
                emergency_meeting_btn = ttk.Button(
                    action_frame,
                    text=meeting_btn_text, 
                    style="Emergency.TButton",
                    state=meeting_btn_state,
                    command=lambda: self.handle_emergency_meeting(self.current_player)
                )
                style = ttk.Style()
                if meeting_btn_state == "normal":
                    style.configure("Emergency.TButton", 
                                  font=(self.font_family, 12),
                                  padding=(10, 5),
                                  background="#FF9800",
                                  foreground="#FFFFFF")
                    style.map("Emergency.TButton",
                      background=[("active", "#F57C00"),("!active", "#FF9800")],
                      foreground=[("active", "#FFF3E0"),("!active", "#FFFFFF")])
                else:
                    style.configure("Emergency.TButton", 
                                  font=(self.font_family, 12),
                                  padding=(10, 5),
                                  background="#CCCCCC",
                                  foreground="#999999")
                    style.map("Emergency.TButton",
                      background=[("active", "#BBBBBB"),("!active", "#CCCCCC")],
                      foreground=[("active", "#666666"),("!active", "#999999")])
            else:
                # Windows上使用普通按钮
                emergency_meeting_btn = tk.Button(
                    action_frame,
                    text=meeting_btn_text,
                    font=(self.font_family, 12),
                    bg=meeting_btn_bg,
                    fg="#ffffff",
                    padx=10,
                    pady=5,
                    width=15,
                    bd=2,
                    relief="flat",
                    state=meeting_btn_state,
                    command=lambda: self.handle_emergency_meeting(self.current_player)
                )
            # 仅在按钮存在时_pack
            if self.emergency_ban_rounds <= 0:
                emergency_meeting_btn.pack(fill="x", pady=5)
            
            # 根据角色显示不同按钮
            if isinstance(self.current_player.role, Crewmate):
                # 检查是否在监控室且监控被破坏
                in_monitor_room = self.current_player.current_location == "监控室"
                monitor_broken = getattr(self, 'monitor_sabotaged', False)
                in_bomb_room = self.bomb_location and self.current_player.current_location == self.bomb_location
                
                # 检查是否在废墟房间
                current_room = self.current_player.current_location
                is_ruined = self.ruined_rooms.get(current_room, False)
                is_cleaned = self.ruin_cleaned.get(current_room, True)
                
                # 步数超限检查（联机模式下不检查）
                if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
                    task_label = tk.Label(
                        action_frame, 
                        text="⚠️ 行动步数已达上限", 
                        font=(self.font_family, 12),
                        fg="#ff0000",
                        bg="#1a1a2e"
                    )
                    task_label.pack(fill="x", pady=5)
                else:
                    # 清理废墟任务最优先
                    if is_ruined and not is_cleaned:
                        task_text = "🏚️ 清理废墟"
                        task_command = self.handle_clean_ruins
                        task_bg = "#795548"
                    # 拆弹任务优先（当玩家在有炸弹的房间时）
                    elif in_bomb_room and self.bomb_location:
                        task_text = "💣 拆弹任务"
                        task_command = self.handle_defuse_bomb
                        task_bg = "#ff4444"
                    elif in_monitor_room and monitor_broken:
                        task_text = "修复监控"
                        task_command = self.handle_repair_monitor
                        task_bg = "#4caf50"
                    else:
                        task_text = "完成任务"
                        task_command = lambda: self.handle_complete_task(self.current_player)
                        task_bg = "#4caf50"
                    
                    if sys.platform == 'darwin':
                        task_button = ttk.Button(
                            action_frame, 
                            text=task_text, 
                            style="Task.TButton",
                            command=task_command
                        )
                        style = ttk.Style()
                        style.configure("Task.TButton", 
                                      font=(self.font_family, 12),
                                      padding=(10, 5),
                                      background=task_bg,
                                      foreground="#FFFFFF")
                        style.map("Task.TButton",
                                      background=[("active", "#388E3C"),("!active", task_bg)],
                                      foreground=[("active", "#E8F5E9"),("!active", "#FFFFFF")])
                    else:
                        task_button = tk.Button(
                            action_frame, 
                            text=task_text, 
                            font=(self.font_family, 12),
                            bg=task_bg,
                            fg="#ffffff",
                            padx=10,
                            pady=5,
                            width=15,
                            bd=2,
                            relief="flat",
                            command=task_command
                        )
                    task_button.pack(fill="x", pady=5)
            elif isinstance(self.current_player.role, Impostor):
                # 内鬼穿梭按钮 - 联机模式使用实时计时
                is_multiplayer = hasattr(self, 'is_multiplayer') and self.is_multiplayer
                
                if is_multiplayer:
                    # 联机模式：检查实时冷却
                    shuttle_cooldown = self.current_player.role.current_shuttle_cooldown_seconds
                    if shuttle_cooldown > 0:
                        # 冷却中显示计时
                        minutes = shuttle_cooldown // 60
                        seconds = shuttle_cooldown % 60
                        self.shuttle_cooldown_label = tk.Label(
                            action_frame, 
                            text=f"⏱️ 穿梭冷却: {minutes:02d}:{seconds:02d}", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e",
                            relief="solid",
                            bd=1
                        )
                        self.shuttle_cooldown_label.pack(fill="x", pady=5)
                    else:
                        # 可用状态
                        if sys.platform == 'darwin':
                            teleport_button = ttk.Button(
                                action_frame, 
                                text="穿梭", 
                                style="Teleport.TButton",
                                command=lambda: self.teleport_to_room(self.current_player)
                            )
                            style = ttk.Style()
                            style.configure("Teleport.TButton", 
                                          font=(self.font_family, 12),
                                          padding=(10, 5),
                                          background="#00FFFF",
                                          foreground="#000000")
                        else:
                            teleport_button = tk.Button(
                                action_frame, 
                                text="穿梭", 
                                font=(self.font_family, 12),
                                bg="#00ffff",
                                fg="#000000",
                                padx=10,
                                pady=5,
                                width=15,
                                bd=2,
                                relief="flat",
                                command=lambda: self.teleport_to_room(self.current_player)
                            )
                        teleport_button.pack(fill="x", pady=5)
                else:
                    # 单机模式：使用回合制
                    teleport_state = "normal"
                    teleport_bg = "#00ffff"
                    teleport_fg = "#000000"
                    teleport_text = "穿梭"
                    
                    # 冷却中禁用
                    if self.current_player.name in self.impostor_teleport_cooldown:
                        teleport_state = "disabled"
                        teleport_bg = "#666666"
                        teleport_fg = "#ffffff"
                        teleport_text = f"穿梭（冷却{self.impostor_teleport_cooldown[self.current_player.name]}回合）"
                    # 步数超限禁用
                    elif self.action_steps > self.max_steps:
                        teleport_state = "disabled"
                        teleport_bg = "#666666"
                        teleport_fg = "#ffffff"
                        teleport_text = "穿梭（步数已达上限）"
                    
                    if sys.platform == 'darwin':
                        teleport_button = ttk.Button(
                            action_frame, 
                            text=teleport_text, 
                            style="Teleport.TButton",
                            state=teleport_state,
                            command=lambda: self.teleport_to_room(self.current_player)
                        )
                        style = ttk.Style()
                        if teleport_state == "normal":
                            style.configure("Teleport.TButton", 
                                          font=(self.font_family, 12),
                                          padding=(10, 5),
                                          background="#00FFFF",
                                          foreground="#000000")
                        else:
                            style.configure("Teleport.TButton", 
                                          font=(self.font_family, 12),
                                          padding=(10, 5),
                                          background="#CCCCCC",
                                          foreground="#999999")
                    else:
                        teleport_button = tk.Button(
                            action_frame, 
                            text=teleport_text, 
                            font=(self.font_family, 12),
                            bg=teleport_bg,
                            fg=teleport_fg,
                            padx=10,
                            pady=5,
                            width=15,
                            bd=2,
                            relief="flat",
                            state=teleport_state,
                            command=lambda: self.teleport_to_room(self.current_player)
                        )
                    teleport_button.pack(fill="x", pady=5)
                
                # 内鬼击杀判定 - 联机模式使用实时计时
                if is_multiplayer:
                    # 联机模式：检查实时冷却
                    kill_cooldown = self.current_player.role.current_kill_cooldown_seconds
                    if kill_cooldown > 0:
                        # 冷却中显示计时
                        minutes = kill_cooldown // 60
                        seconds = kill_cooldown % 60
                        self.kill_cooldown_label = tk.Label(
                            action_frame, 
                            text=f"⏱️ 击杀冷却: {minutes:02d}:{seconds:02d}", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e",
                            relief="solid",
                            bd=1
                        )
                        self.kill_cooldown_label.pack(fill="x", pady=5)
                    else:
                        # 可用状态
                        if sys.platform == 'darwin':
                            kill_button = ttk.Button(
                                action_frame, 
                                text="击杀船员", 
                                style="Kill.TButton",
                                command=lambda: self.handle_kill(self.current_player)
                            )
                            style = ttk.Style()
                            style.configure("Kill.TButton", 
                                          font=(self.font_family, 12),
                                          padding=(10, 5),
                                          background="#E94560",
                                          foreground="#FFFFFF")
                        else:
                            kill_button = tk.Button(
                                action_frame, 
                                text="击杀船员", 
                                font=(self.font_family, 12),
                                bg="#e94560",
                                fg="#ffffff",
                                padx=10,
                                pady=5,
                                width=15,
                                bd=2,
                                relief="flat",
                                command=lambda: self.handle_kill(self.current_player)
                            )
                        kill_button.pack(fill="x", pady=5)
                else:
                    # 单机模式：使用回合制
                    can_kill = self.current_player.role.current_kill_cooldown == 0 and self.global_round > 1
                    
                    if can_kill:
                        if self.action_steps > self.max_steps:
                            kill_label = tk.Label(
                                action_frame, 
                                text="⚠️ 行动步数已达上限", 
                                font=(self.font_family, 12),
                                fg="#ff0000",
                                bg="#1a1a2e"
                            )
                            kill_label.pack(fill="x", pady=5)
                        else:
                            if sys.platform == 'darwin':
                                kill_button = ttk.Button(
                                    action_frame, 
                                    text="击杀船员", 
                                    style="Kill.TButton",
                                    command=lambda: self.handle_kill(self.current_player)
                                )
                                style = ttk.Style()
                                style.configure("Kill.TButton", 
                                              font=(self.font_family, 12),
                                              padding=(10, 5),
                                              background="#E94560",
                                              foreground="#FFFFFF")
                            else:
                                kill_button = tk.Button(
                                    action_frame, 
                                    text="击杀船员", 
                                    font=(self.font_family, 12),
                                    bg="#e94560",
                                    fg="#ffffff",
                                    padx=10,
                                    pady=5,
                                    width=15,
                                    bd=2,
                                    relief="flat",
                                    command=lambda: self.handle_kill(self.current_player)
                                )
                            kill_button.pack(fill="x", pady=5)
                    elif self.global_round == 1:
                        notice_label = tk.Label(
                            action_frame, 
                            text=f"第一回合内鬼禁止击杀！", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e"
                        )
                        notice_label.pack(fill="x", pady=5)
                    else:
                        cooldown_label = tk.Label(
                            action_frame, 
                            text=f"击杀冷却中: {self.current_player.role.current_kill_cooldown}回合", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e"
                        )
                        cooldown_label.pack(fill="x", pady=5)
                
                # 破坏系统按钮 - 联机模式使用实时冷却
                is_multiplayer = hasattr(self, 'is_multiplayer') and self.is_multiplayer
                
                if is_multiplayer:
                    # 联机模式：检查实时冷却
                    sabotage_cooldown = self.current_player.role.current_sabotage_cooldown_seconds
                    if sabotage_cooldown > 0:
                        # 冷却中显示计时
                        minutes = sabotage_cooldown // 60
                        seconds = sabotage_cooldown % 60
                        self.sabotage_cooldown_label = tk.Label(
                            action_frame, 
                            text=f"⏱️ 破坏冷却: {minutes:02d}:{seconds:02d}", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e",
                            relief="solid",
                            bd=1
                        )
                        self.sabotage_cooldown_label.pack(fill="x", pady=5)
                    else:
                        # 可用状态
                        if sys.platform == 'darwin':
                            sabotage_button = ttk.Button(
                                action_frame, 
                                text="破坏系统", 
                                style="Sabotage.TButton",
                                command=lambda: self.handle_sabotage(self.current_player)
                            )
                            style = ttk.Style()
                            style.configure("Sabotage.TButton", 
                                          font=(self.font_family, 12),
                                          padding=(10, 5),
                                          background="#9C27B0",
                                          foreground="#FFFFFF")
                            style.map("Sabotage.TButton",
                                      background=[("active", "#7B1FA2"),("!active", "#9C27B0")],
                                      foreground=[("active", "#F3E5F5"),("!active", "#FFFFFF")])
                        else:
                            sabotage_button = tk.Button(
                                action_frame, 
                                text="破坏系统", 
                                font=(self.font_family, 12),
                                bg="#9c27b0",
                                fg="#ffffff",
                                padx=10,
                                pady=5,
                                width=15,
                                bd=2,
                                relief="flat",
                                command=lambda: self.handle_sabotage(self.current_player)
                            )
                        sabotage_button.pack(fill="x", pady=5)
                else:
                    # 单机模式：使用回合制
                    if self.sabotage_cooldown > 0:
                        # 冷却中显示状态
                        sabotage_cooldown_label = tk.Label(
                            action_frame, 
                            text=f"🔧 破坏系统冷却中 ({self.sabotage_cooldown}回合)", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e"
                        )
                        sabotage_cooldown_label.pack(fill="x", pady=5)
                    elif self.action_steps > self.max_steps:
                        sabotage_label = tk.Label(
                            action_frame, 
                            text="⚠️ 行动步数已达上限", 
                            font=(self.font_family, 12),
                            fg="#ff0000",
                            bg="#1a1a2e"
                        )
                        sabotage_label.pack(fill="x", pady=5)
                    else:
                        # 为所有平台创建兼容的按钮
                        if sys.platform == 'darwin':
                            # Mac上使用ttk按钮
                            sabotage_button = ttk.Button(
                                action_frame, 
                                text="破坏系统", 
                                style="Sabotage.TButton",
                                command=lambda: self.handle_sabotage(self.current_player)
                            )
                            style = ttk.Style()
                            style.configure("Sabotage.TButton", 
                                          font=(self.font_family, 12),
                                          padding=(10, 5),
                                          background="#9C27B0",
                                          foreground="#FFFFFF")
                            style.map("Sabotage.TButton",
                                      background=[("active", "#7B1FA2"),("!active", "#9C27B0")],
                                      foreground=[("active", "#F3E5F5"),("!active", "#FFFFFF")])
                        else:
                            # Windows上使用普通按钮
                            sabotage_button = tk.Button(
                                action_frame, 
                                text="破坏系统", 
                                font=(self.font_family, 12),
                                bg="#9c27b0",
                                fg="#ffffff",
                                padx=10,
                                pady=5,
                                width=15,
                                bd=2,
                                relief="flat",
                                command=lambda: self.handle_sabotage(self.current_player)
                            )
                        sabotage_button.pack(fill="x", pady=5)
                
                # 放置炸弹按钮 - 联机模式使用实时计时
                is_multiplayer = hasattr(self, 'is_multiplayer') and self.is_multiplayer
                
                if is_multiplayer:
                    # 联机模式：检查实时冷却
                    bomb_cooldown = self.current_player.role.current_bomb_cooldown_seconds
                    if bomb_cooldown > 0:
                        # 冷却中显示计时
                        minutes = bomb_cooldown // 60
                        seconds = bomb_cooldown % 60
                        self.bomb_cooldown_label = tk.Label(
                            action_frame, 
                            text=f"⏱️ 炸弹冷却: {minutes:02d}:{seconds:02d}", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e",
                            relief="solid",
                            bd=1
                        )
                        self.bomb_cooldown_label.pack(fill="x", pady=5)
                    else:
                        # 可用状态
                        if sys.platform == 'darwin':
                            bomb_button = ttk.Button(
                                action_frame, 
                                text="放置炸弹", 
                                style="Bomb.TButton",
                                command=lambda: self.handle_place_bomb(self.current_player)
                            )
                            style = ttk.Style()
                            style.configure("Bomb.TButton", 
                                          font=(self.font_family, 12),
                                          padding=(10, 5),
                                          background="#FF5722",
                                          foreground="#FFFFFF")
                        else:
                            bomb_button = tk.Button(
                                action_frame, 
                                text="放置炸弹", 
                                font=(self.font_family, 12),
                                bg="#ff5722",
                                fg="#ffffff",
                                padx=10,
                                pady=5,
                                width=15,
                                bd=2,
                                relief="flat",
                                command=lambda: self.handle_place_bomb(self.current_player)
                            )
                        bomb_button.pack(fill="x", pady=5)
                else:
                    # 单机模式：使用回合制
                    if self.current_player.role.current_bomb_cooldown == 0:
                        if self.action_steps > self.max_steps:
                            bomb_label = tk.Label(
                                action_frame, 
                                text="⚠️ 行动步数已达上限", 
                                font=(self.font_family, 12),
                                fg="#ff0000",
                                bg="#1a1a2e"
                            )
                            bomb_label.pack(fill="x", pady=5)
                        else:
                            if sys.platform == 'darwin':
                                bomb_button = ttk.Button(
                                    action_frame, 
                                    text="放置炸弹", 
                                    style="Bomb.TButton",
                                    command=lambda: self.handle_place_bomb(self.current_player)
                                )
                                style = ttk.Style()
                                style.configure("Bomb.TButton", 
                                              font=(self.font_family, 12),
                                              padding=(10, 5),
                                              background="#FF5722",
                                              foreground="#FFFFFF")
                                style.map("Bomb.TButton",
                                              background=[("active", "#E64A19"),("!active", "#FF5722")],
                                              foreground=[("active", "#FFF3E0"),("!active", "#FFFFFF")])
                            else:
                                bomb_button = tk.Button(
                                    action_frame, 
                                    text="放置炸弹", 
                                    font=(self.font_family, 12),
                                    bg="#ff5722",
                                    fg="#ffffff",
                                    padx=10,
                                    pady=5,
                                    width=15,
                                    bd=2,
                                    relief="flat",
                                    command=lambda: self.handle_place_bomb(self.current_player)
                                )
                            bomb_button.pack(fill="x", pady=5)
                    else:
                        bomb_cooldown_label = tk.Label(
                            action_frame, 
                            text=f"炸弹冷却中: {self.current_player.role.current_bomb_cooldown}回合", 
                            font=(self.font_family, 12),
                            fg="#ff9800",
                            bg="#1a1a2e"
                        )
                        bomb_cooldown_label.pack(fill="x", pady=5)
            
            # 报告尸体按钮（根据尸体清理状态和报告状态更新）
            has_body = False
            for player in self.game.players:
                if not player.is_alive and player.current_location == self.current_player.current_location:
                    # 检查尸体是否已清理或已报告
                    is_cleared = self.dead_player_locations.get(player.name, {}).get("cleared", False)
                    is_reported = self.reported_bodies.get(player.name) is not None
                    if not is_cleared and not is_reported:
                        has_body = True
                        break
            
            report_state = "disabled"
            report_bg = "#666666"
            
            can_report = has_body
            # 步数检查（联机模式下不检查）
            if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                can_report = can_report and not (self.action_steps > self.max_steps)
            
            if can_report:
                report_state = "normal"
                report_bg = "#ff9800"
            
            if sys.platform == 'darwin':
                report_button = ttk.Button(
                    action_frame, 
                    text="报告尸体", 
                    style="Report.TButton",
                    state=report_state,
                    command=lambda: self.handle_report(self.current_player)
                )
                style = ttk.Style()
                if report_state == "normal":
                    style.configure("Report.TButton", 
                                  font=(self.font_family, 12),
                                  padding=(10, 5),
                                  background="#FF9800",
                                  foreground="#FFFFFF")
                    style.map("Report.TButton",
                                  background=[("active", "#F57C00"),("!active", "#FF9800")],
                                  foreground=[("active", "#FFF3E0"),("!active", "#FFFFFF")])
                else:
                    style.configure("Report.TButton", 
                                  font=(self.font_family, 12),
                                  padding=(10, 5),
                                  background="#CCCCCC",
                                  foreground="#999999")
            else:
                report_button = tk.Button(
                    action_frame, 
                    text="报告尸体", 
                    font=(self.font_family, 12),
                    bg=report_bg,
                    fg="#ffffff",
                    padx=10,
                    pady=5,
                    width=15,
                    bd=2,
                    relief="flat",
                    state=report_state,
                    command=lambda: self.handle_report(self.current_player)
                )
            report_button.pack(fill="x", pady=5)
        
        # 结束回合/切换视角按钮（联机模式下不显示，死亡玩家显示切换视角）
        # 只有单机模式才显示结束回合按钮
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
            next_button_text = "切换旁观视角" if self.current_player in self.spectator_players else "结束回合"
            # 为所有平台创建兼容的按钮
            if sys.platform == 'darwin':
                # Mac上使用ttk按钮
                next_button = ttk.Button(
                    action_frame, 
                    text=next_button_text, 
                    style="Next.TButton",
                    command=self.switch_to_next_player
                )
                style = ttk.Style()
                style.configure("Next.TButton", 
                              font=(self.font_family, 12),
                              padding=(10, 5),
                              background="#795548",
                              foreground="#FFFFFF")
                style.map("Next.TButton",
                              background=[("active", "#5D4037"),("!active", "#795548")],
                              foreground=[("active", "#EFEBE9"),("!active", "#FFFFFF")])
            else:
                # Windows上使用普通按钮
                next_button = tk.Button(
                    action_frame, 
                    text=next_button_text, 
                    font=(self.font_family, 12),
                    bg="#795548",
                    fg="#ffffff",
                    padx=10,
                    pady=5,
                    width=15,
                    bd=2,
                    relief="flat",
                    command=self.switch_to_next_player
                )
            next_button.pack(fill="x", pady=5)
        else:
            # 联机模式下，死亡玩家可以切换旁观视角
            if self.current_player in self.spectator_players:
                next_button_text = "切换旁观视角"
                if sys.platform == 'darwin':
                    next_button = ttk.Button(
                        action_frame, 
                        text=next_button_text, 
                        style="Next.TButton",
                        command=self.switch_to_next_player
                    )
                    style = ttk.Style()
                    style.configure("Next.TButton", 
                                  font=(self.font_family, 12),
                                  padding=(10, 5),
                                  background="#795548",
                                  foreground="#FFFFFF")
                    style.map("Next.TButton",
                                  background=[("active", "#5D4037"),("!active", "#795548")],
                                  foreground=[("active", "#EFEBE9"),("!active", "#FFFFFF")])
                else:
                    next_button = tk.Button(
                        action_frame, 
                        text=next_button_text, 
                        font=(self.font_family, 12),
                        bg="#795548",
                        fg="#ffffff",
                        padx=10,
                        pady=5,
                        width=15,
                        bd=2,
                        relief="flat",
                        command=self.switch_to_next_player
                    )
                next_button.pack(fill="x", pady=5)
        
        # 查看监控按钮（仅监控室可用且监控未被破坏，且不在冷却中）
        is_in_monitor = self.current_player.current_location == "监控室" and self.current_player.is_alive and self.current_player not in self.spectator_players
        monitor_not_sabotaged = not getattr(self, 'monitor_sabotaged', False)
        
        # 判断是否在冷却中
        monitor_on_cooldown = False
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
            # 联机模式：所有玩家都使用实时冷却
            monitor_on_cooldown = self.current_player.role.current_monitor_cooldown_seconds > 0
        else:
            # 单机模式：使用回合制冷却
            monitor_on_cooldown = self.current_player.name in self.monitor_cooldown
        
        monitor_state = "normal" if (is_in_monitor and monitor_not_sabotaged and not monitor_on_cooldown) else "disabled"
        monitor_bg = "#ffd54f" if (is_in_monitor and monitor_not_sabotaged and not monitor_on_cooldown) else "#666666"
        monitor_fg = "#000000" if (is_in_monitor and monitor_not_sabotaged and not monitor_on_cooldown) else "#999999"
        
        monitor_text = "查看监控"
        if monitor_on_cooldown:
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                monitor_text = "查看监控（冷却中）"
            else:
                monitor_text = f"查看监控（冷却{self.monitor_cooldown[self.current_player.name]}回合）"
        elif not monitor_not_sabotaged:
            monitor_text = "查看监控（已破坏）"
        
        if sys.platform == 'darwin':
            monitor_button = ttk.Button(
                action_frame, 
                text=monitor_text, 
                style="Monitor.TButton",
                state=monitor_state,
                command=self.view_monitor
            )
            style = ttk.Style()
            if is_in_monitor and monitor_not_sabotaged and not monitor_on_cooldown:
                style.configure("Monitor.TButton", 
                              font=(self.font_family, 12),
                              padding=(10, 5),
                              background="#FFD54F",
                              foreground="#000000")
                style.map("Monitor.TButton",
                          background=[("active", "#FFC107"),("!active", "#FFD54F")],
                          foreground=[("active", "#000000"),("!active", "#000000")])
            else:
                style.configure("Monitor.TButton", 
                              font=(self.font_family, 12),
                              padding=(10, 5),
                              background="#CCCCCC",
                              foreground="#999999")
        else:
            monitor_button = tk.Button(
                action_frame, 
                text=monitor_text, 
                font=(self.font_family, 12),
                bg=monitor_bg,
                fg=monitor_fg,
                padx=10,
                pady=5,
                width=22,
                bd=2,
                relief="flat",
                state=monitor_state,
                command=self.view_monitor
            )
        monitor_button.pack(fill="x", pady=5)
        
        # 联机模式：显示监控冷却
        self.monitor_cooldown_label = None
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
            monitor_cooldown = self.current_player.role.current_monitor_cooldown_seconds
            if monitor_cooldown > 0:
                minutes = monitor_cooldown // 60
                seconds = monitor_cooldown % 60
                self.monitor_cooldown_label = tk.Label(
                    action_frame,
                    text=f"⏱️ 监控冷却: {minutes:02d}:{seconds:02d}",
                    font=(self.font_family, 12),
                    fg="#ffd54f",
                    bg="#1a1a2e",
                    relief="solid",
                    bd=1
                )
                self.monitor_cooldown_label.pack(fill="x", pady=5)
        
        # 底部日志区域
        log_frame = tk.LabelFrame(self.game_frame, text="游戏日志", bg="#1a1a2e", fg="#ffffff", font=(self.font_family, 12))
        log_frame.pack(fill="x", padx=20, pady=10)
        
        # 日志文本框
        self.log_text = tk.Text(
            log_frame, 
            height=5, 
            font=(self.font_family, 10),
            bg="#0f0f0f",
            fg="#ffffff",
            wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text.config(state="disabled")

    def view_monitor(self):
        """查看监控界面"""
        monitor_window = tk.Toplevel(self.root)
        monitor_window.title("监控室")
        monitor_window.geometry("900x700+410+140")
        monitor_window.configure(bg="#1a1a2e")
        monitor_window.transient(self.root)
        monitor_window.grab_set()
        
        # 监听窗口关闭事件，关闭时也设置冷却
        def on_monitor_window_close():
            set_monitor_cooldown()
            self.add_log(f"📡 {self.current_player.name}关闭了监控窗口，对所有存活玩家设置2回合冷却")
            monitor_window.destroy()
            self.create_game_frame()
        
        monitor_window.protocol("WM_DELETE_WINDOW", on_monitor_window_close)
        
        title_label = tk.Label(
            monitor_window,
            text="📡 监控室",
            font=(self.font_family, 20, "bold"),
            fg="#ffd54f",
            bg="#1a1a2e"
        )
        title_label.pack(pady=15)
        
        monitor_frame = tk.LabelFrame(
            monitor_window, 
            text="监控画面", 
            bg="#7f8c8d", 
            fg="#ffffff", 
            font=(self.font_family, 12),
            padx=10,
            pady=10
        )
        monitor_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        map_canvas = tk.Canvas(monitor_frame, width=800, height=550, bg="#0f0f0f", highlightthickness=0)
        map_canvas.pack(fill="both", expand=True)
        
        location_positions = {
            "飞船大厅": (400, 80),
            "电力室": (275, 380),
            "上升引擎室": (150, 80),
            "下降引擎室": (150, 380),
            "反应堆": (100, 230),
            "氧气室": (600, 80),
            "医疗室": (250, 230),
            "通讯室": (550, 380),
            "监控室": (700, 380),
            "燃料室": (400, 380),
            "主控室": (500, 280)
        }
        
        for location, connections in self.game.map.connections.items():
            x1, y1 = location_positions[location]
            for connected in connections:
                x2, y2 = location_positions[connected]
                if location < connected:
                    map_canvas.create_line(x1, y1, x2, y2, fill="#4a4a4a", width=3)
        
        detected_bodies = []
        
        for location, (x, y) in location_positions.items():
            is_bomb_room = self.bomb_location == location
            
            if is_bomb_room:
                map_canvas.create_rectangle(x-50, y-35, x+50, y+35,
                                          fill="#3d0000", outline="#ff0000", width=4)
                map_canvas.create_rectangle(x-40, y-25, x+40, y+25,
                                          fill="#1a1a2e", outline="#ff4444", width=2)
                map_canvas.create_text(x, y, text=f"💣{location}", fill="#ff4444",
                                     font=(self.font_family, 10, "bold"), anchor="center")
            else:
                map_canvas.create_rectangle(x-40, y-25, x+40, y+25,
                                          fill="#1a1a2e", outline="#3498db", width=2)
                map_canvas.create_text(x, y, text=location, fill="#ffffff",
                                     font=(self.font_family, 10), anchor="center")
            
            players_in_room = [p for p in self.game.players if p.current_location == location and p.is_alive]
            bodies_in_room = [p for p in self.game.players if p.current_location == location and not p.is_alive 
                             and not self.dead_player_locations.get(p.name, {}).get("cleared", False)
                             and self.reported_bodies.get(p.name) is None]
            
            for body in bodies_in_room:
                if body not in detected_bodies:
                    detected_bodies.append(body)
            
            if players_in_room:
                player_count = len(players_in_room)
                map_canvas.create_text(x, y+30, text=f"🟢 {player_count}", 
                                     fill="#00ff00", font=(self.font_family, 10))
            
            if bodies_in_room:
                body_count = len(bodies_in_room)
                map_canvas.create_text(x, y+45, text=f"🔴 {body_count}", 
                                     fill="#ff0000", font=(self.font_family, 10))
        
        def set_monitor_cooldown():
            """设置监控冷却（联机模式实时冷却45秒，单机模式2回合）"""
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                # 联机模式：给所有存活玩家设置实时冷却
                for player in self.game.players:
                    if player.is_alive and player not in self.spectator_players:
                        player.role.use_monitor()
                self.add_log(f"📡 {self.current_player.name}查看了监控，对所有存活玩家设置45秒冷却")
            else:
                # 单机模式：对所有存活玩家设置2回合冷却
                for player in self.game.players:
                    if player.is_alive and player not in self.spectator_players:
                        self.monitor_cooldown[player.name] = 2
                self.add_log(f"📡 {self.current_player.name}查看了监控，对所有存活玩家设置2回合冷却")
        
        def finish_viewing():
            set_monitor_cooldown()
            monitor_window.destroy()
            self.create_game_frame()
        
        def report_body_from_monitor():
            if not detected_bodies:
                messagebox.showwarning("警告", "监控画面中没有检测到尸体！", parent=monitor_window)
                return
            set_monitor_cooldown()
            if not hasattr(self, 'is_multiplayer') or not self.is_multiplayer:
                self.add_log(f"📡 {self.current_player.name}在监控室报告尸体，对所有存活玩家设置2回合冷却")
            
            if len(detected_bodies) == 1:
                victim = detected_bodies[0]
            else:
                body_window = tk.Toplevel(monitor_window)
                body_window.title("选择要报告的尸体")
                body_window.geometry("400x300+600+300")
                body_window.configure(bg="#1a1a2e")
                body_window.transient(monitor_window)
                body_window.grab_set()
                
                tk.Label(
                    body_window,
                    text="监控检测到多具尸体，请选择要报告的尸体：",
                    font=(self.font_family, 12),
                    fg="#ffffff",
                    bg="#1a1a2e"
                ).pack(pady=10)
                
                body_listbox = tk.Listbox(
                    body_window,
                    font=(self.font_family, 12),
                    bg="#0f3460",
                    fg="#ffffff",
                    selectbackground="#2196f3",
                    height=5
                )
                body_listbox.pack(padx=20, pady=10)
                
                for body in detected_bodies:
                    body_listbox.insert(tk.END, f"{body.name} ({body.current_location})")
                
                def confirm_report():
                    if body_listbox.curselection():
                        idx = body_listbox.curselection()[0]
                        victim = detected_bodies[idx]
                        body_window.destroy()
                        monitor_window.destroy()
                        self._execute_report(self.current_player, victim)
                    else:
                        messagebox.showwarning("警告", "请选择一具尸体！", parent=body_window)
                
                tk.Button(
                    body_window,
                    text="确认报告",
                    font=(self.font_family, 12),
                    bg="#4caf50",
                    fg="#ffffff",
                    padx=20,
                    pady=5,
                    command=confirm_report
                ).pack(pady=10)
                return
            
            monitor_window.destroy()
            self._execute_report(self.current_player, victim)
        
        button_frame = tk.Frame(monitor_window, bg="#1a1a2e")
        button_frame.pack(pady=15)
        
        has_body = len(detected_bodies) > 0
        
        report_state = "normal" if has_body else "disabled"
        report_bg = "#ff9800" if has_body else "#666666"
        report_fg = "#ffffff"
        report_text = f"报告尸体 ({len(detected_bodies)}具)" if has_body else "报告尸体 (无尸体)"
        
        report_button = tk.Button(
            button_frame,
            text=report_text,
            font=(self.font_family, 12),
            bg=report_bg,
            fg=report_fg,
            padx=20,
            pady=5,
            bd=2,
            relief="flat",
            state=report_state,
            command=report_body_from_monitor
        )
        report_button.pack(side="left", padx=10)
        
        finish_button = tk.Button(
            button_frame,
            text="完成查看",
            font=(self.font_family, 12),
            bg="#4caf50",
            fg="#ffffff",
            padx=20,
            pady=5,
            bd=2,
            relief="flat",
            command=finish_viewing
        )
        finish_button.pack(side="left", padx=10)

    def draw_map(self, parent_frame):
        """绘制高分辨率地图，旁观玩家可切换视角但尸体固定（清理后不显示尸体标记）"""
        # 创建一个容器框架来放置地图
        map_frame = tk.Frame(parent_frame, bg="#0f0f0f")
        map_frame.pack(fill="both", expand=True)
        
        # 创建一个Canvas作为背景，只用于绘制连接线
        canvas = tk.Canvas(map_frame, width=800, height=600, bg="#0f0f0f", highlightthickness=0)
        canvas.place(x=0, y=0)
        
        # 定义位置坐标
        location_positions = {
            "飞船大厅": (400, 100),
            "电力室": (275, 400),
            "上升引擎室": (150, 100),
            "下降引擎室": (150, 400),
            "反应堆": (100, 250),
            "氧气室": (600, 100),
            "医疗室": (250, 250),
            "通讯室": (550, 400),
            "监控室": (700, 400),
            "燃料室": (400, 400),
            "主控室": (500, 300)
        }
        
        # 绘制连接线
        for location, connections in self.game.map.connections.items():
            x1, y1 = location_positions[location]
            for connected in connections:
                x2, y2 = location_positions[connected]
                if location < connected:
                    canvas.create_line(x1, y1, x2, y2, fill="#4a4a4a", width=3)
        
        # 获取当前位置（旁观玩家用视角位置，正常玩家用物理位置）
        if self.current_player in self.spectator_players:
            current_location = self.spectator_view_room or self.current_player.current_location
        else:
            current_location = self.current_player.current_location
        
        available_moves = self.game.map.get_available_moves(current_location)
        
        # 创建按钮字典用于存储所有按钮
        self.location_buttons = {}
        
        # 创建舱室按钮
        for location, (x, y) in location_positions.items():
            # 检查该位置是否有未清理的尸体
            has_uncleared_body = False
            for player in self.game.players:
                if not player.is_alive and player.current_location == location:
                    if not self.dead_player_locations.get(player.name, {}).get("cleared", False):
                        has_uncleared_body = True
                        break
            
            # 检查当前视角/位置是否在该位置
            is_current = location == current_location
            # 检查该位置是否可移动
            can_move = location in available_moves
            
            # 根据状态设置按钮样式
            if is_current:
                bg_color = "#00ff00"
                fg_color = "#000000"
                state = "disabled"
            else:
                bg_color = "#0f3460"
                fg_color = "#ffffff"
                state = "normal" if can_move else "disabled"
            
            # 旁观玩家：所有房间按钮都可用（仅切换视角）
            if self.current_player in self.spectator_players:
                state = "normal"
            
            # 步数超限则禁用所有移动按钮（仅存活玩家，联机模式下不检查）
            if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                if not self.current_player in self.spectator_players and self.action_steps > self.max_steps and state == "normal":
                    state = "disabled"
                    bg_color = "#333333"
            
            # 为Mac平台调整颜色
            if sys.platform == 'darwin':
                if is_current:
                    bg_color = "#4CAF50"
                    fg_color = "#000000"
                elif state == "disabled":
                    bg_color = "#333333"
                    fg_color = "#888888"
                
                else:
                    bg_color = "#2196F3"
                    fg_color = "#FFFFFF"
                
                # 为每个按钮创建唯一样式名称
                style_name = f"Map.{location.replace(' ', '_')}.TButton"
                
                # 创建按钮框架 - 使用ttk.Frame
                button_frame = ttk.Frame(
                    map_frame,
                )
                button_frame.place(x=x-35, y=y-20, anchor="center")
                
                # 创建按钮 - Mac上使用ttk按钮
                button = ttk.Button(
                    button_frame, 
                    text=location,
                    style=style_name,
                    state=state,
                    command=lambda loc=location: self.on_location_click(loc)
                )
                # 为ttk按钮设置样式
                button_style = ttk.Style()
                button_style.configure(style_name, 
                              font=(self.font_family, 9, "bold"),
                              padding=(5, 2),
                              background=bg_color,
                              foreground=fg_color)
                if is_current:
                    button_style.map(style_name,
                              background=[("active", "#4CAF50"), ("disabled", "#4CAF50")],
                              foreground=[("active", "#FFFFFF"), ("disabled", "#FFFFFF")])
                elif state == "disabled":
                    button_style.map(style_name,
                              background=[("active", "#BBBBBB"), ("disabled", "#CCCCCC")],
                              foreground=[("active", "#666666"), ("disabled", "#999999")])
                else:
                    button_style.map(style_name,
                              background=[("active", "#1976D2"), ("!active", bg_color)],
                              foreground=[("active", fg_color), ("!active", fg_color)])
                button.pack(fill="both", expand=True)
            else:
                # Windows和其他平台保持原有样式
                button_frame = tk.Frame(
                    map_frame, 
                    bg=bg_color, 
                    width=50, 
                    height=50,
                    highlightbackground="#ffffff",
                    highlightthickness=2,
                    bd=0
                )
                button_frame.place(x=x-25, y=y-25, anchor="center")
                
                button = tk.Button(
                    button_frame, 
                    text=location, 
                    bg=bg_color,
                    fg=fg_color,
                    font=(self.font_family, 10, "bold"),
                    width=8,
                    height=2,
                    bd=0,
                    relief="flat",
                    state=state,
                    command=lambda loc=location: self.on_location_click(loc)
                )
                button.pack(fill="both", expand=True)
            
            # 存储按钮引用
            self.location_buttons[location] = button
            
            # 标记自己的尸体（如果未清理）
            if self.current_player in self.spectator_players and location == self.current_player.current_location:
                body_cleared = self.dead_player_locations.get(self.current_player.name, {}).get("cleared", False)
                if not body_cleared:
                    canvas.create_text(x, y+30, text="🪦", font=("Arial", 20), fill="#ff6666")

    def send_position_update(self, player_name, location):
        """发送位置更新到服务器"""
        if not hasattr(self, 'is_multiplayer') or not self.is_multiplayer:
            return
        
        # 更新自己的房间状态（房主）
        if self.room_state and player_name == my_name_from_args:
            self.room_state.update_player_location(player_name, location)
        
        try:
            if self.sync_socket:
                message = json.dumps({
                    'type': 'position_update',
                    'player_name': player_name,
                    'location': location
                })
                self.sync_socket.send((message + '\n').encode('utf-8'))
                print(f"📤 发送位置更新: {player_name} -> {location}")
        except Exception as e:
            print(f"❌ 发送位置更新失败: {e}")
    
    def start_sync_server(self):
        """启动位置同步服务器（房主端，在后台线程中运行，持续整个游戏期间）"""
        # 幂等保护：避免重复绑定同一端口（Linux 下会抛 Errno 98）
        if self.sync_server_started:
            print("📍 位置同步服务器已在运行，跳过重复启动")
            return
        self.sync_server_started = True

        import threading

        def sync_server_thread():
            sync_server_socket = None
            try:
                sync_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sync_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sync_port = sync_port_from_args
                sync_server_socket.bind(('0.0.0.0', sync_port))
                sync_server_socket.listen(8)
                print(f"📍 位置同步服务器已启动，端口: {sync_port}")

                # 启动定期广播线程
                threading.Thread(target=self.broadcast_room_state, daemon=True).start()

                while self.sync_running:
                    try:
                        sync_server_socket.settimeout(1.0)
                        client_socket, addr = sync_server_socket.accept()
                        client_socket.settimeout(None)
                        print(f"✅ 新同步客户端连接: {addr}")

                        # 发送初始房间状态
                        try:
                            if self.room_state:
                                state_message = self.room_state.to_json()
                                client_socket.send((state_message + '\n').encode('utf-8'))
                                print(f"📤 已发送初始房间状态给新客户端 {addr}")
                        except Exception as e:
                            print(f"发送初始状态失败: {e}")

                        self.sync_clients.append({'socket': client_socket, 'addr': addr})
                        threading.Thread(
                            target=self.handle_sync_client,
                            args=(client_socket,),
                            daemon=True
                        ).start()
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if self.sync_running:
                            print(f"同步服务器错误: {e}")
            except Exception as e:
                print(f"无法启动同步服务器: {e}")
            finally:
                if sync_server_socket is not None:
                    try:
                        sync_server_socket.close()
                    except Exception:
                        pass

        threading.Thread(target=sync_server_thread, daemon=True).start()

    def broadcast_room_state(self):
        """定期广播房间状态给所有同步客户端"""
        while self.sync_running:
            try:
                if self.room_state:
                    state_message = self.room_state.to_json()
                    for sync_client in self.sync_clients.copy():
                        try:
                            sync_client['socket'].send((state_message + '\n').encode('utf-8'))
                        except Exception:
                            # 移除失效的客户端
                            if sync_client in self.sync_clients:
                                self.sync_clients.remove(sync_client)
                time.sleep(0.5)  # 每500ms广播一次
            except Exception as e:
                print(f"广播状态线程错误: {e}")
                time.sleep(1)

    def handle_sync_client(self, client_socket):
        """处理单个同步客户端的消息（房主端）"""
        try:
            buffer = ""
            while self.sync_running:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break

                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            message = json.loads(line)
                            self.handle_sync_server_message(message, client_socket)
                        except json.JSONDecodeError:
                            print(f"无效的JSON同步消息: {line}")
        except Exception as e:
            print(f"同步客户端处理错误: {e}")
        finally:
            for sync_client in self.sync_clients.copy():
                if sync_client['socket'] == client_socket:
                    self.sync_clients.remove(sync_client)
                    break
            try:
                client_socket.close()
            except Exception:
                pass

    def handle_sync_server_message(self, message, sender_socket):
        """处理同步消息并转发给其他客户端（房主端中转）"""
        msg_type = message.get('type')
        print(f"📨 房主收到同步消息: {msg_type}")

        # 需要更新本地房间状态的消息类型
        if msg_type == 'position_update':
            player_name = message.get('player_name')
            location = message.get('location')
            if self.room_state and player_name:
                self.room_state.update_player_location(player_name, location)
        elif msg_type == 'sabotage':
            system = message.get('system')
            if self.room_state and system:
                self.room_state.set_sabotage(system, True)
        elif msg_type == 'repair_sabotage':
            system = message.get('system')
            if self.room_state and system:
                self.room_state.repair_sabotage(system)
        elif msg_type == 'place_bomb':
            location = message.get('location')
            explode_time = message.get('explode_time')
            if self.room_state and location:
                self.room_state.bomb_location = location
                self.room_state.bomb_explode_time = explode_time if explode_time else time.time() + 60
        elif msg_type == 'defuse_bomb':
            if self.room_state:
                self.room_state.clear_bomb()
        elif msg_type == 'complete_task':
            player_name = message.get('player_name')
            completed_tasks = message.get('completed_tasks', None)
            if self.room_state and player_name:
                if completed_tasks is not None:
                    self.room_state.tasks_completed[player_name] = completed_tasks
                else:
                    self.room_state.complete_task(player_name)
        elif msg_type == 'game_over':
            winner = message.get('winner')
            if self.room_state:
                self.room_state.set_game_over(winner)

        # 统一转发给除发送者外的所有其他客户端
        for sync_client in self.sync_clients:
            if sync_client['socket'] != sender_socket:
                try:
                    sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                except Exception:
                    pass  # 失效连接由广播线程/处理线程负责清理

    def start_sync_client(self):
        """启动位置同步客户端（在新线程中运行）"""
        if not hasattr(self, 'is_multiplayer') or not self.is_multiplayer:
            return
        
        import threading
        
        def sync_client_thread():
            import socket
            
            server_ip = server_ip_from_args
            sync_port = sync_port_from_args
            
            while self.sync_running:
                try:
                    self.sync_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sync_socket.connect((server_ip, sync_port))
                    print(f"✅ 已连接到位置同步服务器 {server_ip}:{sync_port}")
                    
                    self.sync_buffer = ""
                    while self.sync_running:
                        data = self.sync_socket.recv(1024).decode('utf-8')
                        if not data:
                            break
                        
                        self.sync_buffer += data
                        while '\n' in self.sync_buffer:
                            line, self.sync_buffer = self.sync_buffer.split('\n', 1)
                            try:
                                message = json.loads(line)
                                self.process_sync_message(message)
                            except json.JSONDecodeError:
                                print(f"无效的同步消息: {line}")
                except Exception as e:
                    print(f"同步客户端错误: {e}")
                    time.sleep(1)
        
        threading.Thread(target=sync_client_thread, daemon=True).start()
    
    def process_sync_message(self, message):
        """处理收到的同步消息"""
        msg_type = message.get('type')
        print(f"📥 收到同步消息: {msg_type}")
        
        if msg_type == 'room_state':
            # 处理房间状态更新
            if self.room_state:
                self.room_state.from_dict(message)
                # 更新游戏中的玩家位置
                for player_name, player_data in self.room_state.players.items():
                    for player in self.game.players:
                        if player.name == player_name and player.name != my_name_from_args:
                            player.current_location = player_data.get('location', '飞船大厅')
                            player.is_alive = player_data.get('is_alive', True)
                # 更新系统破坏状态
                self.oxygen_sabotaged = self.room_state.oxygen_sabotaged
                self.monitor_sabotaged = self.room_state.monitor_sabotaged
                # 更新氧气超时时间
                if self.room_state.oxygen_timeout:
                    self.oxygen_timeout = self.room_state.oxygen_timeout
                # 更新炸弹状态
                if self.room_state.bomb_location:
                    self.bomb_location = self.room_state.bomb_location
                else:
                    self.bomb_location = None
                print(f"✅ 已更新房间状态")
                # 在主线程中更新UI
                self.root.after(0, self.update_game_display)
        
        elif msg_type == 'position_update':
            player_name = message.get('player_name')
            location = message.get('location')
            
            # 更新其他玩家的位置
            for player in self.game.players:
                if player.name == player_name and player.name != my_name_from_args:
                    player.current_location = location
                    print(f"📥 收到位置更新: {player_name} -> {location}")
                    # 在主线程中更新UI（正确捕获变量）
                    self.root.after(0, self.update_game_display)
                    break
        
        elif msg_type == 'sabotage':
            system = message.get('system')
            player_name = message.get('player_name')
            
            # 更新系统破坏状态
            if system == 'oxygen':
                self.oxygen_sabotaged = True
                self.oxygen_sabotage_round = self.global_round
                self.oxygen_repaired = False
                # 从房间状态中获取氧气超时时间
                if self.room_state and self.room_state.oxygen_timeout:
                    self.oxygen_timeout = self.room_state.oxygen_timeout
                else:
                    self.oxygen_timeout = time.time() + 150  # 默认150秒
                # 向玩家显示通知
                def show_oxygen_notice():
                    messagebox.showinfo(
                        "系统警报", 
                        "⚠️ 氧气系统已被破坏！请尽快前往氧气室修复！"
                    )
                self.root.after(0, show_oxygen_notice)
                self.add_log(f"🔧 氧气系统被破坏！")
            elif system == 'monitor':
                self.monitor_sabotaged = True
                self.monitor_sabotage_round = self.global_round
                self.monitor_repaired = False
                # 监控系统破坏不显示通知
                self.add_log(f"🔧 监控系统被破坏！")
            
            # 更新房间状态
            if self.room_state:
                self.room_state.set_sabotage(system, True)
            
            # 更新UI
            self.root.after(0, self.create_game_frame)
        
        elif msg_type == 'repair_sabotage':
            system = message.get('system')
            player_name = message.get('player_name')
            
            # 更新系统修复状态
            if system == 'oxygen':
                self.oxygen_sabotaged = False
                self.oxygen_repaired = True
                self.oxygen_timeout = None  # 清除氧气超时时间
                self.add_log(f"✅ {player_name}修复了氧气系统！")
            elif system == 'monitor':
                self.monitor_sabotaged = False
                self.monitor_repaired = True
                self.add_log(f"✅ {player_name}修复了监控系统！")
            
            # 更新房间状态
            if self.room_state:
                self.room_state.repair_sabotage(system)
            
            # 更新UI - 重建游戏界面以正确显示按钮状态
            self.root.after(0, self.create_game_frame)
        
        elif msg_type == 'place_bomb':
            location = message.get('location')
            player_name = message.get('player_name')
            explode_time = message.get('explode_time')
            
            # 更新炸弹位置
            self.bomb_location = location
            self.add_log(f"💣 {player_name}在{location}放置了一颗炸弹！")
            
            # 更新房间状态
            if self.room_state:
                self.room_state.bomb_location = location
                if explode_time:
                    self.room_state.bomb_explode_time = explode_time
                else:
                    self.room_state.bomb_explode_time = time.time() + 60
            
            # 更新UI - 重建游戏界面以正确显示按钮状态
            self.root.after(0, self.create_game_frame)
        
        elif msg_type == 'defuse_bomb':
            player_name = message.get('player_name')
            
            # 更新炸弹状态
            self.bomb_location = None
            
            # 清除内鬼的炸弹数据
            for player in self.game.players:
                if isinstance(player.role, Impostor):
                    player.role.bomb_explode_time = None
            
            # 更新房间状态
            if self.room_state:
                self.room_state.clear_bomb()
            
            self.add_log(f"✅ {player_name}拆除了炸弹！")
            
            # 更新UI - 重建游戏界面以正确显示按钮状态
            self.root.after(0, self.create_game_frame)
        
        elif msg_type == 'complete_task':
            player_name = message.get('player_name')
            completed_tasks = message.get('completed_tasks', 0)
            
            # 更新其他玩家的任务完成情况
            for player in self.game.players:
                if player.name == player_name:
                    player.completed_tasks = completed_tasks
                    print(f"📥 同步任务完成信息: {player_name} 完成了 {completed_tasks} 个任务")
                    self.add_log(f"📢 {player_name}完成了常规任务！当前进度：{completed_tasks}/3")
                    break
            
            # 更新任务列表显示
            self.root.after(0, self.update_task_list)
            
            # 更新UI - 重建游戏界面以显示最新任务进度
            self.root.after(0, self.create_game_frame)
        
        elif msg_type == 'game_over':
            winner = message.get('winner')
            reason = message.get('reason', '')
            
            print(f"📥 收到游戏结束消息: {winner}, 原因: {reason}")
            
            # 更新游戏状态
            self.game.winner = winner
            self.game.game_over = True
            
            # 在主线程中显示游戏结束界面
            def show_game_over_ui():
                self.show_game_over()
            
            self.root.after(0, show_game_over_ui)
    
    def broadcast_game_over(self, winner="unknown", reason="unknown"):
        """广播游戏结束消息给所有玩家"""
        if hasattr(self, 'is_multiplayer') and self.is_multiplayer and hasattr(self, 'sync_socket') and self.sync_socket:
            try:
                game_over_msg = json.dumps({
                    "type": "game_over",
                    "winner": winner,
                    "reason": reason
                })
                self.sync_socket.send((game_over_msg + '\n').encode('utf-8'))
                print(f"✓ 已发送游戏结束广播: {winner}, 原因: {reason}")
            except Exception as e:
                print(f"发送游戏结束广播失败: {e}")
    
    def update_game_display(self):
        """更新游戏显示（用于位置同步后刷新UI - 只更新内容不重建界面）"""
        print("🔄 更新游戏界面显示（不重建）")
        
        # 只更新房间内玩家显示（安全检查）
        try:
            if self.room_mates_label and self.room_mates_label.winfo_exists():
                self.room_mates_label.config(text=self.get_room_mates_text())
        except tk.TclError:
            print("⚠️ room_mates_label已失效，跳过更新")
            return
        
        # 更新玩家状态Label（安全检查）
        for player in self.all_players_list:
            if player.name in self.player_labels:
                try:
                    if self.player_labels[player.name].winfo_exists():
                        status = "🔵" if player.is_alive else "🔴"
                        if player in self.spectator_players:
                            status += "👻"
                        self.player_labels[player.name].config(text=f"{status}{player.name}")
                except tk.TclError:
                    pass
    
    def on_location_click(self, location):
        """处理舱室按钮点击事件（旁观玩家仅切换视角，尸体固定）"""
        current_player = self.current_player
        
        # 旁观玩家：仅切换视角，不移动尸体/玩家本体
        if current_player in self.spectator_players:
            self.spectator_view_room = location
            body_cleared = self.dead_player_locations.get(current_player.name, {}).get("cleared", False)
            body_status = "（尸体已清理）" if body_cleared else f"（尸体仍在{current_player.current_location}）"
            self.add_log(f"👻 {current_player.name}(旁观)切换视角到{location} {body_status}")
            self.create_game_frame()
            return
        
        # 执行移动（消耗步数）
        if self.add_action_step():
            old_location = current_player.current_location
            current_player.move(location)
            self.add_log(f"{current_player.name}移动到了{location}")
            
            # 发送位置更新到服务器（联机模式）
            self.send_position_update(current_player.name, location)
            
            # 重新绘制地图以更新状态
            self.create_game_frame()

    def create_task_list(self):
        """创建任务列表显示区域（旁观模式显示所有玩家信息）"""
        task_frame = tk.Frame(self.game_frame, bg="#1a1a2e")
        task_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 任务标题
        task_label = tk.Label(
            task_frame, 
            text="任务列表 / 旁观信息", 
            font=(self.font_family, 14, "bold"),
            fg="#e94560",
            bg="#1a1a2e"
        )
        task_label.pack(pady=5)
        
        # 任务列表框
        self.task_listbox = tk.Listbox(
            task_frame,
            font=(self.font_family, 12),
            bg="#0f3460",
            fg="#ffffff",
            selectbackground="#e94560",
            width=30,
            height=8
        )
        self.task_listbox.pack(fill="both", expand=True, pady=5)
        
        # 更新任务列表
        self.update_task_list()
    
    def update_task_list(self):
        """更新任务列表显示（旁观模式显示所有玩家信息）"""
        if not hasattr(self, 'task_listbox'):
            return
        
        self.task_listbox.delete(0, tk.END)
        current_player = self.current_player
        
        # 旁观模式：显示所有玩家的完整信息 + 尸体状态
        if current_player in self.spectator_players:
            self.task_listbox.insert(tk.END, "👻 旁观视角 - 所有玩家信息")
            self.task_listbox.insert(tk.END, "────────────────────")
            
            # 显示每个玩家的详细信息
            for p in self.all_players_list:
                role_name = p.role.__class__.__name__
                status = "🟢存活" if p.is_alive else "🔴死亡"
                if p in self.spectator_players:
                    body_cleared = self.dead_player_locations.get(p.name, {}).get("cleared", False)
                    if body_cleared:
                        status += f"👻旁观 | 尸体已清理"
                    else:
                        status += f"👻旁观 | 尸体位置：{p.current_location}"
                
                # 船员显示任务进度，内鬼显示身份
                if isinstance(p.role, Crewmate):
                    task_info = f"任务进度: {p.completed_tasks}/3"
                    self.task_listbox.insert(tk.END, f"{p.name}: {role_name} {status} | {task_info}")
                else:
                    self.task_listbox.insert(tk.END, f"{p.name}: {role_name} {status}")
            
            # 显示氧气系统状态（仅对船员显示）
            self.task_listbox.insert(tk.END, "────────────────────")
            if isinstance(current_player.role, Crewmate):
                if self.oxygen_sabotaged and not self.oxygen_repaired:
                    self.task_listbox.insert(tk.END, "⚠️ 氧气系统已破坏！请立即修复！")
                    self.task_listbox.itemconfig(self.task_listbox.size() - 1, fg="#ff0000")
                else:
                    self.task_listbox.insert(tk.END, "✅ 氧气系统正常")
            return
        
        # 正常模式：显示当前玩家的任务
        # 核心修改2：氧气破坏时添加临时任务，修复后移除
        if self.oxygen_sabotaged and not self.oxygen_repaired and isinstance(current_player.role, Crewmate):
            self.task_listbox.insert(tk.END, "🚨 临时紧急任务：修复氧气系统 (氧气室)")
            self.task_listbox.insert(tk.END, "────────────────────")
            # 标记紧急任务行
            self.task_listbox.itemconfig(0, fg="#ff0000")
        
        # 仅显示常规任务（固定3个）
        if hasattr(current_player, 'tasks') and current_player.tasks:
            task_count = 0
            for task in current_player.tasks:
                if task_count >= 3:
                    break
                status = "✓" if task.is_completed else "✗"
                difficulty_stars = "★" * getattr(task, 'difficulty', 1)
                self.task_listbox.insert(tk.END, f"{status} 常规任务：{task.name} ({task.location}) {difficulty_stars}")
                task_count += 1
        else:
            self.task_listbox.insert(tk.END, "无常规任务")
    
    def handle_complete_task(self, player):
        """
        处理玩家完成任务的核心函数
        - 优先处理临时氧气修复任务（不占用常规任务数）
        - 常规任务仅需完成3个即可获胜
        - 集成新版氧气管道修复任务
        """
        # 旁观玩家无法完成任务
        if player in self.spectator_players:
            messagebox.showwarning("旁观限制", "❌ 旁观模式下无法完成任务！")
            return
        
        # 步数超限检查（联机模式下不检查）
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
            if self.action_steps > self.max_steps:
                messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法完成任务")
                return
        
        # 紧急氧气修复任务优先级处理
        current_loc = player.current_location.replace("室", "").replace("区", "").replace("房", "")
        if self.oxygen_sabotaged and not self.oxygen_repaired and isinstance(player.role, Crewmate) and current_loc == "氧气":
            confirm = messagebox.askyesno("紧急任务", "🚨 氧气系统已被破坏！是否立即修复氧气系统？\n(临时任务，不占用3个常规任务数量)", parent=self.root)
            if confirm:
                oxygen_task = OxygenRepairTask()
                task_completed = oxygen_task.run_task_gui(main_root=self.root)
                
                if task_completed:
                    # 先更新状态
                    self.oxygen_repaired = True
                    self.oxygen_sabotaged = False
                    self.oxygen_timeout = None  # 清除氧气超时时间
                    self.add_log(f"🚨 {player.name}完成临时紧急任务：修复了被破坏的氧气系统！")
                    
                    if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                        self.action_steps += 1
                    
                    # 联机模式：发送修复同步消息并更新房间状态
                    if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                        # 更新房间状态
                        if self.room_state:
                            self.room_state.repair_sabotage("oxygen")
                        # 发送同步消息给其他客户端
                        if self.sync_socket:
                            try:
                                repair_msg = json.dumps({
                                    "type": "repair_sabotage",
                                    "system": "oxygen",
                                    "player_name": player.name
                                })
                                self.sync_socket.send((repair_msg + '\n').encode('utf-8'))
                            except Exception as e:
                                print(f"发送修复氧气消息失败: {e}")
                    
                    # 更新任务列表
                    self.update_task_list()
                    
                    # 显示成功提示
                    messagebox.showinfo("任务完成", "✅ 成功修复氧气系统！\n临时紧急任务已完成，不影响常规任务进度", parent=self.root)
                    
                    # 确保在主线程中刷新界面，立即反映状态变化
                    def refresh_ui():
                        self.create_game_frame()
                    
                    # 使用after确保界面正确刷新
                    self.root.after(0, refresh_ui)
                else:
                    messagebox.showinfo("任务取消", "❌ 已取消氧气系统修复任务！", parent=self.root)
            return
        
        # 原有常规任务逻辑
        has_available_task = False
        target_task = None
        task_executed = False
        task_completed = False
        task_name = "未知任务"
        
        current_loc = player.current_location.replace("室", "").replace("区", "").replace("房", "")
        
        if hasattr(player, 'tasks') and player.tasks:
            for task in player.tasks:
                if not task.is_completed:
                    task_loc = getattr(task, 'location', '').replace("室", "").replace("区", "").replace("房", "")
                    if task_loc == current_loc:
                        has_available_task = True
                        target_task = task
                        break
        
        if not has_available_task:
            messagebox.showinfo("无法完成任务", f"当前位置{player.current_location}没有可完成的常规任务", parent=self.root)
            return
        
        # 匹配具体常规任务
        wire_fix_task = None
        filter_clean_task = None
        body_scan_task = None
        download_data_task = None
        calibrate_down_engine_task = None
        calibrate_up_engine_task = None
        repair_reactor_task = None
        fuel_supply_task = None
        start_satellite_task = None
        morse_code_task = None
        normal_task = None
        
        for task in player.tasks:
            if not task.is_completed:
                task_loc = getattr(task, 'location', '').replace("室", "").replace("区", "").replace("房", "")
                if task_loc == current_loc:
                    if isinstance(task, WireFixTask) and current_loc == "电力":
                        wire_fix_task = task
                    elif hasattr(task, 'name') and task.name == "清理过滤器" and current_loc == "氧气":
                        filter_clean_task = task
                    elif hasattr(task, 'name') and task.name == "扫描身体" and current_loc == "医疗":
                        body_scan_task = task
                    elif hasattr(task, 'name') and task.name == "下载数据" and current_loc == "通讯":
                        download_data_task = task
                    elif hasattr(task, 'name') and "下降引擎" in task.name and current_loc == "下降引擎":
                        calibrate_down_engine_task = task
                    elif hasattr(task, 'name') and "上升引擎" in task.name and current_loc == "上升引擎":
                        calibrate_up_engine_task = task
                    elif hasattr(task, 'name') and "反应堆" in task.name and current_loc == "反应堆":
                        repair_reactor_task = task
                    elif hasattr(task, 'name') and "燃料" in task.name and current_loc == "燃料":
                        fuel_supply_task = task
                    elif hasattr(task, 'name') and "卫星" in task.name and current_loc == "监控":
                        start_satellite_task = task
                    elif hasattr(task, 'name') and "摩斯密码" in task.name and current_loc == "主控":
                        morse_code_task = task
                    elif normal_task is None:
                        normal_task = task
        
        # 执行具体常规任务
        if wire_fix_task:
            task_executed = True
            task_name = wire_fix_task.name
            task_completed = wire_fix_task.run_task_gui(main_root=self.root)
        
        elif filter_clean_task:
            task_executed = True
            task_name = filter_clean_task.name
            try:
                task_completed = filter_clean_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"清理过滤器任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"清理过滤器任务执行出错：{str(e)}", parent=self.root)
        
        elif body_scan_task:
            task_executed = True
            task_name = body_scan_task.name
            try:
                task_completed = body_scan_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"扫描身体任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"扫描身体任务执行出错：{str(e)}", parent=self.root)
        
        elif download_data_task:
            task_executed = True
            task_name = download_data_task.name
            try:
                task_completed = download_data_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"下载数据任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"下载数据任务执行出错：{str(e)}", parent=self.root)
        
        elif calibrate_down_engine_task:
            task_executed = True
            task_name = calibrate_down_engine_task.name
            try:
                task_completed = calibrate_down_engine_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"校准下降引擎任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"校准下降引擎任务执行出错：{str(e)}", parent=self.root)
        
        elif calibrate_up_engine_task:
            task_executed = True
            task_name = calibrate_up_engine_task.name
            try:
                task_completed = calibrate_up_engine_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"校准上升引擎任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"校准上升引擎任务执行出错：{str(e)}", parent=self.root)
        
        elif repair_reactor_task:
            task_executed = True
            task_name = repair_reactor_task.name
            try:
                task_completed = repair_reactor_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"反应堆任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"反应堆任务执行出错：{str(e)}", parent=self.root)
        
        elif fuel_supply_task:
            task_executed = True
            task_name = fuel_supply_task.name
            try:
                task_completed = fuel_supply_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"燃料补给任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"燃料补给任务执行出错：{str(e)}", parent=self.root)
        
        elif start_satellite_task:
            task_executed = True
            task_name = start_satellite_task.name
            try:
                task_completed = start_satellite_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"启动卫星任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"启动卫星任务执行出错：{str(e)}", parent=self.root)
                
        elif morse_code_task:
            task_executed = True
            task_name = morse_code_task.name
            try:
                task_completed = morse_code_task.run_task_gui(main_root=self.root)
            except Exception as e:
                print(f"摩斯密码任务异常：{str(e)}")
                messagebox.showerror("任务异常", f"摩斯密码任务执行出错：{str(e)}", parent=self.root)
                
        elif normal_task:
            task_executed = True
            task_name = normal_task.name
            confirm = messagebox.askyesno("确认完成任务", f"是否确认完成常规任务【{task_name}】？", parent=self.root)
            if confirm:
                task_completed = normal_task.complete()
            else:
                task_completed = False
        
        else:
            if target_task and isinstance(target_task, (
                WireFixTask, FilterCleanTask, BodyScanTask,
                DownloadDataTask, CalibrateDownEngineTask, CalibrateUpEngineTask,
                RepairReactorTask, RefuelTask, StartSatelliteTask, MorseCodeTask
            )):
                task_executed = True
                task_name = target_task.name
                try:
                    task_completed = target_task.run_task_gui(main_root=self.root)
                except Exception as e:
                    print(f"兜底执行任务异常：{str(e)}")
                    messagebox.showerror("任务异常", f"任务执行出错：{str(e)}", parent=self.root)
            else:
                messagebox.showinfo("无法完成任务", "未找到可执行的图形化常规任务", parent=self.root)
                return
        
        # 常规任务完成后处理
        if task_executed and task_completed:
            self.action_steps += 1
            
            if wire_fix_task:
                wire_fix_task.is_completed = True
            elif filter_clean_task:
                filter_clean_task.is_completed = True
            elif body_scan_task:
                body_scan_task.is_completed = True
            elif download_data_task:
                download_data_task.is_completed = True
            elif calibrate_down_engine_task:
                calibrate_down_engine_task.is_completed = True
            elif calibrate_up_engine_task:
                calibrate_up_engine_task.is_completed = True
            elif repair_reactor_task:
                repair_reactor_task.is_completed = True
            elif fuel_supply_task:
                fuel_supply_task.is_completed = True
            elif start_satellite_task:
                start_satellite_task.is_completed = True
            elif morse_code_task:
                morse_code_task.is_completed = True
            elif normal_task:
                normal_task.is_completed = True
            
            if player.completed_tasks < 3:
                player.completed_tasks += 1
            
            self.add_log(f"✅ {player.name}完成了常规任务【{task_name}】！当前进度：{player.completed_tasks}/3")
            self.update_task_list()
            
            # 联机模式：同步任务完成信息给所有客户端
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer and self.sync_socket:
                try:
                    task_complete_msg = json.dumps({
                        "type": "complete_task",
                        "player_name": player.name,
                        "completed_tasks": player.completed_tasks
                    })
                    self.sync_socket.send((task_complete_msg + '\n').encode('utf-8'))
                    print(f"✓ 已同步任务完成信息: {player.name} - {player.completed_tasks}/3")
                except Exception as e:
                    print(f"发送任务完成消息失败: {e}")
            
            # 检查是否所有常规任务完成
            all_tasks_completed = all(
                p.completed_tasks >= 3 
                for p in self.game.players 
                if p.is_alive and isinstance(p.role, Crewmate)
            )
            
            # 如果是摩斯密码任务，记录任务对象供后续关闭使用
            is_morse_task = isinstance(wire_fix_task, MorseCodeTask) or isinstance(filter_clean_task, MorseCodeTask) or \
                          isinstance(body_scan_task, MorseCodeTask) or isinstance(download_data_task, MorseCodeTask) or \
                          isinstance(calibrate_down_engine_task, MorseCodeTask) or isinstance(calibrate_up_engine_task, MorseCodeTask) or \
                          isinstance(repair_reactor_task, MorseCodeTask) or isinstance(fuel_supply_task, MorseCodeTask) or \
                          isinstance(start_satellite_task, MorseCodeTask) or isinstance(morse_code_task, MorseCodeTask)
            current_morse_task = morse_code_task if morse_code_task else None
            
            if all_tasks_completed:
                self.game.winner = "crewmate"
                self.game.game_over = True
                
                # 联机模式：发送游戏结束消息给所有客户端
                if hasattr(self, 'is_multiplayer') and self.is_multiplayer and self.sync_socket:
                    try:
                        game_over_msg = json.dumps({
                            "type": "game_over",
                            "winner": "crewmate",
                            "reason": "all_tasks_completed"
                        })
                        self.sync_socket.send((game_over_msg + '\n').encode('utf-8'))
                        print("✓ 已发送游戏结束消息（船员胜利）")
                    except Exception as e:
                        print(f"发送游戏结束消息失败: {e}")
                
                # 显示游戏结束界面（会阻塞）
                self.show_game_over()
                
                # 游戏结束界面关闭后，关闭摩斯密码任务窗口
                if current_morse_task and hasattr(current_morse_task, 'close_task_window'):
                    try:
                        current_morse_task.close_task_window()
                    except Exception as e:
                        print(f"关闭摩斯密码窗口失败: {e}")
            else:
                progress = f"{player.completed_tasks}/3"
                messagebox.showinfo(
                    "任务完成", 
                    f"✅ 成功完成常规任务【{task_name}】！\n当前常规任务进度：{progress}", 
                    parent=self.root
                )
                
                # 消息框关闭后，关闭摩斯密码任务窗口
                if current_morse_task and hasattr(current_morse_task, 'close_task_window'):
                    try:
                        current_morse_task.close_task_window()
                    except Exception as e:
                        print(f"关闭摩斯密码窗口失败: {e}")
                
                if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps and not self.game.game_over:
                    messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                    self.switch_to_next_player()
        elif task_executed and not task_completed:
            messagebox.showinfo("任务取消", f"❌ 已取消常规任务【{task_name}】！", parent=self.root)
    
    def handle_kill(self, impostor):
        """处理击杀操作"""
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法执行击杀")
            return
        
        targets = [p for p in self.game.players 
                if p.is_alive and p != impostor and 
                p.current_location == impostor.current_location and 
                not isinstance(p.role, Impostor)]
        
        if not targets:
            messagebox.showinfo("无法击杀", "当前位置没有可击杀的船员")
            return
        
        # 创建击杀选择对话框
        kill_window = tk.Toplevel(self.root)
        kill_window.title("选择击杀目标")
        kill_window.geometry("1000x750+460+165")
        kill_window.configure(bg="#1a1a2e")
        kill_window.transient(self.root)
        kill_window.grab_set()
        
        label = tk.Label(
            kill_window, 
            text="请选择要击杀的目标:", 
            font=(self.font_family, 14),
            fg="#e94560",
            bg="#1a1a2e"
        )
        label.pack(pady=15)
        
        target_listbox = tk.Listbox(
            kill_window, 
            font=(self.font_family, 12),
            bg="#0f3460",
            fg="#ffffff",
            selectbackground="#e94560",
            width=25, height=10
        )
        target_listbox.pack(pady=10, padx=20)
        
        for target in targets:
            target_listbox.insert(tk.END, target.name)
        
        def confirm_kill():
            if target_listbox.curselection():
                selected_index = target_listbox.curselection()[0]
                target = targets[selected_index]
                
                # 检查击杀冷却
                is_multiplayer = hasattr(self, 'is_multiplayer') and self.is_multiplayer
                
                if is_multiplayer:
                    # 联机模式：使用实时冷却
                    if not impostor.role.kill(multiplayer=True):
                        remaining = impostor.role.current_kill_cooldown_seconds
                        messagebox.showerror("冷却中", f"⚠️ 击杀技能冷却中！\n剩余时间：{remaining}秒")
                        kill_window.destroy()
                        return
                else:
                    # 单机模式：使用回合制冷却
                    if self.global_round == 1:
                        messagebox.showerror("操作拦截", "⚠️ 第1回合内鬼禁止杀人！\n请等待所有玩家轮完第一回合后再进行操作")
                        kill_window.destroy()
                        return
                    
                    if not impostor.role.kill():
                        remaining = impostor.role.current_kill_cooldown
                        messagebox.showerror("冷却中", f"⚠️ 击杀技能冷却中！\n剩余回合：{remaining}回合")
                        kill_window.destroy()
                        return
                
                self.action_steps += 1
                impostor.kill(target)
                self.add_log(f"⚠️ {impostor.name}击杀了{target.name}！")
                
                kill_window.destroy()
                
                if self.game.check_game_over():
                    # 获取胜利者并广播
                    winner = self.game.winner if hasattr(self.game, 'winner') else "unknown"
                    self.broadcast_game_over(winner, "impostor_kill")
                    self.show_game_over()
                else:
                    if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                        if self.action_steps > self.max_steps:
                            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                            self.switch_to_next_player()
                        else:
                            self.create_game_frame()
                    else:
                        self.create_game_frame()
            else:
                messagebox.showwarning("警告", "请选择一个目标")

        button_frame = tk.Frame(kill_window, bg="#1a1a2e")
        button_frame.pack(pady=15)

        if sys.platform == 'darwin':
            confirm_btn = ttk.Button(
                button_frame, 
                text="确认击杀", 
                style="ConfirmKill.TButton",
                command=confirm_kill
            )
            cancel_btn = ttk.Button(
                button_frame, 
                text="取消", 
                style="CancelKill.TButton",
                command=kill_window.destroy
            )
            style = ttk.Style()
            style.configure("ConfirmKill.TButton", 
                          font=(self.font_family, 12),
                          padding=(20, 5),
                          background="#E94560",
                          foreground="#FFFFFF")
            style.map("ConfirmKill.TButton",
                          background=[("active", "#C62828"),("!active", "#E94560")],
                          foreground=[("active", "#FFEBEE"),("!active", "#FFFFFF")])
            style.configure("CancelKill.TButton", 
                          font=(self.font_family, 12),
                          padding=(20, 5),
                          background="#F44336",
                          foreground="#FFFFFF")
            style.map("CancelKill.TButton",
                          background=[("active", "#D32F2F"),("!active", "#F44336")],
                          foreground=[("active", "#FFEBEE"),("!active", "#FFFFFF")])
        else:
            confirm_btn = tk.Button(
                button_frame, 
                text="确认击杀", 
                font=(self.font_family, 12),
                bg="#e94560",
                fg="#ffffff",
                padx=20,
                command=confirm_kill
            )
            cancel_btn = tk.Button(
                button_frame, 
                text="取消", 
                font=(self.font_family, 12),
                bg="#f44336",
                fg="#ffffff",
                padx=20,
                command=kill_window.destroy
            )
        confirm_btn.pack(side="left", padx=10)
        cancel_btn.pack(side="left", padx=10)

    def handle_sabotage(self, player):
        """处理破坏系统操作"""
        # 检查冷却
        is_multiplayer = hasattr(self, 'is_multiplayer') and self.is_multiplayer
        if is_multiplayer:
            # 联机模式：检查实时冷却
            if not player.role.can_sabotage():
                minutes = player.role.current_sabotage_cooldown_seconds // 60
                seconds = player.role.current_sabotage_cooldown_seconds % 60
                messagebox.showinfo("冷却中", f"⚠️ 破坏系统正在冷却中！\n剩余 {minutes:02d}:{seconds:02d}")
                return
        else:
            # 单机模式：检查回合制冷却
            if self.sabotage_cooldown > 0:
                messagebox.showinfo("冷却中", f"⚠️ 破坏系统正在冷却中！\n剩余 {self.sabotage_cooldown} 回合")
                return
        
        # 创建破坏选择窗口
        sabotage_window = tk.Toplevel(self.root)
        sabotage_window.title("破坏系统")
        sabotage_window.geometry("500x300+710+390")
        sabotage_window.configure(bg="#1a1a2e")
        sabotage_window.transient(self.root)
        sabotage_window.grab_set()
        
        # 标题
        title_label = tk.Label(
            sabotage_window,
            text="🔧 选择要破坏的系统",
            font=(self.font_family, 20, "bold"),
            fg="#e94560",
            bg="#1a1a2e"
        )
        title_label.pack(pady=20)
        
        # 按钮框架
        button_frame = tk.Frame(sabotage_window, bg="#1a1a2e")
        button_frame.pack(pady=20)
        
        def sabotage_oxygen():
            """破坏氧气系统"""
            self.oxygen_sabotaged = True
            self.oxygen_sabotage_round = self.global_round
            self.oxygen_repaired = False
            if is_multiplayer:
                self.oxygen_timeout = time.time() + 150  # 150秒后氧气耗尽
            else:
                self.oxygen_remaining_rounds = self.oxygen_timeout_rounds
            
            if not is_multiplayer:
                self.action_steps += 1
            
            # 设置破坏冷却
            if is_multiplayer:
                # 联机模式：设置实时冷却
                player.role.use_sabotage()
                # 更新房间状态
                if self.room_state:
                    self.room_state.set_sabotage("oxygen", True)
                # 发送同步消息
                if self.sync_socket:
                    try:
                        message = json.dumps({
                            'type': 'sabotage',
                            'system': 'oxygen',
                            'player_name': player.name,
                            'oxygen_timeout': self.oxygen_timeout  # 发送倒计时时间戳
                        })
                        self.sync_socket.send((message + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"发送破坏消息失败: {e}")
                self.add_log(f"🔧 {player.name}破坏了氧气系统！")
                messagebox.showinfo("破坏成功", f"⚠️ 氧气系统已被破坏！\n船员需要在150秒内修复！")
            else:
                # 单机模式：设置回合制冷却
                self.sabotage_cooldown = self.sabotage_cooldown_rounds
                player.role.sabotage("氧气")
                self.add_log(f"🔧 {player.name}在第{self.global_round}回合破坏了氧气系统！船员仅有{self.oxygen_remaining_rounds}个回合修复时间！")
                messagebox.showinfo("破坏成功", f"⚠️ 氧气系统已被破坏！\n船员仅有{self.oxygen_remaining_rounds}个回合修复时间，超时则内鬼直接胜利！\n该任务不占用3个常规任务数量")
            
            sabotage_window.destroy()
            
            if not is_multiplayer:
                if self.action_steps > self.max_steps:
                    messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                    self.switch_to_next_player()
                else:
                    self.create_game_frame()
            else:
                self.create_game_frame()
        
        def sabotage_monitor():
            """破坏监控系统"""
            self.monitor_sabotaged = True
            self.monitor_sabotage_round = self.global_round
            self.monitor_repaired = False
            
            if not is_multiplayer:
                self.action_steps += 1
            
            # 设置破坏冷却
            if is_multiplayer:
                # 联机模式：设置实时冷却
                player.role.use_sabotage()
                # 更新房间状态
                if self.room_state:
                    self.room_state.set_sabotage("monitor", True)
                # 发送同步消息
                if self.sync_socket:
                    try:
                        message = json.dumps({
                            'type': 'sabotage',
                            'system': 'monitor',
                            'player_name': player.name
                        })
                        self.sync_socket.send((message + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"发送破坏消息失败: {e}")
                self.add_log(f"🔧 {player.name}破坏了监控系统！")
                messagebox.showinfo("破坏成功", f"⚠️ 监控系统已被破坏！\n需要完成任务才能恢复监控！")
            else:
                # 单机模式：设置回合制冷却
                self.sabotage_cooldown = self.sabotage_cooldown_rounds
                player.role.sabotage("监控")
                self.add_log(f"🔧 {player.name}在第{self.global_round}回合破坏了监控系统！需要完成任务才能恢复！")
                messagebox.showinfo("破坏成功", f"⚠️ 监控系统已被破坏！\n需要完成任务才能恢复监控！")
            
            sabotage_window.destroy()
            
            if not is_multiplayer and self.action_steps > self.max_steps:
                messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                self.switch_to_next_player()
            else:
                self.create_game_frame()
        
        # 氧气系统按钮
        oxygen_button = tk.Button(
            button_frame,
            text="💨 氧气系统",
            font=(self.font_family, 14),
            bg="#4caf50",
            fg="#ffffff",
            padx=30,
            pady=15,
            bd=2,
            relief="flat",
            command=sabotage_oxygen
        )
        oxygen_button.pack(side="left", padx=20)
        
        # 监控系统按钮
        monitor_button = tk.Button(
            button_frame,
            text="📡 监控系统",
            font=(self.font_family, 14),
            bg="#9c27b0",
            fg="#ffffff",
            padx=30,
            pady=15,
            bd=2,
            relief="flat",
            command=sabotage_monitor
        )
        monitor_button.pack(side="left", padx=20)
        
        # 取消按钮
        cancel_button = tk.Button(
            sabotage_window,
            text="取消",
            font=(self.font_family, 12),
            bg="#666666",
            fg="#ffffff",
            padx=20,
            pady=5,
            bd=2,
            relief="flat",
            command=sabotage_window.destroy
        )
        cancel_button.pack(pady=15)

    def handle_place_bomb(self, player):
        """处理放置炸弹操作"""
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！无法放置炸弹")
            return

        is_multiplayer = hasattr(self, 'is_multiplayer') and self.is_multiplayer
        
        # 检查炸弹冷却
        if is_multiplayer:
            # 联机模式：使用实时冷却
            if not player.role.place_bomb(multiplayer=True):
                remaining = player.role.current_bomb_cooldown_seconds
                minutes = remaining // 60
                seconds = remaining % 60
                messagebox.showerror("冷却中", f"⚠️ 炸弹技能冷却中！剩余时间：{minutes}分{seconds}秒")
                return
        else:
            # 单机模式：使用回合制冷却
            if not player.role.place_bomb():
                remaining = player.role.current_bomb_cooldown
                messagebox.showerror("冷却中", f"⚠️ 炸弹技能冷却中！剩余回合：{remaining}回合")
                return

        if not is_multiplayer:
            self.action_steps += 1
        self.bomb_location = player.current_location  # 固定炸弹位置
        bomb_fixed_location = self.bomb_location  # 保存固定位置用于同步

        self.add_log(f"💣 {player.name}在{self.bomb_location}放置了一颗炸弹！")
        
        # 联机模式：发送炸弹同步消息给其他客户端
        if is_multiplayer:
            # 计算爆炸时间
            explode_time = time.time() + 60  # 1分钟后爆炸
            # 更新房间状态
            if self.room_state:
                self.room_state.bomb_location = bomb_fixed_location
                self.room_state.bomb_explode_time = explode_time
            # 发送同步消息
            if self.sync_socket:
                try:
                    bomb_msg = json.dumps({
                        "type": "place_bomb",
                        "location": bomb_fixed_location,
                        "player_name": player.name,
                        "explode_time": explode_time
                    })
                    self.sync_socket.send((bomb_msg + '\n').encode('utf-8'))
                except Exception as e:
                    print(f"发送炸弹放置消息失败: {e}")
            messagebox.showinfo("放置成功", f"💣 炸弹已放置在{self.bomb_location}！炸弹将在1分钟后爆炸！放置冷却：2分30秒")
        else:
            messagebox.showinfo("放置成功", f"💣 炸弹已放置在{self.bomb_location}！炸弹将在3分钟后爆炸！放置冷却：5回合")

        if not is_multiplayer and self.action_steps > self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！自动切换至下一位玩家")
            self.switch_to_next_player()
        else:
            self.create_game_frame()
    def handle_defuse_bomb(self):
        """处理拆弹任务"""
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法拆弹")
            return
        
        if not self.bomb_location:
            messagebox.showinfo("拆弹任务", "⚠️ 当前房间没有炸弹！")
            return
        
        if self.current_player.current_location != self.bomb_location:
            messagebox.showinfo("拆弹任务", "⚠️ 你不在有炸弹的房间！")
            return
        
        from tasks import BombDefuseTask
        bomb_task = BombDefuseTask()
        
        def on_defuse_complete(completed):
            if completed:
                # 先更新状态
                self.bomb_location = None
                for player in self.game.players:
                    if isinstance(player.role, Impostor):
                        player.role.bomb_explode_time = None
                if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                    self.action_steps += 1
                self.add_log(f"💣 {self.current_player.name}成功拆除了炸弹！")
                
                # 联机模式：发送拆弹同步消息给其他客户端
                if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                    # 更新房间状态
                    if self.room_state:
                        self.room_state.clear_bomb()
                    # 发送同步消息
                    if self.sync_socket:
                        try:
                            defuse_msg = json.dumps({
                                "type": "defuse_bomb",
                                "player_name": self.current_player.name
                            })
                            self.sync_socket.send((defuse_msg + '\n').encode('utf-8'))
                        except Exception as e:
                            print(f"发送拆弹消息失败: {e}")
                
                # 显示成功提示
                messagebox.showinfo("拆弹成功", "✅ 炸弹已成功拆除！")
                
                # 确保在主线程中刷新界面，立即反映状态变化
                def refresh_ui():
                    if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
                        messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                        self.switch_to_next_player()
                    else:
                        self.create_game_frame()
                
                # 使用after确保界面正确刷新
                self.root.after(0, refresh_ui)
            else:
                messagebox.showinfo("拆弹失败", "❌ 拆弹失败！炸弹爆炸！")
                self.execute_bomb_explosion(self.current_player)
        
        bomb_task.run_task_gui(self.root, on_close_callback=on_defuse_complete)

    def handle_clean_ruins(self):
        """处理清理废墟任务"""
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法清理废墟")
            return
        
        current_room = self.current_player.current_location
        is_ruined = self.ruined_rooms.get(current_room, False)
        is_cleaned = self.ruin_cleaned.get(current_room, True)
        
        if not is_ruined:
            messagebox.showinfo("清理废墟", "⚠️ 当前房间没有废墟！")
            return
        
        if is_cleaned:
            messagebox.showinfo("清理废墟", "⚠️ 该房间废墟已清理！")
            return
        
        from tasks import RuinCleanTask
        ruin_task = RuinCleanTask(room_name=current_room)
        
        def on_clean_complete(completed):
            if completed:
                # 先更新状态
                self.ruin_cleaned[current_room] = True
                if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                    self.action_steps += 1
                self.add_log(f"🏚️ {self.current_player.name}成功清理了{current_room}的废墟！")
                
                # 如果是飞船大厅，检查是否还在禁用期
                if current_room == "飞船大厅" and self.emergency_ban_rounds <= 0:
                    pass  # 紧急会议功能恢复
                
                # 显示成功提示
                messagebox.showinfo("清理成功", f"✅ {current_room}废墟已清理！房间恢复正常！")
                
                # 确保在主线程中刷新界面，立即反映状态变化
                def refresh_ui():
                    if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
                        messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                        self.switch_to_next_player()
                    else:
                        self.create_game_frame()
                
                # 使用after确保界面正确刷新
                self.root.after(0, refresh_ui)
            else:
                messagebox.showinfo("清理中断", "清理任务中断！")
                # 确保界面也能正确刷新
                self.root.after(0, self.create_game_frame)
        
        ruin_task.run_task_gui(self.root, on_close_callback=on_clean_complete)

    def handle_repair_monitor(self):
        """处理修复监控任务"""
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法修复监控")
            return
        
        if not getattr(self, 'monitor_sabotaged', False):
            messagebox.showinfo("修复监控", "⚠️ 监控系统没有被破坏！")
            return
        
        if self.current_player.current_location != "监控室":
            messagebox.showinfo("修复监控", "⚠️ 你不在监控室！")
            return
        
        from tasks import RepairMonitorTask
        repair_task = RepairMonitorTask()
        
        def on_task_complete():
            # 先更新状态
            self.monitor_sabotaged = False
            self.monitor_repaired = True
            if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer):
                self.action_steps += 1
            self.add_log(f"🔧 {self.current_player.name}修复了被破坏的监控系统！")
            
            # 联机模式：发送修复同步消息并更新房间状态
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                # 更新房间状态
                if self.room_state:
                    self.room_state.repair_sabotage("monitor")
                # 发送同步消息给其他客户端
                if self.sync_socket:
                    try:
                        repair_msg = json.dumps({
                            "type": "repair_sabotage",
                            "system": "monitor",
                            "player_name": self.current_player.name
                        })
                        self.sync_socket.send((repair_msg + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"发送修复监控消息失败: {e}")
            
            # 显示成功提示
            messagebox.showinfo("修复成功", "✅ 监控系统已修复！监控功能已恢复！")
            
            # 先更新任务列表显示
            self.update_task_list()
            
            # 确保在主线程中刷新界面，立即反映状态变化
            def refresh_ui():
                if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
                    messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n自动切换至下一位玩家")
                    self.switch_to_next_player()
                else:
                    self.create_game_frame()
            
            # 使用after确保界面正确刷新
            self.root.after(0, refresh_ui)
        
        repair_task.task_completed = False
        repair_task.is_completed = False
        
        result = repair_task.run_task_gui(self.root)
        
        if repair_task.task_completed or repair_task.is_completed:
            on_task_complete()

    def handle_report(self, player):
        """处理报告尸体操作"""
        if not (hasattr(self, 'is_multiplayer') and self.is_multiplayer) and self.action_steps > self.max_steps:
            messagebox.showinfo("行动限制", "⚠️ 您的行动步数已达上限！\n无法报告尸体")
            return
        
        # 检查当前位置是否有尸体
        dead_players_at_location = [p for p in self.game.players 
                                  if not p.is_alive and p.current_location == player.current_location]
        
        if not dead_players_at_location:
            messagebox.showinfo("报告尸体", "⚠️ 当前位置没有尸体可报告")
            return
        
        # 过滤掉已经被报告过或被投票出去的尸体
        available_bodies = []
        for p in dead_players_at_location:
            status = self.reported_bodies.get(p.name)
            # 只有没有被记录过（None）的尸体才可以报告
            if status is None:
                available_bodies.append(p)
        
        if not available_bodies:
            messagebox.showinfo("报告尸体", "⚠️ 该位置的所有尸体都已经被报告过或被投票出去了")
            return
        
        # 如果只有一个尸体，直接报告；如果有多个，让玩家选择
        if len(available_bodies) == 1:
            victim = available_bodies[0]
            self._execute_report(player, victim)
        else:
            self._show_body_selection(player, available_bodies)
    
    def _show_body_selection(self, player, available_bodies):
        """显示尸体选择界面"""
        selection_window = tk.Toplevel(self.root)
        selection_window.title("选择要报告的尸体")
        selection_window.geometry("800x600+500+300")
        selection_window.configure(bg="#1a1a2e")
        selection_window.transient(self.root)
        selection_window.grab_set()
        
        label = tk.Label(
            selection_window, 
            text=f"当前位置有多个尸体，请选择要报告哪一个：", 
            font=(self.font_family, 12),
            fg="#ffffff",
            bg="#1a1a2e"
        )
        label.pack(pady=15)
        
        # 创建尸体选择列表
        body_listbox = tk.Listbox(
            selection_window, 
            font=(self.font_family, 12),
            bg="#0f3460",
            fg="#ffffff",
            selectbackground="#2196f3",
            width=30, height=8
        )
        body_listbox.pack(pady=10, padx=20)
        
        for body in available_bodies:
            if self.reported_bodies.get(body.name) is None:
                body_listbox.insert(tk.END, f"{body.name}")
        
        # 创建按钮框架
        button_frame = tk.Frame(selection_window, bg="#1a1a2e")
        button_frame.pack(pady=15)
        
        def confirm_selection():
            if body_listbox.curselection():
                selected_index = body_listbox.curselection()[0]
                victim = available_bodies[selected_index]
                selection_window.destroy()
                self._execute_report(player, victim)
            else:
                messagebox.showwarning("警告", "请选择一个尸体")
        
        if sys.platform == 'darwin':
            confirm_btn = ttk.Button(
                button_frame,
                text="确认报告", 
                style="ConfirmReport.TButton",
                command=confirm_selection
            )
            cancel_btn = ttk.Button(
                button_frame,
                text="取消", 
                style="CancelReport.TButton",
                command=selection_window.destroy
            )
            style = ttk.Style()
            style.configure("ConfirmReport.TButton", 
                          font=(self.font_family, 12),
                          padding=(20, 5),
                          background="#4CAF50",
                          foreground="#FFFFFF")
            style.map("ConfirmReport.TButton",
                          background=[("active", "#388E3C"),("!active", "#4CAF50")],
                          foreground=[("active", "#E8F5E9"),("!active", "#FFFFFF")])
            style.configure("CancelReport.TButton", 
                          font=(self.font_family, 12),
                          padding=(20, 5),
                          background="#F44336",
                          foreground="#FFFFFF")
            style.map("CancelReport.TButton",
                          background=[("active", "#D32F2F"),("!active", "#F44336")],
                          foreground=[("active", "#FFEBEE"),("!active", "#FFFFFF")])
        else:
            confirm_btn = tk.Button(
                button_frame,
                text="确认报告", 
                font=(self.font_family, 12),
                bg="#4caf50",
                fg="#ffffff",
                padx=20,
                command=confirm_selection
            )
            cancel_btn = tk.Button(
                button_frame,
                text="取消", 
                font=(self.font_family, 12),
                bg="#f44336",
                fg="#ffffff",
                padx=20,
                command=selection_window.destroy
            )
        confirm_btn.pack(side="left", padx=10)
        cancel_btn.pack(side="left", padx=10)
    
    def _execute_report(self, player, victim):
        """执行尸体报告操作"""
        self.action_steps += 1
        
        # 记录已报告的尸体（基于玩家名称，而不是位置）
        self.reported_bodies[victim.name] = "reported"
        
        # 执行报告逻辑
        result = player.report_dead_body()
        self.discussion_phase(player, victim)

    def discussion_phase(self, reporter, victim):  
        """讨论阶段"""
        # 清除所有现有组件
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # 创建讨论阶段界面
        discussion_frame = tk.Frame(self.root, bg="#16213e")
        discussion_frame.pack(fill="both", expand=True)
        
        # 标题
        title_label = tk.Label(
            discussion_frame, 
            text="讨论阶段", 
            font=(self.font_family, 24, "bold"),
            fg="#e94560",
            bg="#16213e"
        )
        title_label.pack(pady=30)
        
        # 讨论区域
        discussion_text = tk.Text(
            discussion_frame, 
            height=10, 
            font=(self.font_family, 12),
            bg="#0f3460",
            fg="#ffffff",
            wrap="word"
        )
        discussion_text.pack(fill="x", padx=50, pady=10)
        
        # 区分紧急会议和报告尸体的讨论标题
        if victim:
            discussion_text.insert(tk.END, f"{reporter.name}报告了{victim.name}的尸体！请玩家们讨论谁是内鬼。\n")
        else:
            discussion_text.insert(tk.END, f"{reporter.name}发起了紧急会议！请玩家们讨论谁是内鬼。\n")
        
        # 投票结果字典
        votes = {}
        
        # 为每个存活玩家显示投票选项（顺序投票版）
        def collect_votes():
            votes.clear()
            alive_players = [p for p in self.game.players if p.is_alive]
            current_voter_index = [0]
            
            def vote_next_player():
                if current_voter_index[0] >= len(alive_players):
                    show_vote_results()
                    return
                
                voter = alive_players[current_voter_index[0]]
                
                # 创建投票对话框
                vote_window = tk.Toplevel(self.root)
                vote_window.title(f"{voter.name}的投票")
                vote_window.geometry("1000x750+460+165")
                vote_window.configure(bg="#1a1a2e")
                vote_window.transient(self.root)
                vote_window.grab_set()
                
                label = tk.Label(
                    vote_window, 
                    text=f"{voter.name}，请选择要投票的玩家:", 
                    font=(self.font_family, 12),
                    fg="#ffffff",
                    bg="#1a1a2e"
                )
                label.pack(pady=15)
                
                # 创建投票选项列表
                vote_listbox = tk.Listbox(
                    vote_window, 
                    font=(self.font_family, 12),
                    bg="#0f3460",
                    fg="#ffffff",
                    selectbackground="#2196f3",
                    width=25, height=10
                )
                vote_listbox.pack(pady=10, padx=20)
                vote_listbox.insert(tk.END, "跳过投票")
                
                for suspect in alive_players:
                    vote_listbox.insert(tk.END, suspect.name)
                
                # 创建按钮框架
                button_frame = tk.Frame(vote_window, bg="#1a1a2e")
                button_frame.pack(pady=15)
                
                # 确认投票函数
                def confirm_vote():
                    if vote_listbox.winfo_exists() and vote_listbox.curselection():
                        selected_index = vote_listbox.curselection()[0]
                        if selected_index == 0:
                            voter.vote(None)
                            votes["跳过"] = votes.get("跳过", 0) + 1
                        else:
                            selected_name = vote_listbox.get(selected_index)
                            suspect = next(p for p in alive_players if p.name == selected_name)
                            voter.vote(suspect)
                            votes[selected_name] = votes.get(selected_name, 0) + 1
                        
                        vote_window.destroy()
                        current_voter_index[0] += 1
                        vote_next_player()
                    else:
                        messagebox.showwarning("警告", "请做出选择")
                
                # 创建确认按钮
                if sys.platform == 'darwin':
                    # Mac上使用ttk按钮
                    confirm_btn = ttk.Button(
                        button_frame,
                        text="确认投票", 
                        style="ConfirmVote.TButton",
                        command=confirm_vote
                    )
                    style = ttk.Style()
                    style.configure("ConfirmVote.TButton", 
                                  font=(self.font_family, 12),
                                  padding=(20, 5),
                                  background="#4CAF50",
                                  foreground="#FFFFFF")
                    style.map("ConfirmVote.TButton",
                                  background=[("active", "#388E3C"),("!active", "#4CAF50")],
                                  foreground=[("active", "#E8F5E9"),("!active", "#FFFFFF")])
                else:
                    # Windows上使用普通按钮
                    confirm_btn = tk.Button(
                        button_frame,
                        text="确认投票", 
                        font=(self.font_family, 12),
                        bg="#4caf50",
                        fg="#ffffff",
                        padx=20,
                        command=confirm_vote
                    )
                confirm_btn.pack()
            
            vote_next_player()

        # 显示投票结果
        def show_vote_results():
            # 清除投票区域
            for widget in discussion_frame.winfo_children():
                widget.destroy()
            
            if votes:
                result_text = "投票结果:\n"
                for name, count in votes.items():
                    result_text += f"{name}: {count} 票\n"
                
                result_label = tk.Label(
                    discussion_frame, 
                    text=result_text, 
                    font=(self.font_family, 12),
                    fg="#ffffff",
                    bg="#1a1a2e",
                    justify="left"
                )
                result_label.pack(pady=10, padx=20)
                
                # 找出得票最多的人（排除跳过选项）
                player_votes = {k: v for k, v in votes.items() if k != "跳过"}
                if player_votes:
                    max_votes = max(player_votes.values())
                    suspects = [name for name, count in player_votes.items() if count == max_votes]
                    
                    if len(suspects) == 1:
                        ejected_player = next(p for p in self.game.players if p.name == suspects[0])
                        result_text = f"⚠️ {ejected_player.name}被多数票选出，将被流放！\n"
                        result_text += f"{ejected_player.name}的真实身份是: {ejected_player.role.__class__.__name__}"
                        
                        self.reported_bodies[ejected_player.name] = "voted_out"
                        # 流放玩家
                        ejected_player.is_alive = False
                        # 添加到旁观模式
                        if ejected_player not in self.spectator_players:
                            self.spectator_players.append(ejected_player)
                            self.dead_player_locations[ejected_player.name] = {
                                "location": ejected_player.current_location,
                                "cleared": False
                            }
                        
                    else:
                        result_text = "票数相同，没有人被流放"
                    
                    result_label = tk.Label(
                        discussion_frame, 
                        text=result_text, 
                        font=(self.font_family, 12, "bold"),
                        fg="#ffcc00",
                        bg="#1a1a2e",
                        justify="left"
                    )
                    result_label.pack(pady=10, padx=20)
            else:
                result_label = tk.Label(
                    discussion_frame, 
                    text="所有人都跳过了投票", 
                    font=(self.font_family, 12),
                    fg="#ffffff",
                    bg="#1a1a2e"
                )
                result_label.pack(pady=10, padx=20)
            
            # 检查游戏是否结束（直接跳结算）
            if self.game.check_game_over():
                start_vote_button.destroy()
                # 获取胜利者并广播
                winner = self.game.winner if hasattr(self.game, 'winner') else "unknown"
                self.broadcast_game_over(winner, "vote_end")
                self.show_game_over()
            else:
                # 继续游戏按钮
                start_vote_button.destroy()
                if sys.platform == 'darwin':
                    continue_button = ttk.Button(
                        discussion_frame, 
                        text="继续游戏", 
                        style="ContinueGame.TButton",
                        command=self.create_game_frame
                    )
                    style = ttk.Style()
                    style.configure("ContinueGame.TButton", 
                                  font=(self.font_family, 14),
                                  padding=(30, 10),
                                  background="#2196F3",
                                  foreground="#FFFFFF")
                    style.map("ContinueGame.TButton",
                                  background=[("active", "#1976D2"),("!active", "#2196F3")],
                                  foreground=[("active", "#E3F2FD"),("!active", "#FFFFFF")])
                else:
                    continue_button = tk.Button(
                        discussion_frame, 
                        text="继续游戏", 
                        font=(self.font_family, 14),
                        bg="#2196f3",
                        fg="#ffffff",
                        padx=30,
                        pady=10,
                        command=self.create_game_frame
                    )
                continue_button.pack(pady=20)
                
        
        # 开始投票按钮
        if sys.platform == 'darwin':
            # Mac上使用ttk按钮
            start_vote_button = ttk.Button(
                discussion_frame, 
                text="开始投票", 
                style="StartVote.TButton",
                command=collect_votes
            )
            style = ttk.Style()
            style.configure("StartVote.TButton", 
                          font=(self.font_family, 14),
                          padding=(30, 10),
                          background="#FF9800",
                          foreground="#FFFFFF")
            style.map("StartVote.TButton",
                          background=[("active", "#FF9800"),("!active", "#FF9800")],
                          foreground=[("active", "#FFFFFF"),("!active", "#FFFFFF")])
        else:
            # Windows上使用普通按钮
            start_vote_button = tk.Button(
                discussion_frame, 
                text="开始投票", 
                font=(self.font_family, 14),
                bg="#ff9800",
                fg="#ffffff",
                padx=30,
                pady=10,
                command=collect_votes
            )
        start_vote_button.pack(pady=20)
                
    def show_game_over(self):
        """显示游戏结束结算界面（直接跳转，无多余弹窗）"""
        # 清除所有现有组件
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # 创建游戏结束界面
        game_over_frame = tk.Frame(self.root, bg="#16213e")
        game_over_frame.pack(fill="both", expand=True)
        
        # 标题
        title_text = "游戏结束"
        title_label = tk.Label(
            game_over_frame, 
            text=title_text, 
            font=(self.font_family, 36, "bold"),
            fg="#e94560",
            bg="#16213e"
        )
        title_label.pack(pady=20)
        
        # 胜利方
        winner_text = f"胜利方: {'船员' if self.game.winner == 'crewmate' else '内鬼'}"
        winner_color = "#00ff00" if self.game.winner == 'crewmate' else "#e94560"
        
        winner_label = tk.Label(
            game_over_frame, 
            text=winner_text, 
            font=(self.font_family, 24, "bold"),
            fg=winner_color,
            bg="#16213e"
        )
        winner_label.pack(pady=30)
        
        # 显示结束原因（重点标注氧气超时）
        reason_text = ""
        if self.oxygen_sabotaged and not self.oxygen_repaired:
            if hasattr(self, 'is_multiplayer') and self.is_multiplayer:
                reason_text = "⚠️ 氧气系统被破坏，船员未在150秒内完成修复，内鬼胜利！"
            else:
                reason_text = f"⚠️ 氧气系统在第{self.oxygen_sabotage_round}回合被破坏，船员未在2个回合内完成修复，内鬼胜利！"
        elif self.game.winner == "crewmate":
            reason_text = "🎉 所有船员完成3个常规任务，船员胜利！"
        else:
            reason_text = "⚠️ 内鬼击杀足够多船员，人数占优，内鬼胜利！"
        
        if reason_text:
            reason_label = tk.Label(
                game_over_frame,
                text=reason_text,
                font=(self.font_family, 16),
                fg="#ffcc00" if self.game.winner == "crewmate" else "#ff0000",
                bg="#16213e"
            )
            reason_label.pack(pady=10)
        
        # 身份揭示
        reveal_frame = tk.LabelFrame(game_over_frame, text="最终身份揭示", bg="#1a1a2e", fg="#ffffff", font=(self.font_family, 14))
        reveal_frame.pack(fill="x", padx=100, pady=20)
        
        for player in self.game.players:
            status = "存活" if player.is_alive else "死亡"
            role_name = player.role.__class__.__name__
            # 显示船员任务完成情况
            if isinstance(player.role, Crewmate):
                role_name += f" (完成{player.completed_tasks}/3任务)"
            
            player_label = tk.Label(
                reveal_frame, 
                text=f"{player.name}: {role_name} ({status})", 
                font=(self.font_family, 12),
                fg="#ffffff",
                bg="#1a1a2e"
            )
            player_label.pack(pady=5, padx=20)
        
        # 按钮区域
        button_frame = tk.Frame(game_over_frame, bg="#16213e")
        button_frame.pack(pady=40)
        
        # 重新开始按钮
        if sys.platform == 'darwin':
            restart_button = ttk.Button(
                button_frame, 
                text="重新开始", 
                style="Restart.TButton",
                command=self.create_main_frame
            )
            quit_button = ttk.Button(
                button_frame, 
                text="退出游戏", 
                style="Quit.TButton",
                command=self.root.quit
            )
            style = ttk.Style()
            style.configure("Restart.TButton", 
                          font=(self.font_family, 14),
                          padding=(30, 10),
                          background="#4CAF50",
                          foreground="#FFFFFF")
            style.map("Restart.TButton",
                          background=[("active", "#4CAF50"),("!active", "#4CAF50")],
                          foreground=[("active", "#FFFFFF"),("!active", "#FFFFFF")])
            style.configure("Quit.TButton", 
                          font=(self.font_family, 14),
                          padding=(30, 10),
                          background="#F44336",
                          foreground="#FFFFFF")
            style.map("Quit.TButton",
                          background=[("active", "#F44336"),("!active", "#F44336")],
                          foreground=[("active", "#FFFFFF"),("!active", "#FFFFFF")])
        else:
            restart_button = tk.Button(
                button_frame, 
                text="重新开始", 
                font=(self.font_family, 14),
                bg="#4caf50",
                fg="#ffffff",
                padx=30,
                pady=10,
                command=self.create_main_frame
            )
            quit_button = tk.Button(
                button_frame, 
                text="退出游戏", 
                font=(self.font_family, 14),
                bg="#f44336",
                fg="#ffffff",
                padx=30,
                pady=10,
                command=self.root.quit
            )
        restart_button.pack(side="left", padx=20)
        quit_button.pack(side="left", padx=20)

def main():
    """主函数"""
    root = tk.Tk()

    # 捕获 Tk 事件回调中的异常（默认只打印到 stderr，容易丢失）
    import traceback as _tb
    def _report_callback_exception(exc, val, tb):
        msg = "!!! Tk 回调未捕获异常:\n" + "".join(_tb.format_exception(exc, val, tb))
        print(msg, flush=True)
        log_path = os.environ.get("MAIN_GUI_CRASH_LOG")
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass
    root.report_callback_exception = _report_callback_exception

    app = AmongUsGUI(root, game=None)
    root.mainloop()

if __name__ == "__main__":
    main()