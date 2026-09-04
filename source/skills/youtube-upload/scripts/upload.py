#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
YouTube 视频上传脚本（Resumable Upload + OAuth）

用法：
  python upload.py \
    --video <path> \
    --title <title> \
    --description-file <path> \
    --tags-file <path>            # 可选，每行一个 tag
    --category 22 \              # 默认 22 (People & Blogs)
    --privacy private \           # private / public / unlisted
    --playlist-id <id> \         # 可选，上传后加到此播放列表
    --thumbnail <path> \         # 可选，自定义缩略图
    [--dry-run]
"""

import os
import sys
import json
import argparse
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 用共享 OAuth 模块（YouTube + Drive 共用一份 token）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '_shared'))
from google_auth import get_youtube_service


def get_authenticated_service(channel=None):
    return get_youtube_service(channel=channel)


def read_text_file(path):
    if not path:
        return None
    with open(path, encoding='utf-8') as f:
        return f.read().strip()


def read_tags_file(path):
    if not path:
        return []
    with open(path, encoding='utf-8') as f:
        # 一行一个 tag，或者一行多个用逗号分隔
        tags = []
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                # # 开头的算注释（注意：YouTube hashtag 也是 #，但不应该作为 tag 写）
                continue
            for t in line.split(','):
                t = t.strip().lstrip('#').strip()
                if t:
                    tags.append(t)
        return tags


def upload_video(youtube, args):
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    title = args.title
    description = read_text_file(args.description_file) or args.description or ''
    tags = read_tags_file(args.tags_file) if args.tags_file else (args.tags or [])

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': str(args.category),
            'defaultLanguage': args.language,
            'defaultAudioLanguage': args.language,
        },
        'status': {
            'privacyStatus': args.privacy,
            'madeForKids': False,
            'selfDeclaredMadeForKids': False,
        },
    }

    print(f'\n=== 待上传视频 ===')
    print(f'文件:     {args.video}')
    print(f'  大小:   {os.path.getsize(args.video) / 1024 / 1024:.1f} MB')
    print(f'标题:     {title}')
    print(f'描述长度: {len(description)} 字符')
    print(f'标签:     {len(tags)} 个 - {", ".join(tags[:10])}{"..." if len(tags)>10 else ""}')
    print(f'分类:     {args.category}')
    print(f'隐私:     {args.privacy}')
    if args.playlist_id:
        print(f'播放列表: {args.playlist_id}')
    if args.thumbnail:
        print(f'缩略图:   {args.thumbnail}')
    print(f'=================\n')

    if args.dry_run:
        print('[DRY RUN] 不真正上传')
        return None

    media = MediaFileUpload(args.video, chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype='video/*')
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)

    response = None
    last_progress = -1
    start = time.time()
    retries = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct != last_progress and pct % 5 == 0:
                    elapsed = time.time() - start
                    print(f'  上传 {pct}%  已用 {elapsed:.0f}s', flush=True)
                    last_progress = pct
            retries = 0
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retries += 1
                wait = min(2 ** retries, 60)
                print(f'  服务器错误 {e.resp.status}, {wait}秒后重试 ({retries}/10)...')
                time.sleep(wait)
                if retries > 10:
                    raise
                continue
            raise
        except (ConnectionResetError, ConnectionError, OSError) as e:
            retries += 1
            wait = min(2 ** retries, 60)
            print(f'  连接断开: {e}, {wait}秒后重试 ({retries}/10)...', flush=True)
            time.sleep(wait)
            if retries > 10:
                raise
            continue

    video_id = response['id']
    print(f'\n✓ 上传完成! Video ID: {video_id}')
    print(f'  链接: https://www.youtube.com/watch?v={video_id}')

    # 加到播放列表
    if args.playlist_id:
        try:
            youtube.playlistItems().insert(
                part='snippet',
                body={
                    'snippet': {
                        'playlistId': args.playlist_id,
                        'resourceId': {'kind': 'youtube#video', 'videoId': video_id},
                    }
                }
            ).execute()
            print(f'  已加入播放列表 {args.playlist_id}')
        except HttpError as e:
            print(f'  [WARN] 加入播放列表失败: {e}')

    # 上传缩略图（>2MB 自动转 JPG 压到 2MB 内——API 硬上限）
    if args.thumbnail:
        thumb = args.thumbnail
        try:
            if os.path.getsize(thumb) > 2 * 1024 * 1024:
                from PIL import Image
                from pathlib import Path as _P
                src = _P(thumb)
                tmp = src.with_name(src.stem + '_compressed.jpg')
                Image.open(src).convert('RGB').save(tmp, 'JPEG', quality=88, optimize=True)
                print(f'  缩略图 {os.path.getsize(thumb)//1024}KB > 2MB，转 JPG → {tmp.name} ({os.path.getsize(tmp)//1024}KB)')
                thumb = str(tmp)
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb)
            ).execute()
            print(f'  已设置缩略图')
        except HttpError as e:
            print(f'  [WARN] 缩略图设置失败 (需要频道验证): {e}')

    return video_id


def main():
    ap = argparse.ArgumentParser(description='Upload video to YouTube')
    ap.add_argument('--video', required=True, help='视频文件路径')
    ap.add_argument('--title', default=None, help='视频标题（最多 100 字符）')
    ap.add_argument('--title-file', default=None, help='从 UTF-8 文本文件读取标题（避免 shell 编码问题）')
    ap.add_argument('--metadata-json', default=None, help='从 _metadata.json 读取 title 字段')
    ap.add_argument('--description', help='描述文本（直接传字符串）')
    ap.add_argument('--description-file', help='描述文本文件路径（推荐）')
    ap.add_argument('--tags', nargs='*', help='标签列表（空格分隔）')
    ap.add_argument('--tags-file', help='标签文件，一行一个或逗号分隔')
    ap.add_argument('--category', type=int, default=22,
                    help='分类 ID (默认 22=People & Blogs；27=Education)')
    ap.add_argument('--privacy', default='private',
                    choices=['private', 'public', 'unlisted'])
    ap.add_argument('--playlist-id', help='上传后加入此播放列表')
    ap.add_argument('--thumbnail', help='自定义缩略图（需要频道已验证）')
    ap.add_argument('--language', default='zh', help='默认语言 (zh/en/...)')
    ap.add_argument('--channel', default=None,
                    help='频道标识，决定用哪个 token 文件。None/default=token.json（老 SNC 频道）；'
                         '其他值如 sne→token_sne.json。首次用新 channel 会触发浏览器授权')
    ap.add_argument('--dry-run', action='store_true', help='只打印不上传')

    args = ap.parse_args()

    # Resolve title from file sources to avoid shell encoding corruption
    if args.title_file:
        with open(args.title_file, encoding='utf-8') as f:
            args.title = f.read().strip()
    elif args.metadata_json:
        with open(args.metadata_json, encoding='utf-8') as f:
            args.title = json.load(f)['title']
    elif not args.title:
        raise SystemExit('必须提供 --title、--title-file 或 --metadata-json 之一')

    if not os.path.isfile(args.video):
        raise SystemExit(f'视频文件不存在: {args.video}')

    youtube = get_authenticated_service(channel=args.channel)
    upload_video(youtube, args)


if __name__ == '__main__':
    main()
