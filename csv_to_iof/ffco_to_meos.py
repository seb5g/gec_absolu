#!/usr/bin/env python3
"""Retraite un export FFCO d'inscriptions (IOF XML 3.0) pour MeOS.

Usage :
    python ffco_to_meos.py inscriptions39133.xml --category-in-name --year 2026

Réutilise les fonctions de csv_to_iof.py (même dossier). Voir le README.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from csv_to_iof import (IOF_NS, XSI_NS, MODES, Report, _norm, _q, _clean, builtin_class_ids, category_for,
                        load_class_ids, parse_birth, parse_sex, validate)

ENTRY_ORDER = ["Id", "Person", "Organisation", "ControlCard", "Score", "Class", "RaceNumber", "AssignedFee",
               "ServiceRequest", "StartTimeAllocationRequest", "EntryTime", "Extensions"]


def convert_ffco(path: Path, event_name=None, event_id=None, class_ids=None, season_year=None,
                 mode="couleur", category_in_name=False) -> tuple[ET.ElementTree, Report]:
    """Retraite un export FFCO d'inscriptions (IOF XML 3.0) avec les mêmes options que le CSV HelloAsso.

    - remet les éléments de chaque PersonEntry dans l'ordre du schéma (l'export FFCO n'y est pas conforme) ;
    - `category_in_name` : ajoute la catégorie d'âge au prénom (« Aurore (D40) ») ;
    - mode `categorie` : la classe devient la catégorie d'âge/sexe (identifiants via `class_ids`) et la classe
      d'origine (le circuit) devient le parcours ; mode `couleur` : la classe reste celle de l'export.
    """
    season_year = season_year or date.today().year
    report = Report()
    ET.register_namespace("", IOF_NS)
    ET.register_namespace("xsi", XSI_NS)
    tree = ET.parse(path)
    root = tree.getroot()
    event = root.find(_q("Event"))
    if event is not None:
        if event_name:
            event.find(_q("Name")).text = event_name
        if event_id:
            id_el = event.find(_q("Id"))
            if id_el is None:
                id_el = ET.Element(_q("Id"))
                event.insert(0, id_el)
            id_el.text = str(event_id)

    for entry in root.findall(_q("PersonEntry")):
        person = entry.find(_q("Person"))
        family = _clean(person.findtext(f"{_q('Name')}/{_q('Family')}"))
        given_el = person.find(f"{_q('Name')}/{_q('Given')}")
        label = f"{_clean(given_el.text if given_el is not None else '')} {family}".strip()
        sex = parse_sex(person.get("sex", ""))
        birth = parse_birth(person.findtext(_q("BirthDate")) or "")
        category = category_for(birth, sex, season_year) if birth and sex else None

        if category_in_name and given_el is not None:
            if category:
                given_el.text = f"{_clean(given_el.text)} ({category})"
            else:
                report.warnings.append((0, f"{label} : catégorie d'âge non calculable, nom sans catégorie"))

        card = entry.find(_q("ControlCard"))
        if card is not None and not card.get("punchingSystem") and (card.text or "").strip():
            card.set("punchingSystem", "SI")

        cls = entry.find(_q("Class"))
        if mode == "categorie":
            if not category:
                report.warnings.append((0, f"{label} : catégorie non calculable (naissance ou sexe manquant), inscrit sans classe"))
                if cls is not None:
                    entry.remove(cls)
            else:
                old = cls
                new = ET.Element(_q("Class"))
                ref = class_ids[0].get(_norm(category)) if class_ids else None
                if ref:
                    ET.SubElement(new, _q("Id")).text = ref["id"]
                elif class_ids:
                    report.missing_class_ids.add(category)
                ET.SubElement(new, _q("Name")).text = ref["name"] if ref else category
                if old is not None:
                    course = old.find(f"{_q('RaceClass')}/{_q('Course')}")
                    if course is None:  # export sans parcours : le circuit est la classe d'origine
                        course = ET.Element(_q("Course"))
                        ET.SubElement(course, _q("Name")).text = _clean(old.findtext(_q("Name")))
                    ET.SubElement(new, _q("RaceClass")).append(course)
                    entry.remove(old)
                entry.append(new)

        # ordre du schéma
        children = list(entry)
        rank = lambda el: ENTRY_ORDER.index(el.tag.split("}")[1]) if el.tag.split("}")[1] in ENTRY_ORDER else 99
        for el in children:
            entry.remove(el)
        for el in sorted(children, key=rank):
            entry.append(el)
        report.converted += 1

    ET.indent(root)
    return tree, report




def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("xml", type=Path, help="export FFCO d'inscriptions (IOF XML 3.0)")
    p.add_argument("-o", "--output", type=Path, help="fichier XML (défaut : <nom>_meos.xml)")
    p.add_argument("--event-name", help="remplace Event/Name (facultatif)")
    p.add_argument("--event-id", help="remplace Event/Id (facultatif)")
    p.add_argument("--mode", choices=MODES, default="couleur",
                   help="couleur (défaut) : la classe reste celle de l'export ; categorie : la classe devient la "
                        "catégorie d'âge/sexe calculée (D14, H21...) et la classe d'origine (circuit) devient le parcours")
    p.add_argument("--category-in-name", action="store_true",
                   help="ajoute la catégorie d'âge au prénom (« Aurore (D40) »)")
    p.add_argument("--year", type=int, default=date.today().year,
                   help="année de l'événement : âge calculé au 31 décembre (défaut : année en cours)")
    p.add_argument("--class-ids", type=Path,
                   help="export FFCO d'inscriptions ou fichier de catégories FFCO (CSV « Nr catg. ») : identifiants des catégories")
    p.add_argument("--no-validate", action="store_true", help="ne pas valider contre IOF.xsd")
    args = p.parse_args(argv)

    class_ids = builtin_class_ids()
    if args.class_ids:
        loaded = load_class_ids(args.class_ids)
        class_ids = ({**class_ids[0], **loaded[0]}, {**class_ids[1], **loaded[1]})
    tree, report = convert_ffco(args.xml, args.event_name, args.event_id, class_ids, args.year,
                                args.mode, args.category_in_name)
    out = args.output or args.xml.with_name(args.xml.stem + "_meos.xml")
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
