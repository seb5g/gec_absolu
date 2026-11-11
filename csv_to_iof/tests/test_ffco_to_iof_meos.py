import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import csv_to_iof_meos as c  # noqa: E402
import ffco_to_iof_meos as f  # noqa: E402

NS = {"i": c.IOF_NS}
FFCO = HERE / "sample_ffco.xml"


class FfcoExportTests(unittest.TestCase):
    def test_reorders_to_schema_and_adds_punching_system(self):
        tree, report = f.convert_ffco(FFCO)
        e = tree.getroot().find("i:PersonEntry", NS)
        self.assertEqual([el.tag.split("}")[1] for el in e], ["Person", "Organisation", "ControlCard", "Class"])
        self.assertEqual(e.find("i:ControlCard", NS).get("punchingSystem"), "SI")
        self.assertEqual(report.converted, 2)

    def test_category_in_name_keeps_colour_class(self):
        tree, _ = f.convert_ffco(FFCO, category_in_name=True, season_year=2026)
        es = tree.getroot().findall("i:PersonEntry", NS)
        self.assertEqual(es[0].findtext("i:Person/i:Name/i:Given", namespaces=NS), "Camille (D35)")
        self.assertEqual(es[1].findtext("i:Person/i:Name/i:Given", namespaces=NS), "Paul (H16)")
        self.assertEqual(es[0].findtext("i:Class/i:Name", namespaces=NS), "Violet Long")

    def test_mode_categorie_class_becomes_age_category(self):
        classes, courses = c.load_class_ids(HERE / "categories_ffco.csv")
        tree, report = f.convert_ffco(FFCO, mode="categorie", season_year=2026, class_ids=(classes, courses))
        e = tree.getroot().findall("i:PersonEntry", NS)[1]
        self.assertEqual(e.findtext("i:Class/i:Name", namespaces=NS), "H16")
        self.assertEqual(e.findtext("i:Class/i:RaceClass/i:Course/i:Name", namespaces=NS), "Bleu")
        self.assertEqual(e.findtext("i:Class/i:RaceClass/i:Course/i:Id", namespaces=NS), "41727")
        self.assertEqual(report.missing_class_ids, {"D35", "H16"})  # absents du fichier de catégories de test

    def test_cli_and_schema_validity(self):
        try:
            import lxml  # noqa: F401
        except ImportError:
            self.skipTest("lxml non installé")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.xml"
            self.assertEqual(f.main([str(FFCO), "--category-in-name", "--year", "2026", "-o", str(out)]), 0)
            self.assertEqual(c.validate(out), [])
            self.assertNotEqual(c.validate(FFCO), [])  # l'export brut n'est pas conforme au schéma


if __name__ == "__main__":
    unittest.main()
