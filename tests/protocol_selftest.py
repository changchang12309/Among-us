#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太空狼人杀 v2.0.0 —— 联机协议层自测（无 GUI / 无 X11 / 不起游戏进程）

设计目标：
  * 不创建任何 tkinter 窗口（窗口对象用假桩替代，只记录调用）；
  * 不启动 main_gui / multiplayergui 子进程，不写角色分配文件；
  * 但网络协议部分复用**游戏本体的真实方法**，而不是重写一份模拟实现：
      - A. 8888 房间协议    -> multiplayer.MultiplayerMenu.start_server
                             multiplayer.MultiplayerMenu.update_player_list
                             multiplayer.MultiplayerMenu._start_game_for_all
                             multiplayer.MultiplayerMenu.proceed_to_start_game
                             multiplayer.MultiplayerMenu.assign_roles
      - B. 客户端消息分发   -> multiplayer.MultiplayerMenu.handle_server_message
      - C. 12346 同步协议   -> main_gui.AmongUsGUI.start_sync_server
                             main_gui.AmongUsGUI.broadcast_room_state
                             main_gui.AmongUsGUI.handle_sync_client
                             main_gui.AmongUsGUI.handle_sync_server_message
      - D. 房间状态序列化   -> room_state.RoomState.to_json / from_json

用法：
    python -u tests/protocol_selftest.py

