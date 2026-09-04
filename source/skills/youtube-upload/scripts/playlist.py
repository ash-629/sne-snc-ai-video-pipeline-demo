#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YouTube playlist management — create / add-video / list.

用法：
  # 创建播放列表
  python playlist.py create \
    --title "Phrases Native Speakers Actually Use" \
    --description "..." \
    --privacy public \
    --channel sne

  # 把视频加入已有播放列表
  python playlist.py add \
    --playlist-id PLxxxxx \
    --video-id yyyyyyy \
    --channel sne

  # 列出当前频道下的所有播放列表
  python playlist.py list --channel sne
"""
import argparse
import json
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '_shared'))
from google_auth import get_youtube_service


def cmd_create(args):
    yt = get_youtube_service(channel=args.channel)
    body = {
        'snippet': {
            'title': args.title,
            'description': args.description or '',
        },
        'status': {'privacyStatus': args.privacy},
    }
    resp = yt.playlists().insert(part='snippet,status', body=body).execute()
    pid = resp['id']
    print(f'✓ 创建播放列表: {pid}', file=sys.stderr)
    print(f'  标题: {resp["snippet"]["title"]}', file=sys.stderr)
    print(f'  隐私: {resp["status"]["privacyStatus"]}', file=sys.stderr)
    print(f'  链接: https://www.youtube.com/playlist?list={pid}', file=sys.stderr)
    print(json.dumps({
        'id': pid,
        'title': resp['snippet']['title'],
        'url': f'https://www.youtube.com/playlist?list={pid}',
    }, ensure_ascii=False))


def cmd_add(args):
    yt = get_youtube_service(channel=args.channel)
    body = {
        'snippet': {
            'playlistId': args.playlist_id,
            'resourceId': {'kind': 'youtube#video', 'videoId': args.video_id},
        }
    }
    resp = yt.playlistItems().insert(part='snippet', body=body).execute()
    print(f'✓ 视频 {args.video_id} 已加入 {args.playlist_id}', file=sys.stderr)
    print(json.dumps({
        'playlistItemId': resp['id'],
        'playlistId': args.playlist_id,
        'videoId': args.video_id,
    }, ensure_ascii=False))


def cmd_list(args):
    yt = get_youtube_service(channel=args.channel)
    out = []
    pageToken = None
    while True:
        resp = yt.playlists().list(
            part='snippet,contentDetails,status',
            mine=True, maxResults=50, pageToken=pageToken,
        ).execute()
        for p in resp.get('items', []):
            out.append({
                'id': p['id'],
                'title': p['snippet']['title'],
                'itemCount': p['contentDetails']['itemCount'],
                'privacy': p['status']['privacyStatus'],
                'url': f'https://www.youtube.com/playlist?list={p["id"]}',
            })
        pageToken = resp.get('nextPageToken')
        if not pageToken:
            break
    for p in out:
        print(f'  {p["id"]}  [{p["privacy"]:8}] {p["itemCount"]:>3} videos  {p["title"]}',
              file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    pc = sub.add_parser('create', help='创建播放列表')
    pc.add_argument('--title', required=True)
    pc.add_argument('--description', default='')
    pc.add_argument('--privacy', default='public', choices=['public', 'unlisted', 'private'])
    pc.add_argument('--channel', default=None)
    pc.set_defaults(func=cmd_create)

    pa = sub.add_parser('add', help='加视频到播放列表')
    pa.add_argument('--playlist-id', required=True)
    pa.add_argument('--video-id', required=True)
    pa.add_argument('--channel', default=None)
    pa.set_defaults(func=cmd_add)

    pl = sub.add_parser('list', help='列出当前频道下所有播放列表')
    pl.add_argument('--channel', default=None)
    pl.set_defaults(func=cmd_list)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
