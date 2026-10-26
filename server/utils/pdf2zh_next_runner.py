"""Run PDF2zh Next with local formula and figure fixes."""

import os
import re

FIGURE_LAYOUTS = {"figure", "image", "chart", "figure_text", "figure_text_hybrid"}


def is_element_contained_in_formula(element_box, formula_box, containment_threshold=0.95, tolerance=2.0):
    if element_box is None or formula_box is None:
        return False
    if element_box.x == element_box.x2 and element_box.y == element_box.y2:
        return False
    coverage = 1.0
    for start, end in (("x", "x2"), ("y", "y2")):
        low, high = getattr(element_box, start), getattr(element_box, end)
        bound_low, bound_high = getattr(formula_box, start), getattr(formula_box, end)
        if high < low or bound_high < bound_low:
            return False
        bound_low -= tolerance
        bound_high += tolerance
        if high == low:
            if not bound_low <= low <= bound_high:
                return False
        else:
            coverage *= max(0, min(high, bound_high) - max(low, bound_low)) / (high - low)
    return coverage >= containment_threshold


def protect_math_glyphs(page):
    from babeldoc.format.pdf.document_il.utils.formular_helper import collect_page_formula_font_ids

    math_fonts, xobj_math_fonts = collect_page_formula_font_ids(page, None)
    fonts = {None: {font.font_id: font.name for font in page.pdf_font}}
    for xobj in page.pdf_xobject:
        fonts[xobj.xobj_id] = {**fonts[None], **{font.font_id: font.name for font in xobj.pdf_font}}
    lines = [
        comp.pdf_line for para in page.pdf_paragraph for comp in para.pdf_paragraph_composition
        if comp.pdf_line
    ]
    glyphs = [(char, line) for line in lines for char in line.pdf_character]
    protected = set()
    for line in lines:
        chars = line.pdf_character
        for i, char in enumerate(chars):
            text = char.char_unicode or ""
            font = fonts.get(char.xobj_id, fonts[None]).get(char.pdf_style.font_id, "")
            if not (len(text) == 1 and text.isascii() and text.isalpha() and re.fullmatch(r"CMBX\d+", font.split("+")[-1])):
                continue
            # Bold Computer Modern also prints headings: protect single variables, not words.
            if any(
                other.pdf_style.font_id == char.pdf_style.font_id
                and (other.char_unicode or "").isalpha()
                and abs(other.box.y - char.box.y) < char.pdf_style.font_size * 0.2
                for other in chars[max(0, i - 1):i] + chars[i + 1:i + 2]
            ):
                continue
            protected.add(id(char))

    bases = [
        (char, line) for char, line in glyphs
        if (char.char_unicode or "").isalpha() and (
            id(char) in protected or char.formula_layout_id
            or char.pdf_style.font_id in xobj_math_fonts.get(char.xobj_id, math_fonts)
        )
    ]
    for accent, old_line in glyphs:
        if accent.char_unicode not in {"ˆ", "\u0302"}:
            continue
        a = accent.visual_bbox.box
        center = (a.x + a.x2) / 2
        candidates = []
        for base, line in bases:
            if accent.xobj_id != base.xobj_id:
                continue
            b = base.visual_bbox.box
            size = base.pdf_style.font_size
            gap = a.y - b.y2
            if b.x - size * 0.1 <= center <= b.x2 + size * 0.1 and -size * 0.1 <= gap <= size * 0.5:
                candidates.append((abs(gap) + abs(center - (b.x + b.x2) / 2), base, line))
        if not candidates:
            continue
        _, base, new_line = min(candidates, key=lambda candidate: candidate[0])
        # The line finder can put a hat on the preceding line; retain its original geometry.
        old_line.pdf_character = [char for char in old_line.pdf_character if char is not accent]
        index = next(i for i, char in enumerate(new_line.pdf_character) if char is base)
        new_line.pdf_character.insert(index, accent)
        protected.add(id(accent))
    for para in page.pdf_paragraph:
        para.pdf_paragraph_composition = [
            comp for comp in para.pdf_paragraph_composition
            if not comp.pdf_line or comp.pdf_line.pdf_character
        ]
    return protected


