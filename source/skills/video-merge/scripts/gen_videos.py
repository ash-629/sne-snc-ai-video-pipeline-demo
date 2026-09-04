#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频素材拼接脚本（v2，支持 对话视频/ 库结构）

素材库命名规范（每个子文件夹一组素材）：
  {角色} {场景} outfit {编号} {左/右}

例：
  甜甜 工作室 outfit 1 左
  阿杰 工作室 outfit 1 右
  小悦 甜品店 outfit 2 左
  Leo 甜品店 outfit 3 右

选素材规则：
1. 两个角色必须在同一场景（场景一致）
2. outfit 编号可以不同（每人独立选）
3. 一期视频内每个角色 outfit 固定（中场不换衣服）
4. 一期视频内每个角色位置（左/右）固定

用法（新版，从 对话视频/ 库自动选）：
  python gen_videos.py \
    --audio-dir <音频文件夹> \
    --library "g:/youtube workspace/Simply Natural Chinese/对话视频" \
    --speakers "甜甜,阿杰" \
    [--scene 工作室]    # 不指定就自动选两人共有的场景
    [--outfit-甜甜 1] [--outfit-阿杰 2]  # 不指定就随机

旧版兼容（直接给一个 video-dir，文件名前缀=角色名）：
  python gen_videos.py --audio-dir <音频文件夹> --video-dir <video_material文件夹>
