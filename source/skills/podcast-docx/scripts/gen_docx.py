#!/usr/bin/env python3
"""
播客三语文档生成器
输入：对话脚本 txt + 中/拼/英三个 SRT 文件
输出：格式化的 DOCX 学习文档
"""

import re
import sys
import json

# Fix Windows GBK console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'cp936', 'gb2312'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml


# ============ 颜色定义 ============
COLOR_ORANGE = RGBColor(0xC0, 0x5C, 0x1A)  # #C05C1A
COLOR_GRAY = RGBColor(0x4A, 0x4A, 0x4A)    # #4A4A4A
COLOR_BLUE = RGBColor(0x2E, 0x75, 0xB6)    # #2E75B6
COLOR_TEAL = RGBColor(0x1A, 0x7A, 0x6E)    # #1A7A6E 小悦
COLOR_BLACK = RGBColor(0x1A, 0x1A, 0x1A)   # #1A1A1A

# 角色颜色（甜甜/小悦 → 青绿；阿杰/Leo → 橙）
SPEAKER_COLORS = {
    '甜甜':  {'bg': RGBColor(0xE8, 0xF5, 0xF3), 'border': COLOR_TEAL},
    '小悦':  {'bg': RGBColor(0xE8, 0xF5, 0xF3), 'border': COLOR_TEAL},
    '阿杰':  {'bg': RGBColor(0xFE, 0xF3, 0xEC), 'border': COLOR_ORANGE},
    'Leo':   {'bg': RGBColor(0xFE, 0xF3, 0xEC), 'border': COLOR_ORANGE},
}
# Fallback palette for unknown speakers: alternate teal / orange
_FALLBACK_COLORS = [
    {'bg': RGBColor(0xE8, 0xF5, 0xF3), 'border': COLOR_TEAL},
    {'bg': RGBColor(0xFE, 0xF3, 0xEC), 'border': COLOR_ORANGE},
]
_fallback_index: dict = {}

# ============ SRT 解析 ============
def normalize_text(s):
    """去掉标点和空格，用于匹配"""
    return re.sub(r'[\\s，。！？：；""''""（）()—…·《》、～~\\[\\]]', '', s).lower()

def parse_srt(raw):
    """解析 SRT，返回 {index: {time, text}}"""
    blocks = re.split(r'(?=\n\d+\n\d{2}:\d{2})', raw.strip())
    items = {}
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3 and re.match(r'^\d+$', lines[0].strip()) and re.match(r'\d{2}:\d{2}', lines[1].strip()):
            idx = lines[0].strip()
            items[idx] = {'index': idx, 'time': lines[1].strip(), 'text': lines[2].strip()}
    return items

def parse_dialogue_script(txt_path):
    """解析对话脚本 txt，返回 [{speaker, text}]"""
    lines = []
    with open(txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.match(r'^([甜甜阿杰]+)[：:]\s*(.+)$', line)
            if m:
                lines.append({'speaker': m.group(1), 'text': m.group(2)})
    return lines


def parse_trilingual_script(txt_path):
    """解析三语脚本 txt，返回 [{speaker, cn, py, en}]"""
    entries = []
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 按空行分割段落
    paragraphs = re.split(r'\n\n+', content.strip())
    
    for para in paragraphs:
        lines = [l.strip() for l in para.strip().split('\n') if l.strip()]
        if len(lines) >= 3:
            # 第一行：中文（带说话人）
            cn_line = lines[0]
            m = re.match(r'^([^：:]+)[：:]\s*(.+)$', cn_line)
            if m:
                speaker = m.group(1)
                cn_text = m.group(2)
            else:
                speaker = '小悦'
                cn_text = cn_line
            
            # 第二行：拼音
            py_text = lines[1]
            # 第三行：英文（去掉说话人前缀，如果有）
            en_text = lines[2]
            en_m = re.match(r'^[^：:]+[：:]\s*(.+)$', en_text)
            if en_m:
                en_text = en_m.group(1)
            
            entries.append({
                'speaker': speaker,
                'cn': cn_text,
                'py': py_text,
                'en': en_text
            })
    
    return entries

# ============ DOCX 格式工具 ============
def add_dialogue_block(doc, speaker, cn, py, en, border_color, bg_color):
    """添加一段对话（带左边框竖线）"""
    border_hex = ''.join([f'{c:02X}' for c in border_color])
    bg_hex = ''.join([f'{c:02X}' for c in bg_color])
    
    # 说话人姓名（带竖线前缀）
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.left_indent = Cm(0.5)  # 文字离竖线的距离
    
    # 添加左边框
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="18" w:color="{border_hex}"/>'
        f'</w:pBdr>'
    )
    p._p.get_or_add_pPr().append(pBdr)
    
    # 背景色
    shd = parse_xml(
        f'<w:shd {nsdecls("w")} w:fill="{bg_hex}" w:val="clear"/>'
    )
    p._p.get_or_add_pPr().append(shd)
    
    run = p.add_run(speaker)
    run.font.size = Pt(10)
    run.font.color.rgb = border_color
    run.font.bold = True
    run.font.name = '微软雅黑'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    
    # 中文原文
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.left_indent = Cm(0.5)
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="18" w:color="{border_hex}"/>'
        f'</w:pBdr>'
    )
    p._p.get_or_add_pPr().append(pBdr)
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_hex}" w:val="clear"/>')
    p._p.get_or_add_pPr().append(shd)
    run = p.add_run(cn)
    run.font.size = Pt(13)
    run.font.color.rgb = COLOR_BLACK
    run.font.name = '微软雅黑'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    
    # 拼音
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.left_indent = Cm(0.5)
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="18" w:color="{border_hex}"/>'
        f'</w:pBdr>'
    )
    p._p.get_or_add_pPr().append(pBdr)
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_hex}" w:val="clear"/>')
    p._p.get_or_add_pPr().append(shd)
    run = p.add_run(py)
    run.font.size = Pt(10)
    run.font.color.rgb = COLOR_GRAY
    run.font.name = '微软雅黑'
    
    # 英文
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.left_indent = Cm(0.5)
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="18" w:color="{border_hex}"/>'
        f'</w:pBdr>'
    )
    p._p.get_or_add_pPr().append(pBdr)
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_hex}" w:val="clear"/>')
    p._p.get_or_add_pPr().append(shd)
    run = p.add_run(en)
    run.font.size = Pt(10)
    run.font.color.rgb = COLOR_BLUE
    run.font.name = '微软雅黑'


