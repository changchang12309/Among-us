import os
import sys
import socket
import threading
import json
import base64
import subprocess
import tkinter as tk
from tkinter import messagebox, simpledialog
import time
from room_state import RoomState

# ========== 控制台编码兜底 ==========
# Windows 中文环境的 stdout 默认是 GBK，而本文件里有大量 ✓ ✗ 等非 GBK 字符的
# print。一旦 print 抛 UnicodeEncodeError：
#   - 服务端线程里会跳过其后的 root.after(...)，导致房主端看不到新玩家、按钮不刷新；
#   - 客户端消息线程里会被 except Exception 捕获并 break，导致收不到开场消息。
# 这里只放宽错误处理、不改编码，保证中文正常且输出不再因符号崩溃。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="backslashreplace")
    except Exception:
        pass

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    pass


def spawn_detached_game(cmd_args, log_tag):
    """以“完全分离”方式启动游戏主进程（main_gui）。

    背景：游戏开始后大厅进程会立即退出。若游戏子进程继承大厅的控制台/管道
    句柄并处于同一进程组，大厅退出会导致：
      - Windows：控制台关闭，游戏进程收到 CTRL_CLOSE_EVENT 被连带终止；
      - Linux/WSL：管道读端关闭，游戏线程 print 时收到 SIGPIPE 被终止。
    这就是“能进房间、一点开始游戏双端立刻闪退”的根因。

    处理：
      1. 游戏进程的 stdout/stderr 重定向到游戏目录内独立日志文件，与大厅句柄解耦；
      2. Windows 使用 DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP；
      3. Linux/WSL 使用 start_new_session（setsid 成为新会话首进程）。
    返回 subprocess.Popen 对象；失败抛异常由调用方处理。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 日志文件名只允许安全字符
    safe_tag = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(log_tag))
    log_path = os.path.join(script_dir, f"game_{safe_tag}.log")

    # 子进程继承该文件句柄；父进程随后关闭自己的副本不影响子进程
    log_file = open(log_path, "ab", buffering=0)

    # 游戏子进程的 stdout 统一为 UTF-8：Windows 中文环境下若按 GBK 写日志，
    # main_gui 里大量 emoji print 会抛 UnicodeEncodeError 并打断后台线程。
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"

    popen_kwargs = {
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "cwd": script_dir,
        "env": child_env,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS(0x08) | CREATE_NEW_PROCESS_GROUP(0x200)
        popen_kwargs["creationflags"] = 0x00000008 | 0x00000200
        popen_kwargs["close_fds"] = True
    else:
        popen_kwargs["start_new_session"] = True
        popen_kwargs["close_fds"] = True

    proc = subprocess.Popen(cmd_args, **popen_kwargs)
    # 父进程关闭自身副本（子进程已 dup 独立句柄）
    try:
        log_file.close()
    except Exception:
        pass
    print(f"DEBUG: 游戏子进程已分离启动 pid={proc.pid} 日志={log_path}", flush=True)
    return proc


def build_game_launch_args(entry_path, game_args):
    """构造拉起游戏进程的命令行，兼容「源码运行」与「PyInstaller 打包」两种形态。

    源码形态：python -u <entry>.py <args>
    打包形态：<exe> --game <args>  （由本文件 __main__ 分发到 main_gui）

    打包后既没有独立的 python.exe，也没有 entry .py 文件，只能复用 exe 自身，
    用 --game 参数让同一个可执行文件切换成游戏进程。
    """
    game_args = list(game_args)
    if getattr(sys, "frozen", False):
        return [sys.executable, "--game"] + game_args
    return [sys.executable, "-u", entry_path] + game_args


def _run_frozen_game(game_args):
    """打包形态入口：把参数原样交给 main_gui，并以主程序身份运行。"""
    role = ""
    for arg in game_args:
        if arg.startswith("--my_role="):
            role = arg.split("=", 1)[1]
            break
    if role:
        os.environ["PLAYER_ROLE"] = role

    # main_gui 在 import 时就会用 argparse 解析 sys.argv，必须先摆好参数
    sys.argv = ["main_gui.py"] + list(game_args)
    import main_gui
    main_gui.main()


class MultiplayerMenu:
    """联机模式选择界面"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("太空狼人杀 - 选择模式")
        self.root.geometry("800x600+300+150")
        self.root.configure(bg="#1a1a2e")

        self.font_family = 'Arial'
        self.font_title_size = 32
        self.font_button_size = 18
        self.font_info_size = 14

        self.server_socket = None
        self.client_socket = None
        self.is_server = False
        self.is_client = False
        self.server_port = 8888
        self.player_count = 0
        self.min_players = 4
        self.max_players = 10
        self.clients = []
        self.running = False
        self.role_assignments = {}
        self.player_names = []
        self.my_role = None
        
        # 房间状态同步
        self.room_state = None
        self.sync_thread = None
        self.sync_running = False
        # 同步客户端列表
        self.sync_clients = []

        self.create_widgets()

    def create_widgets(self):
        title_frame = tk.Frame(self.root, bg="#1a1a2e")
        title_frame.pack(pady=60)

        title_label = tk.Label(
            title_frame,
            text="太空狼人杀",
            font=(self.font_family, self.font_title_size, "bold"),
            fg="#00d4ff",
            bg="#1a1a2e"
        )
        title_label.pack()

        subtitle_label = tk.Label(
            title_frame,
            text="局域网联机版",
            font=(self.font_family, self.font_title_size - 8),
            fg="#4a9eff",
            bg="#1a1a2e"
        )
        subtitle_label.pack()

        button_frame = tk.Frame(self.root, bg="#1a1a2e")
        button_frame.pack(pady=40)

        btn_style = {
            "width": 25,
            "height": 2,
            "font": (self.font_family, self.font_button_size),
            "relief": "flat",
            "cursor": "hand2"
        }

        self.single_btn = tk.Button(
            button_frame,
            text="🎮 单机模式",
            bg="#2d5a87",
            fg="white",
            activebackground="#3d7ab7",
            activeforeground="white",
            command=self.start_single_player,
            **btn_style
        )
        self.single_btn.pack(pady=15)

        self.create_btn = tk.Button(
            button_frame,
            text="🏠 创建房间",
            bg="#2d5a87",
            fg="white",
            activebackground="#3d7ab7",
            activeforeground="white",
            command=self.create_room,
            **btn_style
        )
        self.create_btn.pack(pady=15)

        self.join_btn = tk.Button(
            button_frame,
            text="🔗 加入房间",
            bg="#2d5a87",
            fg="white",
            activebackground="#3d7ab7",
            activeforeground="white",
            command=self.join_room,
            **btn_style
        )
        self.join_btn.pack(pady=15)

        info_label = tk.Label(
            self.root,
            text="提示：创建房间后，其他玩家可通过您的IP地址加入",
            font=(self.font_family, self.font_info_size),
            fg="#888888",
            bg="#1a1a2e"
        )
        info_label.pack(side="bottom", pady=20)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def start_single_player(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_gui_path = os.path.join(script_dir, "main_gui.py")
        try:
            spawn_detached_game([sys.executable, "-u", main_gui_path], "single")
        except Exception as e:
            print(f"启动游戏子进程失败: {e}", flush=True)
        self.root.destroy()

    def create_room(self):
        ip_address = self.get_local_ip()
        if not ip_address:
            messagebox.showerror("错误", "无法获取本机IP地址，请检查网络连接")
            return

        # 创建输入窗口让用户输入房主名称
        input_window = tk.Toplevel(self.root)
        input_window.title("设置房主名称")
        input_window.geometry("400x200+450+250")
        input_window.configure(bg="#1a1a2e")
        input_window.transient(self.root)

        tk.Label(
            input_window,
            text="输入您的名称",
            font=(self.font_family, 18, "bold"),
            fg="#00d4ff",
            bg="#1a1a2e"
        ).pack(pady=20)

        name_entry = tk.Entry(
            input_window,
            font=(self.font_family, 16),
            width=20,
            justify="center",
            relief="flat",
            bg="#16213e",
            fg="#00ff88",
            insertbackground="#00d4ff"
        )
        name_entry.pack(pady=10)
        name_entry.insert(0, "玩家1(房主)")
        name_entry.focus()

        def on_confirm():
            player_name = name_entry.get().strip()
            if not player_name:
                player_name = "玩家1(房主)"
            
            input_window.destroy()
            self.show_server_window(ip_address, player_name)

        button_frame = tk.Frame(input_window, bg="#1a1a2e")
        button_frame.pack(pady=20)

        tk.Button(
            button_frame,
            text="确认",
            font=(self.font_family, 14),
            bg="#00d4ff",
            fg="#1a1a2e",
            relief="flat",
            cursor="hand2",
            command=on_confirm
        ).pack(side="left", padx=10)

        tk.Button(
            button_frame,
            text="取消",
            font=(self.font_family, 14),
            bg="#ff4757",
            fg="white",
            relief="flat",
            cursor="hand2",
            command=input_window.destroy
        ).pack(side="left", padx=10)

        input_window.bind('<Return>', lambda e: on_confirm())

    def show_server_window(self, ip_address, host_name):
        """显示服务器房间窗口"""
        self.is_server = True
        self.player_count = 1
        self.player_names = [host_name]
        self.host_name = host_name

        server_window = tk.Toplevel(self.root)
        server_window.title("房间信息")
        server_window.geometry("500x450+400+200")
        server_window.configure(bg="#1a1a2e")
        server_window.transient(self.root)

        tk.Label(
            server_window,
            text="🏠 房间已创建",
            font=(self.font_family, 24, "bold"),
            fg="#00d4ff",
            bg="#1a1a2e"
        ).pack(pady=20)

        ip_frame = tk.Frame(server_window, bg="#1a1a2e")
        ip_frame.pack(pady=10)

        tk.Label(
            ip_frame,
            text="您的IP地址：",
            font=(self.font_family, 16),
            fg="#ffffff",
            bg="#1a1a2e"
        ).pack(side="left")

        ip_label = tk.Label(
            ip_frame,
            text=ip_address,
            font=(self.font_family, 20, "bold"),
            fg="#00ff88",
            bg="#1a1a2e"
        )
        ip_label.pack(side="left")

        tk.Label(
            server_window,
            text="请将此IP地址分享给其他玩家",
            font=(self.font_family, 12),
            fg="#888888",
            bg="#1a1a2e"
        ).pack(pady=5)

        count_frame = tk.Frame(server_window, bg="#16213e", padx=20, pady=20)
        count_frame.pack(pady=20, fill="both", expand=True, padx=40)

        tk.Label(
            count_frame,
            text="当前房间人数",
            font=(self.font_family, 14),
            fg="#ffffff",
            bg="#16213e"
        ).pack(pady=10)

        self.player_count_label = tk.Label(
            count_frame,
            text=f"{self.player_count} / {self.max_players}",
            font=(self.font_family, 36, "bold"),
            fg="#00d4ff",
            bg="#16213e"
        )
        self.player_count_label.pack(pady=10)

        self.players_listbox = tk.Listbox(
            count_frame,
            font=(self.font_family, 12),
            bg="#0f3460",
            fg="#ffffff",
            width=30,
            height=4,
            relief="flat",
            selectbackground="#00d4ff"
        )
        self.players_listbox.pack(pady=10)
        for name in self.player_names:
            self.players_listbox.insert(tk.END, name)

        status_frame = tk.Frame(server_window, bg="#1a1a2e")
        status_frame.pack(pady=10)

        self.status_label = tk.Label(
            status_frame,
            text=f"等待其他玩家加入...（最少需要{self.min_players}人开始）",
            font=(self.font_family, 12),
            fg="#888888",
            bg="#1a1a2e"
        )
        self.status_label.pack()

        button_frame = tk.Frame(server_window, bg="#1a1a2e")
        button_frame.pack(pady=20)

        self.start_btn = tk.Button(
            button_frame,
            text="开始游戏",
            font=(self.font_family, 14),
            bg="#888888",
            fg="white",
            relief="flat",
            cursor="hand2",
            state="disabled",
            command=lambda: self.start_multiplayer_game(server_window)
        )
        self.start_btn.pack(side="left", padx=10)

        tk.Button(
            button_frame,
            text="取消",
            font=(self.font_family, 14),
            bg="#ff4757",
            fg="white",
            relief="flat",
            cursor="hand2",
            command=lambda: self.close_server(server_window)
        ).pack(side="left", padx=10)

        server_window.protocol("WM_DELETE_WINDOW", lambda: self.close_server(server_window))

        threading.Thread(target=self.start_server, daemon=True).start()

    def join_room(self):
        join_window = tk.Toplevel(self.root)
        join_window.title("加入房间")
        join_window.geometry("500x430+400+200")
        join_window.configure(bg="#1a1a2e")
        join_window.transient(self.root)

        tk.Label(
            join_window,
            text="🔗 加入房间",
            font=(self.font_family, 24, "bold"),
            fg="#00d4ff",
            bg="#1a1a2e"
        ).pack(pady=20)

        tk.Label(
            join_window,
            text="请输入房主的IP地址：",
            font=(self.font_family, 14),
            fg="#ffffff",
            bg="#1a1a2e"
        ).pack(pady=10)

        ip_entry = tk.Entry(
            join_window,
            font=(self.font_family, 16),
            width=20,
            justify="center",
            relief="flat",
            bg="#16213e",
            fg="#00ff88",
            insertbackground="#00d4ff"
        )
        ip_entry.pack(pady=5)
        ip_entry.focus()
        
        tk.Label(
            join_window,
            text="请输入您的名称：",
            font=(self.font_family, 14),
            fg="#ffffff",
            bg="#1a1a2e"
        ).pack(pady=10)

        name_entry = tk.Entry(
            join_window,
            font=(self.font_family, 16),
            width=20,
            justify="center",
            relief="flat",
            bg="#16213e",
            fg="#00ff88",
            insertbackground="#00d4ff"
        )
        name_entry.pack(pady=5)

        count_frame = tk.Frame(join_window, bg="#16213e", padx=20, pady=20)
        count_frame.pack(pady=20, fill="both", expand=True, padx=40)

        self.join_player_count_label = tk.Label(
            count_frame,
            text="等待连接...",
            font=(self.font_family, 12),
            fg="#888888",
            bg="#16213e"
        )
        self.join_player_count_label.pack(pady=10)

        self.join_players_listbox = tk.Listbox(
            count_frame,
            font=(self.font_family, 12),
            bg="#0f3460",
            fg="#ffffff",
            width=30,
            height=3,
            relief="flat",
            selectbackground="#00d4ff"
        )
        self.join_players_listbox.pack(pady=10)
        self.join_players_listbox.insert(0, "连接中...")

        button_frame = tk.Frame(join_window, bg="#1a1a2e")
        button_frame.pack(pady=20)

        tk.Button(
            button_frame,
            text="连接",
            font=(self.font_family, 14),
            bg="#00d4ff",
            fg="#1a1a2e",
            relief="flat",
            cursor="hand2",
            command=lambda: self.connect_to_server(ip_entry.get(), name_entry.get(), join_window)
        ).pack(side="left", padx=10)
        
        join_window.bind('<Return>', lambda e: self.connect_to_server(ip_entry.get(), name_entry.get(), join_window))

        tk.Button(
            button_frame,
            text="取消",
            font=(self.font_family, 14),
            bg="#ff4757",
            fg="white",
            relief="flat",
            cursor="hand2",
            command=join_window.destroy
        ).pack(side="left", padx=10)

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
                if ip.startswith("127."):
                    return None
                return ip
            except Exception:
                return None

    def start_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', self.server_port))
            self.server_socket.listen(self.max_players)
            self.running = True
            self.server_ip = '127.0.0.1'  # 房主自己使用本地IP

            self.root.after(0, lambda: self.status_label.config(
                text="服务器已启动，等待玩家加入...",
                fg="#00ff88"
            ))

            while self.running and self.player_count < self.max_players:
                try:
                    self.server_socket.settimeout(1.0)
                    try:
                        client_socket, address = self.server_socket.accept()
                    
                        # 等待客户端发送玩家名称
                        client_socket.settimeout(10.0)  # 设置超时10秒
                        try:
                            data = client_socket.recv(1024).decode('utf-8')
                            if data:
                                received_data = json.loads(data)
                                if received_data.get('type') == 'player_name':
                                    player_name = received_data.get('name', '').strip()
                                else:
                                    player_name = ''
                            else:
                                player_name = ''
                        except (socket.timeout, json.JSONDecodeError, Exception):
                            player_name = ''
                        
                        # 如果没有输入名称，则根据加入顺序自动分配
                        if not player_name:
                            # 计算下一个可用的玩家编号
                            # 已有玩家数量（不包括房主）
                            existing_players = len([name for name in self.player_names if name != self.host_name])
                            player_num = existing_players + 2  # 房主是玩家1，所以下一个是玩家2
                            player_name = f"玩家{player_num}"
                        
                        # 检查玩家名称是否重复，重复的话自动重命名
                        original_name = player_name
                        counter = 1
                        while player_name in self.player_names:
                            player_name = f"{original_name}({counter})"
                            counter += 1

                        self.player_count += 1
                        self.player_names.append(player_name)
                        self.clients.append({
                            'socket': client_socket,
                            'address': address,
                            'name': player_name
                        })
                        
                        # 向客户端发送服务器分配的名字（可能是重命名后的）
                        try:
                            name_confirm_msg = json.dumps({
                                'type': 'name_confirmed',
                                'my_name': player_name  # 发送服务器分配的名字
                            })
                            client_socket.send((name_confirm_msg + '\n').encode('utf-8'))
                            print(f"✓ 已向 {player_name} 确认其名称")
                        except Exception as e:
                            print(f"✗ 发送名字确认给 {player_name} 失败：{e}")
                        
                        self.root.after(0, lambda ps=client_socket, pn=player_name: self.on_player_joined(ps, pn))
                        self.root.after(0, lambda: self.update_player_list())
                        
                        # 启动线程处理客户端发来的消息
                        threading.Thread(target=self.handle_client_messages, args=(client_socket, player_name), daemon=True).start()

                    except socket.timeout:
                        continue

                except Exception as e:
                    if self.running:
                        pass

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("服务器错误", f"无法启动服务器：{str(e)}"))

    def on_player_joined(self, client_socket, player_name):
        self.status_label.config(text=f"{player_name} 已加入！", fg="#00ff88")
        messagebox.showinfo("玩家加入", f"{player_name} 已成功加入房间！")
    
    def handle_client_messages(self, client_socket, player_name):
        """处理客户端发来的消息（如玩家确认）"""
        try:
            buffer = ""
            while self.running:
                try:
                    client_socket.settimeout(1.0)
                    data = client_socket.recv(4096).decode('utf-8')
                    if not data:
                        break
                    
                    buffer += data
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line:
                            try:
                                json.loads(line)  # 解析消费客户端消息（目前无需处理）
                            except json.JSONDecodeError as e:
                                print(f"JSON解析错误: {e}")
                except socket.timeout:
                    continue
        except Exception as e:
            print(f"处理客户端消息错误: {e}")
        finally:
            client_socket.close()
            self.remove_player_on_disconnect(client_socket, player_name)

    def remove_player_on_disconnect(self, client_socket, player_name):
        """客户端断开后回收名额，避免"幽灵玩家"长期占用房间。

        说明：
        - 游戏开始后大厅即将退出，此处的 UI 更新可能失败，全部静默忽略；
        - 只回收本次连接对应的那个名额，不影响其他玩家。
        """
        try:
            removed = False
            for client in list(self.clients):
                if client.get('socket') is client_socket:
                    self.clients.remove(client)
                    removed = True
                    break
            if player_name in self.player_names:
                self.player_names.remove(player_name)
                removed = True
            if removed:
                self.player_count = max(1, self.player_count - 1)
                print(f"↩️ 玩家断开，已回收名额: {player_name}，当前 {self.player_count} 人", flush=True)
            try:
                self.root.after(0, self.update_player_list)
            except Exception:
                pass
        except Exception as e:
            print(f"回收断线玩家名额失败: {e}", flush=True)

    def update_player_list(self):
        self.players_listbox.delete(0, tk.END)
        for name in self.player_names:
            self.players_listbox.insert(tk.END, name)

        self.player_count_label.config(text=f"{self.player_count} / {self.max_players}")

        if self.player_count >= self.min_players:
            self.start_btn.config(state="normal", bg="#00d4ff", fg="#1a1a2e")
            self.status_label.config(text=f"可以开始游戏了！({self.player_count}/{self.min_players}人)", fg="#00ff88")
        else:
            self.start_btn.config(state="disabled", bg="#888888", fg="white")
            self.status_label.config(text=f"等待更多玩家加入...({self.player_count}/{self.min_players}人)", fg="#888888")

        for client in self.clients:
            try:
                message = json.dumps({
                    'type': 'player_count',
                    'count': self.player_count,
                    'players': self.player_names.copy()
                })
                client['socket'].send((message + '\n').encode('utf-8'))
            except:
                pass

    def connect_to_server(self, ip_address, player_name, window):
        if not ip_address:
            messagebox.showerror("错误", "请输入IP地址")
            return
        
        # 处理玩家名称，默认是玩家n（服务器会分配）
        player_name = player_name.strip()

        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(10)
            self.client_socket.connect((ip_address, self.server_port))
            self.is_client = True
            self.player_names = ["已连接"]
            self.server_ip = ip_address  # 保存服务器IP地址
            
            # 发送玩家名称给服务器
            try:
                name_msg = json.dumps({
                    'type': 'player_name',
                    'name': player_name
                })
                self.client_socket.send((name_msg).encode('utf-8'))
            except Exception as e:
                print(f"发送玩家名称失败: {e}")

            window.destroy()

            connect_window = tk.Toplevel(self.root)
            connect_window.title("等待开始")
            connect_window.geometry("500x300+400+200")
            connect_window.configure(bg="#1a1a2e")

            tk.Label(
                connect_window,
                text="🎮 联机模式",
                font=(self.font_family, 24, "bold"),
                fg="#00d4ff",
                bg="#1a1a2e"
            ).pack(pady=20)

            tk.Label(
                connect_window,
                text=f"已连接到：{ip_address}",
                font=(self.font_family, 14),
                fg="#00ff88",
                bg="#1a1a2e"
            ).pack(pady=10)

            count_frame = tk.Frame(connect_window, bg="#16213e", padx=20, pady=20)
            count_frame.pack(pady=20, fill="both", expand=True, padx=40)

            tk.Label(
                count_frame,
                text="当前房间人数",
                font=(self.font_family, 14),
                fg="#ffffff",
                bg="#16213e"
            ).pack(pady=10)

            self.client_player_count_label = tk.Label(
                count_frame,
                text="等待更新...",
                font=(self.font_family, 36, "bold"),
                fg="#00d4ff",
                bg="#16213e"
            )
            self.client_player_count_label.pack(pady=10)

            self.client_players_listbox = tk.Listbox(
                count_frame,
                font=(self.font_family, 12),
                bg="#0f3460",
                fg="#ffffff",
                width=30,
                height=3,
                relief="flat",
                selectbackground="#00d4ff"
            )
            self.client_players_listbox.pack(pady=10)

            tk.Label(
                connect_window,
                text="等待房主开始游戏...",
                font=(self.font_family, 12),
                fg="#888888",
                bg="#1a1a2e"
            ).pack(pady=10)

            connect_window.protocol("WM_DELETE_WINDOW", self.on_client_closing)

            self.client_connect_window = connect_window

            threading.Thread(target=self.receive_server_messages, daemon=True).start()

        except socket.timeout:
            messagebox.showerror("连接失败", "连接超时，请检查IP地址是否正确")
        except ConnectionRefusedError:
            messagebox.showerror("连接失败", "无法连接到服务器，请确认房间是否已创建")
        except Exception as e:
            messagebox.showerror("连接失败", f"连接错误：{str(e)}")

    def receive_server_messages(self):
        print("客户端开始监听服务器消息...")
        buffer = ""
        while self.is_client and self.client_socket:
            try:
                self.client_socket.settimeout(0.5)
                data = self.client_socket.recv(4096)  # 增大缓冲区
                if data:
                    buffer += data.decode('utf-8')
                    # 处理缓冲区中的所有完整消息
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line:
                            try:
                                print(f"收到服务器数据: {line[:100]}...")
                                message = json.loads(line)
                                self.handle_server_message(message)
                            except json.JSONDecodeError as e:
                                print(f"JSON解析错误: {e}")
                else:
                    # 连接关闭
                    break
            except socket.timeout:
                continue
            except Exception as e:
                print(f"接收消息时出错: {e}")
                break

    def handle_server_message(self, message):
        msg_type = message.get('type')
        print(f"处理消息类型: {msg_type}")

        if msg_type == 'player_count':
            count = message.get('count', 0)
            players = message.get('players', [])
            self.root.after(0, lambda: self._update_player_count_ui(count, players))
        
        elif msg_type == 'name_confirmed':
            # 服务器确认了分配的名字（可能是重命名后的）
            confirmed_name = message.get('my_name', None)
            if confirmed_name:
                self.player_name = confirmed_name
                print(f"✓ 服务器确认我的名字为: {confirmed_name}")

        elif msg_type == 'all_ready' or msg_type == 'start_game':
            # 所有玩家都就绪，开始游戏（兼容两种消息类型）
            # 防重入：all_ready 和 start_game 可能连续到达，避免重复启动
            if getattr(self, '_game_starting', False):
                print(f"忽略重复的游戏开始消息: {msg_type}")
                return
            self._game_starting = True

            print(f"收到游戏开始消息！类型: {msg_type}")
            player_count = message.get('player_count', 0)
            role_assignments = message.get('role_assignments', {})
            player_names = message.get('player_names', [])
            my_role = message.get('my_role', None)
            my_name = message.get('my_name', None)
            sync_port = message.get('sync_port', 12346)
            room_state_data = message.get('room_state', None)

            # 如果已经收到服务器确认的名字，使用确认的名字；否则使用服务器发送的名字
            actual_my_name = getattr(self, 'player_name', None) or my_name
            print(f"我的身份: {my_role}, 我的名字: {actual_my_name}, 同步端口: {sync_port}")
            
            # 初始化房间状态
            self.room_state = RoomState(is_host=False)
            if room_state_data:
                self.room_state.from_dict(room_state_data)
                print(f"✓ 已接收房间状态，玩家数: {len(self.room_state.players)}")

            # 保存角色分配信息
            self.temp_role_assignments = role_assignments
            self.temp_my_role = my_role
            self.temp_my_name = actual_my_name  # 使用服务器确认的名字
            self.temp_player_count = player_count
            self.temp_player_names = player_names
            self.temp_sync_port = sync_port
            
            # 直接进入游戏（窗口销毁在 proceed_client_to_game 中统一处理）
            self.root.after(0, lambda: self.proceed_client_to_game(None))
    
    def _update_player_count_ui(self, count, players):
        try:
            self.join_player_count_label.config(text=f"{count} / {self.max_players}人")
            self.join_players_listbox.delete(0, tk.END)
            for player in players:
                self.join_players_listbox.insert(tk.END, player)
            if count >= self.min_players:
                self.join_player_count_label.config(fg="#00ff88")
        except:
            try:
                self.client_player_count_label.config(text=f"{count} / {self.max_players}人")
                self.client_players_listbox.delete(0, tk.END)
                for player in players:
                    self.client_players_listbox.insert(tk.END, player)
                if count >= self.min_players:
                    self.client_player_count_label.config(fg="#00ff88")
            except:
                pass
    
    def _start_game_for_all(self):
        """全员就绪后，向所有客户端发送开始游戏消息"""
        print("所有玩家都已确认，开始游戏！")
        
        # 初始化房间状态
        self.room_state = RoomState(is_host=True)
        
        # 添加所有玩家到房间状态
        for player_name in self.player_names:
            role = self.role_assignments.get(player_name, "Crewmate")
            self.room_state.add_player(player_name, role)
        
        self.room_state.game_started = True
        
        # 注意：位置同步服务器不再由大厅进程启动。
        # 大厅进程游戏开始后即退出，其 daemon 线程中的同步服务器会随之死亡，
        # 导致所有玩家连接 12346 被拒。同步服务器已移至房主的 main_gui.py 进程内运行。
        
        # 生成配置文件
        self.generate_config_file(self.host_name, self.my_role)
        
        # 向所有客户端发送开始游戏消息
        for idx, client in enumerate(self.clients):
            player_name = self.player_names[idx + 1]
            player_role = self.role_assignments[player_name]
            
            try:
                message = json.dumps({
                    'type': 'all_ready',
                    'player_count': self.player_count,
                    'role_assignments': self.role_assignments,
                    'player_names': self.player_names,
                    'my_role': player_role,
                    'my_name': player_name,
                    'sync_port': 12346,
                    'room_state': self.room_state.to_dict()
                })
                client['socket'].send((message + '\n').encode('utf-8'))
                print(f"✓ 已向 {player_name} 发送全员确认消息")
            except Exception as e:
                print(f"✗ 发送消息给 {player_name} 失败：{e}")
        
        # 房主自己也启动游戏
        # （已移除弹窗提示）
        
        # 房主启动游戏
        self.proceed_to_start_game(None)
    
    def generate_config_file_client(self, my_name, my_role, role_assignments, player_count):
        """客户端生成配置文件"""
        import datetime
        config_data = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "player_count": player_count,
            "assignments": role_assignments,
            "my_name": my_name,
            "my_role": my_role
        }
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 使用玩家名字作为配置文件名的一部分，避免多客户端冲突
        safe_name = my_name.replace(" ", "_").replace("(", "").replace(")", "")
        config_filename = f"player_roles_config_{safe_name}.json"
        config_path = os.path.join(script_dir, config_filename)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 配置文件已生成: {config_path}")
        print(f"📋 配置内容: {config_data}")
        
        return config_path
    
    def proceed_client_to_game(self, confirm_window):
        """客户端确认后启动游戏"""
        print("DEBUG: proceed_client_to_game 开始", flush=True)
        # 生成配置文件
        self.generate_config_file_client(self.temp_my_name, self.temp_my_role, self.temp_role_assignments, self.temp_player_count)
        
        # 关闭窗口（如果窗口存在）
        print("DEBUG: 开始关闭确认窗口", flush=True)
        if confirm_window is not None:
            try:
                confirm_window.destroy()
                print("DEBUG: confirm_window 已销毁", flush=True)
            except:
                pass
        if hasattr(self, 'client_confirm_window') and self.client_confirm_window.winfo_exists():
            try:
                self.client_confirm_window.destroy()
                print("DEBUG: client_confirm_window 已销毁", flush=True)
            except:
                pass
        print("DEBUG: 确认窗口处理完成", flush=True)
        
        # 准备参数
        role_assignments_json = json.dumps(self.temp_role_assignments)
        role_assignments_base64 = base64.b64encode(role_assignments_json.encode()).decode()
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 根据角色类型调用不同的入口文件
        if self.temp_my_role == "Impostor":
            entry_path = os.path.join(script_dir, "impostor_entry.py")
        else:
            entry_path = os.path.join(script_dir, "crewmate_entry.py")
        
        print(f"DEBUG: 准备启动子进程 entry={entry_path}", flush=True)
        # 先启动子进程，再销毁窗口；子进程与大厅完全分离（独立日志/进程组/会话）
        try:
            spawn_detached_game(build_game_launch_args(entry_path, [
                "--multiplayer",
                f"--player_count={self.temp_player_count}",
                f"--roles={role_assignments_base64}",
                f"--names_b64={base64.b64encode(json.dumps(list(self.temp_player_names), ensure_ascii=False).encode('utf-8')).decode()}",
                f"--my_role={self.temp_my_role}",
                f"--my_name={self.temp_my_name}",
                f"--sync_port={self.temp_sync_port}",
                f"--server_ip={self.server_ip}",
            ]), f"client_{self.temp_my_name}")
            print("DEBUG: 子进程已启动", flush=True)
        except Exception as e:
            print(f"启动游戏子进程失败: {e}", flush=True)
        print("DEBUG: 准备销毁 root", flush=True)
        self.root.destroy()

    def assign_roles(self):
        import random

        if self.player_count <= 6:
            num_impostors = 1
        else:
            num_impostors = 2

        all_players = self.player_names.copy()

        impostors = random.sample(all_players, num_impostors)
        for player_name in all_players:
            if player_name in impostors:
                self.role_assignments[player_name] = "Impostor"
            else:
                self.role_assignments[player_name] = "Crewmate"

        self.my_role = self.role_assignments[self.host_name]

        return self.role_assignments

    def generate_config_file(self, my_name, my_role):
        """生成保险配置文件"""
        import datetime
        config_data = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "player_count": self.player_count,
            "assignments": self.role_assignments,
            "my_name": my_name,
            "my_role": my_role
        }
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 使用固定的配置文件名
        config_filename = "player_roles_config.json"
        config_path = os.path.join(script_dir, config_filename)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 配置文件已生成: {config_path}")
        print(f"📋 配置内容: {config_data}")
        
        return config_path

    def start_sync_server(self):
        """启动位置同步服务器（在新线程中运行）"""
        import threading
        
        def sync_server_thread():
            sync_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sync_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 使用一个固定的端口进行同步
            sync_port = 12346
            try:
                sync_socket.bind(('0.0.0.0', sync_port))
                sync_socket.listen(5)
                print(f"📍 位置同步服务器已启动，端口: {sync_port}")
                
                # 启动广播线程
                self.sync_running = True
                threading.Thread(target=self.broadcast_room_state, daemon=True).start()
                
                while self.running:
                    try:
                        sync_socket.settimeout(1.0)
                        client_socket, addr = sync_socket.accept()
                        client_socket.settimeout(None)
                        
                        print(f"✅ 新同步客户端连接: {addr}")
                        
                        # 发送初始房间状态
                        try:
                            if self.room_state:
                                state_message = self.room_state.to_json()
                                client_socket.send((state_message + '\n').encode('utf-8'))
                                print(f"📤 已发送初始房间状态给新客户端")
                        except Exception as e:
                            print(f"发送初始状态失败: {e}")
                        
                        # 添加到同步客户端列表
                        self.sync_clients.append({'socket': client_socket, 'addr': addr})
                        
                        # 创建一个线程处理这个客户端的同步消息
                        threading.Thread(target=self.handle_sync_client, args=(client_socket,), daemon=True).start()
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if self.running:
                            print(f"同步服务器错误: {e}")
            except Exception as e:
                print(f"无法启动同步服务器: {e}")
        
        threading.Thread(target=sync_server_thread, daemon=True).start()
    
    def broadcast_room_state(self):
        """定期广播房间状态给所有同步客户端"""
        while self.sync_running and self.running:
            try:
                if self.room_state:
                    state_message = self.room_state.to_json()
                    for sync_client in self.sync_clients.copy():
                        try:
                            sync_client['socket'].send((state_message + '\n').encode('utf-8'))
                        except Exception as e:
                            print(f"广播状态失败: {e}")
                            # 移除失效的客户端
                            if sync_client in self.sync_clients:
                                self.sync_clients.remove(sync_client)
                
                time.sleep(0.5)  # 每500ms广播一次
            except Exception as e:
                print(f"广播状态线程错误: {e}")
                time.sleep(1)
    
    def handle_sync_client(self, client_socket):
        """处理单个客户端的位置同步消息"""
        try:
            buffer = ""
            while self.running:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    try:
                        message = json.loads(line)
                        self.process_sync_message(message, client_socket)
                    except json.JSONDecodeError:
                        print(f"无效的JSON消息: {line}")
        except Exception as e:
            print(f"同步客户端处理错误: {e}")
        finally:
            # 从同步客户端列表中移除
            for sync_client in self.sync_clients.copy():
                if sync_client['socket'] == client_socket:
                    self.sync_clients.remove(sync_client)
                    break
            client_socket.close()
    
    def process_sync_message(self, message, sender_socket):
        """处理同步消息并转发给其他客户端"""
        msg_type = message.get('type')
        print(f"📨 收到同步消息: {msg_type}")
        
        if msg_type == 'position_update':
            player_name = message.get('player_name')
            location = message.get('location')
            
            # 更新房间状态
            if self.room_state and player_name:
                self.room_state.update_player_location(player_name, location)
            
            # 转发位置更新给所有其他同步客户端
            for sync_client in self.sync_clients:
                if sync_client['socket'] != sender_socket:
                    try:
                        sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"转发位置更新失败: {e}")
        
        elif msg_type == 'sabotage':
            system = message.get('system')
            
            # 更新房间状态
            if self.room_state and system:
                self.room_state.set_sabotage(system, True)
            
            # 转发给所有其他同步客户端
            for sync_client in self.sync_clients:
                if sync_client['socket'] != sender_socket:
                    try:
                        sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"转发系统破坏消息失败: {e}")
        
        elif msg_type == 'repair_sabotage':
            system = message.get('system')
            
            # 更新房间状态
            if self.room_state and system:
                self.room_state.repair_sabotage(system)
            
            # 转发给所有其他同步客户端
            for sync_client in self.sync_clients:
                if sync_client['socket'] != sender_socket:
                    try:
                        sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"转发系统修复消息失败: {e}")
        
        elif msg_type == 'place_bomb':
            location = message.get('location')
            player_name = message.get('player_name')
            explode_time = message.get('explode_time')
            
            # 更新房间状态
            if self.room_state and location:
                self.room_state.bomb_location = location
                if explode_time:
                    self.room_state.bomb_explode_time = explode_time
                else:
                    self.room_state.bomb_explode_time = time.time() + 60
            
            # 转发给所有其他同步客户端
            for sync_client in self.sync_clients:
                if sync_client['socket'] != sender_socket:
                    try:
                        sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"转发炸弹放置消息失败: {e}")
        
        elif msg_type == 'defuse_bomb':
            player_name = message.get('player_name')
            
            # 更新房间状态
            if self.room_state:
                self.room_state.clear_bomb()
            
            # 转发给所有其他同步客户端
            for sync_client in self.sync_clients:
                if sync_client['socket'] != sender_socket:
                    try:
                        sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"转发炸弹拆除消息失败: {e}")
        
        elif msg_type == 'complete_task':
            player_name = message.get('player_name')
            completed_tasks = message.get('completed_tasks', None)
            
            # 更新房间状态
            if self.room_state and player_name:
                if completed_tasks is not None:
                    self.room_state.tasks_completed[player_name] = completed_tasks
                else:
                    self.room_state.complete_task(player_name)
            
            # 转发给所有其他同步客户端
            for sync_client in self.sync_clients:
                if sync_client['socket'] != sender_socket:
                    try:
                        sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"转发任务完成消息失败: {e}")
        
        elif msg_type == 'game_over':
            winner = message.get('winner')
            
            # 更新房间状态
            if self.room_state:
                self.room_state.set_game_over(winner)
            
            # 转发给所有其他同步客户端
            for sync_client in self.sync_clients:
                if sync_client['socket'] != sender_socket:
                    try:
                        sync_client['socket'].send((json.dumps(message) + '\n').encode('utf-8'))
                    except Exception as e:
                        print(f"转发游戏结束消息失败: {e}")
    
    def proceed_to_start_game(self, window):
        """确认后启动游戏"""
        # 初始化房间状态
        self.room_state = RoomState(is_host=True)
        
        # 添加所有玩家到房间状态
        for player_name in self.player_names:
            role = self.role_assignments.get(player_name, "Crewmate")
            self.room_state.add_player(player_name, role)
        
        self.room_state.game_started = True
        
        # 注意：位置同步服务器不再由大厅进程启动。
        # 大厅进程游戏开始后即退出，其 daemon 线程中的同步服务器会随之死亡，
        # 导致所有玩家连接 12346 被拒。同步服务器已移至房主的 main_gui.py 进程内运行。
        
        # 生成配置文件
        self.generate_config_file(self.host_name, self.my_role)
        
        # 发送游戏开始消息给所有客户端
        for idx, client in enumerate(self.clients):
            player_name = self.player_names[idx + 1]
            player_role = self.role_assignments[player_name]
            
            try:
                message = json.dumps({
                    'type': 'start_game',
                    'player_count': self.player_count,
                    'role_assignments': self.role_assignments,
                    'player_names': self.player_names,
                    'my_role': player_role,
                    'my_name': player_name,
                    'sync_port': 12346,
                    'room_state': self.room_state.to_dict()  # 发送房间状态
                })
                client['socket'].send((message + '\n').encode('utf-8'))  # 添加换行符
                print(f"✓ 已向 {player_name} 发送游戏开始消息")
            except Exception as e:
                print(f"✗ 发送消息给 {player_name} 失败：{e}")

        # （已移除弹窗提示）
        
        # 等待一下确保消息发送完成
        time.sleep(0.5)

        # 关闭窗口（如果窗口存在）
        if window is not None:
            window.destroy()
        if hasattr(self, 'host_confirm_window') and self.host_confirm_window.winfo_exists():
            self.host_confirm_window.destroy()

        role_assignments_json = json.dumps(self.role_assignments)
        role_assignments_base64 = base64.b64encode(role_assignments_json.encode()).decode()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 根据角色类型调用不同的入口文件
        if self.my_role == "Impostor":
            entry_path = os.path.join(script_dir, "impostor_entry.py")
        else:
            entry_path = os.path.join(script_dir, "crewmate_entry.py")
        
        # 先启动子进程，再销毁根窗口；子进程与大厅完全分离（独立日志/进程组/会话）
        try:
            spawn_detached_game(build_game_launch_args(entry_path, [
                "--multiplayer", "--server",
                f"--player_count={self.player_count}",
                f"--roles={role_assignments_base64}",
                f"--names_b64={base64.b64encode(json.dumps(list(self.player_names), ensure_ascii=False).encode('utf-8')).decode()}",
                f"--my_role={self.my_role}",
                f"--my_name={self.host_name}",
                "--sync_port=12346",
            ]), f"host_{self.host_name}")
        except Exception as e:
            print(f"启动游戏子进程失败: {e}", flush=True)
        self.root.destroy()
    
    def start_multiplayer_game(self, window):
        if self.player_count < self.min_players:
            messagebox.showwarning("人数不足", f"至少需要{self.min_players}名玩家才能开始游戏！")
            return

        self.assign_roles()
        
        # 直接进入游戏，不显示确认界面
        self._start_game_for_all()
    
    def close_server(self, window):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        for client in self.clients:
            try:
                client['socket'].close()
            except:
                pass

        window.destroy()
        self.is_server = False
        self.clients = []
        self.player_count = 0

    def on_closing(self):
        if self.is_server:
            self.running = False
            if self.server_socket:
                try:
                    self.server_socket.close()
                except:
                    pass

        if self.is_client and self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass

        self.root.destroy()
        sys.exit()

    def on_client_closing(self):
        if self.is_client and self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        sys.exit()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    # 打包形态：exe --game <参数> 表示"以游戏进程身份运行"，交给 main_gui
    if getattr(sys, "frozen", False) and len(sys.argv) > 1 and sys.argv[1] == "--game":
        _run_frozen_game(sys.argv[2:])
    else:
        menu = MultiplayerMenu()
        menu.run()
