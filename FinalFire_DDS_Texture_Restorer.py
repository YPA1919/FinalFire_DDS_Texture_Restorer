#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
《最后一炮》DDS 批量修复工具

功能：
- 批量扫描脚本所在目录及其子目录中的 .dds
- 识别游戏额外的 8 字节文件头
- 恢复 DDS 的正确 Width / Height
- 输出到 fixed 文件夹
- 不修改原始文件

使用：
1. 把本脚本放到需要处理的 DDS 文件夹里
2. 双击运行，或在命令行运行：
       python fix_dds.py
3. 修复后的文件会放在：
       fixed\\
"""

from pathlib import Path
import struct
import shutil
import sys

DDS_MAGIC = b"DDS "
DDS_HEADER_SIZE = 124
GAME_HEADER_SIZE = 8

# DDS_HEADER 中：
# magic: 0-3
# size:  4-7
# flags: 8-11
# height: 12-15
# width: 16-19
HEIGHT_OFFSET = 12
WIDTH_OFFSET = 16


def read_u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def write_u32(data, offset, value):
    struct.pack_into("<I", data, offset, value)


def mip_size(width, height, fourcc):
    """计算压缩纹理所有 mipmap 的理论数据大小。"""
    block_bytes = 8 if fourcc in (b"DXT1", b"BC1 ") else 16
    total = 0

    while True:
        bw = max(1, (width + 3) // 4)
        bh = max(1, (height + 3) // 4)
        total += bw * bh * block_bytes

        if width == 1 and height == 1:
            break

        width = max(1, width // 2)
        height = max(1, height // 2)

    return total


def detect_fourcc(dds):
    # DDS_PIXELFORMAT 在 DDS 文件中的偏移：
    # magic 4 + DDS_HEADER 124
    # pixel format 起始于 DDS_HEADER + 76
    pf = 4 + 76
    if len(dds) < pf + 20:
        return b""

    return dds[pf + 8:pf + 12]


def restore_dimensions(dds):
    """
    根据目前已经验证的《最后一炮》DDS格式恢复尺寸。

    文件布局：
        [8 bytes game header][DDS magic + 124 byte DDS header][texture data]

    游戏会把真实 Width/Height 与前8字节中的第一个 uint32
    进行算术混淆。

    对当前已验证的资源：
        real_width  = abs(game_value - stored_width)
        real_height = abs(game_value - stored_height)

    之后通过纹理数据大小进行验证，并选择正确的方向。
    """
    if len(dds) < GAME_HEADER_SIZE + 128:
        raise ValueError("文件太小，不是完整 DDS")

    if dds[GAME_HEADER_SIZE:GAME_HEADER_SIZE + 4] != DDS_MAGIC:
        raise ValueError("第9字节不是 DDS magic")

    game_value = read_u32(dds, 0)

    # 注意：这里的 DDS Header 从原文件偏移 8 开始。
    stored_height = read_u32(dds, GAME_HEADER_SIZE + HEIGHT_OFFSET)
    stored_width = read_u32(dds, GAME_HEADER_SIZE + WIDTH_OFFSET)

    candidates = []

    # 直接按两者差值恢复
    h = abs(game_value - stored_height)
    w = abs(game_value - stored_width)

    if h > 0 and w > 0 and h <= 32768 and w <= 32768:
        candidates.append((w, h, "abs"))

    # 有些资源可能表现为有符号加减，尝试 uint32 环绕差值
    h2 = (stored_height - game_value) & 0xFFFFFFFF
    w2 = (stored_width - game_value) & 0xFFFFFFFF

    if h2 > 0 and w2 > 0 and h2 <= 32768 and w2 <= 32768:
        candidates.append((w2, h2, "reverse"))

    # 读取 FourCC 和原始 mip 数
    fourcc = detect_fourcc(dds)
    mip_count = read_u32(dds, GAME_HEADER_SIZE + 28)

    # 文件中 DDS Header 后面的纹理数据
    texture_offset = GAME_HEADER_SIZE + 128
    texture_bytes = len(dds) - texture_offset

    # 优先选择能够与实际纹理数据大小匹配的候选
    checked = []
    for w, h, method in candidates:
        if fourcc in (b"DXT1", b"BC1 "):
            expected = mip_size(w, h, fourcc)
            # 允许文件存在额外尾部数据，但正常情况下应精确匹配
            match = expected == texture_bytes
        elif fourcc in (b"DXT3", b"DXT5", b"BC2 ", b"BC3 "):
            expected = mip_size(w, h, fourcc)
            match = expected == texture_bytes
        else:
            expected = None
            match = False

        checked.append((match, w, h, method, expected))

    for item in checked:
        if item[0]:
            return item[1], item[2], game_value, stored_width, stored_height, fourcc

    # 如果 mipmap 数据无法验证，仍使用第一个合理候选
    if candidates:
        w, h, _ = candidates[0]
        return w, h, game_value, stored_width, stored_height, fourcc

    raise ValueError(
        f"无法恢复尺寸：game=0x{game_value:08X}, "
        f"stored={stored_width}x{stored_height}"
    )


def fix_file(src, dst):
    raw = src.read_bytes()

    w, h, game_value, stored_w, stored_h, fourcc = restore_dimensions(raw)

    # 去掉游戏额外8字节
    dds = bytearray(raw[GAME_HEADER_SIZE:])

    # 修改标准 DDS Header
    write_u32(dds, HEIGHT_OFFSET, h)
    write_u32(dds, WIDTH_OFFSET, w)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(dds)

    return w, h, fourcc, stored_w, stored_h


def main():
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parent
    output = root / "fixed"

    # 不重复处理 fixed 文件夹
    files = [
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() == ".dds"
        and output not in p.parents
    ]

    if not files:
        print("没有找到 DDS 文件。")
        input("\n按 Enter 退出...")
        return

    output.mkdir(exist_ok=True)

    ok = 0
    failed = 0

    print("=" * 72)
    print("《最后一炮》 DDS 批量修复工具")
    print("=" * 72)
    print(f"找到 {len(files)} 个 DDS")
    print(f"输出目录：{output}")
    print()

    for src in files:
        try:
            # 保持相对于根目录的目录结构
            rel = src.relative_to(root)
            dst = output / rel

            w, h, fourcc, old_w, old_h = fix_file(src, dst)

            ok += 1
            fmt = fourcc.decode("ascii", errors="replace") if fourcc else "UNKNOWN"

            print(
                f"[OK] {src.name:<35} "
                f"{w}x{h:<12} {fmt}"
            )

        except Exception as e:
            failed += 1
            print(f"[失败] {src}: {e}")

    print()
    print("=" * 72)
    print(f"完成：成功 {ok} 个，失败 {failed} 个")
    print(f"修复后的 DDS 位于：{output}")
    print("=" * 72)

    input("\n按 Enter 退出...")


if __name__ == "__main__":
    main()
    
#Made by 響爷Hibiki