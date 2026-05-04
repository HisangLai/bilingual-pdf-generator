#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外刊阅读语言学分析工具 - 双栏对照PDF生成器
支持：粘贴AI分析结果 → 生成双栏对照PDF
左侧：原文 + 中文翻译
右侧：词汇解析（音标、词性、含义、例句等）
特点：左右栏完全独立分页
"""

import os, re, sys, threading, subprocess, datetime, time, tempfile
from typing import List, Tuple

# ---------- GUI ----------
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ---------- PDF 生成 ----------
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate,
                                 Paragraph, Spacer)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor

# ---------- PDF 合并 ----------
from PyPDF2 import PdfReader, PdfWriter

# ==================== 配置 ====================
DEFAULT_OUTPUT = "analysis_output.pdf"

# ---------- 默认字体设置 ----------
_CANDIDATE_FONTS = [
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "SimSun.ttf",
    "MSYH.ttf",
]

DEFAULT_ENGLISH_FONT = "Times-Roman"

FONT_PATH = None
for _f in _CANDIDATE_FONTS:
    if os.path.exists(_f):
        FONT_PATH = _f
        break
if FONT_PATH:
    pdfmetrics.registerFont(TTFont("ChineseFont", FONT_PATH))
    FONT_NAME = "ChineseFont"
else:
    FONT_NAME = "Helvetica"
    print("⚠ 未找到中文字体，PDF中中文可能无法正常显示")


# ==================== 解析函数 ====================
def parse_analysis(text: str) -> Tuple[str, str, List[Tuple[str, str, str, str]]]:
    """
    解析粘贴的AI分析结果
    返回：(原文, 中文翻译, 词汇列表)
    词汇列表格式：[(词汇, 音标, 词性, 含义+例句), ...]
    支持三种词汇格式：
    1. 英语格式：word /phonetic/ pos meaning
    2. 德语格式1：word (词性). meaning
    3. 德语格式2：word (完整形式, 复数). 词性. meaning
       例如：der Rechtsgeschäftslehre (die Rechtsgeschäftslehre, Sg.) 名词（阴性）. 法律行为学说
    """
    orig_match = re.search(r'【原文】\s*([\s\S]*?)(?=\s*【翻译】)', text)
    original = orig_match.group(1).strip() if orig_match else ""
    
    trans_match = re.search(r'【翻译】\s*([\s\S]*?)(?=\s*【词汇解析】|\s*【解析】|\s*$)', text)
    translation = trans_match.group(1).strip() if trans_match else ""
    
    vocab_section = ""
    vocab_match = re.search(r'【词汇解析】\s*([\s\S]*)$', text)
    if not vocab_match:
        vocab_match = re.search(r'【解析】\s*([\s\S]*)$', text)
    if vocab_match:
        vocab_section = vocab_match.group(1).strip()
    
    vocab_list = []
    
    # 支持德语特殊字符：ä, ö, ü, ß, Ä, Ö, Ü
    # 格式1：英语格式 word /phonetic/ pos meaning
    vocab_pattern_en = r'([a-zA-ZäöüÄÖÜß]+(?:[\'-][a-zA-ZäöüÄÖÜß]+)?)\s*/([^/]+)/\s*([a-zA-Z.]+)\s*([\s\S]*?)(?=\s*[a-zA-ZäöüÄÖÜß]+(?:[\'-][a-zA-ZäöüÄÖÜß]+)?\s*/|$)'
    
    # 格式2：德语格式1 word (词性). meaning
    vocab_pattern_de1 = r'([a-zA-ZäöüÄÖÜß]+(?:[\'-][a-zA-ZäöüÄÖÜß]+)?)\s*\(([^)]+)\)\.\s*([\s\S]*?)(?=\s*[a-zA-ZäöüÄÖÜß]+(?:[\'-][a-zA-ZäöüÄÖÜß]+)?\s*\(|$)'
    
    # 格式3：德语格式2 word (完整形式, 复数). 词性. meaning
    vocab_pattern_de2 = r'([a-zA-ZäöüÄÖÜß]+(?:[\'-][a-zA-ZäöüÄÖÜß]+)?)\s*\(([^)]+)\)\s*([^.]+)\.\s*([\s\S]*?)(?=\s*[a-zA-ZäöüÄÖÜß]+(?:[\'-][a-zA-ZäöüÄÖÜß]+)?\s*\(|$)'
    
    # 先尝试英语格式
    matches = re.finditer(vocab_pattern_en, vocab_section)
    for match in matches:
        word = match.group(1).strip()
        phonetic = match.group(2).strip()
        pos = match.group(3).strip()
        meaning = match.group(4).strip()
        vocab_list.append((word, phonetic, pos, meaning))
    
    # 如果没有找到英语格式的词汇，尝试德语格式1
    if not vocab_list:
        matches = re.finditer(vocab_pattern_de1, vocab_section)
        for match in matches:
            word = match.group(1).strip()
            phonetic = ""  # 德语格式没有音标
            pos = match.group(2).strip()
            meaning = match.group(3).strip()
            vocab_list.append((word, phonetic, pos, meaning))
    
    # 如果还是没有找到，尝试德语格式2
    if not vocab_list:
        matches = re.finditer(vocab_pattern_de2, vocab_section)
        for match in matches:
            word = match.group(1).strip()
            phonetic = ""  # 德语格式没有音标
            pos = match.group(3).strip()  # 词性在第三个组
            meaning = match.group(4).strip()
            vocab_list.append((word, phonetic, pos, meaning))
    
    return (original, translation, vocab_list)


# ==================== PDF 生成辅助函数 ====================
def _create_styles(font_names, line_spacing_factor, base_font_size):
    """创建段落样式"""
    left_en_font_name, left_zh_font_name, right_en_font_name, right_zh_font_name = font_names
    
    styles = {
        'article_title': ParagraphStyle(
            'ArticleTitle', fontName=left_zh_font_name, fontSize=base_font_size + 4,
            leading=(base_font_size + 4) * line_spacing_factor, alignment=TA_CENTER, 
            spaceAfter=8, textColor=HexColor('#1a252f'), fontWeight='bold'
        ),
        'date': ParagraphStyle(
            'Date', fontName=left_en_font_name, fontSize=base_font_size - 1,
            leading=(base_font_size - 1) * line_spacing_factor, alignment=TA_CENTER, 
            spaceAfter=12, textColor=HexColor('#7f8c8d')
        ),
        'original': ParagraphStyle(
            'Original', fontName=left_en_font_name, fontSize=base_font_size,
            leading=base_font_size * line_spacing_factor, alignment=TA_JUSTIFY, 
            spaceAfter=6, textColor=HexColor('#2c3e50')
        ),
        'translation': ParagraphStyle(
            'Translation', fontName=left_zh_font_name, fontSize=base_font_size,
            leading=base_font_size * line_spacing_factor * 0.9, alignment=TA_JUSTIFY, 
            spaceAfter=8, textColor=HexColor('#2c3e50')
        ),
        'vocab_title': ParagraphStyle(
            'VocabTitle', fontName=right_zh_font_name, fontSize=base_font_size + 1,
            leading=(base_font_size + 1) * line_spacing_factor, alignment=TA_LEFT, 
            spaceAfter=8, textColor=HexColor('#3498db'), fontWeight='bold'
        ),
        'vocab': ParagraphStyle(
            'Vocab', fontName=right_zh_font_name, fontSize=base_font_size - 1,
            leading=(base_font_size - 1) * line_spacing_factor, alignment=TA_LEFT, 
            spaceAfter=4, textColor=HexColor('#2c3e50')
        ),
        'line': ParagraphStyle(
            'Line', fontName=left_zh_font_name, fontSize=base_font_size - 2,
            alignment=TA_CENTER, spaceAfter=0
        ),
        'trans_header': ParagraphStyle(
            'TransHeader', fontName=left_zh_font_name, fontSize=base_font_size, 
            spaceAfter=6, textColor=HexColor('#27ae60')
        ),
        'vocab_header': ParagraphStyle(
            'VocabHeader', fontName=right_zh_font_name, fontSize=base_font_size, 
            spaceAfter=10, textColor=HexColor('#3498db')
        ),
        'vocab_subheader': ParagraphStyle(
            'VocabSubheader', fontName=right_zh_font_name, fontSize=base_font_size - 1, 
            spaceAfter=6, textColor=HexColor('#3498db'), fontWeight='bold'
        )
    }
    return styles


def _register_custom_fonts(left_english_font, left_chinese_font, right_english_font, right_chinese_font):
    """注册自定义字体"""
    left_en_font_name = DEFAULT_ENGLISH_FONT
    left_zh_font_name = FONT_NAME
    right_en_font_name = DEFAULT_ENGLISH_FONT
    right_zh_font_name = FONT_NAME
    
    if left_english_font and os.path.exists(left_english_font):
        font_id = f"LeftEn_{os.path.basename(left_english_font)}"
        pdfmetrics.registerFont(TTFont(font_id, left_english_font))
        left_en_font_name = font_id
    
    if left_chinese_font and os.path.exists(left_chinese_font):
        font_id = f"LeftZh_{os.path.basename(left_chinese_font)}"
        pdfmetrics.registerFont(TTFont(font_id, left_chinese_font))
        left_zh_font_name = font_id
    
    if right_english_font and os.path.exists(right_english_font):
        font_id = f"RightEn_{os.path.basename(right_english_font)}"
        pdfmetrics.registerFont(TTFont(font_id, right_english_font))
        right_en_font_name = font_id
    
    if right_chinese_font and os.path.exists(right_chinese_font):
        font_id = f"RightZh_{os.path.basename(right_chinese_font)}"
        pdfmetrics.registerFont(TTFont(font_id, right_chinese_font))
        right_zh_font_name = font_id
    
    return (left_en_font_name, left_zh_font_name, right_en_font_name, right_zh_font_name)


def _build_single_column_pdf(content_story, out_path, font_names, line_spacing_factor, base_font_size, 
                             is_left_column, page_w, page_h, margin, inner_margin, progress_callback=None):
    """生成单栏PDF"""
    left_col_width = (page_w - 2 * margin - inner_margin) * 0.55
    right_col_width = (page_w - 2 * margin - inner_margin) * 0.45
    
    if is_left_column:
        col_width = left_col_width
        col_x = margin
    else:
        col_width = right_col_width
        col_x = margin + left_col_width + inner_margin
    
    _, left_zh_font_name, _, _ = font_names
    
    def on_page(canvas, doc):
        page_num = doc.page
        canvas.saveState()
        canvas.setFont(left_zh_font_name, base_font_size - 1)
        canvas.setFillColor(HexColor('#7f8c8d'))
        canvas.drawCentredString(page_w / 2, 1 * cm, f"{page_num}")
        canvas.restoreState()
    
    doc = BaseDocTemplate(out_path, pagesize=A4,
                          leftMargin=0, rightMargin=0,
                          topMargin=margin, bottomMargin=1.5 * cm)
    
    frame = Frame(col_x, margin, col_width, page_h - 2.5 * cm, 
                 id='col', leftPadding=0, rightPadding=0)
    
    doc.addPageTemplates([PageTemplate(id='SingleColumn', frames=[frame], onPage=on_page)])
    
    doc.build(content_story)
    time.sleep(0.3)


def _merge_pdfs(left_pdf_path, right_pdf_path, out_path):
    """合并左右栏PDF"""
    left_reader = PdfReader(left_pdf_path)
    right_reader = PdfReader(right_pdf_path)
    
    writer = PdfWriter()
    
    max_pages = max(len(left_reader.pages), len(right_reader.pages))
    
    for i in range(max_pages):
        left_page = left_reader.pages[i] if i < len(left_reader.pages) else None
        right_page = right_reader.pages[i] if i < len(right_reader.pages) else None
        
        if left_page and right_page:
            # 合并两个页面：以左栏为基础，合并右栏
            left_page.merge_page(right_page)
            writer.add_page(left_page)
        elif left_page:
            writer.add_page(left_page)
        elif right_page:
            writer.add_page(right_page)
    
    with open(out_path, 'wb') as f:
        writer.write(f)


# ==================== PDF 生成主函数 ====================
def build_pdf(original: str, translation: str, vocab_list: List[Tuple[str, str, str, str]], 
              out_path: str, title: str = "外刊精读",
              left_english_font: str = None, left_chinese_font: str = None,
              right_english_font: str = None, right_chinese_font: str = None,
              line_spacing: float = None, font_size: int = None,
              progress_callback=None):
    if progress_callback:
        progress_callback("正在注册字体...")
    
    page_w, page_h = A4
    margin = 2.0 * cm
    inner_margin = 0.6 * cm
    
    line_spacing_factor = line_spacing if line_spacing else 1.4
    base_font_size = font_size if font_size else 10
    
    # 注册自定义字体
    font_names = _register_custom_fonts(left_english_font, left_chinese_font, 
                                        right_english_font, right_chinese_font)
    left_en_font_name, left_zh_font_name, right_en_font_name, right_zh_font_name = font_names
    
    # 创建样式
    styles = _create_styles(font_names, line_spacing_factor, base_font_size)
    
    # ========== 使用表格布局实现段落级左右对应 ==========
    if progress_callback:
        progress_callback("正在生成内容...")
    
    from reportlab.platypus import Table, TableStyle
    
    def get_word_stem(word):
        """提取单词的词干，支持英语和德语词形变化"""
        stems = {word.lower()}
        
        # 英语常见词尾
        if word.endswith('s'):
            stems.add(word[:-1].lower())
            if word.endswith('ities'):
                stems.add((word[:-5] + 'ity').lower())
        elif word.endswith('es'):
            stems.add(word[:-2].lower())
        elif word.endswith('ies'):
            stems.add((word[:-3] + 'y').lower())
        
        if word.endswith('ed'):
            stems.add(word[:-2].lower())
            if word.endswith('ied'):
                stems.add((word[:-3] + 'y').lower())
            elif len(word) > 2 and word[-3] == word[-2]:
                stems.add(word[:-1].lower())
            elif len(word) > 2 and word[-2] == 'e':
                stems.add(word[:-1].lower())
        
        if word.endswith('ing'):
            stems.add(word[:-3].lower())
            if word.endswith('ying'):
                stems.add((word[:-4] + 'y').lower())
            elif len(word) > 4 and word[-4] == word[-5]:
                stems.add(word[:-4].lower())
        
        if word.endswith('ly'):
            stems.add(word[:-2].lower())
        
        if word.endswith('est'):
            stems.add(word[:-3].lower())
            if len(word) > 4 and word[-4] == word[-5]:
                stems.add(word[:-4].lower())
        elif word.endswith('er'):
            stems.add(word[:-2].lower())
            if len(word) > 3 and word[-3] == word[-4]:
                stems.add(word[:-3].lower())
        
        # 德语常见词尾 - 动词
        if word.endswith('en'):
            stems.add(word[:-2].lower())
            if word.endswith('nen'):
                stems.add(word[:-3].lower())
                stems.add(word[:-2].lower() + 'n')  # 如: machen -> mach -> macht
        elif word.endswith('t'):
            stems.add(word[:-1].lower())
        
        if word.endswith('te'):
            stem = word[:-2].lower()
            stems.add(stem)
            stems.add(stem + 'en')
        elif word.endswith('ten'):
            stem = word[:-3].lower()
            stems.add(stem)
            stems.add(stem + 'en')
        
        # 德语名词复数词尾
        if word.endswith('e') and len(word) > 1:
            stems.add(word[:-1].lower())
        if word.endswith('er') and len(word) > 2:
            stems.add(word[:-2].lower())
        
        # 德语特有的复数形式
        if word.endswith('nen'):
            stems.add(word[:-3].lower())
        if word.endswith('s') and len(word) > 1:
            stems.add(word[:-1].lower())
        
        # 德语形容词词尾
        if word.endswith('en'):
            stems.add(word[:-2].lower())
        if word.endswith('er'):
            stems.add(word[:-2].lower())
        if word.endswith('em'):
            stems.add(word[:-2].lower())
        if word.endswith('es'):
            stems.add(word[:-2].lower())
        if word.endswith('er'):
            stems.add(word[:-2].lower())
        
        return stems
    
    # 创建词干到释义的映射
    vocab_stem_map = {}
    for word, phonetic, pos, meaning in vocab_list:
        stems = get_word_stem(word)
        for stem in stems:
            if stem not in vocab_stem_map:
                vocab_stem_map[stem] = (word, phonetic, pos, meaning)
    
    def get_vocab_in_text(text):
        """获取文本中出现的词汇及其释义"""
        found_vocab = set()
        text_words = re.findall(r'\b([a-zA-ZäöüÄÖÜß]+)\b', text)
        for text_word in text_words:
            text_stems = get_word_stem(text_word)
            for stem in text_stems:
                if stem in vocab_stem_map:
                    found_vocab.add(vocab_stem_map[stem])
                    break
        return list(found_vocab)
    
    def mark_vocab_in_text(text):
        """仅对文本中的词汇添加下划线标记"""
        words_to_mark = set()
        text_words = re.findall(r'\b([a-zA-ZäöüÄÖÜß]+)\b', text)
        for text_word in text_words:
            text_stems = get_word_stem(text_word)
            for stem in text_stems:
                if stem in vocab_stem_map:
                    words_to_mark.add(text_word)
                    break
        
        marked_text = text
        for word in words_to_mark:
            pattern = r'\b(' + re.escape(word) + r')\b'
            replacement = r'<u>\1</u>'
            marked_text = re.sub(pattern, replacement, marked_text)
        return marked_text
    
    # 计算列宽
    left_col_width = (page_w - 2 * margin - inner_margin) * 0.55
    right_col_width = (page_w - 2 * margin - inner_margin) * 0.45
    
    # 准备表格数据
    table_data = []
    
    # 添加标题行（跨两列）
    title_cell = Paragraph(f"<b>{title}</b>", styles['article_title'])
    table_data.append([title_cell])
    
    # 添加日期行
    date_cell = Paragraph(f"June 2025 【Britain】", styles['date'])
    table_data.append([date_cell])
    
    # 添加分隔线
    line_cell = Paragraph("<para alignment='center'><font color='#dddddd'>───────────────────────────────────────────────────────</font></para>", styles['line'])
    table_data.append([line_cell])
    
    # 将原文和译文按段落分割
    original_paragraphs = re.split(r'\n\n+', original.strip()) if original else []
    translation_paragraphs = re.split(r'\n\n+', translation.strip()) if translation else []
    
    # 计算最大段落数
    max_paragraphs = max(len(original_paragraphs), len(translation_paragraphs))
    
    # 交替添加：一段原文 + 一段译文
    for i in range(max_paragraphs):
        # 添加原文段落（如果有）
        if i < len(original_paragraphs) and original_paragraphs[i].strip():
            para = original_paragraphs[i]
            # 左栏：带下划线标记的原文段落
            marked_para = mark_vocab_in_text(para)
            left_cell = Paragraph(marked_para, styles['original'])
            
            # 右栏：对应段落中的词汇解析
            vocab_in_para = get_vocab_in_text(para)
            vocab_html = ""
            if i == 0:
                vocab_html += "<b>中文导读</b><br/>"
            vocab_html += f"<font color='#3498db'><b>段落 {i+1}</b></font><br/>"
            for word, phonetic, pos, meaning in vocab_in_para:
                vocab_html += f"<font name='{right_en_font_name}' color='#1a5276'><b>{word}</b></font> <font name='{right_en_font_name}' color='#7f8c8d'>/{phonetic}/</font> <font name='{right_zh_font_name}' color='#9b59b6'>{pos}</font>：<font name='{right_zh_font_name}'>{meaning}</font><br/>"
            
            right_cell = Paragraph(vocab_html, styles['vocab'])
            table_data.append([left_cell, right_cell])
        
        # 添加译文段落（如果有）
        if i < len(translation_paragraphs) and translation_paragraphs[i].strip():
            para = translation_paragraphs[i]
            trans_cell = Paragraph(para.strip(), styles['translation'])
            table_data.append([trans_cell, Paragraph("", styles['vocab'])])
    
    # 创建表格
    table = Table(table_data, colWidths=[left_col_width, right_col_width])
    
    # 设置表格样式
    table_style = TableStyle([
        ('SPAN', (0, 0), (-1, 0)),  # 标题跨两列
        ('SPAN', (0, 1), (-1, 1)),  # 日期跨两列
        ('SPAN', (0, 2), (-1, 2)),  # 分隔线跨两列
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ])
    
    table.setStyle(table_style)
    
    # 生成PDF
    story = [table]
    
    if progress_callback:
        progress_callback("正在生成PDF...")
    
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin
    )
    doc.build(story)


# ==================== GUI ====================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("外刊精读双栏PDF生成器")
        self.root.geometry("900x600")
        self.root.resizable(True, True)

        today = datetime.date.today().strftime("%Y%m%d")
        self.pdf_title = tk.StringVar(value=f"外刊精读{today}")
        self.output_path = tk.StringVar(value=DEFAULT_OUTPUT)
        
        self.left_english_font = tk.StringVar(value="")
        self.left_chinese_font = tk.StringVar(value="")
        self.right_english_font = tk.StringVar(value="")
        self.right_chinese_font = tk.StringVar(value="")
        
        self.line_spacing = tk.DoubleVar(value=1.4)
        self.font_size = tk.IntVar(value=10)
        self._running = False

        self._build_ui()

    def _build_ui(self):
        main_canvas = tk.Canvas(self.root)
        main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=main_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        main = ttk.Frame(main_canvas, padding=10)
        main_canvas.create_window((0, 0), window=main, anchor=tk.NW)
        
        def on_frame_configure(event):
            main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        main.bind("<Configure>", on_frame_configure)
        
        def on_mousewheel(event):
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        main_canvas.bind_all("<MouseWheel>", on_mousewheel)

        pdf_frame = ttk.LabelFrame(main, text="PDF 设置", padding=8)
        pdf_frame.pack(fill=tk.X, pady=(0, 8))

        title_row = ttk.Frame(pdf_frame)
        title_row.pack(fill=tk.X, pady=2)
        ttk.Label(title_row, text="PDF 标题:").pack(side=tk.LEFT)
        ttk.Entry(title_row, textvariable=self.pdf_title, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        out_frame = ttk.LabelFrame(main, text="输出设置", padding=8)
        out_frame.pack(fill=tk.X, pady=(0, 8))
        out_row = ttk.Frame(out_frame)
        out_row.pack(fill=tk.X)
        ttk.Label(out_row, text="输出 PDF 路径:").pack(side=tk.LEFT)
        ttk.Entry(out_row, textvariable=self.output_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(out_row, text="浏览", width=6, command=self._browse_output).pack(side=tk.LEFT)

        left_font_frame = ttk.LabelFrame(main, text="左栏字体设置", padding=8)
        left_font_frame.pack(fill=tk.X, pady=(0, 8))
        
        left_en_row = ttk.Frame(left_font_frame)
        left_en_row.pack(fill=tk.X, pady=2)
        ttk.Label(left_en_row, text="左栏外文字体(原文):").pack(side=tk.LEFT)
        ttk.Entry(left_en_row, textvariable=self.left_english_font).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(left_en_row, text="浏览", width=6, command=self._browse_left_english_font).pack(side=tk.LEFT)
        
        left_zh_row = ttk.Frame(left_font_frame)
        left_zh_row.pack(fill=tk.X, pady=2)
        ttk.Label(left_zh_row, text="左栏中文字体(译文):").pack(side=tk.LEFT)
        ttk.Entry(left_zh_row, textvariable=self.left_chinese_font).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(left_zh_row, text="浏览", width=6, command=self._browse_left_chinese_font).pack(side=tk.LEFT)

        right_font_frame = ttk.LabelFrame(main, text="右栏字体设置", padding=8)
        right_font_frame.pack(fill=tk.X, pady=(0, 8))
        
        right_en_row = ttk.Frame(right_font_frame)
        right_en_row.pack(fill=tk.X, pady=2)
        ttk.Label(right_en_row, text="右栏外文字体(词汇/音标):").pack(side=tk.LEFT)
        ttk.Entry(right_en_row, textvariable=self.right_english_font).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(right_en_row, text="浏览", width=6, command=self._browse_right_english_font).pack(side=tk.LEFT)
        
        right_zh_row = ttk.Frame(right_font_frame)
        right_zh_row.pack(fill=tk.X, pady=2)
        ttk.Label(right_zh_row, text="右栏中文字体(词性/含义):").pack(side=tk.LEFT)
        ttk.Entry(right_zh_row, textvariable=self.right_chinese_font).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(right_zh_row, text="浏览", width=6, command=self._browse_right_chinese_font).pack(side=tk.LEFT)
        
        font_tip = ttk.Label(right_font_frame, text="推荐音标字体：Charis SIL、DejaVu Sans、Gentium Plus、Noto Sans IPA", 
                            foreground="#666666", font=("Arial", 9))
        font_tip.pack(anchor=tk.W, pady=2)

        layout_frame = ttk.LabelFrame(main, text="排版设置", padding=8)
        layout_frame.pack(fill=tk.X, pady=(0, 8))
        
        spacing_row = ttk.Frame(layout_frame)
        spacing_row.pack(fill=tk.X, pady=2)
        ttk.Label(spacing_row, text="行距系数:").pack(side=tk.LEFT)
        ttk.Entry(spacing_row, textvariable=self.line_spacing, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Label(spacing_row, text="(默认1.4，建议范围1.2-2.0)").pack(side=tk.LEFT)
        
        font_size_row = ttk.Frame(layout_frame)
        font_size_row.pack(fill=tk.X, pady=2)
        ttk.Label(font_size_row, text="基础字体大小:").pack(side=tk.LEFT)
        ttk.Entry(font_size_row, textvariable=self.font_size, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Label(font_size_row, text="(默认10号字，建议范围9-12)").pack(side=tk.LEFT)

        paste_frame = ttk.LabelFrame(main, text="粘贴AI分析结果", padding=8)
        paste_frame.pack(fill=tk.X, pady=(0, 8))

        info = ("请将AI分析结果粘贴到下方文本框，格式如下：\n\n"
                "【原文】\n英文原文内容...\n\n"
                "【翻译】\n中文翻译内容...\n\n"
                "【词汇解析】\n"
                "grid /ɡrɪd/ n. 网格；方格；赛车起跑线...\n"
                "circuit /ˈsɜːrkɪt/ n. 电路；环道；赛道...")
        ttk.Label(paste_frame, text=info, justify=tk.LEFT,
                  background="#f8f9fa", padding=6).pack(fill=tk.X, pady=8)

        self.paste_text = scrolledtext.ScrolledText(paste_frame, height=10,
                                                    font=("Consolas", 10), wrap=tk.WORD)
        self.paste_text.pack(fill=tk.X, padx=4, pady=4)

        btn_frame = ttk.Frame(paste_frame)
        btn_frame.pack(fill=tk.X, pady=8)

        self.paste_btn = ttk.Button(btn_frame, text="生成双栏PDF",
                                    command=self._start_paste, width=20)
        self.paste_btn.pack(side=tk.LEFT, padx=4)

        self.progress_paste = ttk.Progressbar(btn_frame, mode='indeterminate', length=200)
        self.progress_paste.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        log_frame = ttk.LabelFrame(main, text="运行日志", padding=4)
        log_frame.pack(fill=tk.X, pady=(8, 0))
        self.log = scrolledtext.ScrolledText(log_frame, height=4,
                                             font=("Consolas", 10), wrap=tk.WORD)
        self.log.pack(fill=tk.X)
        
        main.update_idletasks()
        main_canvas.config(scrollregion=main_canvas.bbox("all"))

    def _log(self, msg: str):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.root.update_idletasks()

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="保存 PDF", defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if path:
            self.output_path.set(path)

    def _browse_left_english_font(self):
        path = filedialog.askopenfilename(
            title="选择左栏外文字体",
            filetypes=[("字体文件", "*.ttf;*.ttc;*.otf")])
        if path:
            self.left_english_font.set(path)

    def _browse_left_chinese_font(self):
        path = filedialog.askopenfilename(
            title="选择左栏中文字体",
            filetypes=[("字体文件", "*.ttf;*.ttc;*.otf")])
        if path:
            self.left_chinese_font.set(path)

    def _browse_right_english_font(self):
        path = filedialog.askopenfilename(
            title="选择右栏外文字体",
            filetypes=[("字体文件", "*.ttf;*.ttc;*.otf")])
        if path:
            self.right_english_font.set(path)

    def _browse_right_chinese_font(self):
        path = filedialog.askopenfilename(
            title="选择右栏中文字体",
            filetypes=[("字体文件", "*.ttf;*.ttc;*.otf")])
        if path:
            self.right_chinese_font.set(path)

    def _disable_buttons(self):
        self.paste_btn.config(state=tk.DISABLED)

    def _enable_buttons(self):
        self.paste_btn.config(state=tk.NORMAL)

    def _open_pdf(self, path):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path])
            elif sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            self._log(f"无法自动打开 PDF: {e}")

    def _start_paste(self):
        if self._running:
            messagebox.showwarning("提示", "任务正在运行中")
            return
        self._disable_buttons()
        self._running = True
        self.progress_paste.start()
        threading.Thread(target=self._run_paste, daemon=True).start()

    def _run_paste(self):
        try:
            content = self.paste_text.get("1.0", tk.END).strip()
            if not content:
                raise ValueError("请先粘贴 AI 分析结果")
            self._log("正在解析粘贴内容...")
            
            original, translation, vocab_list = parse_analysis(content)
            
            if not original:
                raise ValueError("未找到【原文】部分")
            if not translation:
                raise ValueError("未找到【翻译】部分")
            
            self._log(f"原文长度: {len(original)} 字符")
            self._log(f"翻译长度: {len(translation)} 字符")
            self._log(f"解析词汇: {len(vocab_list)} 个")

            title = self.pdf_title.get() or f"外刊精读{datetime.date.today().strftime('%Y%m%d')}"
            out = self.output_path.get() or DEFAULT_OUTPUT
            
            left_en = self.left_english_font.get().strip() or None
            left_zh = self.left_chinese_font.get().strip() or None
            right_en = self.right_english_font.get().strip() or None
            right_zh = self.right_chinese_font.get().strip() or None
            
            spacing = self.line_spacing.get()
            fsize = self.font_size.get()
            
            out_dir = os.path.dirname(out)
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir)
            
            build_pdf(original, translation, vocab_list, out, title=title,
                      left_english_font=left_en,
                      left_chinese_font=left_zh,
                      right_english_font=right_en,
                      right_chinese_font=right_zh,
                      line_spacing=spacing,
                      font_size=fsize,
                      progress_callback=lambda s: self._log(f"   {s}"))
            self._log(f"PDF 已生成：{out}")
            
            if os.path.exists(out):
                self._log(f"文件大小: {os.path.getsize(out)} 字节")
            else:
                raise ValueError("PDF文件生成失败")

            if messagebox.askyesno("完成", f"PDF 已生成：\n{out}\n\n是否打开？"):
                self._open_pdf(out)

        except Exception as e:
            self._log(f"错误：{e}")
            messagebox.showerror("错误", str(e))
        finally:
            self._running = False
            self._enable_buttons()
            self.progress_paste.stop()


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
