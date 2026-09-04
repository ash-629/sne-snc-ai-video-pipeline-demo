#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频拼接脚本
将多个视频片段合并为一个完整视频。

用法:
    python concat_videos.py --input-dir <视频文件夹> [--output <输出文件>]

    若不指定 --output，则在输入文件夹的父目录生成 final.mp4。

示例:
    python concat_videos.py --input-dir ./merge
    python concat_videos.py --input-dir ./merge --output final.mp4
"""

import os
import sys
import subprocess
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def main():
    parser = argparse.ArgumentParser(description='将多个视频拼接为一个')
    parser.add_argument('--input-dir', required=True, help='视频文件夹路径')
    parser.add_argument('--output', help='输出文件路径（默认：输入文件夹父级目录/final.mp4）')

    args = parser.parse_args()

    video_files = sorted([f for f in os.listdir(args.input_dir) if f.endswith('.mp4')])

    if not video_files:
        print("错误：没有找到视频文件")
        return

    print(f"共 {len(video_files)} 个视频文件")

    # 自动设定输出文件：输入文件夹父级目录/final.mp4
    if args.output:
        output_path = args.output
    else:
        input_parent = os.path.dirname(os.path.abspath(args.input_dir))
        output_path = os.path.join(input_parent, 'final.mp4')

    print(f"输出文件：{output_path}")

    # 生成临时文件列表
    temp_list = os.path.join(args.input_dir, "concat_list.txt")
    with open(temp_list, 'w', encoding='utf-8') as f:
        for vf in video_files:
            # 写绝对路径：concat demuxer 按 list 文件所在目录解析相对路径
            abs_p = os.path.abspath(os.path.join(args.input_dir, vf)).replace(chr(92), '/')
            f.write(f"file '{abs_p}'\n")

    print("正在拼接...")

    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', temp_list,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac',
        output_path
    ], capture_output=True)

    os.remove(temp_list)

    if os.path.exists(output_path):
        print(f"✓ 完成：{output_path}")
    else:
        print("✗ 错误：视频拼接失败")


if __name__ == "__main__":
    main()
