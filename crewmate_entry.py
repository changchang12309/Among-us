#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""船员角色入口文件
当服务器分配玩家为船员时，调用此文件。

历史与根因：
  原实现用 `os.execv` 把当前进程替换成 main_gui.py。
  但 Windows 的 os.execv 在重建命令行时不会给含空格的参数加引号，而本项目
  路径含两个空格（`Among-us  v2.0.0`），导致 python.exe 收到的脚本路径在
  空格处被截断，实测报错：
      python.exe: can't open file 'C:\\...\\Desktop\\Among-us': [Errno 2]
  游戏进程因此根本没起来，表现为"点开始游戏后闪退"。

现实现：
  改用 runpy 在同一进程内以 __main__ 执行 main_gui.py：
  1. 不经过命令行重建，路径含空格也安全；
  2. PID 不变，不产生中间进程/孤儿进程；
  3. 标准输出与日志继承关系不变（配合 -u 无缓冲）。
"""
import os
import runpy
import sys

# 设置环境变量，表示当前是船员角色
os.environ['PLAYER_ROLE'] = 'Crewmate'

script_dir = os.path.dirname(os.path.abspath(__file__))
main_gui_path = os.path.join(script_dir, "main_gui.py")

# main_gui.py 顶部的 argparse 读取 sys.argv[1:]，这里把脚本名放回 argv[0]
sys.argv = [main_gui_path] + sys.argv[1:]
os.chdir(script_dir)

# 以 __main__ 执行，等价于 `python main_gui.py <args>`
runpy.run_path(main_gui_path, run_name="__main__")