退出码：0 = 全部通过（含已知缺陷 XFAIL）；1 = 有 FAIL。
"""

import base64
import json
import os
import socket
import sys
import threading
import time
import types

# 控制台编码兜底（项目代码里有 emoji print，避免 UnicodeEncodeError 打断测试）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

GAME_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GAME_DIR not in sys.path:
    sys.path.insert(0, GAME_DIR)

# ============================ 结果记录 ============================

_PASS = []
_FAIL = []
_XFAIL = []
_XPASS = []
_ARTIFACTS = []  # 测试运行会顺带产生的文件（需人工清理）


def check(name, cond, detail=""):
    """普通断言：预期行为。"""
    cond = bool(cond)
    if cond:
        _PASS.append(name)
        print(f"PASS   | {name}")
    else:
        _FAIL.append((name, detail))
        print(f"FAIL   | {name}" + (f"  <- {detail}" if detail else ""))
    return cond


def check_xfail(name, correct_behavior, detail=""):
    """已知缺陷断言：correct_behavior 为 True 表示缺陷已修复。"""
    if correct_behavior:
        _XPASS.append(name)
        print(f"XPASS  | {name}  <- 缺陷已修复，请更新本用例")
    else:
        _XFAIL.append(name)
        print(f"XFAIL  | {name}（已知缺陷，本轮只记录不修复）" + (f"  <- {detail}" if detail else ""))


# ============================ 网络小工具 ============================


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Peer:
    """测试用裸 socket 对端：后台线程收集所有 JSON 行帧，支持等待/快照。"""

    def __init__(self, sock):
        self.sock = sock
        self.frames = []
        self._lock = threading.Lock()
        self.closed = False
        threading.Thread(target=self._reader, daemon=True).start()

    @classmethod
    def connect(cls, port, timeout=8.0):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                return cls(socket.create_connection(("127.0.0.1", port), timeout=1.5))
            except OSError as exc:
                last = exc
                time.sleep(0.05)
        raise last if last else RuntimeError("connect failed")

    def _reader(self):
        buf = b""
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    with self._lock:
                        self.frames.append(msg)
        except Exception:
            pass
        self.closed = True

    def send(self, obj, sep="\n"):
        self.sock.sendall((json.dumps(obj) + sep).encode("utf-8"))

    def send_raw(self, text):
        self.sock.sendall(text.encode("utf-8"))

    def snapshot(self):
        with self._lock:
            return list(self.frames)

    def wait(self, pred, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                for msg in self.frames:
                    if pred(msg):
                        return msg
            time.sleep(0.02)
        return None

    def wait_count(self, pred, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                n = len([m for m in self.frames if pred(m)])
            if n:
                return n
            time.sleep(0.02)
        return 0

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def wait_until(pred, timeout=5.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


# ============================ tkinter 假桩 ============================


class FakeWidget:
    def config(self, *a, **k):
        pass

    configure = config

    def delete(self, *a, **k):
        pass

    def insert(self, *a, **k):
        pass

    def winfo_exists(self):
        return False


class ImmediateRoot:
    """after() 立即执行（等价于 mainloop 空闲瞬间执行），用于驱动服务端 UI 回调。"""

    def after(self, ms, fn=None, *a):
        if fn:
            fn(*a)

    def destroy(self):
        pass


class DeferredRoot:
    """after() 只记录不执行，用于观察"客户端被要求启动游戏几次"。"""

    def __init__(self):
        self.scheduled = []

    def after(self, ms, fn=None, *a):
        if fn:
            self.scheduled.append(fn)

    def destroy(self):
        pass


def make_menu_stub(port):
    """绕过 MultiplayerMenu.__init__（它会建 Tk 窗口），只补齐 start_server 需要的属性。"""
    import multiplayer as mp

    menu = mp.MultiplayerMenu.__new__(mp.MultiplayerMenu)
    menu.root = ImmediateRoot()
    menu.status_label = FakeWidget()
    menu.players_listbox = FakeWidget()
    menu.player_count_label = FakeWidget()
    menu.start_btn = FakeWidget()
    menu.server_port = port
    menu.max_players = 10
    menu.min_players = 2
    menu.running = True
    menu.player_count = 1
    menu.player_names = ["玩家1(房主)"]
    menu.host_name = "玩家1(房主)"
    menu.clients = []
    menu.server_socket = None
    menu.is_server = True
    menu.role_assignments = {}
    menu.my_role = None
    return menu


# ============================ A. 8888 房间协议 ============================


def scenario_room_protocol():
    print("\n=== A. 8888 房间协议（复用真实 start_server / _start_game_for_all）===")
    import multiplayer as mp

    mp.messagebox = types.SimpleNamespace(
        showinfo=lambda *a, **k: None,
        showerror=lambda *a, **k: None,
        showwarning=lambda *a, **k: None,
    )

    spawn_calls = []
    mp.spawn_detached_game = lambda cmd, tag: (
        spawn_calls.append((list(cmd), tag)) or types.SimpleNamespace(pid=0)
    )

    port = free_port()
    menu = make_menu_stub(port)
    # 不落盘：拦截配置文件写入
    menu.generate_config_file = lambda *a, **k: os.path.join(GAME_DIR, ".__skipped__.json")
    threading.Thread(target=mp.MultiplayerMenu.start_server, args=(menu,), daemon=True).start()

    # --- A1 客户端连接与名字确认 ---
    client = Peer.connect(port)
    # 真实客户端发送时**不带换行**（multiplayer.py:676），这里保持一致以复现真实行为
    client.send({"type": "player_name", "name": "玩家2"}, sep="")

    confirmed = client.wait(lambda m: m.get("type") == "name_confirmed", 6)
    check("A1 房主回 name_confirmed", confirmed is not None)
    check("A1 name_confirmed 名字与请求一致",
          confirmed and confirmed.get("my_name") == "玩家2",
          f"实际={confirmed!r}")

    count_msg = client.wait(lambda m: m.get("type") == "player_count", 6)
    check("A2 收到 player_count 广播", count_msg is not None)
    check("A2 人数为 2", count_msg and count_msg.get("count") == 2, f"实际={count_msg!r}")
    check("A2 名单含房主与客户端",
          count_msg and count_msg.get("players") == ["玩家1(房主)", "玩家2"],
          f"实际={count_msg!r}")

    # --- A3 开始游戏：all_ready + start_game 双消息 ---
    ok = wait_until(lambda: menu.player_count == 2, 3)
    check("A3 服务端已记录 2 名玩家", ok, f"player_count={menu.player_count}")

    mp.MultiplayerMenu.start_multiplayer_game(menu, None)

    all_ready = client.wait(lambda m: m.get("type") == "all_ready", 6)
    start_game = client.wait(lambda m: m.get("type") == "start_game", 6)
    check("A3 客户端收到 all_ready", all_ready is not None)
    check("A3 客户端收到 start_game", start_game is not None)
    check("A3 两条消息都带 sync_port=12346",
          all_ready and start_game
          and all_ready.get("sync_port") == 12346 and start_game.get("sync_port") == 12346,
          f"all_ready={all_ready and all_ready.get('sync_port')}, "
          f"start_game={start_game and start_game.get('sync_port')}")

    roles = (start_game or {}).get("role_assignments") or {}
    names = (start_game or {}).get("player_names") or []
    check("A4 role_assignments 覆盖全部玩家",
          set(roles.keys()) == {"玩家1(房主)", "玩家2"}, f"实际={roles!r}")
    check("A4 2 人局恰好 1 名内鬼",
          len([r for r in roles.values() if r == "Impostor"]) == 1, f"实际={roles!r}")
    check("A4 my_role 与 role_assignments[my_name] 一致",
          start_game and roles.get(start_game.get("my_name")) == start_game.get("my_role"),
          f"实际 my_name={start_game and start_game.get('my_name')}, "
          f"my_role={start_game and start_game.get('my_role')}")
    check("A4 player_names 长度为 2 且含两端名字",
          names == ["玩家1(房主)", "玩家2"], f"实际={names!r}")
    check("A4 room_state 随 start_game 下发且含 2 名玩家",
          start_game and isinstance(start_game.get("room_state"), dict)
          and len(start_game["room_state"].get("players", {})) == 2,
          f"实际={start_game and start_game.get('room_state')}")

    # --- A5 房主进程启动参数 ---
    check("A5 房主只启动 1 个游戏进程", len(spawn_calls) == 1, f"实际={len(spawn_calls)}")
    cmd = spawn_calls[0][0] if spawn_calls else []
    joined = " ".join(str(x) for x in cmd)
    check("A5 参数含 --multiplayer --server",
          "--multiplayer" in cmd and "--server" in cmd, joined)
    check("A5 由 entry 脚本启动（角色入口）",
          any(str(x).endswith("_entry.py") for x in cmd), joined)
    check("A5 含 --sync_port=12346", "--sync_port=12346" in cmd, joined)

    # --- A6 命令行参数可还原（模拟 main_gui 的解析方式）---
    roles_arg = next((x for x in cmd if str(x).startswith("--roles=")), None)
    names_arg = next((x for x in cmd if str(x).startswith("--names_b64=")), None)
    decoded_roles = None
    if roles_arg:
        try:
            raw = base64.b64decode(roles_arg.split("=", 1)[1].encode()).decode()
            decoded_roles = json.loads(raw)
        except Exception as exc:
            decoded_roles = f"解码失败: {exc}"
    check("A6 --roles 可被 base64+JSON 还原", decoded_roles == menu.role_assignments,
          f"还原={decoded_roles!r}, 期望={menu.role_assignments!r}")

    decoded_names = None
    if names_arg:
        try:
            decoded_names = json.loads(
                base64.b64decode(names_arg.split("=", 1)[1].encode()).decode())
        except Exception as exc:
            decoded_names = f"解码失败: {exc}"
    check("A6 --names_b64 可还原名单", decoded_names == menu.player_names,
          f"还原={decoded_names!r}, 期望={menu.player_names!r}")

    # --- A7 回归：含逗号/空格的名字经 base64 传递必须完整还原 ---
    bad_names = ["玩家1(房主)", "A,B", "带 空格 的名字"]
    bad_b64 = base64.b64encode(
        json.dumps(bad_names, ensure_ascii=False).encode("utf-8")).decode()
    restored = json.loads(base64.b64decode(bad_b64.encode()).decode("utf-8"))
    check("A7 含逗号/空格的名字经 base64 往返保持完整",
          restored == bad_names, f"还原={restored!r}, 期望={bad_names!r}")

    # 收尾
    menu.running = False
    client.close()
    try:
        menu.server_socket.close()
    except Exception:
        pass
    time.sleep(0.2)


def scenario_duplicate_name():
    print("\n=== A2. 重名自动重命名（复用真实 start_server）===")
    import multiplayer as mp

    mp.messagebox = types.SimpleNamespace(
        showinfo=lambda *a, **k: None,
        showerror=lambda *a, **k: None,
        showwarning=lambda *a, **k: None,
    )
    port = free_port()
    menu = make_menu_stub(port)
    threading.Thread(target=mp.MultiplayerMenu.start_server, args=(menu,), daemon=True).start()

    c1 = Peer.connect(port)
    c1.send({"type": "player_name", "name": "同名玩家"}, sep="")
    m1 = c1.wait(lambda m: m.get("type") == "name_confirmed", 6)
    check("A2 第一个连接保留原名", m1 and m1.get("my_name") == "同名玩家", f"实际={m1!r}")

    c2 = Peer.connect(port)
    c2.send({"type": "player_name", "name": "同名玩家"}, sep="")
    m2 = c2.wait(lambda m: m.get("type") == "name_confirmed", 6)
    check("A2 重名连接被自动重命名", m2 and m2.get("my_name") == "同名玩家(1)", f"实际={m2!r}")

    menu.running = False
    c1.close()
    c2.close()
    try:
        menu.server_socket.close()
    except Exception:
        pass
    time.sleep(0.2)


# ============================ E. 客户端启动参数 ============================


def scenario_client_launch_args():
    print("\n=== E. 客户端启动参数（复用真实 proceed_client_to_game）===")
    import multiplayer as mp

    original_spawn = mp.spawn_detached_game
    mp.messagebox = types.SimpleNamespace(
        showinfo=lambda *a, **k: None,
        showerror=lambda *a, **k: None,
        showwarning=lambda *a, **k: None,
    )
    try:
        for role, expect_entry in (("Impostor", "impostor_entry.py"),
                                   ("Crewmate", "crewmate_entry.py")):
            calls = []
            mp.spawn_detached_game = (
                lambda cmd, tag, _c=calls: _c.append((list(cmd), tag))
                or types.SimpleNamespace(pid=0)
            )
            try:
                stub = types.SimpleNamespace()
                stub.root = ImmediateRoot()
                stub.temp_role_assignments = {"玩家1(房主)": "Impostor", "玩家2": role}
                stub.temp_my_role = role
                stub.temp_my_name = "玩家2"
                stub.temp_player_count = 2
                stub.temp_player_names = ["玩家1(房主)", "玩家2"]
                stub.temp_sync_port = 12346
                stub.server_ip = "192.168.3.41"
                stub.generate_config_file_client = lambda *a, **k: "stub.json"
                mp.MultiplayerMenu.proceed_client_to_game(stub, None)
            finally:
                mp.spawn_detached_game = original_spawn

            cmd = calls[0][0] if calls else []
            joined = " ".join(str(x) for x in cmd)
            check(f"E1 {role} 客户端 1 次启动且含 --multiplayer",
                  len(calls) == 1 and "--multiplayer" in cmd, f"calls={len(calls)} {joined}")
            check(f"E2 {role} 选择正确角色入口 {expect_entry}",
                  any(str(x).endswith(expect_entry) for x in cmd), joined)
            check(f"E3 {role} 透传房主 IP（--server_ip=192.168.3.41）",
                  "--server_ip=192.168.3.41" in cmd, joined)
            check(f"E4 {role} 透传身份与名字",
                  f"--my_role={role}" in cmd and "--my_name=玩家2" in cmd, joined)
            check(f"E5 {role} 同步端口一致", "--sync_port=12346" in cmd, joined)
    finally:
        mp.spawn_detached_game = original_spawn


# ============================ F. 异常输入与断线 ============================


def scenario_bad_input_and_disconnect():
    print("\n=== F. 非法名字与断线（复用真实 start_server）===")
    import multiplayer as mp

    mp.messagebox = types.SimpleNamespace(
        showinfo=lambda *a, **k: None,
        showerror=lambda *a, **k: None,
        showwarning=lambda *a, **k: None,
    )
    port = free_port()
    menu = make_menu_stub(port)
    threading.Thread(target=mp.MultiplayerMenu.start_server, args=(menu,), daemon=True).start()

    # F1 非法 JSON 名字帧：服务端不应崩溃，应回退为自动命名
    c = Peer.connect(port)
    c.send_raw("这不是JSON")
    auto = c.wait(lambda m: m.get("type") == "name_confirmed", 6)
    check("F1 非法名字帧不导致服务端崩溃", auto is not None, f"实际={auto!r}")
    check("F1 非法名字帧回退为自动命名（玩家2）",
          auto and auto.get("my_name") == "玩家2", f"实际={auto!r}")

    # F2 客户端断开后：人数是否回落（文档记录的"幽灵玩家"问题）
    check("F2 断开前人数为 2", wait_until(lambda: menu.player_count == 2, 3),
          f"实际={menu.player_count}")
    c.close()
    time.sleep(1.5)
    check("F2 客户端断开后人数回落到 1",
          menu.player_count == 1,
          f"实际 player_count={menu.player_count}, player_names={menu.player_names}")

    menu.running = False
    try:
        menu.server_socket.close()
    except Exception:
        pass
    time.sleep(0.2)


# ============================ B. 客户端消息分发 ============================


def scenario_client_dispatch():
    print("\n=== B. 客户端消息分发（复用真实 handle_server_message）===")
    import multiplayer as mp

    stub = types.SimpleNamespace()
    stub.root = DeferredRoot()
    stub.player_name = "玩家2"
    stub.proceed_client_to_game = lambda win: None

    role_assignments = {"玩家1(房主)": "Impostor", "玩家2": "Crewmate"}
    payload = {
        "type": "all_ready",
        "player_count": 2,
        "role_assignments": role_assignments,
        "player_names": ["玩家1(房主)", "玩家2"],
        "my_role": "Crewmate",
        "my_name": "玩家2",
        "sync_port": 12346,
        "room_state": {
            "type": "room_state",
            "players": {
                "玩家1(房主)": {"location": "飞船大厅", "is_alive": True,
                                "role": "Impostor", "tasks_completed": 0},
                "玩家2": {"location": "飞船大厅", "is_alive": True,
                          "role": "Crewmate", "tasks_completed": 0},
            },
        },
    }
    start_payload = dict(payload, type="start_game")

    mp.MultiplayerMenu.handle_server_message(stub, payload)
    mp.MultiplayerMenu.handle_server_message(stub, start_payload)

    check("B1 客户端解析 room_state 得到 2 名玩家",
          getattr(stub, "room_state", None) is not None
          and len(stub.room_state.players) == 2,
          f"实际={getattr(getattr(stub, 'room_state', None), 'players', None)!r}")
    check("B2 玩家名字取服务器确认值", getattr(stub, "temp_my_name", None) == "玩家2",
          f"实际={getattr(stub, 'temp_my_name', None)!r}")
    check("B3 同步端口透传正确", getattr(stub, "temp_sync_port", None) == 12346,
          f"实际={getattr(stub, 'temp_sync_port', None)!r}")
    check("B4 角色分配透传正确", getattr(stub, "temp_role_assignments", None) == role_assignments,
          f"实际={getattr(stub, 'temp_role_assignments', None)!r}")
    check("B5 all_ready + start_game 连续到达只启动一次游戏（防重入）",
          len(stub.root.scheduled) == 1, f"实际调度次数={len(stub.root.scheduled)}")


# ============================ C. 12346 位置同步 ============================


def import_main_gui():
    """main_gui 在 import 时会 parse_args()，必须先把 argv 清干净。

    注意：main_gui 顶部的 _setup_crash_logger() 会在游戏目录写 crash_<pid>.log，
    这是导入副作用、无法在进程内删除（文件被占用），本脚本会记录路径供人工清理。
    """
    saved = sys.argv
    sys.argv = [saved[0]]
    try:
        import main_gui
    finally:
        sys.argv = saved
    crash_log = os.environ.get("MAIN_GUI_CRASH_LOG")
    if crash_log:
        _ARTIFACTS.append(crash_log)
    return main_gui


def scenario_sync_protocol():
    print("\n=== C. 12346 位置同步（复用真实 start_sync_server / 转发逻辑）===")
    from room_state import RoomState

    mg = import_main_gui()
    port = free_port()
    mg.sync_port_from_args = port  # 服务端线程运行时读取该全局

    host = types.SimpleNamespace()
    host.sync_server_started = False
    host.sync_running = True
    host.sync_clients = []
    host.room_state = RoomState(is_host=True)
    host.room_state.add_player("玩家1(房主)", "Crewmate")
    host.room_state.add_player("玩家2", "Impostor")
    host.start_sync_server = lambda: mg.AmongUsGUI.start_sync_server(host)
    host.broadcast_room_state = lambda: mg.AmongUsGUI.broadcast_room_state(host)
    host.handle_sync_client = lambda sock: mg.AmongUsGUI.handle_sync_client(host, sock)
    host.handle_sync_server_message = lambda msg, sock: \
        mg.AmongUsGUI.handle_sync_server_message(host, msg, sock)

    host.start_sync_server()

    peer_a = Peer.connect(port)
    peer_b = Peer.connect(port)

    # --- C1 新连接收到初始房间状态 ---
    init_a = peer_a.wait(lambda m: m.get("type") == "room_state", 6)
    init_b = peer_b.wait(lambda m: m.get("type") == "room_state", 6)
    check("C1 客户端 A 收到初始 room_state", init_a is not None)
    check("C1 客户端 B 收到初始 room_state", init_b is not None)
    check("C1 初始状态含 2 名玩家",
          init_a is not None and len(init_a.get("players", {})) == 2,
          f"实际={init_a and init_a.get('players')}")
    check("C2 服务端已登记 2 个同步客户端",
          wait_until(lambda: len(host.sync_clients) == 2, 3),
          f"实际={len(host.sync_clients)}")

    # --- C3 位置更新：转发给他人、不回显给自己、写回房主状态 ---
    a_before = len([m for m in peer_a.snapshot() if m.get("type") == "position_update"])
    peer_a.send({"type": "position_update", "player_name": "玩家2", "location": "监控室"})

    relayed = peer_b.wait(
        lambda m: m.get("type") == "position_update"
        and m.get("player_name") == "玩家2"
        and m.get("location") == "监控室", 4)
    check("C3 位置更新被转发给另一端", relayed is not None, f"B 收到={relayed!r}")
    time.sleep(0.7)
    a_after = len([m for m in peer_a.snapshot() if m.get("type") == "position_update"])
    check("C3 位置更新不回显给发送者", a_after == a_before, f"发送前={a_before}, 发送后={a_after}")
    check("C3 房主 RoomState 已更新位置",
          host.room_state.players["玩家2"]["location"] == "监控室",
          f"实际={host.room_state.players['玩家2']['location']!r}")
    check("C4 广播的 room_state 带最新位置",
          peer_b.wait(lambda m: m.get("type") == "room_state"
                      and m.get("players", {}).get("玩家2", {}).get("location") == "监控室", 4)
          is not None)

    # --- C5 破坏系统同步 ---
    peer_a.send({"type": "sabotage", "system": "oxygen", "player_name": "玩家1(房主)"})
    check("C5 破坏消息被转发", peer_b.wait(
        lambda m: m.get("type") == "sabotage" and m.get("system") == "oxygen", 4) is not None)
    check("C5 房主 RoomState 记录氧气破坏",
          host.room_state.oxygen_sabotaged is True and host.room_state.oxygen_timeout is not None,
          f"oxygen_sabotaged={host.room_state.oxygen_sabotaged}, "
          f"timeout={host.room_state.oxygen_timeout}")

    # --- C6 游戏结束广播 ---
    peer_a.send({"type": "game_over", "winner": "impostor", "reason": "selftest"})
    check("C6 game_over 被转发", peer_b.wait(lambda m: m.get("type") == "game_over", 4) is not None)
    check("C6 房主 RoomState 记录结束状态",
          host.room_state.game_over is True and host.room_state.winner == "impostor",
          f"game_over={host.room_state.game_over}, winner={host.room_state.winner!r}")

    # --- C7 断开清理 ---
    peer_a.close()
    check("C7 客户端断开后服务端移除该连接",
          wait_until(lambda: len(host.sync_clients) == 1, 6),
          f"实际={len(host.sync_clients)}")

    # --- C8 重复启动幂等（防 Errno 98）---
    t0 = time.time()
    host.start_sync_server()
    elapsed = time.time() - t0
    check("C8 重复调用 start_sync_server 立即返回（幂等）",
          elapsed < 1.0 and host.sync_server_started is True,
          f"耗时={elapsed:.3f}s")

    # --- C9 房间状态序列化往返 ---
    raw_json = host.room_state.to_json()
    restored = RoomState()
    restored.from_json(raw_json)
    check("C9 RoomState JSON 往返保持玩家集合",
          set(restored.players.keys()) == set(host.room_state.players.keys()),
          f"还原={list(restored.players.keys())}")
    check("C9 RoomState JSON 往返保持破坏与结束状态",
          restored.oxygen_sabotaged is True and restored.game_over is True
          and restored.winner == "impostor",
          f"oxygen={restored.oxygen_sabotaged}, over={restored.game_over}, "
          f"winner={restored.winner!r}")

    # 收尾
    host.sync_running = False
    peer_b.close()
    time.sleep(0.3)


# ============================ 主流程 ============================


def main():
    print(f"项目目录: {GAME_DIR}")
    print(f"Python: {sys.version.split()[0]}  平台: {sys.platform}")

    t0 = time.time()
    # 每个场景独立端口、独立桩对象，互不污染
    for fn in (scenario_room_protocol, scenario_duplicate_name,
               scenario_client_launch_args, scenario_bad_input_and_disconnect,
               scenario_client_dispatch, scenario_sync_protocol):
        try:
            fn()
        except Exception:
            import traceback
            print(f"FAIL   | 场景 {fn.__name__} 异常中断")
            traceback.print_exc()
            _FAIL.append((f"场景 {fn.__name__} 异常中断", "见上方 traceback"))

    elapsed = time.time() - t0
    print("\n" + "=" * 62)
    print(f"通过 {len(_PASS)} 项 | 失败 {len(_FAIL)} 项 | "
          f"已知缺陷 {len(_XFAIL)} 项 | 缺陷消失 {len(_XPASS)} 项 | 耗时 {elapsed:.1f}s")
    if _FAIL:
        print("\n失败清单：")
        for name, detail in _FAIL:
            print(f"  - {name}" + (f"  <- {detail}" if detail else ""))
    if _XFAIL:
        print("\n已知缺陷清单（本轮不修复，仅记录）：")
        for name in _XFAIL:
            print(f"  - {name}")
    if _ARTIFACTS:
        print("\n测试副产物（导入 main_gui 触发其崩溃日志器，进程退出后可删除）：")
        for path in dict.fromkeys(_ARTIFACTS):
            print(f"  - {path}")
    print("=" * 62)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
