#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
摩斯密码解锁小游戏（修复bordercolor报错+输错红框抖动+浅蓝色进度条+自适应缩放）
"""
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import random
import sys
import os

if sys.platform == 'win32':
    try:
        # 设置高DPI感知
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass


class MorseCodeUnlockGame:
    def __init__(self, root):
        # 初始化主窗口
        self.root = root
        self.root.title("摩斯密码解锁")
        self.root.geometry("1000x1000+460+165")
        self.root.resizable(True, True)  # 允许窗口缩放
        
        # 摩斯密码与数字对应表
        self.morse_dict = {
            "1": "•----",
            "2": "••---",
            "3": "•••--",
            "4": "••••-",
            "5": "•••••",
            "6": "-••••",
            "7": "--•••",
            "8": "---••",
            "9": "----•",
            "0": "-----"
        }
        
        # 游戏核心变量
        self.ending = 0
        self.target_numbers = [str(random.randint(0, 9)) for _ in range(5)]  # 随机5个目标数字
        self.target_morse = [self.morse_dict[num] for num in self.target_numbers]  # 对应摩斯密码
        self.input_record = []  # 玩家输入的数字
        self.progress = 0  # 解锁进度（0-100%）
        self.flash_state = True  # 校徽闪烁状态
        self.gradient_step = 0  # 渐变动画步数
        self.target_bg = "#1a1a2e"  # 破解界面目标色调（深蓝）
        self.start_bg = "#add8e6"   # 初始浅蓝背景
        self.computer_screen_color = "#e0f7fa"  # 电脑屏幕固定颜色（不渐变）
        self.progress_color = "#add8e6"         # 进度条浅蓝色
        self.shake_count = 0  # 抖动次数计数器
        self.original_x = 0   # 破解窗口初始X坐标
        
        # 界面Frame切换（初始/摩斯解锁/成功界面）
        self.frame_start = tk.Frame(self.root, bg=self.start_bg)  # 初始浅蓝背景
        
        # 修复：用嵌套Frame模拟边框（外层Frame做边框，内层做内容）
        # 外层边框Frame（初始背景=目标背景，输错变红）
        self.frame_morse_border = tk.Frame(
            self.root, 
            bg=self.target_bg,  # 初始边框色与背景一致
            bd=0
        )
        # 内层内容Frame（破解界面主体）
        self.frame_morse = tk.Frame(
            self.frame_morse_border, 
            bg=self.target_bg
        )
        
        self.frame_success = tk.Frame(self.root, bg="#add8e6")    # 成功界面浅蓝
        
        # 自定义进度条样式（浅蓝色）
        self._custom_progress_style()
        
        # 启动初始动画界面
        self._create_start_animation()
        self.frame_start.pack(fill="both", expand=True)
        # 启动整张界面渐变动画（3秒完成）
        self._start_full_gradient_animation()

    # -------------------------- 自定义浅蓝色进度条样式 --------------------------
    def _custom_progress_style(self):
        # 创建自定义进度条样式
        style = ttk.Style()
        style.theme_use('default')
        
        # 解锁界面进度条样式（浅蓝色）
        style.configure(
            "LightBlue.Horizontal.TProgressbar",
            troughcolor=self.target_bg,  # 进度条背景（与破解界面一致）
            background=self.progress_color,  # 进度条填充色（浅蓝色）
            bordercolor=self.progress_color,
            lightcolor=self.progress_color,
            darkcolor=self.progress_color
        )
        
        # 成功界面进度条样式（浅蓝色）
        style.configure(
            "Success.LightBlue.Horizontal.TProgressbar",
            troughcolor="#add8e6",  # 成功界面背景
            background=self.progress_color,  # 浅蓝色进度条
            bordercolor=self.progress_color,
            lightcolor=self.progress_color,
            darkcolor=self.progress_color
        )

    # -------------------------- 初始动画界面（侧对电脑+电脑不渐变） --------------------------
    def _create_start_animation(self):
        # 创建全屏Canvas（覆盖整个初始界面）
        self.canvas = tk.Canvas(
            self.frame_start, 
            bg=self.start_bg,
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        
        # 绑定窗口大小变化事件，实现Canvas自适应
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        
        # 绘制初始界面元素
        self._draw_animation_elements()

    def _create_start_animation(self):
        # 创建全屏Canvas（覆盖整个初始界面）
        self.canvas = tk.Canvas(
            self.frame_start, 
            width=1000, 
            height=1000, 
            bg=self.start_bg,
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        
         # 绘制小人（卡通风格，适配侧对电脑）
        # 1. 头部（圆形）
        self.head = self.canvas.create_oval(
            320+130, 150+150, 420+130, 250+150,
            fill="#f0e6d2", outline="#1a1a2e", width=2
        )
        # 2. 身体（矩形）
        self.body = self.canvas.create_rectangle(
            340+130, 250+150, 400+130, 380+150,
            fill="#0f3460", outline="#1a1a2e", width=2
        )
        # 3. 手臂（适配侧对电脑的姿势）
        self.arm_left = self.canvas.create_line(
            340+130, 290+150, 280+130, 350+150,
            fill="#1a1a2e", width=5
        )
        self.arm_right = self.canvas.create_line(
            400+130, 290+150, 450+130, 330+150,
            fill="#1a1a2e", width=5
        )
        
        # 绘制侧对观众的电脑（梯形屏幕+立体机身，不参与渐变）
        # 电脑屏幕（侧对梯形，固定颜色不渐变）
        self.computer_screen = self.canvas.create_polygon(
            280+130, 350+150,  # 左上
            480+130, 330+150,  # 右上
            490+130, 440+150,  # 右下
            290+130, 460+150,  # 左下
            fill=self.computer_screen_color, outline="#ffffff", width=3
        )
        # 电脑机身（侧对矩形，带厚度，固定样式）
        self.computer_body = self.canvas.create_rectangle(
            290+130, 460+150, 490+130, 480+150,
            fill="#333333", outline="#ffffff", width=2
        )
        # 电脑侧面厚度（模拟3D，固定样式）
        self.computer_side = self.canvas.create_rectangle(
            490+130, 330+150, 500+130, 480+150,
            fill="#222222", outline="#ffffff", width=1
        )
        
        # 屏幕文字提示（固定颜色，不随渐变变化）
        self.screen_text = self.canvas.create_text(
            380+130, 400+150,
            text="正在启动解锁系统...",
            font=("SimHei", 18, "bold"),
            fill="#1a1a2e"
        )

    def _on_canvas_resize(self, event):
        # 当Canvas尺寸变化时，重新绘制所有元素
        self.canvas.delete("all")
        self._draw_animation_elements()

    # 整张界面渐变动画（电脑不参与渐变）
    def _start_full_gradient_animation(self):
        if self.gradient_step < 30:  # 30步完成渐变（每100ms一步，共3秒）
            # 计算RGB渐变值（start_bg: #add8e6 → target_bg: #1a1a2e）
            start_r = int(self.start_bg[1:3], 16)
            start_g = int(self.start_bg[3:5], 16)
            start_b = int(self.start_bg[5:7], 16)
            
            target_r = int(self.target_bg[1:3], 16)
            target_g = int(self.target_bg[3:5], 16)
            target_b = int(self.target_bg[5:7], 16)
            
            # 计算当前步的RGB背景色
            curr_r = int(start_r - (start_r - target_r) * self.gradient_step/30)
            curr_g = int(start_g - (start_g - target_g) * self.gradient_step/30)
            curr_b = int(start_b - (start_b - target_b) * self.gradient_step/30)
            
            # 生成当前背景色
            curr_bg = f"#{curr_r:02x}{curr_g:02x}{curr_b:02x}"
            
            # 文本颜色渐变：从黑色(#000000)渐变到初始背景色(#add8e6)
            text_start_r, text_start_g, text_start_b = 0, 0, 0  # 黑色
            text_target_r, text_target_g, text_target_b = start_r, start_g, start_b  # 初始背景色
            
            # 计算当前步的文本颜色RGB值
            text_curr_r = int(text_start_r + (text_target_r - text_start_r) * self.gradient_step/30)
            text_curr_g = int(text_start_g + (text_target_g - text_start_g) * self.gradient_step/30)
            text_curr_b = int(text_start_b + (text_target_b - text_start_b) * self.gradient_step/30)
            
            # 生成当前文本颜色
            text_color = f"#{text_curr_r:02x}{text_curr_g:02x}{text_curr_b:02x}"
            
            # 更新Canvas背景和文本颜色
            self.canvas.config(bg=curr_bg)
            self.canvas.itemconfig(self.screen_text, fill=text_color)
            
            self.gradient_step += 1
            self.root.after(100, self._start_full_gradient_animation)
        else:
            # 渐变完成，确保最终文本颜色与最终背景匹配
            self.canvas.itemconfig(self.screen_text, fill="#add8e6")
            # 渐变完成，切换到摩斯解锁界面
            self.root.after(500, self._switch_to_morse_frame)

    # -------------------------- 摩斯密码解锁界面（修复边框+抖动） --------------------------
    def _switch_to_morse_frame(self):
        self.frame_start.pack_forget()
        self._create_morse_frame()
        # 使用fill=both和expand=True使Frame自适应窗口大小
        self.frame_morse_border.pack(fill="both", expand=True)
        # 内层内容Frame填充外层Frame（边距=3像素，模拟边框宽度）
        self.frame_morse.pack(fill="both", expand=True, padx=3, pady=3)
        # 记录初始位置
        self.original_x = 0

    def _create_morse_frame(self):
        # 1. 已获取的密码区域
        tk.Label(
            self.frame_morse,
            text=">> 已获取的密码",
            font=("SimHei", 14),
            bg=self.target_bg,
            fg="white"
        ).pack(anchor="w", padx=30, pady=(20, 5))
        
        # 显示5个目标摩斯密码
        tk.Label(
            self.frame_morse,
            text=" | ".join(self.target_morse),
            font=("SimHei", 16),
            bg=self.target_bg,
            fg="white"
        ).pack(anchor="w", padx=50, pady=5)

        # 2. 密码破译线索区域（初始隐藏）
        self.clue_title = tk.Label(
            self.frame_morse,
            text=">> 密码破译线索",
            font=("SimHei", 14),
            bg=self.target_bg,
            fg="white"
        )
        self.clue_title.pack(anchor="w", padx=30, pady=(20, 5))
        self.clue_title.pack_forget()
        
        # 线索表格容器（初始隐藏）
        self.clue_frame = tk.Frame(self.frame_morse, bg=self.target_bg)
        self.clue_frame.pack(anchor="w", padx=50, pady=5)
        self.clue_frame.pack_forget()
        
        # 构建线索表格内容
        clue_rows = [
            ("•----", "1"), ("••---", "2"),
            ("•••--", "3"), ("••••-", "4"),
            ("•••••", "5"), ("-••••", "6"),
            ("--•••", "7"), ("---••", "8"),
            ("----•", "9"), ("-----", "0")
        ]
        for i in range(5):
            for j in range(2):
                morse, num = clue_rows[i*2 + j]
                tk.Label(
                    self.clue_frame, text=morse, font=("SimHei", 12),
                    bg=self.target_bg, fg="white", width=10
                ).grid(row=i, column=j*2, padx=2)
                tk.Label(
                    self.clue_frame, text=num, font=("SimHei", 12),
                    bg=self.target_bg, fg="white", width=2
                ).grid(row=i, column=j*2+1, padx=2)
        
        # 显示破译密码线索按钮
        self.show_clue_btn = tk.Button(
            self.frame_morse,
            text="显示破译密码线索",
            font=("SimHei", 12, "bold"),
            bg="#0f3460",
            fg="white",
            padx=15,
            pady=5,
            command=self.show_clue
        )
        self.show_clue_btn.pack(anchor="w", padx=30, pady=(20, 10))

        # 3. 密码输入区域
        tk.Label(
            self.frame_morse,
            text="请输入密码",
            font=("SimHei", 14),
            bg=self.target_bg,
            fg="white"
        ).pack(anchor="w", padx=30, pady=(10, 5))
        
        # 输入显示框
        self.input_display = tk.Label(
            self.frame_morse,
            text="",
            font=("SimHei", 20),
            bg="#0f3460",
            fg="white",
            width=10,
            height=2
        )
        self.input_display.pack(anchor="w", padx=50, pady=5)

        # 4. 数字键盘（789/456/123/0）
        keypad_frame = tk.Frame(self.frame_morse, bg=self.target_bg)
        keypad_frame.pack(anchor="w", padx=50, pady=10)
        keys = [["7","8","9"], ["4","5","6"], ["1","2","3"], ["","0",""]]
        for i, row in enumerate(keys):
            for j, key in enumerate(row):
                if key:
                    tk.Button(
                        keypad_frame,
                        text=key,
                        font=("SimHei", 16, "bold"),
                        bg="#0f3460",
                        fg="white",
                        width=4,
                        height=2,
                        command=lambda k=key: self._on_key_press(k)
                    ).grid(row=i, column=j, padx=5, pady=5)

        # 5. 解锁进度条（浅蓝色自定义样式） - 自适应宽度
        self.progress_bar = ttk.Progressbar(
            self.frame_morse,
            mode="determinate",
            maximum=100,
            style="LightBlue.Horizontal.TProgressbar"  # 应用浅蓝色样式
        )
        self.progress_bar.pack(anchor="w", padx=50, pady=20, fill="x", expand=True)
        self.progress_bar["value"] = 0

    # 显示密码破译线索
    def show_clue(self):
        self.clue_title.pack(anchor="w", padx=30, pady=(20, 5))
        self.clue_frame.pack(anchor="w", padx=50, pady=5)
        self.show_clue_btn.pack_forget()

    # 窗口抖动效果实现 - 自适应窗口大小
    def _shake_frame(self):
        if self.shake_count < 6:  # 抖动3次（左右各一次为1组，共3组）
            # 交替左右移动5像素
            if self.shake_count % 2 == 0:
                self.frame_morse_border.place(x=self.original_x + 5, y=0, width=1000, height=1000)
            else:
                self.frame_morse_border.place(x=self.original_x - 5, y=0, width=1000, height=1000)
            self.shake_count += 1
            self.root.after(50, self._shake_frame)  # 50ms移动一次，快速抖动
        else:
            # 抖动结束，恢复原位+恢复边框颜色
            self.frame_morse_border.place(x=self.original_x, y=0, width=1000, height=1000)
            self.frame_morse_border.config(bg=self.target_bg)
            self.shake_count = 0

    # 数字键盘点击事件（输错时红框+抖动+弹窗）
    def _on_key_press(self, key):
        if len(self.input_record) < 5:
            self.input_record.append(key)
            self.input_display.config(text="".join(self.input_record))
            
            # 检查输入是否正确
            current_idx = len(self.input_record) - 1
            if key == self.target_numbers[current_idx]:
                # 输入正确：进度+20%（1/5）
                self.progress += 20
                self.progress_bar["value"] = self.progress
                
                # 5个数字都正确 → 进入成功界面
                if len(self.input_record) == 5:
                    self.root.after(1000, self._switch_to_success_frame)
            else:
                # 输入错误：弹窗+红边框+抖动+清空重输
                self.frame_morse_border.config(bg="red")  # 外层Frame背景变红（模拟边框）
                messagebox.showwarning("输入错误", "这个数字不对哦，请重新输入~")
                self._shake_frame()  # 启动抖动
                self.input_record = []
                self.input_display.config(text="")
                # 输错代码后进度条清零
                self.progress = 0
                self.progress_bar["value"] = 0

    # -------------------------- 解锁成功界面（闪烁校徽） --------------------------
    def _switch_to_success_frame(self):
        self.frame_morse_border.pack_forget()
        self._create_success_frame()
        self.frame_success.pack(fill="both", expand=True)
        # 启动校徽闪烁+快速填充进度条
        self.ending = 1
        self._fill_success_progress()
        self._start_logo_flash()
        
        
        

    def _create_success_frame(self):
        # 科技感深蓝校徽（单一颜色+发光边框）
        global success_progress
        self.logo_frame = tk.Frame(
            self.frame_success,
            bg="#add8e6",
            bd=5,  # 科技感边框
            relief="solid",
            highlightbackground="#0066cc",  # 科技蓝边框
            highlightcolor="#0066cc",
            highlightthickness=3
        )
        self.logo_frame.pack(pady=30)
        
        # 校徽图片显示
        # 获取当前脚本所在目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 构建图片的绝对路径
        logo_path = os.path.join(script_dir, "pictures//bingtuanerzhong_logo_resized.png")
        
        self.logo_img = tk.PhotoImage(file=logo_path)
        self.logo_label = tk.Label(
            self.logo_frame,
            image=self.logo_img,
            bg="#ffffff",
            bd=0
        )
        self.logo_label.pack()

        # 快速进度条（浅蓝色自定义样式） - 自适应宽度
        self.success_progress = ttk.Progressbar(
            self.frame_success,
            mode="determinate",
            maximum=100,
            style="Success.LightBlue.Horizontal.TProgressbar"  # 应用成功界面浅蓝色样式
        )
        self.success_progress.pack(pady=20, fill="x", expand=True, padx=50)
        self.success_progress["value"] = 0

        # 解锁成功提示
        self.success_label = tk.Label(
            self.frame_success,
            text="解锁成功！",
            font=("SimHei", 28, "bold"),
            bg="#add8e6",
            fg="#1a1a2e"
            
        )

    # 校徽持续闪烁效果
    def _start_logo_flash(self):
        if self.flash_state:
            self.logo_frame.config(highlightbackground="#ffffff", highlightcolor="#ffffff")
        else:
            self.logo_frame.config(highlightbackground="#0066cc", highlightcolor="#0066cc")
        self.flash_state = not self.flash_state
        self.flash_timer = self.root.after(500, self._start_logo_flash)

    # 快速填充进度条
    def _fill_success_progress(self):
        current = self.success_progress["value"]
        if current < 100:
            self.success_progress["value"] = current + 10
            self.root.after(50, self._fill_success_progress)
        else:
            self.success_label.pack(pady=20)
            # 进度条填满后，自动关闭系统
            self.root.after(1500, self._auto_close)

    def _auto_close(self):
        """自动关闭窗口"""
        try:
            # 取消闪烁定时器
            if hasattr(self, 'flash_timer'):
                self.root.after_cancel(self.flash_timer)
            # 关闭窗口
            self.root.quit()
            self.root.destroy()
        except:
            pass

# -------------------------- 图片校徽替换（可选） --------------------------
# 替换logo_label代码：
# self.logo_img = tk.PhotoImage(file="bingtuanerzhong_logo.png")
# self.logo_label = tk.Label(self.logo_frame, image=self.logo_img, bg="#1a1a2e", bd=0)
# self.logo_label.pack()
def main():
    """主函数"""
    root = tk.Tk()
    app = MorseCodeUnlockGame(root)
    root.mainloop()
    if (app.ending):
        return True
    else:
        return False
if __name__ == "__main__":
    main()