#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频+音频合并脚本
将视频与对应音频合并，输出到指定文件夹。

用法:
    python merge_audio_video.py --audio-dir <音频文件夹> --video-dir <视频文件夹> [--output-dir <输出文件夹>]

    若不指定 --output-dir，则在音频文件夹的父目录创建 merge/ 文件夹。

示例:
    python merge_audio_video.py --audio-dir ./audio --video-dir ./video
    python merge_audio_video.py --audio-dir ./audio --video-dir ./video --output-dir ./merge
"""

import os
import sys
import subprocess
import argparse
import re

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def main():
    parser = argparse.ArgumentParser(description='将视频与音频合并')
    parser.add_argument('--audio-dir', required=True, help='音频文件夹路径')
    parser.add_argument('--video-dir', required=True, help='视频文件夹路径')
    parser.add_argument('--output-dir', help='输出文件夹路径（默认：音频父级目录/merge）')

    args = parser.parse_args()

    # 自动设定输出目录：音频父级目录/merge
    if args.output_dir:
        output_dir = args.output_dir
    else:
        audio_parent = os.path.dirname(os.path.abspath(args.audio_dir))
        output_dir = os.path.join(audio_parent, 'merge')

    os.makedirs(output_dir, exist_ok=True)

    video_files = sorted([f for f in os.listdir(args.video_dir) if f.endswith('.mp4')])
    print(f"共 {len(video_files)} 个视频文件")
    print(f"输出目录：{output_dir}")

    success = 0
    for i, video_file in enumerate(video_files, 1):
        match = re.match(r'(\d+)_v\.mp4', video_file)
        if not match:
            print(f"  跳过：{video_file}")
            continue

        idx = match.group(1)

        # 找对应的音频文件
        audio_file = None
        for f in os.listdir(args.audio_dir):
            if f.startswith(f"{idx}_") and f.endswith('.wav'):
                audio_file = f
                break

        if not audio_file:
            print(f"  警告：找不到 {idx} 对应的音频")
            continue

        video_path = os.path.join(args.video_dir, video_file)
        audio_path = os.path.join(args.audio_dir, audio_file)
        output_path = os.path.join(output_dir, f"{idx}.mp4")

        print(f"[{i}/{len(video_files)}] {video_file} + {audio_file} -> {idx}.mp4", end=" ")

        subprocess.run([
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-shortest',
            output_path
        ], capture_output=True)

        print("✓")
        success += 1

    print(f"\n完成：{success}/{len(video_files)} 成功")


if __name__ == "__main__":
    main()
