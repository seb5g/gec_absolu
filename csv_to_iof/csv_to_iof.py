#!/usr/bin/env python3
"""Convertit un export CSV HelloAsso en IOF XML 3.0 (EntryList) pour MeOS.

Usage :
    python csv_to_iof.py export.csv --event-name "Mon événement" -o inscriptions.xml

Seule la bibliothèque standard est nécessaire. La validation contre le schéma
officiel (IOF.xsd, fourni à côté du script) utilise lxml s'il est installé.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

IOF_NS = "http://www.orienteering.org/datastandard/3.0"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
DEFAULT_XSD = Path(__file__).with_name("IOF.xsd")
NO_CLUB_VALUES = {"sans club", "sans", "aucun", "aucun club", "non licencie"}  # normalisés : pas de club
VALID_STATUSES = {"valide", "validee"}

# Correspondances FFCO intégrées (relevées dans les exports FFCO de l'événement 107534).
# Circuits : identifiants propres à cet
# événement, probablement différents pour un autre ; --class-ids les remplace.
# Classes FFCO « couleur » (mode couleur) : identifiants de l'événement 107534.
BUILTIN_CLASSES = {"Bleu": "200", "Jaune": "201", "Vert": "202", "Violet Court": "203", "Violet Long": "204"}
MODES = ("couleur", "categorie")
# Catégories FFCO d'âge : (âge maximum, libellé). Âge = année de l'événement - année de naissance
# (âge au 31 décembre) ; au-delà de 79 ans : 80.
AGE_CLASSES = [(10, "10"), (12, "12"), (14, "14"), (16, "16"), (18, "18"), (20, "20"), (34, "21"), (39, "35"),
               (44, "40"), (49, "45"), (54, "50"), (59, "55"), (64, "60"), (69, "65"), (74, "70"), (79, "75")]
BUILTIN_COURSES = {"Violet Long": "41724", "Violet Court": "41725", "Jaune": "41726", "Bleu": "41727", "Vert": "41728"}
CLUBS_FILE = Path(__file__).with_name("ffco_clubs.xml")  # liste officielle des clubs FFCO (IOF OrganisationList)
# Noms sous lesquels les exports FFCO d'inscriptions écrivent certains clubs (≠ liste officielle) -> id club.
BUILTIN_CLUB_ALIASES = {"ABSOLU RAID": "3108", "CENT VALLEES ORIENTATION 12": "1202"}

# Rôle logique -> mots-clés (sans accents, minuscules) qui doivent tous apparaître
# dans l'en-tête de la colonne. Premier en-tête qui correspond.
COLUMN_RULES = {
    "status": [["statut", "commande"]],
    "family": [["nom", "participant"]],
    "given": [["prenom", "participant"]],
    "birth": [["naissance"]],
    "club": [["club"]],
    "card": [["puce", "numero"], ["puce", "sport ident"]],
    "circuit": [["circuit"]],
    "sex": [["femme", "homme"], ["sexe"]],
    "card_loan": [["pret", "puce"]],
    "licence": [["licence"]],
    "phone": [["telephone"], ["portable"], ["mobile"], ["tel"]],
}
REQUIRED_COLUMNS = ("status", "family", "given", "circuit")


@dataclass
class Report:
    converted: int = 0
    skipped: list = field(default_factory=list)  # (n° ligne, raison)
    warnings: list = field(default_factory=list)  # (n° ligne, message)
    missing_card: list = field(default_factory=list)  # noms
    missing_class_ids: set = field(default_factory=set)  # catégories sans identifiant

    def render(self) -> str:
        lines = [f"{self.converted} inscrit(s) converti(s)."]
        if self.skipped:
            lines.append(f"{len(self.skipped)} ligne(s) ignorée(s) :")
            lines += [f"  - ligne {n} : {why}" for n, why in self.skipped]
        if self.missing_card:
            lines.append(
                f"{len(self.missing_card)} coureur(s) sans n° de puce (à saisir dans MeOS) :"
            )
            lines += [f"  - {name}" for name in self.missing_card]
        if self.missing_class_ids:
            lines.append("Catégories sans identifiant FFCO (MeOS en créera de nouvelles ; utilise --class-ids) : "
                         + ", ".join(sorted(self.missing_class_ids)))
        if self.warnings:
            lines.append("Avertissements :")
            lines += [f"  - ligne {n} : {msg}" for n, msg in self.warnings]
        return "\n".join(lines)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def _norm_club(text: str) -> str:
    """Comme _norm, et la ponctuation devient un espace (« Absolu'O » -> « absolu o »)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", _norm(text).replace("_", " "))).strip()


def _clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def read_rows(path: Path) -> tuple[list[str], list[dict]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    return list(reader.fieldnames or []), list(reader)


def map_columns(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for role, alternatives in COLUMN_RULES.items():
        for keywords in alternatives:
            for header in headers:
                if all(k in _norm(header) for k in keywords):
                    mapping.setdefault(role, header)
                    break
            if role in mapping:
                break
    missing = [r for r in REQUIRED_COLUMNS if r not in mapping]
    if missing:
        raise SystemExit(
            "Colonnes introuvables dans le CSV : " + ", ".join(missing)
            + "\nEn-têtes lus : " + " | ".join(headers)
        )
    return mapping


def class_name(circuit: str, class_map: dict[str, str],
               known: Optional[list[str]] = None) -> tuple[str, bool]:
    """« Bleu ( 2,5 km - Niveau ... ) » -> « Bleu ».

    Si `known` est fourni, le nom est rapproché (casse/accents ignorés) de cette
    liste ; le booléen retourné vaut False si le circuit n'y figure pas.
    """
    name = _clean(re.split(r"\s*\(", circuit, maxsplit=1)[0])
    name = class_map.get(name, name)
    if known:
        by_norm = {_norm(k): k for k in known}
        if _norm(name) in by_norm:
            return by_norm[_norm(name)], True
        return name, False
    return name, True


def parse_birth(value: str) -> Optional[date]:
    value = _clean(value)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def parse_sex(value: str) -> Optional[str]:
    v = _norm(value)
    if v in {"femme", "f", "feminin", "female"}:
        return "F"
    if v in {"homme", "h", "m", "masculin", "male"}:
        return "M"
    return None


def category_for(birth: date, sex: str, year: int) -> str:
    """Catégorie FFCO d'âge et de sexe (D14, H21...), âge au 31 décembre de `year`."""
    age = year - birth.year
    label = next((lab for limit, lab in AGE_CLASSES if age <= limit), "80")
    return ("D" if sex == "F" else "H") + label


def parse_card(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _q(tag: str) -> str:
    return f"{{{IOF_NS}}}{tag}"


def load_clubs(path: Path) -> dict[str, dict]:
    """Lit les clubs d'un fichier IOF XML 3.0 (OrganisationList, ou tout fichier dont les
    éléments Organisation portent un Id et un Name, comme un export FFCO d'inscriptions).

    Retourne {nom normalisé: {"id", "name", "short", "country"}} ; le sigle (ShortName)
    est aussi indexé. Un nom partagé par plusieurs clubs (ex. « INDIVIDUEL », un par
    département) est ambigu et n'est pas indexé.
    """
    clubs: dict[str, dict] = {}
    ambiguous: set[str] = set()
    for org in ET.parse(path).getroot().iter(_q("Organisation")):
        oid, name = org.findtext(_q("Id")), _clean(org.findtext(_q("Name")))
        if not oid or not name:
            continue
        country = org.find(_q("Country"))
        info = {"id": oid.strip(), "name": name,
                "short": _clean(org.findtext(_q("ShortName"))),
                "country": country.get("code") if country is not None else None}
        for key in (name, info["short"]):
            k = _norm_club(key) if key else ""
            if not k:
                continue
            if k in clubs and clubs[k]["id"] != info["id"]:
                ambiguous.add(k)
            clubs.setdefault(k, info)
    for k in ambiguous:
        del clubs[k]
    return clubs


def load_class_ids(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Lit les identifiants de classes et de circuits d'un export FFCO (IOF XML 3.0).

    Retourne ({nom normalisé de classe: {"id", "name"}}, {nom normalisé de circuit: {"id", "name"}}).
    """
    classes: dict[str, dict] = {}
    courses: dict[str, dict] = {}
    if path.suffix.lower() == ".csv":
        return _load_oe_categories(path), courses
    for cls in ET.parse(path).getroot().iter(_q("Class")):
        cid, cname = cls.findtext(_q("Id")), _clean(cls.findtext(_q("Name")))
        if cid and cname:
            classes.setdefault(_norm(cname), {"id": cid.strip(), "name": cname})
        for course in cls.iter(_q("Course")):
            oid, oname = course.findtext(_q("Id")), _clean(course.findtext(_q("Name")))
            if oid and oname:
                courses.setdefault(_norm(oname), {"id": oid.strip(), "name": oname})
    return classes, courses


def _load_oe_categories(path: Path) -> dict[str, dict]:
    """Fichier de catégories FFCO au format OE (CSV « ;  » : colonnes « Nr catg. » et « Catg. Court »)."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=";")
    by_norm = {_norm(h): h for h in (reader.fieldnames or [])}
    id_col = next((h for n, h in by_norm.items() if n.startswith("nr catg")), None)
    name_col = next((h for n, h in by_norm.items() if n.startswith("catg") and "court" in n), None)
    if not id_col or not name_col:
        raise SystemExit("Fichier de catégories : colonnes « Nr catg. » et « Catg. Court » introuvables")
    classes: dict[str, dict] = {}
    for row in reader:
        cid, name = _clean(row.get(id_col)), _clean(row.get(name_col))
        if cid and name:
            classes.setdefault(_norm(name), {"id": cid, "name": name})
    return classes


def builtin_class_ids() -> tuple[dict[str, dict], dict[str, dict]]:
    """(classes « couleur », circuits). Les identifiants des catégories d'âge viennent de --class-ids."""
    return (
        {_norm(n): {"id": i, "name": n} for n, i in BUILTIN_CLASSES.items()},
        {_norm(n): {"id": i, "name": n} for n, i in BUILTIN_COURSES.items()},
    )


def builtin_clubs() -> dict[str, dict]:
    """Liste officielle FFCO fournie avec le script + alias des noms vus dans les exports FFCO."""
    clubs = load_clubs(CLUBS_FILE) if CLUBS_FILE.exists() else {}
    by_id = {v["id"]: v for v in clubs.values()}
    for alias, club_id in BUILTIN_CLUB_ALIASES.items():
        if club_id in by_id:
            clubs.setdefault(_norm_club(alias), by_id[club_id])
    return clubs


def match_club(name: str, clubs: dict[str, dict]) -> tuple[Optional[dict], bool]:
    """(club, approximatif). Exact (casse, accents, ponctuation ignorés), sinon voisin très proche."""
    key = _norm_club(name)
    if key in clubs:
        return clubs[key], False
    close = difflib.get_close_matches(key, list(clubs), n=1, cutoff=0.85)
    if close:
        return clubs[close[0]], True
    # nom abrégé : « Absolu » -> « Absolu'O », seulement s'il n'y a qu'un candidat
    words = [k for k in clubs if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", k)] if len(key) >= 3 else []
    if len({id(clubs[k]) for k in words}) == 1:
        return clubs[words[0]], True
    return None, False


def build_tree(rows, cols, event_name, event_id=None, nationality="FRA",
               class_map=None, known_classes=None, clubs=None, class_ids=None, season_year=None, mode="couleur",
               category_in_name=False, now=None) -> tuple[ET.ElementTree, Report]:
    class_map = class_map or {}
    season_year = season_year or date.today().year
    report = Report()
    ET.register_namespace("", IOF_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.Element(_q("EntryList"), {
        "iofVersion": "3.0",
        "createTime": (now or datetime.now()).replace(microsecond=0).isoformat(),
        "creator": "csv_to_iof.py",
    })
    event = ET.SubElement(root, _q("Event"))
    if event_id:
        ET.SubElement(event, _q("Id")).text = str(event_id)
    ET.SubElement(event, _q("Name")).text = event_name

    def get(row, role):
        col = cols.get(role)
        return _clean(row.get(col)) if col else ""

    for lineno, row in enumerate(rows, start=2):  # ligne 1 = en-têtes
        status = get(row, "status")
        if not status and not get(row, "family") and not get(row, "given"):
            continue  # ligne vide / résidu d'export

        if _norm(status) not in VALID_STATUSES:
            report.skipped.append((lineno, f"commande « {status or 'sans statut'} »"))
            continue
        family, given = get(row, "family"), get(row, "given")
        if not family or not given:
            report.skipped.append((lineno, "nom ou prénom manquant"))
            continue
        label = f"{given} {family}"

        entry = ET.SubElement(root, _q("PersonEntry"))
        sex = parse_sex(get(row, "sex"))
        if get(row, "sex") and not sex:
            report.warnings.append((lineno, f"{label} : sexe « {get(row, 'sex')} » non reconnu"))
        person = ET.SubElement(entry, _q("Person"), {"sex": sex} if sex else {})
        licence = get(row, "licence")
        if licence:
            ET.SubElement(person, _q("Id"), {"type": "FFCO"}).text = licence
        birth_raw = get(row, "birth")
        birth = parse_birth(birth_raw) if birth_raw else None
        name = ET.SubElement(person, _q("Name"))
        ET.SubElement(name, _q("Family")).text = family
        given_xml = given
        if category_in_name:
            # La catégorie d'âge apparaît dans les listes MeOS à la suite du prénom : « Aurore (D40) ».
            if birth and sex:
                given_xml = f"{given} ({category_for(birth, sex, season_year)})"
            else:
                report.warnings.append((lineno, f"{label} : catégorie d'âge non calculable, nom sans catégorie"))
        ET.SubElement(name, _q("Given")).text = given_xml
        if birth:
            ET.SubElement(person, _q("BirthDate")).text = birth.isoformat()
        elif birth_raw:
            report.warnings.append((lineno, f"{label} : date de naissance « {birth_raw} » illisible"))
        if nationality:
            ET.SubElement(person, _q("Nationality"), {"code": nationality})

        phone = re.sub(r"[^\d+ ]", "", get(row, "phone")).strip()
        if phone:
            ET.SubElement(person, _q("Contact"), {"type": "MobilePhoneNumber"}).text = phone

        club_name = get(row, "club")
        if club_name and _norm_club(club_name) not in NO_CLUB_VALUES:
            org = ET.SubElement(entry, _q("Organisation"))
            found = None
            if clubs:
                found, approx = match_club(club_name, clubs)
                if found is None:
                    report.warnings.append((lineno, f"{label} : club « {club_name} » absent de la liste des clubs"))
                elif approx:
                    report.warnings.append((lineno, f"{label} : club « {club_name} » rapproché de « {found['name']} »"))
            if found:
                ET.SubElement(org, _q("Id")).text = found["id"]
                ET.SubElement(org, _q("Name")).text = found["name"]
                if found["short"]:
                    ET.SubElement(org, _q("ShortName")).text = found["short"]
                if found["country"]:
                    ET.SubElement(org, _q("Country"), {"code": found["country"]})
            else:
                ET.SubElement(org, _q("Name")).text = club_name
        # club vide ou « Sans club » : pas d'élément Organisation, MeOS laisse le club vide

        card = parse_card(get(row, "card"))
        if card:
            ET.SubElement(entry, _q("ControlCard"), {"punchingSystem": "SI"}).text = card
            if _norm(get(row, "card_loan")) == "oui":
                report.warnings.append((lineno, f"{label} : puce renseignée ET prêt de puce demandé"))
        else:
            report.missing_card.append(label)

        circuit = get(row, "circuit")
        course = known = None
        if circuit:
            course, known = class_name(circuit, class_map, known_classes)
        if mode == "couleur":
            # Classe MeOS = circuit (course « couleur ») : comme l'export FFCO d'un événement à circuits de couleur.
            class_label = course
            if not circuit:
                report.warnings.append((lineno, f"{label} : aucun circuit choisi, inscrit sans classe"))
        else:
            # Classe MeOS = catégorie d'âge/sexe calculée ; le circuit devient le parcours.
            class_label = None
            if not (birth and sex):
                report.warnings.append((lineno, f"{label} : catégorie non calculable (naissance ou sexe manquant), inscrit sans classe"))
            else:
                class_label = category_for(birth, sex, season_year)
            if class_label and not circuit:
                report.warnings.append((lineno, f"{label} : aucun circuit choisi"))
        if class_label:
            cls = ET.SubElement(entry, _q("Class"))
            class_ref = class_ids[0].get(_norm(class_label)) if class_ids else None
            if class_ref:
                ET.SubElement(cls, _q("Id")).text = class_ref["id"]
                class_label = class_ref["name"]
            elif class_ids:
                report.missing_class_ids.add(class_label)
            ET.SubElement(cls, _q("Name")).text = class_label
            if circuit:
                course_ref = class_ids[1].get(_norm(course)) if class_ids else None
                race_class = ET.SubElement(cls, _q("RaceClass"))
                course_el = ET.SubElement(race_class, _q("Course"))
                if course_ref:
                    ET.SubElement(course_el, _q("Id")).text = course_ref["id"]
                    course = course_ref["name"]
                ET.SubElement(course_el, _q("Name")).text = course
        if circuit and not known:
            report.warnings.append((lineno, f"{label} : circuit « {course} » absent de la liste --classes"))
        report.converted += 1

    ET.indent(root)
    return ET.ElementTree(root), report


def validate(xml_path: Path, xsd_path: Path = DEFAULT_XSD) -> list[str]:
    """Retourne la liste des erreurs de schéma (vide si valide)."""
    try:
        from lxml import etree
    except ImportError:
        raise SystemExit("La validation demande lxml : pip install lxml")
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    doc = etree.parse(str(xml_path))
    if schema.validate(doc):
        return []
    return [f"ligne {e.line} : {e.message}" for e in schema.error_log]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("csv", type=Path, help="export CSV HelloAsso")
    p.add_argument("--event-name", required=True, help="nom de l'épreuve (Event/Name, exigé par le schéma)")
    p.add_argument("--event-id", help="identifiant de l'événement (facultatif)")
    p.add_argument("-o", "--output", type=Path, help="fichier XML (défaut : <csv>.xml)")
    p.add_argument("--nationality", default="FRA", help="code pays par défaut, vide pour l'omettre (défaut : FRA)")
    p.add_argument("--class-map", type=Path, help="JSON {\"nom du circuit\": \"nom du circuit dans MeOS\"} (facultatif)")
    p.add_argument("--classes", help="liste des circuits (parcours) attendus, séparés par « ; » (ex. \"Violet Long;Jaune;Bleu\") : "
                   "normalise la casse et signale les circuits inconnus")
    p.add_argument("--clubs", type=Path, help="liste officielle des clubs (IOF XML : OrganisationList ou export FFCO) : "
                   "ajoute l'identifiant de club, que MeOS utilise pour rapprocher sa base")
    p.add_argument("--class-ids", type=Path, help="export FFCO d'inscriptions (IOF XML) ou fichier de catégories FFCO (CSV « Nr catg. ») dont on reprend les identifiants "
                   "de catégories et de circuits : MeOS crée une nouvelle catégorie si l'identifiant diffère")
    p.add_argument("--mode", choices=MODES, default="couleur",
                   help="couleur (défaut) : la classe MeOS est le circuit ; categorie : la classe est la catégorie "
                        "d'âge/sexe calculée (D14, H21...) et le circuit devient le parcours")
    p.add_argument("--category-in-name", action="store_true",
                   help="ajoute la catégorie d'âge au prénom (« Aurore (D40) ») pour qu'elle apparaisse dans les listes MeOS")
    p.add_argument("--year", type=int, default=date.today().year,
                   help="année de l'événement (mode categorie) : l'âge est calculé au 31 décembre de cette année (défaut : année en cours)")
    p.add_argument("--no-builtin", action="store_true",
                   help="n'utilise pas les identifiants FFCO intégrés (catégories, circuits, clubs)")
    p.add_argument("--no-validate", action="store_true", help="ne pas valider contre IOF.xsd")
    args = p.parse_args(argv)

    headers, rows = read_rows(args.csv)
    cols = map_columns(headers)
    class_map = json.loads(args.class_map.read_text(encoding="utf-8")) if args.class_map else {}
    clubs = {} if args.no_builtin else builtin_clubs()
    class_ids = None if args.no_builtin else builtin_class_ids()
    if args.clubs:
        clubs = {**clubs, **load_clubs(args.clubs)}  # --clubs complète / remplace la liste intégrée
    if args.class_ids:
        loaded = load_class_ids(args.class_ids)
        class_ids = ({**(class_ids or ({}, {}))[0], **loaded[0]}, {**(class_ids or ({}, {}))[1], **loaded[1]})
    tree, report = build_tree(rows, cols, args.event_name, args.event_id,
                              args.nationality, class_map,
                              [c for c in (args.classes or "").split(";") if c.strip()],
                              clubs, class_ids, args.year, args.mode, args.category_in_name)
    out = args.output or args.csv.with_suffix(".xml")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    print(report.render())
    print(f"Écrit : {out}")

    if not args.no_validate:
        try:
            errors = validate(out)
        except SystemExit as exc:
            print(f"Validation ignorée : {exc}", file=sys.stderr)
            return 0
        if errors:
            print("XML NON VALIDE :", *errors, sep="\n  ", file=sys.stderr)
            return 1
        print("XML valide selon IOF.xsd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
