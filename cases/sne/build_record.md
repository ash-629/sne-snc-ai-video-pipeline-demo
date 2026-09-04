# 0902 SNE Dialogue Podcast — Build Record

- Topic: `Fair Enough?`
- CEFR: `B1`
- Script: 196 turns (Maya 98 / Ethan 98), 2,323 dialogue words
- Audio: 196/196 WAV files, 48 kHz 16-bit mono PCM
- Voice map: Maya = `en-US-Ava:DragonHDLatestNeural`; Ethan = `en-US-Andrew:DragonHDOmniLatestNeural`
- Speech rate: `0.7`

## Locked talking-head assets

- Library: `<WORKSPACE>/SImply Natural English/对话视频/`
- Maya: `Maya 播客厅 sage丝衫 左`
- Ethan: `Ethan 播客厅 卡其西装 右`
- Both folders were checked using real MP4 frames before the batch build.
- Maya remains left and Ethan remains right for the full episode.

## Image generation

- The episode scene base and complete cover were generated with Codex's built-in image generation capability.
- No relay, third-party image API, or workspace external-image wrapper was used.
- `背景图.png` and `封面.png` are both 1280x720.
- The final background uses the fixed SNE video-window and subtitle-panel template.
- The cover follows the established dialogue layout: Maya left, Ethan right, two microphones, sticker outlines, central stacked title, cream hook banner, B1 badge, and channel handle.
- Full-size and 320px QC versions were visually checked.

## Subtitle and video build

- Whisper ran cue-by-cue on CUDA and produced 196 timing cues.
- Karaoke ASS: 249 display cues from 196 dialogue turns.
- Alignment: 191 exact one-to-one turns, 3 hyphen merges, and 2 proportional fallbacks; displayed text remains the script original.
- Two Azure pauses in turns 98 and 116 were shortened to natural phrase pauses; original WAV files are preserved in `_audio_backup_silencefix/`.
- The fixed master has no silence interval of 2.5 seconds or longer at a -45 dB threshold.
- Clean main video: `final.mp4`
- Background + karaoke master: `final_with_bg_karaoke.mp4`
- Final local master: `Fair Enough.mp4`
- Final specs: H.264, 1920x1080, 30 fps; AAC, 48 kHz stereo; duration 1296.296 seconds; size 184,979,794 bytes.
- Soft intro: 0.5-second cover hold + 0.5-second fade. YouTube captions use `--offset 1.0`.

## Quality control

- Checked frames: cover at 0.2s, fade at 0.8s, Maya, Ethan, repaired turns 98 and 116, middle, final dialogue turn, and outro.
- Cover text is complete and correctly spelled; the B1 label and channel handle are visible.
- Ethan's black rectangular glasses and Maya's left mint highlight are present.
- The fixed title card, video window, and karaoke subtitle area are unobstructed.
- Outro is present after the final dialogue.
- Final audio mean volume: -23.9 dB; peak: -3.0 dB.
- DOCX: 196 dialogue turns + 15 vocabulary entries; English-only content; no CJK characters.
- Independent subtitles: 11 languages, 196 cues each, all matching the English timeline with no replacement characters.

## Publication state

- Uploaded to YouTube as unlisted: `https://www.youtube.com/watch?v=ysUnLJgMOKk`
- YouTube video ID: `ysUnLJgMOKk`
- Processing verified: upload status `processed`, processing status `succeeded`, definition `hd`, duration `PT21M37S`.
- Custom thumbnail verified.
- Uploaded caption tracks with `--offset 1.0`: `zh-Hans`, `es`, `pt`, `id`, `vi`, `ja`, `ko`, `ru`, `fr`, `th`, `de`.
- All 11 caption tracks were read back from YouTube and verified `status=serving`.
