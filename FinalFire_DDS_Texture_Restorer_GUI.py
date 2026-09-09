# -*- coding: utf-8 -*-

"""
《最后一炮》DDS批量修复工具 GUI版

输出规则：
程序目录
 └── fixed
     └── 原DDS文件夹名_fixed
         └── 原目录结构
             └── 修复后的DDS
"""

from pathlib import Path
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import sys
import traceback

DDS_MAGIC = b"DDS "
GAME_HEADER_SIZE = 8
HEIGHT_OFFSET = 12
WIDTH_OFFSET = 16


def read_u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def write_u32(data, offset, value):
    struct.pack_into("<I", data, offset, value)


def restore_dimensions(dds):
    if len(dds) < GAME_HEADER_SIZE + 128:
        raise Exception("文件太小")

    if dds[GAME_HEADER_SIZE:GAME_HEADER_SIZE+4] != DDS_MAGIC:
        raise Exception("不是游戏DDS")

    game_value = read_u32(dds, 0)
    stored_height = read_u32(dds, GAME_HEADER_SIZE + HEIGHT_OFFSET)
    stored_width = read_u32(dds, GAME_HEADER_SIZE + WIDTH_OFFSET)

    w = abs(game_value - stored_width)
    h = abs(game_value - stored_height)

    if w <= 0 or h <= 0 or w > 32768 or h > 32768:
        raise Exception("无法恢复尺寸")

    return w, h


def fix_file(src, dst):
    raw = src.read_bytes()

    w, h = restore_dimensions(raw)

    dds = bytearray(raw[8:])

    write_u32(dds, HEIGHT_OFFSET, h)
    write_u32(dds, WIDTH_OFFSET, w)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(dds)


def process_folder(root):
    root = Path(root)

    # PyInstaller --onefile 运行时，__file__ 会指向临时 _MEI 目录。
    # EXE 模式必须使用 sys.executable 获取 EXE 的真实所在目录。
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parent

    # fixed\原文件夹名_fixed
    output = app_dir / "fixed" / (root.name + "_fixed")

    files = [
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() == ".dds"
        and output not in p.parents
    ]

    if not files:
        raise Exception("没有找到DDS文件")

    success = 0
    fail = 0

    for index, src in enumerate(files):

        try:
            rel = src.relative_to(root)
            dst = output / rel
            fix_file(src, dst)
            success += 1

        except Exception:
            fail += 1

        progress_var.set((index + 1) / len(files) * 100)
        status_var.set(
    f"正在还原 {index+1}/{len(files)} / Restoring {index+1}/{len(files)}"
)
        window.update_idletasks()

    return success, fail, output


def choose_folder():

    folder = filedialog.askdirectory()

    if not folder:
        return

    def run():
        try:
            result = process_folder(folder)
            if result is None or len(result) != 3:
                raise RuntimeError("处理函数没有返回有效结果，请重新打包此版本脚本")

            success, fail, output = result

            messagebox.showinfo(
                "完成",
                f"还原完成 / Restore Complete\n\n"
f"成功 Success:{success}\n"
f"失败 Failed:{fail}\n\n"
f"输出 Output:\n{output}"
            )

        except Exception as e:
            app_dir = (Path(sys.executable).resolve().parent
                       if getattr(sys, "frozen", False)
                       else Path(__file__).resolve().parent)
            try:
                with open(app_dir / "error.log", "a", encoding="utf-8") as f:
                    f.write("\n" + "=" * 60 + "\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass
            messagebox.showerror("错误", str(e))

        finally:
            btn.config(state="normal")

    btn.config(state="disabled")

    threading.Thread(target=run).start()


window = tk.Tk()
window.title("FinalFire DDS Texture Restorer\n最后一炮 DDS贴图还原工具")
window.geometry("420x220")

tk.Label(
    window,
    text="选择包含 DDS 文件的文件夹\nSelect DDS Folder",
    font=("Microsoft YaHei", 12)
).pack(pady=20)

btn = tk.Button(
    window,
    text="开始还原 / Start Restore",
    width=25,
    height=2,
    command=choose_folder
)
btn.pack()

progress_var = tk.DoubleVar()

ttk.Progressbar(
    window,
    variable=progress_var,
    maximum=100,
    length=350
).pack(pady=20)

status_var = tk.StringVar(value="等待操作 / Ready")

tk.Label(
    window,
    textvariable=status_var
).pack()

window.mainloop()

#Made by 響爷Hibiki