"""Generate trilingual skeleton from dialogue script.

Reads xxx_对话.txt and produces xxx_三语.txt with:
  Line 1: Chinese (with speaker prefix, untouched)
  Line 2: pinyin (no speaker, no punctuation, lowercase tone-marked, space-separated)
  Line 3: [en]   ← placeholder for Claude to fill with English translation
  blank line between turns

The pinyin is generated programmatically (pypinyin Style.TONE) for accuracy on
less common characters and tone marks. English translation is left to Claude.

See SKILL.md for the translation style guide.
"""
import argparse
from pathlib import Path

from pypinyin import lazy_pinyin, Style


def line_to_pinyin(text: str) -> str:
    """Convert a Chinese text line into a space-separated pinyin string.

    Rules:
      - Chinese characters → one pinyin token each (with tone diacritics, lowercase)
      - Latin runs (Leo, App, MBTI, T) → kept as one token, original case preserved
      - Digits → kept as digits
      - Punctuation, whitespace, anything else → dropped
    """
    tokens: list[str] = []
    latin_buffer = ""

    def flush_latin():
        nonlocal latin_buffer
        if latin_buffer:
            tokens.append(latin_buffer)
            latin_buffer = ""

    for ch in text:
        if "a" <= ch.lower() <= "z":
            latin_buffer += ch
        elif "0" <= ch <= "9":
            flush_latin()
            tokens.append(ch)
        elif "一" <= ch <= "鿿":
            flush_latin()
            py = lazy_pinyin(ch, style=Style.TONE)
            if py:
                tokens.extend(py)
        else:
            # punctuation / whitespace / decorative chars → skip
            flush_latin()

    flush_latin()
    return " ".join(tokens)


def parse_dialogue_line(line: str) -> tuple[str, str] | None:
    """Split a dialogue line into (speaker, content). Returns None for blanks/non-dialogue."""
    line = line.rstrip("\n").rstrip()
    if not line.strip():
        return None
    if "：" in line:
        speaker, content = line.split("：", 1)
    elif ":" in line:
        speaker, content = line.split(":", 1)
    else:
        return None
    return speaker.strip(), content.strip()


def main():
    parser = argparse.ArgumentParser(description="Generate trilingual skeleton from dialogue script")
    parser.add_argument("--in", dest="input", required=True, help="Input xxx_对话.txt path")
    parser.add_argument("--out", required=True, help="Output xxx_三语.txt path")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.out)

    out_lines: list[str] = []
    turn_count = 0
    for raw in input_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_dialogue_line(raw)
        if parsed is None:
            continue
        speaker, content = parsed
        pinyin = line_to_pinyin(content)
        out_lines.append(f"{speaker}：{content}")
        out_lines.append(pinyin)
        out_lines.append("[en]")
        out_lines.append("")  # blank between turns
        turn_count += 1

    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"Generated skeleton: {output_path}")
    print(f"Turns: {turn_count} (each has {{Chinese, pinyin, [en] placeholder}})")
    print(f"Next: Claude reads this file and replaces every [en] with a natural English translation.")


if __name__ == "__main__":
    main()
