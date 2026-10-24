#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 Windows 上 os.execv 重建命令行时是否会给含空格的参数加引号。"""
import os
import sys

print("PARENT argv=", repr(sys.argv), flush=True)

if len(sys.argv) > 1 and sys.argv[1] == "--child":
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_execv_probe_out.txt"),
              "w", encoding="utf-8") as f:
        f.write("CHILD_ARGV=" + repr(sys.argv[2:]) + "\n")
    print("CHILD_ARGV=", repr(sys.argv[2:]), flush=True)
    sys.exit(0)

os.execv(sys.executable, [sys.executable, "-u", os.path.abspath(__file__),
                          "--child", "A  B", "C:D"])
print("EXECV_RETURNED (不应该执行到这里)", flush=True)
