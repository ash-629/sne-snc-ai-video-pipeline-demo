#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Azure TTS 批量音频生成

把对话脚本（角色：台词 / Speaker: text）转成多个 WAV 文件，每行对话生成一个文件。
输出格式: 48kHz 16-bit mono PCM WAV，文件名 {001}_{speaker}.wav

用法：
  python tts.py \
    --script <脚本.txt> \
    --output-dir <输出文件夹> \
    [--rate 0.6] \              # 语速（0.5=慢, 1.0=正常）
    [--start 1] [--end 999] \    # 只合成指定行
    [--region eastus] \
    [--api-key <Azure key>]      # 默认从 AZURE_SPEECH_KEY 环境变量读

角色音色映射用 --voice-map 传 JSON 字符串，或用环境变量 {ROLE}_VOICE。
"""

import os
import re
import sys
import time
import json
import argparse
import datetime
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# 默认音色映射（覆盖项目里现有的角色）
DEFAULT_VOICE_MAP = {
    '小悦': 'zh-CN-Xiaoxiao2:DragonHDFlashLatestNeural',  # 晓晓HD 多情感
    'Leo': 'zh-CN-Yunyi:DragonHDFlashLatestNeural',        # 云逸HD
    '甜甜': 'zh-CN-Xiaochen:DragonHDLatestNeural',         # Xiaochen Dragon HD（2026-05-28 用户指定永久从晓伊HD换成此）
    '阿杰': 'zh-CN-Yunxi:DragonHDFlashLatestNeural',       # 云希 Yunxi DragonHD Flash（2026-06-22 用户试听后从云翰HD永久换）
}
DEFAULT_VOICE = 'zh-CN-XiaoxiaoNeural'  # fallback


def parse_line(line):
    """从 '角色：台词' 或 '角色: 台词' 提取 (speaker, text)

    取最先出现的冒号（中文 '：' 或英文 ':'）作为说话人分隔符，
    避免台词里的英文冒号（如情感标记 {calm:1.2}）被误当成分隔符。
    """
    i_en = line.find(':')
    i_cn = line.find('：')
    candidates = [i for i in (i_en, i_cn) if i != -1]
    if not candidates:
        return None, None
    idx = min(candidates)
    return line[:idx].strip(), line[idx + 1:].strip()


def extract_style(text):
    """解析台词开头可选的情感标记 → (style, degree, text_without_marker)。

    向后兼容：不带标记的台词原样返回 (None, 1.0, text)。
    支持格式（紧贴台词开头）：
        {sad}台词           → style=sad, degree=1.0
        {cheerful:0.8}台词  → style=cheerful, degree=0.8
    情感样式由音色支持，经典 Neural（如 zh-CN-XiaoxiaoNeural）支持最全：
    calm/gentle/sad/cheerful/serious/affectionate/chat/angry/fearful/lyrical 等。
    """
    if not text.startswith('{'):
        return None, 1.0, text
    close = text.find('}')
    if close == -1:
        return None, 1.0, text
    marker = text[1:close].strip()
    rest = text[close + 1:].lstrip()
    if not marker:
        return None, 1.0, rest
    if ':' in marker:
        style, _, deg = marker.partition(':')
        try:
            degree = float(deg)
        except ValueError:
            degree = 1.0
        return style.strip(), degree, rest
    return marker, 1.0, rest


def get_voice(speaker, voice_map):
    if speaker in voice_map:
        return voice_map[speaker]
    env_key = f"{speaker.upper()}_VOICE"
    env_voice = os.getenv(env_key)
    if env_voice:
        return env_voice
    return DEFAULT_VOICE


def _lang_from_voice(voice_name: str) -> str:
    """Derive xml:lang from a voice name like 'en-US-Ava:...' or 'zh-CN-Xiaoyi:...'."""
    parts = voice_name.split('-')
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1].split(':')[0]}"
    return "zh-CN"


_CJK_RE = re.compile(r'[一-鿿]')


def split_long_text(text, max_words):
    """
    把长台词按自然边界切成若干段，避免 Azure RTF 超时把长句截断。

    - 中文台词（含 CJK 字符）：max_words 视为最大**字符数**，优先按 。！？
      切句，单句还过长再按 ；，、 切分句。
    - 英文台词：max_words 视为最大**词数**，优先按 .!? 切句，过长再按 ;, 切。

    末尾标点保留。max_words <= 0 表示不切。
    """
    text = text.strip()
    if max_words <= 0:
        return [text]

    chinese = bool(_CJK_RE.search(text))
    measure = (lambda s: len(s)) if chinese else (lambda s: len(s.split()))
    join = (lambda parts: ''.join(parts)) if chinese else (lambda parts: ' '.join(parts))
    end_pat = r'(?<=[。！？])' if chinese else r'(?<=[.!?])\s+'
    clause_pat = r'(?<=[；，、])' if chinese else r'(?<=[;,])\s+'

    if measure(text) <= max_words:
        return [text]

    def pack(pieces):
        """把若干片段贪心打包成不超过 max_words 的 chunk 列表"""
        chunks, buf, buf_n = [], [], 0
        for p in pieces:
            if not p:
                continue
            n = measure(p)
            if buf and buf_n + n > max_words:
                chunks.append(join(buf))
                buf, buf_n = [p], n
            else:
                buf.append(p)
                buf_n += n
        if buf:
            chunks.append(join(buf))
        return chunks

    # 1) 按句末标点打包
    chunks = pack(re.split(end_pat, text))

    # 2) 单句仍超长的，再按分句标点切
    final = []
    for c in chunks:
        if measure(c) <= max_words:
            final.append(c)
        else:
            final.extend(pack(re.split(clause_pat, c)))
    return final


def _pad_wav_silence(wav_path, head_s=0.0, tail_s=0.0):
    """Add silence to head and/or tail of a WAV file (in-place)."""
    if head_s <= 0 and tail_s <= 0:
        return
    parts = []
    if head_s > 0:
        parts.append(f'adelay={int(head_s * 1000)}')
    if tail_s > 0:
        parts.append(f'apad=pad_dur={tail_s}')
    af = ','.join(parts)
    tmp = wav_path + '.pad.wav'
    subprocess.run(
        ['ffmpeg', '-y', '-i', wav_path, '-af', af,
         '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '1', tmp],
        check=True, capture_output=True,
    )
    os.replace(tmp, wav_path)


def concat_wavs(part_paths, out_path):
    """用 ffmpeg concat demuxer 把若干同格式 WAV 拼成一个 WAV"""
    # list 文件写绝对路径：concat demuxer 按 list 文件所在目录（临时目录）
    # 解析相对路径，传相对 --output-dir 时会找不到 part 文件
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
        for p in part_paths:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
        list_path = f.name
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_path,
             '-c', 'copy', out_path],
            check=True, capture_output=True
        )
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass


def synthesize_one(speech_config, voice_name, text, file_path, rate,
                   max_retries=2, style=None, degree=1.0):
    """合成一句台词到 file_path，最多重试 max_retries 次。

    style 不为空时用 <mstts:express-as> 包裹，给台词加情感语气（degree 为强度 0.01–2.0）。
    style 为 None 时行为与旧版完全一致（只有 <prosody rate>）。
    """
    import azure.cognitiveservices.speech as speechsdk

    lang = _lang_from_voice(voice_name)
    # Azure voices (Ava/DragonHD esp.) often SWALLOW the whole clause after an
    # em/en-dash instead of pausing — e.g. "bright blue — not one cloud" loses
    # "not one cloud". Replace —/–/-- with a comma so it reliably pauses. Only
    # the synthesis text is touched; the visible script & subtitles keep the
    # dashes. Single hyphens (thirty-five) are left intact.
    # See [[feedback-snippets-tts-explain-split-dash]].
    text = re.sub(r'\s*(?:—|–|--)\s*', ', ', text)
    inner = f'<prosody rate="{rate}">{text}</prosody>'
    if style:
        inner = (f'<mstts:express-as style="{style}" styledegree="{degree}">'
                 f'{inner}</mstts:express-as>')
    ssml_text = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{lang}">
  <voice name="{voice_name}">
    {inner}
  </voice>
</speak>"""

    for attempt in range(max_retries + 1):
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

        # 每次都重建 audio_config 和 synthesizer，避免 SDK 复用句柄堆叠
        audio_config = speechsdk.audio.AudioOutputConfig(filename=file_path)
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config,
                                                  audio_config=audio_config)
        result = synthesizer.speak_ssml_async(ssml_text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return True, result.audio_duration

        if result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            if attempt < max_retries:
                print(f'   ⚠ 重试 {attempt + 1}/{max_retries + 1}', flush=True)
                time.sleep(1)
                continue
            print(f'   ❌ 失败: {details.reason}', flush=True)
            if details.reason == speechsdk.CancellationReason.Error:
                print(f'      详情: {details.error_details}', flush=True)
            return False, None

    return False, None


def _make_speech_config(api_key, region):
    import azure.cognitiveservices.speech as speechsdk
    cfg = speechsdk.SpeechConfig(subscription=api_key, region=region)
    proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or os.getenv('ALL_PROXY')
    if proxy_url:
        from urllib.parse import urlparse
        p = urlparse(proxy_url)
        cfg.set_proxy(p.hostname, p.port or 7897)
    cfg.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, '30000'
    )
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm
    )
    return cfg


