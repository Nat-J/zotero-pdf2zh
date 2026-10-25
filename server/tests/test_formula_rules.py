import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.pdf2zh_next_runner import install_formula_fix, is_element_contained_in_formula


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


if __name__ == "__main__":
    unittest.main()
