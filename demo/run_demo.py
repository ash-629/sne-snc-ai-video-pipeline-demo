"""Offline, standard-library-only processing demo using copied production scripts.

Demo runner added on 2026-09-04. No TTS, ASR inference or network
calls are made. Negative fixtures simulate damaged cached text/timing output.
"""
from pathlib import Path
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'demo' / 'output'
SRC = ROOT / 'source' / 'skills'
FIX = ROOT / 'demo' / 'fixtures'


def relative(path):
    return str(Path(path).relative_to(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    OUT.mkdir(parents=True, exist_ok=True)
    checks = []

    def run(name, script, *args, expected=0):
        cmd = [sys.executable, relative(script), *map(str, args)]
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                              encoding='utf-8', errors='replace', timeout=60)
        log = OUT / f'{name}.txt'
        log.write_text(proc.stdout + proc.stderr, encoding='utf-8')
        result = {'name': name, 'expected_exit': expected, 'actual_exit': proc.returncode,
                  'passed': proc.returncode == expected, 'log': relative(log)}
        checks.append(result)
        print(f"{'PASS' if result['passed'] else 'FAIL'} {name} (exit={proc.returncode}, expected={expected})")
        return proc

    # Work on copies; never alter the evidence fixtures.
    good = OUT / 'sne'
    good.mkdir(exist_ok=True)
    for name in ['script.txt', 'script_sentences.txt', '全片_words.json', 'timeline.json']:
        shutil.copyfile(FIX / 'sne' / name, good / name)

    run('01_real_sample_ass', SRC / 'sne-video-pipeline/scripts/build_karaoke_ass.py',
        '--episode-dir', relative(good))
    run('02_real_sample_tts_check', SRC / 'sne-easy-monologue/scripts/check_tts_coverage.py',
        '--episode-dir', relative(good), '--strict')
    run('03_real_sample_pinyin', SRC / 'dialogue-trilingual/scripts/check_pinyin_count.py',
        '--script', relative(FIX / 'snc/trilingual.txt'))

    # Ensure display text actually preserves the source wording, not just that
    # the generation command exited successfully.
    original = (good / 'script.txt').read_text(encoding='utf-8')
    expected = []
    for line in original.splitlines():
        if line.strip():
            expected.extend(line.split(':', 1)[1].split())
    ass = good / '全片.ass'
    actual = []
    if ass.exists():
        for line in ass.read_text(encoding='utf-8').splitlines():
            if line.startswith('Dialogue: '):
                actual.extend(re.sub(r'\{[^}]*\}', '', line.split(',', 9)[9]).split())
    checks.append({'name':'04_source_wording_preserved', 'passed': actual == expected,
                   'expected_words':len(expected), 'actual_words':len(actual)})

    # This is a controlled damaged-ASR-cache fixture, not newly generated audio.
    bad = OUT / 'negative_truncation'
    bad.mkdir(exist_ok=True)
    shutil.copyfile(good / 'script_sentences.txt', bad / 'script_sentences.txt')
    cues = json.loads((good / '全片_words.json').read_text(encoding='utf-8'))
    cues['cues'][-1] = cues['cues'][-1][:2]
    (bad / '全片_words.json').write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding='utf-8')
    run('05_detect_truncated_cache', SRC / 'sne-easy-monologue/scripts/check_tts_coverage.py',
        '--episode-dir', relative(bad), '--strict', expected=1)

    lines = (FIX / 'snc/trilingual.txt').read_text(encoding='utf-8').splitlines()
    lines[1] = ' '.join(lines[1].split()[:-1])
    damaged = OUT / 'negative_pinyin.txt'
    damaged.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    run('06_detect_missing_pinyin', SRC / 'dialogue-trilingual/scripts/check_pinyin_count.py',
        '--script', relative(damaged), expected=1)

    # Import only the pure timestamp helper; no authorization/client is created.
    spec = importlib.util.spec_from_file_location('captions_demo', SRC / 'youtube-upload/scripts/captions.py')
    captions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(captions)
    srt = OUT / 'offset_input.srt'
    srt.write_text('1\n00:00:00,250 --> 00:00:01,750\nFair enough.\n', encoding='utf-8')
    shifted_path = Path(captions.shift_srt(str(srt), 1.0))
    try:
        shifted = shifted_path.read_text(encoding='utf-8')
        (OUT / 'offset_plus_1s.srt').write_text(shifted, encoding='utf-8')
        checks.append({'name':'07_soft_intro_offset', 'passed': shifted ==
                       '1\n00:00:01,250 --> 00:00:02,750\nFair enough.\n'})
    finally:
        shifted_path.unlink()

    report = {'scope':'Offline subset only: existing ASR cache, ASS generation, text/pinyin QA, SRT offset.',
              'network_calls':False, 'new_model_inference':False,
              'negative_cases':'Controlled damaged cache and missing pinyin token, added for this demo.',
              'checks':checks, 'passed':all(c['passed'] for c in checks)}
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n{'PASS' if report['passed'] else 'FAIL'}: {sum(c['passed'] for c in checks)}/{len(checks)} checks. See demo/output/report.json")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
