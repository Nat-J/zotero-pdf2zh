import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.pdf2zh_next_runner import (
    install_formula_fix,
    is_element_contained_in_formula,
    split_wrapped_text_lines,
)


def box(x, y, x2, y2):
    return SimpleNamespace(x=x, y=y, x2=x2, y2=y2)


class FormulaRulesTest(unittest.TestCase):
    def test_fraction_rules_and_small_shapes_are_contained(self):
        formula = box(10, 10, 40, 40)
        for element in (box(15, 25, 35, 25), box(25, 15, 25, 35), box(15, 20, 35, 22)):
            with self.subTest(element=element):
                self.assertTrue(is_element_contained_in_formula(element, formula))

    def test_unrelated_table_rules_and_invalid_boxes_are_excluded(self):
        formula = box(10, 10, 40, 40)
        for element in (box(0, 25, 100, 25), box(15, 50, 35, 50), box(25, 25, 25, 25), box(35, 25, 15, 25), None):
            with self.subTest(element=element):
                self.assertFalse(is_element_contained_in_formula(element, formula))

    def test_tolerance_and_coverage_threshold_are_respected(self):
        formula = box(10, 10, 40, 40)
        self.assertTrue(is_element_contained_in_formula(box(15, 9, 35, 9), formula))
        self.assertFalse(is_element_contained_in_formula(box(15, 9, 35, 9), formula, tolerance=0))
        self.assertFalse(is_element_contained_in_formula(box(0, 25, 40, 25), formula))
        self.assertTrue(is_element_contained_in_formula(box(0, 25, 40, 25), formula, containment_threshold=0.8))

    @unittest.skipUnless(importlib.util.find_spec("babeldoc"), "Requires the PDF2zh Next environment")
    def test_upstream_moves_fraction_rule_into_owning_formula(self):
        from babeldoc.format.pdf.document_il.midend import styles_and_formulas
        from babeldoc.format.pdf.document_il.utils import spatial_analyzer

        formula = SimpleNamespace(box=box(10, 10, 40, 40), pdf_curve=[], pdf_form=[])
        fraction = SimpleNamespace(box=box(15, 25, 35, 25), xobj_id=1)
        table_rule = SimpleNamespace(box=box(0, 25, 100, 25), xobj_id=1)
        other_object = SimpleNamespace(box=fraction.box, xobj_id=2)
        paragraph = SimpleNamespace(xobj_id=1, pdf_paragraph_composition=[SimpleNamespace(pdf_formula=formula)])
        page = SimpleNamespace(pdf_paragraph=[paragraph], pdf_curve=[fraction, table_rule, other_object], pdf_form=[])
        parser = styles_and_formulas.StylesAndFormulas.__new__(styles_and_formulas.StylesAndFormulas)
        with (
            patch.object(spatial_analyzer, "is_element_contained_in_formula", spatial_analyzer.is_element_contained_in_formula),
            patch.object(styles_and_formulas, "is_element_contained_in_formula", styles_and_formulas.is_element_contained_in_formula),
        ):
            parser.collect_contained_elements(page)
            self.assertEqual(formula.pdf_curve, [])
            install_formula_fix()
            parser.collect_contained_elements(page)
        self.assertEqual(formula.pdf_curve, [fraction])
        self.assertEqual(page.pdf_curve, [table_rule, other_object])


