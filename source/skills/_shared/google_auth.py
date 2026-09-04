#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google API 共享 OAuth 模块（YouTube + Drive）

被 youtube-upload, google-drive-upload, youtube-comment 共享。
首次授权时一次性请求所有 scope，后续每次免登录。
"""

import os
import sys
from pathlib import Path

# 工作区根目录从本文件位置反推（skills/_shared/google_auth.py → parents[2]），搬家不用改
CRED_DIR = str(Path(__file__).resolve().parents[2] / '.youtube_credentials')
CLIENT_SECRET = os.path.join(CRED_DIR, 'client_secret.json')
DEFAULT_TOKEN_FILE = os.path.join(CRED_DIR, 'token.json')  # legacy single-channel path

# 所有功能需要的 scope 集合（personal Google 账号 = 主频道 = 默认 channel）
#
# ⚠️ 2026-07-30：Google 开始拒绝把 Drive scope 和 YouTube scope 放进**同一个**授权请求
#    （"This request contains scopes that cannot be requested together"，Error 400
#    invalid_request）。所以 Drive 单独拆出去授权，见 DRIVE_SCOPES / token_drive.json。
ALL_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl',  # 评论 + 置顶 + 字幕
    'https://www.googleapis.com/auth/yt-analytics.readonly',  # YouTube Analytics 只读（播放量/留存/流量来源）
]

# Drive 独立授权（不能和 YouTube scope 一起请求）。永远走 personal 账号。
DRIVE_SCOPES = [
    'https://www.googleapis.com/auth/drive.file',         # Drive 上传（仅本应用创建的文件）
]
DRIVE_TOKEN_FILE = os.path.join(CRED_DIR, 'token_drive.json')

# Brand Channel（YouTube 品牌账号）只有 YouTube 服务，**没有 Drive**。
# 用这个 scope 集做 OAuth 才能授权过；否则 Google 会报"您的账号没有权限使用您尝试访问的服务"。
# Drive 上传请一律走 personal 账号（不传 --channel）。
BRAND_CHANNEL_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/yt-analytics.readonly',  # YouTube Analytics 只读
]


def _default_scopes(channel):
    """channel=None/default → 主频道, 含 Drive; 其他 → Brand Channel, 无 Drive."""
    if not channel or channel == 'default':
        return ALL_SCOPES
    return BRAND_CHANNEL_SCOPES


def _safe_channel(channel):
    """Normalize a channel name to a filesystem-safe slug, or '' for default."""
    channel = channel or os.getenv('YT_CHANNEL')
    if not channel or channel == 'default':
        return ''
    safe = ''.join(c for c in channel if c.isalnum() or c in ('-', '_')).lower()
    if not safe:
        raise SystemExit(f'invalid channel name: {channel!r}')
    return safe


def _token_path(channel=None, kind='youtube'):
    """Map channel name to token file path.

    - kind='drive': token_drive.json — Drive 独立授权，永远主账号，不分频道
    - channel=None (or env var unset): use the legacy single-channel token.json
    - channel='sne': token_sne.json — one file per channel, never overwrites others
    """
    if kind == 'drive':
        return DRIVE_TOKEN_FILE
    safe = _safe_channel(channel)
    if not safe:
        return DEFAULT_TOKEN_FILE
    return os.path.join(CRED_DIR, f'token_{safe}.json')


def _client_secret_path(channel=None):
    """Map a channel to its OAuth client_secret file.

    A channel can live in its own Google Cloud project (so it gets a separate
    daily API quota). If client_secret_{channel}.json exists, use it; otherwise
    fall back to the shared client_secret.json (single-project setup).

    Note: a token file bakes in the client_id/secret it was authorized with, so
    after dropping in a new client_secret_{channel}.json you must delete the old
    token_{channel}.json to force a fresh authorization against the new project.
    """
    safe = _safe_channel(channel)
    if safe:
        per_channel = os.path.join(CRED_DIR, f'client_secret_{safe}.json')
        if os.path.exists(per_channel):
            return per_channel
    return CLIENT_SECRET


def get_credentials(scopes=None, channel=None, kind='youtube'):
    """获取 Google OAuth 凭证

    channel: 用来区分多频道的 token 文件名。None / 'default' → token.json (老路径)。
             其他值 → token_{channel}.json，每个频道一份不互相覆盖。
             也可以走环境变量 YT_CHANNEL 设置。
    kind:    'youtube'（默认）或 'drive'。Drive 必须单独授权——Google 不允许
             Drive scope 和 YouTube scope 出现在同一个授权请求里。
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    if kind == 'drive':
        target_scopes = scopes or DRIVE_SCOPES
    else:
        target_scopes = scopes or _default_scopes(channel)
    token_file = _token_path(channel, kind=kind)

    creds = None
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, target_scopes)
        except Exception:
            # scope 变了导致 token 不兼容，重新授权
            creds = None

    needs_reauth = False
    if not creds:
        needs_reauth = True
    else:
        # 检查现有 token 是否覆盖所有需要的 scope
        existing_scopes = set(creds.scopes or [])
        if not set(target_scopes).issubset(existing_scopes):
            print(f'{token_file} 的 scope 不全，需要重新授权', file=sys.stderr)
            needs_reauth = True
        elif not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f'token 刷新失败: {e}, 重新授权', file=sys.stderr)
                    needs_reauth = True
            else:
                needs_reauth = True

    if needs_reauth:
        client_secret = _client_secret_path(channel)
        if not os.path.exists(client_secret):
            raise SystemExit(
                f'未找到 client_secret 文件: {client_secret}\n'
                f'参见 youtube-upload SKILL.md 配置 Google Cloud OAuth'
            )
        flow = InstalledAppFlow.from_client_secrets_file(client_secret, target_scopes)
        ch_hint = f'[频道: {channel}] ' if channel and channel != 'default' else ''
        print(f'{ch_hint}首次授权（或 scope 变更）：浏览器会打开 Google 登录页，请授权...',
              file=sys.stderr)
        print(f'⚠ 关键步骤：登录后会出现"选择频道"页，必须选对要绑定的频道（如 Simply Natural English），'
              f'不要选默认个人频道，否则 token 会绑到错的频道。',
              file=sys.stderr)
        creds = flow.run_local_server(port=0)
        with open(token_file, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())
        print(f'授权令牌已保存到: {token_file}', file=sys.stderr)

    return creds


