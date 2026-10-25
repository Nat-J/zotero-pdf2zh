import sys
import importlib.util
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.config import Config
from utils import execute
from utils.pdf2zh_next_runner import figure_layout, install_figure_protection, restore_figures


def box(x, y, x2, y2):
    return SimpleNamespace(x=x, y=y, x2=x2, y2=y2)


class PreserveImagesTest(unittest.TestCase):
    def setUp(self):
        self.char = SimpleNamespace(visual_bbox=SimpleNamespace(box=box(10, 10, 20, 20)))
        self.figure = SimpleNamespace(id=1, class_name="figure", box=box(0, 0, 100, 100))
        self.text = SimpleNamespace(id=2, class_name="plain text", box=box(5, 5, 25, 25))
        self.layouts = {1: self.figure, 2: self.text}
        self.index = SimpleNamespace(intersection=lambda bounds: self.layouts.keys())

    @unittest.skipUnless(importlib.util.find_spec("babeldoc"), "Run in the PDF2zh Next environment to test the upstream hook")
    def test_figure_wins_when_upstream_prioritizes_overlapping_body_text(self):
        from babeldoc.format.pdf.document_il.midend import paragraph_finder
        from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater

        with (
            patch.object(paragraph_finder, "get_character_layout", paragraph_finder.get_character_layout),
            patch.object(PDFCreater, "update_page_content_stream", PDFCreater.update_page_content_stream),
        ):
            original = paragraph_finder.get_character_layout(self.char, self.index, self.layouts)
            self.assertEqual(original.name, "plain text")
            install_figure_protection()
            protected = paragraph_finder.get_character_layout(self.char, self.index, self.layouts)
            self.assertEqual(protected.name, "figure")

    def test_original_figure_is_restored_without_rasterizing_or_changing_body(self):
        import pymupdf

        with pymupdf.open() as source, pymupdf.open() as translated:
            page = source.new_page(width=200, height=300)
            page.draw_rect((20, 40, 180, 100), fill=(0.8, 0.9, 1))
            page.insert_text((30, 70), "Original Figure")
            target = translated.new_page(width=200, height=300)
            target.insert_text((30, 70), "corrupted")
            target.insert_text((30, 150), "Translated body")
            layout = SimpleNamespace(class_name="figure", box=box(20, 200, 180, 260))
            restore_figures(target, page, [layout])
            clip = pymupdf.Rect(20, 40, 180, 100)
            self.assertEqual(target.get_pixmap(clip=clip).samples, page.get_pixmap(clip=clip).samples)
            self.assertIn("Translated body", target.get_text())
            self.assertEqual(target.get_images(), [])

    def test_caption_outside_figure_remains_translatable(self):
        self.char.visual_bbox.box = box(10, 110, 20, 120)
        self.assertIsNone(figure_layout(self.char, self.index, self.layouts))

    def test_small_overlap_does_not_suppress_body_text(self):
        self.char.visual_bbox.box = box(95, 10, 115, 20)
        self.assertIsNone(figure_layout(self.char, self.index, self.layouts))

    def test_zero_area_and_non_figure_layouts_are_ignored(self):
        self.figure.class_name = "table"
        self.assertIsNone(figure_layout(self.char, self.index, self.layouts))
        self.char.visual_bbox.box = box(10, 10, 10, 20)
        self.assertIsNone(figure_layout(self.char, self.index, self.layouts))

    def test_protection_overrides_ocr_but_can_be_disabled(self):
        with redirect_stdout(StringIO()):
            protected = Config({"engine": "pdf2zh_next", "ocr": True, "autoOcr": True})
            unprotected = Config({"engine": "pdf2zh_next", "preserveImages": "false", "ocr": True})
        self.assertTrue(protected.preserve_images)
        self.assertFalse(protected.ocr)
        self.assertFalse(protected.auto_ocr)
        self.assertFalse(unprotected.preserve_images)
        self.assertTrue(unprotected.ocr)

    def test_runner_keeps_original_cli_flags_and_managed_python(self):
        command = [str(Path(sys.executable).parent / "pdf2zh_next"), "paper.pdf", "--deepseek", "--deepseek-thinking-mode", "disabled"]
        with (
            patch.object(execute, "prepare_deepseek_runtime_command", side_effect=lambda cmd, env: cmd),
            patch.object(execute, "_python_for_invocation_prefix", return_value=Path(sys.executable)),
            patch.object(execute, "_execute_with_pty") as run,
            redirect_stdout(StringIO()),
        ):
            execute.execute_with_progress(command, None, SimpleNamespace(enable_venv=False), None, preserve_images=True)
        actual = run.call_args.args[0]
        self.assertEqual(Path(actual[0]).resolve(), Path(sys.executable).resolve())
        self.assertTrue(actual[2].endswith("pdf2zh_next_runner.py"))
        self.assertEqual(actual[3:], command[1:])
        self.assertEqual(run.call_args.args[1]["PDF2ZH_PRESERVE_IMAGES"], "1")

    def test_formula_fix_runs_even_when_figure_protection_is_disabled(self):
        command = [sys.executable, "-m", "pdf2zh_next", "paper.pdf"]
        with (
            patch.object(execute, "prepare_deepseek_runtime_command", side_effect=lambda cmd, env: cmd),
            patch.object(execute, "_execute_with_pty") as run,
            redirect_stdout(StringIO()),
        ):
            execute.execute_with_progress(command, None, SimpleNamespace(enable_venv=False), None)
        actual, env = run.call_args.args[:2]
        self.assertTrue(actual[2].endswith("pdf2zh_next_runner.py"))
        self.assertEqual(actual[3:], ["paper.pdf"])
        self.assertEqual(env["PDF2ZH_PRESERVE_IMAGES"], "0")


if __name__ == "__main__":
    unittest.main()