def generate_audio(script_path, output_dir, rate=0.7, start=1, end=None,
                   voice_map=None, region='eastus', api_key=None, concurrency=5,
                   max_words=0, speaker_head_pad=0.0, speaker_tail_pad=0.0):
    api_key = api_key or os.getenv('AZURE_SPEECH_KEY')
    if not api_key:
        raise SystemExit('需要 Azure API Key（环境变量 AZURE_SPEECH_KEY 或 --api-key）')

    voice_map = voice_map or DEFAULT_VOICE_MAP

    os.makedirs(output_dir, exist_ok=True)

    with open(script_path, encoding='utf-8') as f:
        lines = [l.strip() for l in f if l.strip()]

    end = end or float('inf')

    # 先解析出所有要合成的任务
    tasks = []
    # 全量 line_number -> speaker（不受 --start/--end 限制）。speaker 切换静音必须按
    # 整份脚本的前后行判断：局部重生成（--start 50 --end 52）时 tasks 只有子集，
    # 拿子集判断会让重合成的那几句丢掉 pad，跟周围对不上。
    all_speakers = {}
    line_number = 0
    for raw in lines:
        speaker, text = parse_line(raw)
        if not speaker:
            print(f'⚠ 跳过格式错误的行: {raw[:40]}...', flush=True)
            continue
        style, degree, text = extract_style(text)
        line_number += 1
        all_speakers[line_number] = speaker
        if line_number < start or line_number > end:
            continue
        voice_name = get_voice(speaker, voice_map)
        # 删除该序号的旧文件（角色名可能改了）
        prefix = f'{line_number:03d}_'
        for fn in os.listdir(output_dir):
            if fn.startswith(prefix) and fn.endswith('.wav'):
                try:
                    os.remove(os.path.join(output_dir, fn))
                except OSError:
                    pass
        file_path = os.path.join(output_dir, f'{line_number:03d}_{speaker}.wav')
        chunks = split_long_text(text, max_words)
        tasks.append((line_number, speaker, chunks, voice_name, file_path, style, degree))

    total_duration = datetime.timedelta()
    success = 0
    fail = 0
    t0 = time.time()
    lock = threading.Lock()
    done = [0]
    n = len(tasks)

    # 每个线程一个 SpeechConfig（SDK 对象不保证完全线程安全，分开更稳）
    tlocal = threading.local()

    def worker(task):
        ln, speaker, chunks, voice_name, file_path, style, degree = task
        if not hasattr(tlocal, 'cfg'):
            tlocal.cfg = _make_speech_config(api_key, region)

        if len(chunks) == 1:
            ok, duration = synthesize_one(tlocal.cfg, voice_name, chunks[0], file_path, rate,
                                          style=style, degree=degree)
            split_note = ''
        else:
            # 长段切片合成 → ffmpeg 拼接
            part_paths = []
            total_dur = datetime.timedelta()
            all_ok = True
            for i, chunk in enumerate(chunks, 1):
                part_path = file_path.replace('.wav', f'.part{i}.wav')
                pok, pdur = synthesize_one(tlocal.cfg, voice_name, chunk, part_path, rate,
                                           style=style, degree=degree)
                if not pok:
                    all_ok = False
                    break
                part_paths.append(part_path)
                if pdur:
                    total_dur += pdur
            if all_ok:
                try:
                    concat_wavs(part_paths, file_path)
                    ok, duration = True, total_dur
                except subprocess.CalledProcessError as e:
                    print(f'   ❌ concat 失败 line {ln}: {e.stderr.decode("utf-8", "replace")[-500:]}', flush=True)
                    ok, duration = False, None
            else:
                ok, duration = False, None
            # 清理 part 文件
            for p in part_paths:
                try: os.remove(p)
                except OSError: pass
            split_note = f' [split×{len(chunks)}]'

        with lock:
            done[0] += 1
            elapsed = time.time() - t0
            status = 'ok' if ok else 'FAIL'
            print(f'[{done[0]:03d}/{n}] line {ln:03d} {speaker} ({voice_name.split(":")[0]}) | rate={rate}{split_note} | {status} | 已用{elapsed:.0f}s', flush=True)
        return ok, duration

    if concurrency <= 1:
        for task in tasks:
            ok, duration = worker(task)
            if ok:
                success += 1
                if duration:
                    total_duration += duration
            else:
                fail += 1
            time.sleep(0.3)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = [ex.submit(worker, task) for task in tasks]
            for fut in as_completed(futures):
                ok, duration = fut.result()
                if ok:
                    success += 1
                    if duration:
                        total_duration += duration
                else:
                    fail += 1

    if (speaker_head_pad > 0 or speaker_tail_pad > 0) and success > 0:
        print(f'\n--- 添加 speaker 切换静音 (head={speaker_head_pad}s, tail={speaker_tail_pad}s) ---', flush=True)
        sorted_tasks = sorted(tasks, key=lambda t: t[0])
        pad_count = 0
        for ln, speaker, chunks, voice_name, file_path, style, degree in sorted_tasks:
            if not os.path.exists(file_path):
                continue
            # 缺省取自身 speaker → 整份脚本的首行不加 head、末行不加 tail
            head = speaker_head_pad if all_speakers.get(ln - 1, speaker) != speaker else 0.0
            tail = speaker_tail_pad if all_speakers.get(ln + 1, speaker) != speaker else 0.0
            if head > 0 or tail > 0:
                try:
                    _pad_wav_silence(file_path, head, tail)
                    pad_count += 1
                except subprocess.CalledProcessError:
                    print(f'  ⚠ pad 失败: {os.path.basename(file_path)}', flush=True)
        print(f'  padded {pad_count}/{len(sorted_tasks)} WAVs', flush=True)

    print(f'\n=== 完成 ===', flush=True)
    print(f'成功: {success} | 失败: {fail} | 并发: {concurrency} | 总耗时: {time.time()-t0:.0f}s', flush=True)
    if total_duration.total_seconds() > 0:
        print(f'音频总时长: {total_duration}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--script', required=True, help='对话脚本 txt 路径')
    ap.add_argument('--output-dir', required=True, help='输出 WAV 文件夹')
    ap.add_argument('--rate', type=float, default=0.7, help='语速倍率（默认 0.7）')
    ap.add_argument('--start', type=int, default=1, help='起始行号')
    ap.add_argument('--end', type=int, default=None, help='结束行号（含）')
    ap.add_argument('--voice-map', help='角色→音色映射 JSON 字符串，如 \'{"甜甜":"zh-CN-Xiaoxiao2:DragonHDFlashLatestNeural"}\'')
    ap.add_argument('--region', default='eastus', help='Azure 区域（默认 eastus）')
    ap.add_argument('--api-key', help='Azure Speech API Key（默认从环境变量读）')
    ap.add_argument('--concurrency', type=int, default=5, help='并发线程数（默认 5；设 1 则串行）')
    ap.add_argument('--max-words', type=int, default=0,
                    help='超长台词按句末/分句标点切片合成再 ffmpeg 拼接（避免 Azure RTF 超时截断）。'
                         '0=不切（默认）。中文按字符数算，推荐 38-42；英文 SNE 按词数算，推荐 25-30')
    ap.add_argument('--speaker-head-pad', type=float, default=0.1,
                    help='Silence (seconds) prepended to WAV when previous speaker differs (default 0.1). '
                         '单说话人脚本（独白系列）永远不触发，设 0 可完全关闭')
    ap.add_argument('--speaker-tail-pad', type=float, default=0.2,
                    help='Silence (seconds) appended to WAV when next speaker differs (default 0.2). '
                         '设 0 可完全关闭')
    args = ap.parse_args()

    voice_map = None
    if args.voice_map:
        voice_map = json.loads(args.voice_map)

    generate_audio(args.script, args.output_dir, args.rate, args.start, args.end,
                   voice_map, args.region, args.api_key, args.concurrency, args.max_words,
                   args.speaker_head_pad, args.speaker_tail_pad)


if __name__ == '__main__':
    main()
