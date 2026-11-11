import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import csv_to_iof as c  # noqa: E402

SAMPLE = HERE / "sample_helloasso.csv"
NS = {"i": c.IOF_NS}


def convert(**kw):
    headers, rows = c.read_rows(SAMPLE)
    cols = c.map_columns(headers)
    kw.setdefault("season_year", 2026)
    kw.setdefault("mode", "categorie")
    return c.build_tree(rows, cols, "Test O", **kw)


class ConvertTests(unittest.TestCase):
    def test_only_validated_rows_are_converted(self):
        tree, report = convert()
        entries = tree.getroot().findall("i:PersonEntry", NS)
        self.assertEqual(len(entries), 2)
        self.assertEqual(report.converted, 2)
        self.assertEqual(len(report.skipped), 1)  # « En-attente » ; ligne vide ignorée sans bruit

    def test_fields(self):
        tree, _ = convert()
        e = tree.getroot().findall("i:PersonEntry", NS)[0]
        p = e.find("i:Person", NS)
        self.assertEqual(p.get("sex"), "F")
        self.assertEqual(p.findtext("i:Name/i:Family", namespaces=NS), "DUPONT")
        self.assertEqual(p.findtext("i:BirthDate", namespaces=NS), "2015-03-30")
        self.assertEqual(e.findtext("i:Class/i:Name", namespaces=NS), "D12")  # née en 2015, 11 ans au 31/12/2026
        self.assertEqual(e.findtext("i:Class/i:RaceClass/i:Course/i:Name", namespaces=NS), "Bleu")
        self.assertEqual(e.findtext("i:Organisation/i:Name", namespaces=NS), "ABSOLU RAID")
        self.assertIsNone(e.find("i:ControlCard", NS))

    def test_phone(self):
        tree, _ = convert()
        es = tree.getroot().findall("i:PersonEntry", NS)
        c0 = es[0].find("i:Person/i:Contact", NS)
        self.assertEqual((c0.get("type"), c0.text), ("MobilePhoneNumber", "06 12 34 56 78"))
        self.assertIsNone(es[1].find("i:Person/i:Contact", NS))

    def test_card_and_default_club(self):
        tree, report = convert()
        e = tree.getroot().findall("i:PersonEntry", NS)[1]
        self.assertEqual(e.findtext("i:ControlCard", namespaces=NS), "34566323")
        self.assertEqual(e.find("i:ControlCard", NS).get("punchingSystem"), "SI")
        self.assertIsNone(e.find("i:Organisation", NS))  # club vide : pas d'Organisation
        self.assertEqual(report.missing_card, ["Léa DUPONT"])

    def test_circuit_map_renames_course_only(self):
        tree, _ = convert(class_map={"Bleu": "Circuit Bleu"})
        cls = tree.getroot().findall("i:PersonEntry", NS)[0].find("i:Class", NS)
        self.assertEqual(cls.findtext("i:Name", namespaces=NS), "D12")
        self.assertEqual(cls.findtext("i:RaceClass/i:Course/i:Name", namespaces=NS), "Circuit Bleu")

    def test_mode_couleur_uses_circuit_as_class(self):
        tree, report = convert(mode="couleur", class_ids=c.builtin_class_ids())
        cls = tree.getroot().findall("i:PersonEntry", NS)[0].find("i:Class", NS)
        self.assertEqual(cls.findtext("i:Name", namespaces=NS), "Bleu")
        self.assertEqual(cls.findtext("i:Id", namespaces=NS), "200")
        self.assertEqual(cls.findtext("i:RaceClass/i:Course/i:Name", namespaces=NS), "Bleu")
        self.assertEqual(cls.findtext("i:RaceClass/i:Course/i:Id", namespaces=NS), "41727")
        self.assertEqual(report.missing_class_ids, {"Violet"})  # « Violet » seul n'existe pas

    def test_mode_couleur_needs_no_birth_or_sex(self):
        headers, rows = c.read_rows(SAMPLE)
        rows[0]["Femme/Homme"] = ""
        rows[0]["Date  de Naissance"] = ""
        tree, _ = c.build_tree(rows, c.map_columns(headers), "T", mode="couleur")
        self.assertEqual(tree.getroot().findall("i:PersonEntry", NS)[0].findtext("i:Class/i:Name", namespaces=NS), "Bleu")

    def test_category_for_age_and_sex(self):
        from datetime import date
        f = lambda y, s, year=2026: c.category_for(date(y, 6, 1), s, year)
        self.assertEqual(f(2016, "F"), "D10")   # 10 ans
        self.assertEqual(f(2015, "M"), "H12")   # 11 ans
        self.assertEqual(f(2005, "F"), "D21")   # 21 ans
        self.assertEqual(f(1992, "M"), "H21")   # 34 ans
        self.assertEqual(f(1991, "M"), "H35")   # 35 ans
        self.assertEqual(f(1986, "F"), "D40")   # 40 ans
        self.assertEqual(f(1947, "M"), "H75")   # 79 ans
        self.assertEqual(f(1946, "M"), "H80")   # 80 ans
        self.assertEqual(f(1990, "M", 2027), "H35")  # l'année de l'événement compte

    def test_missing_birth_or_sex_gives_no_class(self):
        headers, rows = c.read_rows(SAMPLE)
        rows[0]["Femme/Homme"] = ""
        tree, report = c.build_tree(rows, c.map_columns(headers), "T", season_year=2026, mode="categorie")
        self.assertIsNone(tree.getroot().findall("i:PersonEntry", NS)[0].find("i:Class", NS))
        self.assertTrue(any("non calculable" in m for _, m in report.warnings))

    def test_clubs_list_adds_ids(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "clubs.xml"
            f.write_text(
                f'<OrganisationList xmlns="{c.IOF_NS}" iofVersion="3.0">'
                '<Organisation><Id>3108</Id><Name>ABSOLU RAID</Name><ShortName>3108OC</ShortName>'
                '<Country code="FRA">France</Country></Organisation></OrganisationList>',
                encoding="utf-8")
            clubs = c.load_clubs(f)
        tree, report = convert(clubs=clubs)
        org = tree.getroot().findall("i:PersonEntry", NS)[0].find("i:Organisation", NS)
        self.assertEqual(org.findtext("i:Id", namespaces=NS), "3108")
        self.assertEqual(org.findtext("i:ShortName", namespaces=NS), "3108OC")
        # club vide : pas d'Organisation, pas d'avertissement
        self.assertIsNone(tree.getroot().findall("i:PersonEntry", NS)[1].find("i:Organisation", NS))
        self.assertFalse(any("Sans club" in m for _, m in report.warnings))  # club vide : pas de bruit
        self.assertEqual(c.match_club("absolu  raid", clubs)[1], False)
        self.assertEqual(c.match_club("Absolu Raids", clubs)[1], True)
        self.assertEqual(c.match_club("Absolu", clubs)[0]["id"], "3108")
        self.assertIsNone(c.match_club("BOA", clubs)[0])

    def test_class_ids_from_ffco_export(self):
        ffco = (f'<EntryList xmlns="{c.IOF_NS}" iofVersion="3.0"><Event><Name>E</Name></Event><PersonEntry>'
                '<Person><Name><Family>A</Family><Given>B</Given></Name></Person>'
                '<Class><Id>312</Id><Name>D12</Name><RaceClass><Course><Id>41727</Id><Name>Bleu</Name>'
                '</Course></RaceClass></Class></PersonEntry></EntryList>')
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ffco.xml"
            f.write_text(ffco, encoding="utf-8")
            ids = c.load_class_ids(f)
        tree, report = convert(class_ids=ids)
        cls = tree.getroot().findall("i:PersonEntry", NS)[0].find("i:Class", NS)
        self.assertEqual(cls.findtext("i:Id", namespaces=NS), "312")
        self.assertEqual(cls.findtext("i:RaceClass/i:Course/i:Id", namespaces=NS), "41727")
        # « H45 » absente de l'export FFCO : sans identifiant, signalée une fois dans le rapport
        cls2 = tree.getroot().findall("i:PersonEntry", NS)[1].find("i:Class", NS)
        self.assertIsNone(cls2.find("i:Id", NS))
        self.assertEqual(report.missing_class_ids, {"H45"})

    def test_class_ids_from_ffco_category_csv(self):
        classes, courses = c.load_class_ids(HERE / "categories_ffco.csv")
        self.assertEqual(classes[c._norm("D12")]["id"], "312")
        self.assertEqual(courses, {})
        tree, report = convert(class_ids=(classes, courses))
        cls0 = tree.getroot().findall("i:PersonEntry", NS)[0].find("i:Class", NS)
        self.assertEqual(cls0.findtext("i:Id", namespaces=NS), "312")
        self.assertEqual(report.missing_class_ids, set())

    def test_official_club_list_bundled(self):
        clubs = c.builtin_clubs()
        self.assertEqual(c.match_club("Absolu'O", clubs)[0]["id"], "3108")
        self.assertEqual(c.match_club("ABSOLU RAID", clubs)[0]["id"], "3108")  # alias vu dans les exports
        self.assertEqual(c.match_club("BOA Albi", clubs)[0]["id"], "8105")
        self.assertEqual(c.match_club("boa", clubs)[0]["id"], "8105")
        self.assertIsNone(c.match_club("INDIVIDUEL", clubs)[0])  # un par département : ambigu

    def test_sans_club_value_gives_no_organisation(self):
        self.assertIn(c._norm_club("Sans Club"), c.NO_CLUB_VALUES)

    def test_builtin_mapping(self):
        classes, courses = c.builtin_class_ids()
        tree, _ = convert(class_ids=(classes, courses), clubs=c.builtin_clubs())
        e = tree.getroot().findall("i:PersonEntry", NS)[0]
        self.assertIsNone(e.find("i:Class/i:Id", NS))  # catégories : identifiants via --class-ids
        self.assertEqual(e.findtext("i:Class/i:RaceClass/i:Course/i:Id", namespaces=NS), "41727")
        self.assertEqual(e.findtext("i:Organisation/i:Id", namespaces=NS), "3108")

    def test_known_classes(self):
        _, report = convert(known_classes=["Violet Long", "Jaune"])
        self.assertTrue(any("Bleu" in m for _, m in report.warnings))
        name, ok = c.class_name("violet  long (7 km)", {}, ["Violet Long"])
        self.assertEqual((name, ok), ("Violet Long", True))

    def test_missing_required_column(self):
        with self.assertRaises(SystemExit):
            c.map_columns(["foo", "bar"])

    def test_helpers(self):
        self.assertEqual(c.parse_sex("Homme"), "M")
        self.assertEqual(c.parse_sex("Femme"), "F")
        self.assertIsNone(c.parse_sex("?"))
        self.assertEqual(c.parse_card(" 7502 111 "), "7502111")
        self.assertIsNone(c.parse_birth("n'importe quoi"))


@unittest.skipUnless(c.DEFAULT_XSD.exists(), "IOF.xsd absent")
class SchemaTests(unittest.TestCase):
    def test_output_with_class_ids_is_valid(self):
        try:
            import lxml  # noqa: F401
        except ImportError:
            self.skipTest("lxml non installé")
        ids = ({c._norm("D12"): {"id": "312", "name": "D12"}}, {c._norm("Bleu"): {"id": "41727", "name": "Bleu"}})
        tree, _ = convert(class_ids=ids)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.xml"
            tree.write(out, encoding="utf-8", xml_declaration=True)
            self.assertEqual(c.validate(out), [])

    def test_output_with_clubs_is_valid(self):
        try:
            import lxml  # noqa: F401
        except ImportError:
            self.skipTest("lxml non installé")
        club = {"id": "3108", "name": "ABSOLU RAID", "short": "3108OC", "country": "FRA"}
        tree, _ = convert(clubs={c._norm("ABSOLU RAID"): club})
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.xml"
            tree.write(out, encoding="utf-8", xml_declaration=True)
            self.assertEqual(c.validate(out), [])

    def test_output_is_valid_against_iof_xsd(self):
        try:
            import lxml  # noqa: F401
        except ImportError:
            self.skipTest("lxml non installé")
        tree, _ = convert()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.xml"
            tree.write(out, encoding="utf-8", xml_declaration=True)
            self.assertEqual(c.validate(out), [])

    def test_cli_end_to_end(self):
        try:
            import lxml  # noqa: F401
        except ImportError:
            self.skipTest("lxml non installé")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.xml"
            rc = c.main([str(SAMPLE), "--event-name", "Test", "-o", str(out)])
            self.assertEqual(rc, 0)
            self.assertEqual(ET.parse(out).getroot().get("iofVersion"), "3.0")


if __name__ == "__main__":
    unittest.main()