def install_formula_fix():
    from babeldoc.format.pdf.document_il.midend import styles_and_formulas
    from babeldoc.format.pdf.document_il.utils import spatial_analyzer

    # shortcut: BabelDOC 0.6 uses IoU for containment and loses zero-height fraction rules; remove when upstream fixes it.
    spatial_analyzer.is_element_contained_in_formula = is_element_contained_in_formula
    styles_and_formulas.is_element_contained_in_formula = is_element_contained_in_formula
    cls = styles_and_formulas.StylesAndFormulas
    if getattr(cls.process_page_formulas, "_pdf2zh_math_fix", False):
        return
    original_process = cls.process_page_formulas
    original_classify = cls._classify_characters_in_composition

    def process_page_formulas(self, page):
        self._pdf2zh_protected_math_chars = protect_math_glyphs(page)
        original_process(self, page)

    def classify(self, *args, **kwargs):
        tagged, first_is_bullet = original_classify(self, *args, **kwargs)
        protected = getattr(self, "_pdf2zh_protected_math_chars", set())
        return [(char, bool(is_formula or id(char) in protected), corner) for char, is_formula, corner in tagged], first_is_bullet

    # shortcut: BabelDOC 0.6 misses bold math letters and detaches hats; remove when upstream preserves both.
    process_page_formulas._pdf2zh_math_fix = True
    cls.process_page_formulas = process_page_formulas
    cls._classify_characters_in_composition = classify


def figure_layout(char, layout_index, layout_map):
    box = char.visual_bbox.box
    area = (box.x2 - box.x) * (box.y2 - box.y)
    if area <= 0:
        return None
    for layout_id in layout_index.intersection((box.x, box.y, box.x2, box.y2)):
        layout = layout_map[layout_id]
        if layout.class_name not in FIGURE_LAYOUTS:
            continue
        region = layout.box
        overlap = max(0, min(box.x2, region.x2) - max(box.x, region.x)) * max(
            0, min(box.y2, region.y2) - max(box.y, region.y)
        )
        if overlap / area >= 0.5:
            return layout
    return None


def restore_figures(target, source, layouts):
    import pymupdf

    for layout in layouts:
        if layout.class_name not in FIGURE_LAYOUTS:
            continue
        box = layout.box
        region = pymupdf.Rect(box.x, box.y, box.x2, box.y2)
        clip = region * source.transformation_matrix
        destination = region * target.transformation_matrix
        clip &= source.rect
        destination &= target.rect
        if clip.is_empty or destination.is_empty:
            continue
        # BabelDOC can corrupt embedded figure fonts even when their text is skipped.
        target.draw_rect(destination, color=None, fill=(1, 1, 1), overlay=True)
        target.show_pdf_page(destination, source.parent, source.number, clip=clip, keep_proportion=False)


def install_figure_protection():
    import pymupdf
    from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
    from babeldoc.format.pdf.document_il.midend import paragraph_finder
    from babeldoc.format.pdf.document_il.utils.layout_helper import Layout, build_layout_index

    original = paragraph_finder.get_character_layout

    def get_character_layout(char, layout_index, layout_map, *args, **kwargs):
        protected = figure_layout(char, layout_index, layout_map)
        if protected is not None:
            return Layout(protected.id, "figure")
        return original(char, layout_index, layout_map, *args, **kwargs)

    # shortcut: BabelDOC 0.6 has no skip-figure-text option; use its paragraph hook until one exists.
    paragraph_finder.get_character_layout = get_character_layout
    original_render = PDFCreater.update_page_content_stream

    def render_page(self, check_font_exists, page, pdf, translation_config, skip_char=False):
        layout_index, layout_map = build_layout_index(page)
        page.pdf_character = [
            char for char in page.pdf_character
            if figure_layout(char, layout_index, layout_map) is None
        ]
        original_render(self, check_font_exists, page, pdf, translation_config, skip_char)
        with pymupdf.open(translation_config.input_file) as source:
            original_page = source[page.page_number]
            original_page.set_rotation(0)
            restore_figures(pdf[page.page_number], original_page, page.page_layout)

    PDFCreater.update_page_content_stream = render_page


# multiprocessing.spawn reimports this entry point in the translation worker.
if __name__ in {"__main__", "__mp_main__"}:
    install_formula_fix()
    if os.environ.get("PDF2ZH_PRESERVE_IMAGES", "1") == "1":
        install_figure_protection()

if __name__ == "__main__":
    from pdf2zh_next.main import cli

    cli()