"""

import os
import sys
import re
import json
import random
import argparse
import subprocess
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

REVERSE_PROBABILITY = 0.25


def get_duration(file_path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


# ============== 素材库扫描（新） ==============

def parse_folder_name(name):
    """
    解析 '{角色} {场景} outfit {编号} {左/右}' 或 '{角色} {场景} {描述} {左/右}' 格式。
    outfit 编号可以是数字（1, 2, 3）或描述性字符串（运动服、休闲、正装 等）。
    返回 dict，失败返回 None。
    """
    # 优先匹配 "outfit N" 形式（向后兼容）
    m = re.match(r'^(\S+)\s+(\S+)\s+outfit\s+(\S+)\s+([左右])\s*$', name)
    if m:
        outfit_raw = m.group(3)
        outfit = int(outfit_raw) if outfit_raw.isdigit() else outfit_raw
        return {
            'role': m.group(1),
            'scene': m.group(2),
            'outfit': outfit,
            'side': m.group(4),
        }
    # 再匹配 "{描述}" 直接代替 outfit 标签（如 "甜甜 工作室 运动服 左"）
    m = re.match(r'^(\S+)\s+(\S+)\s+(\S+)\s+([左右])\s*$', name)
    if m:
        return {
            'role': m.group(1),
            'scene': m.group(2),
            'outfit': m.group(3),
            'side': m.group(4),
        }
    return None


def scan_library(library_dir):
    """扫描素材库，返回结构化 dict。

    返回 {role: {scene: {outfit: {side, folder_path}}}}
    """
    library = defaultdict(lambda: defaultdict(dict))
    if not os.path.isdir(library_dir):
        raise SystemExit(f'素材库不存在: {library_dir}')

    for entry in os.listdir(library_dir):
        full = os.path.join(library_dir, entry)
        if not os.path.isdir(full):
            continue
        meta = parse_folder_name(entry)
        if not meta:
            print(f'  [跳过] 文件夹名不符合规范: {entry}', file=sys.stderr)
            continue
        library[meta['role']][meta['scene']][meta['outfit']] = {
            'side': meta['side'],
            'path': full,
        }
    return library


def select_materials(library, speakers, scene=None, outfits=None):
    """
    给定两个角色，自动选场景和 outfit。

    Args:
        library: scan_library 返回的结构
        speakers: [角色1, 角色2]，第 1 个是左侧（先发言）
        scene: 指定场景，None 表示自动选两人共有的场景
        outfits: {角色: outfit_id}，None 表示随机

    Returns:
        {角色: {scene, outfit, side, path}}
    """
    if len(speakers) != 2:
        raise SystemExit(f'必须指定 2 个角色，得到: {speakers}')

    s1, s2 = speakers
    for s in speakers:
        if s not in library:
            raise SystemExit(f'素材库里没有角色 "{s}"。已有: {list(library.keys())}')

    # 1) 找两人共有的场景
    scenes_s1 = set(library[s1].keys())
    scenes_s2 = set(library[s2].keys())
    common_scenes = scenes_s1 & scenes_s2
    if not common_scenes:
        raise SystemExit(f'{s1} 和 {s2} 没有共同的场景。{s1}={scenes_s1}, {s2}={scenes_s2}')

    if scene:
        if scene not in common_scenes:
            raise SystemExit(f'指定的场景 "{scene}" 不是两人共有。共有的: {common_scenes}')
        chosen_scene = scene
    else:
        chosen_scene = random.choice(sorted(common_scenes))

    # 2) 给每个角色选 outfit
    outfits = outfits or {}
    chosen = {}
    for s in speakers:
        avail = library[s][chosen_scene]
        if not avail:
            raise SystemExit(f'{s} 在场景 {chosen_scene} 下没有 outfit')
        if s in outfits:
            o_id = outfits[s]
            if o_id not in avail:
                raise SystemExit(f'指定的 {s} outfit {o_id} 不存在。可选: {sorted(avail.keys(), key=str)}')
        else:
            o_id = random.choice(sorted(avail.keys(), key=str))
        info = avail[o_id]
        chosen[s] = {
            'scene': chosen_scene,
            'outfit': o_id,
            'side': info['side'],
            'path': info['path'],
        }

    # 3) 检查左右一致：第一个角色应该是左，第二个是右
    if chosen[s1]['side'] == chosen[s2]['side']:
        raise SystemExit(
            f'警告: {s1} 和 {s2} 都是同侧 ({chosen[s1]["side"]})！\n'
            f'  {s1}: {chosen[s1]["path"]}\n'
            f'  {s2}: {chosen[s2]["path"]}\n'
            f'同一期视频不能两人都在同一侧。请重选 outfit 或检查素材命名。'
        )

    return chosen


def list_videos_in_folder(folder):
    """从素材文件夹列出所有 mp4"""
    return sorted([os.path.join(folder, f) for f in os.listdir(folder)
                   if f.lower().endswith('.mp4')])


# ============== 视频生成 ==============

def generate_video_for_audio(audio_path, output_path, video_files):
    """为单个音频生成视频（拼接素材+随机倒放+缩放到 1920x1080）"""
    audio_duration = get_duration(audio_path)

    if not video_files:
        return False

    selected_videos = []
    current_duration = 0
    while current_duration < audio_duration:
        v = random.choice(video_files)
        v_dur = get_duration(v)
        selected_videos.append((v, v_dur))
        current_duration += v_dur

    temp_list = os.path.join(os.path.dirname(output_path), 'temp_list.txt')
    with open(temp_list, 'w', encoding='utf-8') as f:
        for v, _ in selected_videos:
            # 写绝对路径：concat demuxer 按 list 文件所在目录解析相对路径
            f.write(f"file '{os.path.abspath(v).replace(chr(92), '/')}'\n")

    do_reverse = random.random() < REVERSE_PROBABILITY
    temp_concat = output_path.replace('.mp4', '_concat.mp4')
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', temp_list, '-c', 'copy', temp_concat
    ], capture_output=True)

    common_args = [
        '-t', str(audio_duration),
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
        '-r', '30',
    ]

    if do_reverse:
        temp_reversed = output_path.replace('.mp4', '_reversed.mp4')
        subprocess.run(['ffmpeg', '-y', '-i', temp_concat, '-vf', 'reverse', temp_reversed],
                       capture_output=True)
        subprocess.run(['ffmpeg', '-y', '-i', temp_reversed] + common_args + [output_path],
                       capture_output=True)
        if os.path.exists(temp_reversed):
            os.remove(temp_reversed)
    else:
        subprocess.run(['ffmpeg', '-y', '-i', temp_concat] + common_args + [output_path],
                       capture_output=True)

    for f in [temp_list, temp_concat]:
        if os.path.exists(f):
            os.remove(f)
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


# ============== 主流程 ==============

def main():
    ap = argparse.ArgumentParser(description='根据音频时长拼接视频素材')
    ap.add_argument('--audio-dir', required=True, help='音频文件夹路径')
    ap.add_argument('--output-dir', help='输出文件夹路径（默认：音频父级/video）')

    # 新版（推荐）：从素材库自动选
    ap.add_argument('--library', help='素材库路径（如 g:/youtube workspace/Simply Natural Chinese/对话视频）')
    ap.add_argument('--speakers', help='当期角色对（逗号分隔，第1个=左/先发言），如 "甜甜,阿杰"')
    ap.add_argument('--scene', help='指定场景（不指定则自动选两人共有的）')
    ap.add_argument('--outfits', help='指定 outfit JSON，如 \'{"甜甜":1,"阿杰":2}\'')

    # 旧版兼容：所有素材在一个 dir 里，文件名前缀=角色
    ap.add_argument('--video-dir', help='[旧] 视频素材文件夹（文件名以角色名开头）')

    args = ap.parse_args()

    # 输出目录
    if args.output_dir:
        output_dir = args.output_dir
    else:
        audio_parent = os.path.dirname(os.path.abspath(args.audio_dir))
        output_dir = os.path.join(audio_parent, 'video')
    os.makedirs(output_dir, exist_ok=True)

    # 构建 speaker -> 视频文件列表 的映射
    speaker_videos = {}

    if args.library and args.speakers:
        # 新版：从素材库选
        speakers = [s.strip() for s in args.speakers.split(',')]
        outfits = json.loads(args.outfits) if args.outfits else None
        library = scan_library(args.library)
        chosen = select_materials(library, speakers, args.scene, outfits)

        print(f'素材选择：')
        for s, info in chosen.items():
            videos = list_videos_in_folder(info['path'])
            speaker_videos[s.lower()] = videos
            print(f"  {s} ({info['side']}, 场景={info['scene']}, outfit {info['outfit']}): {len(videos)} 个片段")
            print(f"    {info['path']}")
    elif args.video_dir:
        # 旧版：扫描单一文件夹
        for f in os.listdir(args.video_dir):
            if not f.lower().endswith('.mp4'):
                continue
            for s in ['小悦', 'leo', '甜甜', '阿杰', 'Leo']:
                if f.lower().startswith(s.lower()):
                    key = s.lower()
                    speaker_videos.setdefault(key, []).append(os.path.join(args.video_dir, f))
                    break
        print(f'视频素材：{", ".join(f"{k} {len(v)}个" for k, v in speaker_videos.items())}')
    else:
        raise SystemExit('请指定 --library + --speakers，或者 --video-dir（旧版）')

    # 生成
    audio_files = sorted([f for f in os.listdir(args.audio_dir) if f.endswith('.wav')])
    print(f'\n共 {len(audio_files)} 个音频文件')
    print(f'输出目录：{output_dir}\n')

    success = 0
    for i, audio_file in enumerate(audio_files, 1):
        m = re.match(r'(\d+)_(.+)\.wav', audio_file)
        if not m:
            print(f'  跳过: {audio_file}')
            continue
        idx = m.group(1)
        speaker = m.group(2)
        videos = speaker_videos.get(speaker.lower())
        if not videos:
            print(f'  [{i}/{len(audio_files)}] {audio_file}: 没有 {speaker} 的素材，跳过')
            continue

        audio_path = os.path.join(args.audio_dir, audio_file)
        output_path = os.path.join(output_dir, f'{idx}_v.mp4')

        if generate_video_for_audio(audio_path, output_path, videos):
            print(f'  [{i}/{len(audio_files)}] {audio_file} ({speaker}) -> {idx}_v.mp4 ✓', flush=True)
            success += 1
        else:
            print(f'  [{i}/{len(audio_files)}] {audio_file}: 失败', flush=True)

    print(f'\n完成：{success}/{len(audio_files)} 成功')


if __name__ == '__main__':
    main()