def _proxy_http():
    """Return a google_auth_httplib2.AuthorizedHttp-compatible httplib2.Http
    with proxy from HTTPS_PROXY/HTTP_PROXY env vars, or None if no proxy.

    httplib2 (googleapiclient 底层) 不读 HTTPS_PROXY 环境变量，必须显式注入。
    """
    proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
    if not proxy_url:
        return None
    import httplib2
    from urllib.parse import urlparse
    u = urlparse(proxy_url)
    # proxy_type=3 = HTTP (avoids needing socks module)
    proxy_info = httplib2.ProxyInfo(
        proxy_type=3,
        proxy_host=u.hostname,
        proxy_port=u.port or 80,
    )
    http = httplib2.Http(proxy_info=proxy_info, timeout=300)
    # Resumable uploads return 308 Resume Incomplete as a control-flow signal;
    # httplib2 mistakes it for a redirect (because some proxies strip Location).
    # googleapiclient handles redirects/308s itself, so turn httplib2 off.
    http.follow_redirects = False
    return http


def _build(api, version, credentials):
    from googleapiclient.discovery import build
    http = _proxy_http()
    if http is None:
        return build(api, version, credentials=credentials)
    import google_auth_httplib2
    authed = google_auth_httplib2.AuthorizedHttp(credentials, http=http)
    return build(api, version, http=authed)


def get_youtube_service(channel=None):
    return _build('youtube', 'v3', get_credentials(channel=channel))


def get_analytics_service(channel=None):
    """YouTube Analytics API v2（reports.query：播放量/留存/流量来源）。

    需要 yt-analytics.readonly scope（已并入默认 scope 集）。注意：
    展示次数(impressions) 和 展示点击率(CTR) 公共 API 不提供，只能在
    YouTube Studio 里看；留存(averageViewPercentage) 和流量来源可以拿到。
    """
    return _build('youtubeAnalytics', 'v2', get_credentials(channel=channel))


def get_drive_service(channel=None):
    """Drive 上传永远走 personal 账号，用独立的 token_drive.json。

    Brand Channel（YouTube 品牌账号）没有 Google Drive，所以即便上游
    命令传了 --channel sne，这里也强制忽略，落到主账号 token。Drive
    文件设为"任何人凭链接可查看"后，宿主账号对观众不可见。

    2026-07-30 起 Drive 和 YouTube 分开授权（Google 拒绝二者同请求），
    所以第一次调用会单独弹一次浏览器授权，存到 token_drive.json。
    """
    if channel and channel != 'default':
        print(f'[google_auth] 忽略 --channel {channel}：Drive 一律走主账号 token_drive.json',
              file=sys.stderr)
    return _build('drive', 'v3', get_credentials(channel=None, kind='drive'))