def add_paragraph_with_bg(doc, text, font_size, color, bg_color=None, bold=False, space_after=0, indent=0):
    """添加带背景色的段落"""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.space_before = Pt(0)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    
    run = p.add_run(text)
    run.font.size = Pt(font_size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.name = '微软雅黑'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    
    # 背景色
    if bg_color:
        shd = parse_xml(
            f'<w:shd {nsdecls("w")} w:fill="{bg_color}" w:val="clear"/>'
        )
        p._p.get_or_add_pPr().append(shd)
    
    return p

def add_horizontal_line(doc, color_hex, sz=4):
    """添加水平分隔线"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6)
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'<w:bottom w:val="single" w:sz="{sz}" w:color="{color_hex}"/>'
        f'</w:pBdr>'
    )
    p._p.get_or_add_pPr().append(pBdr)
    return p

def _get_speaker_colors(speaker: str) -> dict:
    if speaker in SPEAKER_COLORS:
        return SPEAKER_COLORS[speaker]
    if speaker not in _fallback_index:
        _fallback_index[speaker] = len(_fallback_index) % len(_FALLBACK_COLORS)
    return _FALLBACK_COLORS[_fallback_index[speaker]]


# ============ 文档生成 ============
def generate_docx_from_trilingual(script_path, output_path, title, title_pinyin, title_en, episode_name, vocab_list):
    """
    从三语脚本生成播客三语文档
    
    参数：
        script_path: 三语脚本 TXT 路径（每段三行：中文、拼音、英文）
        output_path: 输出 DOCX 路径
        title: 主标题（如"外卖"）
        title_pinyin: 标题拼音（如"wài mài"）
        title_en: 标题英文（如"Takeout"）
        episode_name: 节目名（如"Simply Natural Chinese"）
        vocab_list: 词汇列表，每项为 {cn, py, en, example_cn, example_py, example_en}
    """
    # 解析三语脚本
    dialogue_entries = parse_trilingual_script(script_path)
    print(f'✓ 解析了 {len(dialogue_entries)} 段对话')
    
    # 创建文档
    doc = Document()
    
    # 页面设置：A4，左右 2.0cm，上下 1.8cm
    for section in doc.sections:
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)
        section.top_margin = Cm(1.8)
        section.bottom_margin = Cm(1.8)
    
    # ========== 标题区 ==========
    # 主标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.font.size = Pt(36)
    run.font.color.rgb = COLOR_ORANGE
    run.font.bold = True
    run.font.name = '微软雅黑'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    
    # 拼音副标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title_pinyin)
    run.font.size = Pt(14)
    run.font.color.rgb = COLOR_GRAY
    run.font.name = '微软雅黑'
    
    # 英文标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title_en)
    run.font.size = Pt(14)
    run.font.color.rgb = COLOR_BLUE
    run.font.name = '微软雅黑'
    
    # 节目名
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(episode_name)
    run.font.size = Pt(11)
    run.font.color.rgb = COLOR_BLUE
    run.font.name = '微软雅黑'
    
    # 栏目行
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('汉语学习 · Chinese Learning')
    run.font.size = Pt(10)
    run.font.color.rgb = COLOR_GRAY
    run.font.name = '微软雅黑'
    
    # 标题区分隔线
    add_horizontal_line(doc, 'C05C1A', sz=8)
    
    # ========== 角色介绍行（动态从对话中读取出场人物）==========
    seen_speakers = []
    for entry in dialogue_entries:
        if entry['speaker'] not in seen_speakers:
            seen_speakers.append(entry['speaker'])

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    for i, spk in enumerate(seen_speakers):
        colors = _get_speaker_colors(spk)
        if i > 0:
            p.add_run('  ')
        run = p.add_run(f'■ {spk}')
        run.font.size = Pt(11)
        run.font.color.rgb = colors['border']
        run.font.bold = True
        run.font.name = '微软雅黑'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')

    # 角色区分隔线
    add_horizontal_line(doc, 'F5F5F5', sz=4)
    
    # ========== 对话区 ==========
    for entry in dialogue_entries:
        speaker = entry['speaker']
        colors = _get_speaker_colors(speaker)
        
        add_dialogue_block(
            doc, speaker, 
            entry['cn'], entry['py'], entry['en'],
            colors['border'], colors['bg']
        )
    
    # ========== 词汇总结区 ==========
    doc.add_paragraph()
    
    # 标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('重点词汇 · Key Vocabulary')
    run.font.size = Pt(14)
    run.font.color.rgb = COLOR_ORANGE
    run.font.bold = True
    run.font.name = '微软雅黑'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    
    # 副标题
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('本期核心词汇，助你掌握实用表达')
    run.font.size = Pt(10)
    run.font.color.rgb = COLOR_GRAY
    run.font.name = '微软雅黑'
    
    doc.add_paragraph()
    
    # 词汇列表
    for i, vocab in enumerate(vocab_list, 1):
        # 第1行：序号 + 中文 | 拼音 | 英文
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        
        run = p.add_run(f'{i}. {vocab["cn"]} | ')
        run.font.size = Pt(10)
        run.font.color.rgb = COLOR_BLACK
        run.font.bold = True
        run.font.name = '微软雅黑'
        
        run = p.add_run(f'{vocab["py"]} | ')
        run.font.size = Pt(10)
        run.font.color.rgb = COLOR_GRAY
        run.font.name = '微软雅黑'
        
        run = p.add_run(vocab['en'])
        run.font.size = Pt(10)
        run.font.color.rgb = COLOR_BLUE
        run.font.name = '微软雅黑'
        
        # 第2行：中文例句
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.left_indent = Cm(0.5)
        run = p.add_run(vocab['example_cn'])
        run.font.size = Pt(10)
        run.font.color.rgb = COLOR_BLACK
        run.font.name = '微软雅黑'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
        
        # 第3行：拼音例句
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.left_indent = Cm(0.5)
        run = p.add_run(vocab['example_py'])
        run.font.size = Pt(9)
        run.font.color.rgb = COLOR_GRAY
        run.font.name = '微软雅黑'
        
        # 第4行：英文例句
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.left_indent = Cm(0.5)
        run = p.add_run(vocab['example_en'])
        run.font.size = Pt(9)
        run.font.color.rgb = COLOR_BLUE
        run.font.name = '微软雅黑'
    
    # 保存
    doc.save(output_path)
    print(f'✓ 文档已生成: {output_path}')


# ============ 命令行入口 ============
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='播客三语文档生成器')
    parser.add_argument('--script', required=True, help='三语脚本 TXT 路径')
    parser.add_argument('--output', required=True, help='输出 DOCX 路径')
    parser.add_argument('--title', required=True, help='主标题（中文）')
    parser.add_argument('--title-py', required=True, help='标题拼音')
    parser.add_argument('--title-en', required=True, help='标题英文')
    parser.add_argument('--episode', default='Simply Natural Chinese', help='节目名')
    
    # 词汇输入方式（二选一）
    vocab_group = parser.add_mutually_exclusive_group(required=True)
    vocab_group.add_argument('--vocab-file', help='词汇 JSON 文件路径')
    vocab_group.add_argument('--vocab-json', help='词汇 JSON 字符串')
    
    args = parser.parse_args()
    
    # 加载词汇列表
    if args.vocab_file:
        with open(args.vocab_file, 'r', encoding='utf-8') as f:
            vocab_list = json.load(f)
        print(f'✓ 从文件加载词汇: {args.vocab_file}')
    else:
        vocab_list = json.loads(args.vocab_json)
        print(f'✓ 加载了 {len(vocab_list)} 个词汇')
    
    generate_docx_from_trilingual(
        args.script, args.output,
        args.title, args.title_py, args.title_en, args.episode, vocab_list
    )
