#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Upload caption tracks (SRT/VTT) to a YouTube video.

Each caption track has a BCP-47 language code and a display name that viewers see
in the player's caption menu. One video can have multiple tracks; viewers can switch.

Requires the `youtube.force-ssl` OAuth scope (already in shared ALL_SCOPES).

Usage:
  python captions.py --video-id <id> --language zh-Hans --name "中文" --srt 中文.srt
  python captions.py --video-id <id> --language ko --name "한국어" --srt 한국어.srt
  python captions.py --video-id <id> --language ja --name "日本語" --srt 日本語.srt

Batch (one --track per language, repeatable):
  python captions.py --video-id <id> \
    --track zh-Hans:中文:中文.srt \
    --track ko:한국어:한국어.srt \
    --track ja:日本語:日本語.srt

List existing tracks (delete-and-replace flow):
  python captions.py --video-id <id> --list
  python captions.py --video-id <id> --delete-existing \
    --track zh-Hans:中文:中文.srt ...
"""
import argparse
import os
import re
import sys
import tempfile

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '_shared'))
from google_auth import get_youtube_service


_TS_RE = re.compile(
    r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})')


def _fmt_srt_ts(t):
    """seconds → SRT timestamp HH:MM:SS,mmm (comma ms, clamped ≥ 0)."""
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def shift_srt(srt_path, offset):
    """Shift every cue in an SRT by +offset seconds; write a temp .srt; return its path.

    Used when the final video has a soft intro (cover-hold + fade) before the body —
    body-time SRTs are `offset` seconds early on the final video. VTT is left
    untouched (warn) since it uses a different header/format.
    """
    with open(srt_path, encoding='utf-8-sig') as f:
        text = f.read()
    if text.lstrip().upper().startswith('WEBVTT'):
        print(f'  [offset] {os.path.basename(srt_path)} looks like VTT — uploading without offset', flush=True)
        return srt_path

    def repl(m):
        a = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1000 + offset
        b = int(m[5]) * 3600 + int(m[6]) * 60 + int(m[7]) + int(m[8]) / 1000 + offset
        return f'{_fmt_srt_ts(a)} --> {_fmt_srt_ts(b)}'

    shifted, n = _TS_RE.subn(repl, text)
    tmp = tempfile.NamedTemporaryFile('w', suffix='.srt', delete=False, encoding='utf-8')
    tmp.write(shifted)
    tmp.close()
    print(f'  [offset] {os.path.basename(srt_path)} +{offset:g}s ({n} cues) → temp', flush=True)
    return tmp.name


def list_captions(youtube, video_id):
    resp = youtube.captions().list(part='id,snippet', videoId=video_id).execute()
    items = resp.get('items', [])
    print(f'video {video_id} has {len(items)} caption track(s):')
    for it in items:
        s = it['snippet']
        print(f'  id={it["id"]} lang={s["language"]:8} name={s.get("name", "")!r} '
              f'kind={s.get("trackKind", "")} status={s.get("status", "")}')
    return items


def delete_caption(youtube, caption_id):
    youtube.captions().delete(id=caption_id).execute()
    print(f'  deleted caption {caption_id}')


def upload_caption(youtube, video_id, language, name, srt_path, is_draft=False):
    from googleapiclient.http import MediaFileUpload
    body = {
        'snippet': {
            'videoId': video_id,
            'language': language,
            'name': name,
            'isDraft': is_draft,
        }
    }
    # YouTube auto-detects format from file content; SRT is supported.
    media = MediaFileUpload(srt_path, mimetype='application/octet-stream',
                            resumable=False)
    resp = youtube.captions().insert(part='snippet', body=body, media_body=media).execute()
    print(f'  uploaded {language:8} "{name}" → caption id {resp["id"]}')
    return resp


def parse_track_spec(spec):
    """spec format: 'language:name:srt_path' — name may contain colons in path? we split twice"""
    parts = spec.split(':', 2)
    if len(parts) != 3:
        raise SystemExit(f'--track must be language:name:srt_path, got: {spec!r}')
    lang, name, srt = parts
    return lang.strip(), name.strip(), srt.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video-id', required=True)
    ap.add_argument('--list', action='store_true', help='List existing captions and exit')
    ap.add_argument('--delete-existing', action='store_true',
                    help='Delete tracks matching the same language before uploading')

    # Single-track form
    ap.add_argument('--language', help='BCP-47 code (zh-Hans, ko, ja, en, ...)')
    ap.add_argument('--name', help='Display name shown in player menu')
    ap.add_argument('--srt', help='SRT/VTT file to upload')

    # Batch form
    ap.add_argument('--track', action='append', default=[],
                    help='Repeatable: language:name:srt_path')

    ap.add_argument('--is-draft', action='store_true',
                    help='Upload as draft (not visible to viewers)')
    ap.add_argument('--offset', type=float, default=0.0,
                    help='把每条字幕时间整体 +offset 秒再上传（成片有软开场时用片头长度，'
                         '默认软开场 cover-hold+fade=1.0）。SRT 专用；VTT 不动')
    ap.add_argument('--channel', default=None,
                    help='channel id deciding which token file to use (sne → token_sne.json)')
    args = ap.parse_args()

    youtube = get_youtube_service(channel=args.channel)

    if args.list:
        list_captions(youtube, args.video_id)
        return

    # Build the list of tracks to upload
    tracks = []
    if args.language or args.name or args.srt:
        if not (args.language and args.name and args.srt):
            raise SystemExit('--language, --name, --srt must all be provided together')
        tracks.append((args.language, args.name, args.srt))
    tracks.extend(parse_track_spec(t) for t in args.track)
    if not tracks:
        raise SystemExit('no tracks specified (use --language/--name/--srt or --track)')

    if args.delete_existing:
        existing = list_captions(youtube, args.video_id)
        target_langs = {lang for lang, _, _ in tracks}
        for it in existing:
            if it['snippet']['language'] in target_langs:
                delete_caption(youtube, it['id'])

    temps = []
    try:
        for lang, name, srt in tracks:
            if not os.path.exists(srt):
                raise SystemExit(f'srt not found: {srt}')
            upload_path = srt
            if args.offset:
                upload_path = shift_srt(srt, args.offset)
                if upload_path != srt:
                    temps.append(upload_path)
            upload_caption(youtube, args.video_id, lang, name, upload_path, args.is_draft)
    finally:
        for t in temps:
            try:
                os.unlink(t)
            except OSError:
                pass

    print('done')


if __name__ == '__main__':
    main()