@unittest.skipUnless(importlib.util.find_spec("babeldoc"), "Requires the PDF2zh Next environment")
class MathGlyphsTest(unittest.TestCase):
    def setUp(self):
        from babeldoc.format.pdf.document_il.midend import styles_and_formulas

        cls = styles_and_formulas.StylesAndFormulas
        for name in ("process_page_formulas", "_classify_characters_in_composition", "split_formula_by_comma"):
            self.enterContext(patch.object(cls, name, getattr(cls, name)))
        install_formula_fix()
        self.parser = cls.__new__(cls)
        self.parser.font_mapper = SimpleNamespace(has_char=lambda char: True)
        self.parser.translation_config = SimpleNamespace(formular_font_pattern=None, formular_char_pattern=None)

    def char(self, text, font, bounds, size=10):
        from babeldoc.format.pdf.document_il.il_version_1 import Box, PdfCharacter, PdfStyle, VisualBbox

        return PdfCharacter(
            char_unicode=text, pdf_style=PdfStyle(font_id=font, font_size=size),
            box=Box(*bounds), visual_bbox=VisualBbox(box=Box(*bounds)), vertical=False,
        )

    def page(self, lines):
        from babeldoc.format.pdf.document_il.il_version_1 import PdfLine, PdfParagraph, PdfParagraphComposition

        return SimpleNamespace(
            pdf_font=[SimpleNamespace(font_id=name, name=name) for name in ("CMMI10", "CMBX10", "CMR10", "Times-Roman")],
            pdf_xobject=[],
            pdf_paragraph=[PdfParagraph(pdf_paragraph_composition=[
                PdfParagraphComposition(pdf_line=PdfLine(pdf_character=chars)) for chars in lines
            ])],
        )

    def test_bold_action_variable_is_protected_with_its_subscript(self):
        a = self.char("a", "CMBX10", (480.35, 511.39, 485.60, 515.96))
        t = self.char("t", "CMMI10", (485.90, 508.45, 488.26, 512.88), 7)
        page = self.page([[a, t]])
        self.parser.process_page_formulas(page)
        comps = page.pdf_paragraph[0].pdf_paragraph_composition
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].pdf_formula.pdf_character, [a, t])

    def test_hat_on_previous_line_is_reunited_with_its_base(self):
        # Coordinates from pi0.5 p5: the hat was assigned to the preceding text line.
        hat = self.char("ˆ", "CMR10", (189.96, 304.23, 192.62, 305.77))
        base = self.char("ℓ", "CMMI10", (188.22, 296.11, 192.08, 303.25))
        prose = self.char("x", "Times-Roman", (195, 308, 200, 315))
        page = self.page([[prose, hat], [base]])
        self.parser.process_page_formulas(page)
        comps = page.pdf_paragraph[0].pdf_paragraph_composition
        self.assertEqual(comps[0].pdf_line.pdf_character, [prose])
        self.assertEqual(comps[1].pdf_formula.pdf_character, [hat, base])
        self.assertEqual((hat.visual_bbox.box.y, base.visual_bbox.box.y), (304.23, 296.11))

    def test_isolated_hat_line_is_removed_after_attaching_to_base(self):
        hat = self.char("ˆ", "CMR10", (295.22, 328.23, 297.88, 329.76))
        base = self.char("ℓ", "CMMI10", (293.49, 320.10, 297.34, 327.24))
        page = self.page([[hat], [base]])
        self.parser.process_page_formulas(page)
        comps = page.pdf_paragraph[0].pdf_paragraph_composition
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].pdf_formula.pdf_character, [hat, base])

    def test_ordinary_articles_and_bold_words_remain_translatable(self):
        letters = [self.char(c, "CMBX10", (i * 5, 10, i * 5 + 4, 17)) for i, c in enumerate("FAST")]
        article = self.char("a", "Times-Roman", (30, 10, 34, 17))
        space = self.char(" ", "Times-Roman", (34, 10, 37, 17))
        variable = self.char("ℓ", "CMMI10", (37, 10, 41, 17))
        page = self.page([letters + [article, space, variable]])
        self.parser.process_page_formulas(page)
        comps = page.pdf_paragraph[0].pdf_paragraph_composition
        self.assertEqual(comps[0].pdf_line.pdf_character, letters + [article, space])
        self.assertEqual(comps[1].pdf_formula.pdf_character, [variable])

    def test_math_parentheses_commas_and_operators_stay_in_formula(self):
        chars = [self.char(c, "CMR10" if c in "exp()," else "CMMI10", (i * 5, 10, i * 5 + 4, 20))
                 for i, c in enumerate("exp(π,ℓ)")]
        page = self.page([chars])
        self.parser.process_page_formulas(page)
        comps = page.pdf_paragraph[0].pdf_paragraph_composition
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].pdf_formula.pdf_character, chars)

    def test_wrapped_formula_lines_get_distinct_line_ids(self):
        # pi0.6 p3: the line finder joins the end-of-line '=' to the next line's expectation.
        chars = [self.char("π", "CMMI10", (522, 498, 528, 508)),
                 self.char("=", "CMR10", (555, 498, 563, 508)),
                 self.char("E", "CMMI10", (312, 486, 319, 496)),
                 self.char("τ", "CMMI10", (319, 484, 322, 491), 7)]
        page = self.page([chars])
        self.parser.process_page_formulas(page)
        formulas = [c.pdf_formula for c in page.pdf_paragraph[0].pdf_paragraph_composition]
        self.assertEqual([f.pdf_character for f in formulas], [chars[:2], chars[2:]])
        self.assertNotEqual(formulas[0].line_id, formulas[1].line_id)

    def test_sum_limits_and_display_fractions_are_not_split(self):
        chars = [self.char("∑", "CMMI10", (10, 100, 20, 110)),
                 self.char("T", "CMMI10", (20, 105, 50, 112), 7),
                 self.char("t", "CMMI10", (20, 92, 24, 99), 7)]
        page = self.page([chars])
        split_wrapped_text_lines(page)
        self.assertEqual(len(page.pdf_paragraph[0].pdf_paragraph_composition), 1)

        chars = [self.char("x", "CMMI10", (100, 100, 106, 110)),
                 self.char("y", "CMMI10", (10, 80, 16, 90))]
        for char in chars:
            char.formula_layout_id = 1
        page = self.page([chars])
        split_wrapped_text_lines(page)
        self.assertEqual(len(page.pdf_paragraph[0].pdf_paragraph_composition), 1)

    def test_superscript_comma_does_not_split_the_variable(self):
        from babeldoc.format.pdf.document_il.il_version_1 import PdfFormula

        chars = [self.char("a", "CMBX10", (10, 10, 16, 20)),
                 self.char("η", "CMMI10", (16, 15, 20, 22), 7),
                 self.char(",", "CMR10", (20, 15, 22, 22), 7),
                 self.char("ω", "CMMI10", (22, 15, 26, 22), 7),
                 self.char(",", "CMR10", (27, 10, 29, 20)),
                 self.char("x", "CMMI10", (32, 10, 38, 20))]
        parts = self.parser.split_formula_by_comma(PdfFormula(pdf_character=chars))
        self.assertEqual(parts, [(chars[:4], chars[4]), ([chars[5]], None)])

    def test_hat_split_paragraphs_are_rejoined_before_translation(self):
        from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraph

        left = self.char("π", "CMMI10", (10, 10, 20, 20))
        hat = self.char("ˆ", "CMR10", (22, 21, 24, 23))
        base = self.char("ℓ", "CMMI10", (21, 10, 26, 20))
        page = self.page([[left], [hat], [base]])
        comps = page.pdf_paragraph[0].pdf_paragraph_composition
        page.pdf_paragraph = []
        for i, comp in enumerate(comps):
            comp.pdf_line.box = comp.pdf_line.pdf_character[0].box
            page.pdf_paragraph.append(PdfParagraph(
                box=comp.pdf_line.box, layout_id=8 if i != 1 else 10, xobj_id=0,
                pdf_paragraph_composition=[comp],
            ))
        self.parser.process_page_formulas(page)
        self.assertEqual(len(page.pdf_paragraph), 1)
        chars = page.pdf_paragraph[0].pdf_paragraph_composition[0].pdf_formula.pdf_character
        self.assertEqual(chars, [left, hat, base])


if __name__ == "__main__":
    unittest.main()
