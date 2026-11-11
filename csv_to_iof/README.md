# csv_to_iof_meos : export HelloAsso → IOF XML 3.0 pour MeOS

Convertit l'export CSV des participants HelloAsso en `EntryList` IOF XML 3.0,
importable dans MeOS (Événement → Importer des inscriptions) et validé contre
le schéma officiel `IOF.xsd` (fourni ici, source : international-orienteering-federation/datastandard-v3).

L'export FFCO est déjà au format IOF : il n'a pas besoin de ce script. MeOS
accepte plusieurs imports successifs sans écrasement.

## Deux modes : `--mode couleur` (défaut) ou `--mode categorie`

- **`couleur`** (défaut) : la **classe MeOS est le circuit** (« Violet Long », « Bleu »…), comme dans l'export FFCO d'un
  événement à circuits de couleur. Seul le champ « Circuit » du formulaire HelloAsso compte, ni sexe ni date de
  naissance ne sont nécessaires.
- **`categorie`** : la **classe MeOS est la catégorie d'âge et de sexe**, calculée par le script d'après le sexe et
  l'âge au 31 décembre de l'année de l'événement (`--year`) : D/H 10 (≤ 10 ans), 12 (11-12), 14, 16, 18, 20 (19-20),
  21 (21-34), 35 (35-39), 40, 45, 50, 55, 60, 65, 70, 75 (75-79), 80 (≥ 80). Le **circuit**, choix libre du coureur
  quel que soit son âge, devient le parcours (`Class/RaceClass/Course`). Il faut alors la date de naissance et le
  sexe dans le formulaire HelloAsso ; sans l'un des deux, le coureur n'a pas de classe et est signalé.

## Préparer l'export correctement (à faire avant le premier usage)

MeOS rapproche les catégories et les circuits par leur identifiant FFCO. Pour que ces identifiants soient exacts :

1. Sur le site FFCO, prépare une inscription de test avec **au moins un licencié sur chacun des circuits** de
   l'événement (y compris « Initiation » s'il existe) et, en mode `categorie`, **dans chacune des catégories d'âge
   et de sexe** (D10 à D80, H10 à H80), puis exporte-la au format IOF XML 3.0 (fichier `inscriptions<N>.xml`). Le fichier de catégories FFCO
   (CSV `Nr catg.` / `Catg. Court`) donne aussi les identifiants de catégories.
2. Passe ce fichier au script : `--class-ids inscriptions<N>.xml`. Il en reprend les identifiants de catégories et de
   circuits de l'événement, qui complètent ou remplacent ceux intégrés au script.
3. Les noms de circuit du formulaire HelloAsso doivent être identiques à ceux de l'export FFCO
   (ex. « Violet Long », « Violet Court », « Jaune », « Bleu », « Vert »), et les catégories s'appeler « D14 »,
   « H21 », etc., comme dans l'export FFCO.

Une catégorie ou un circuit absent de cet export est écrit sans identifiant : MeOS créera alors une nouvelle
catégorie ou un nouveau circuit.

## Utilisation

```
python csv_to_iof_meos.py export.csv --event-name "Absolu O MD 2026" --class-ids inscriptions<N>.xml -o inscriptions.xml
python csv_to_iof_meos.py export.csv --event-name "Absolu O MD 2026" --mode categorie --year 2026 \
    --class-ids inscriptions<N>.xml -o inscriptions.xml
```

Python 3.9+ ; la conversion n'utilise que la bibliothèque standard. La validation
XSD (automatique) demande `pip install lxml` ; sans lxml elle est ignorée avec un message.
Options : `--category-in-name` (ajoute la catégorie d'âge au prénom, « Aurore (D40) » : elle apparaît dans toutes les listes MeOS, ex. un classement par circuit ; calculée avec `--year` d'après la naissance et le sexe), `--mode` (`couleur` par défaut, ou `categorie`), `--year` (année de l'événement pour l'âge en mode `categorie`, défaut : année en cours), `--event-id`,
`--nationality` (défaut `FRA`), `--class-map circuits.json` (`{"Violet": "Violet Long"}` pour renommer un circuit),
`--classes "Violet Long;Violet Court;Jaune;Bleu;Vert;Initiation"` (liste des circuits : normalise la casse et signale
tout circuit inconnu), `--clubs clubs.xml` et `--class-ids export_ffco.xml` (voir ci-dessous), `--no-builtin`,
`--no-validate`.

## Export FFCO : `ffco_to_iof_meos.py`

Un second script retraite l'export FFCO d'inscriptions (IOF XML) avec les mêmes options de classe et de nom :

```
python ffco_to_iof_meos.py inscriptions39133.xml --category-in-name --year 2026
python ffco_to_iof_meos.py inscriptions39133.xml --mode categorie --year 2026 --class-ids inscriptions39133.xml
```

Il écrit `<nom>_meos.xml` (option `-o`), qui est validé contre `IOF.xsd` :
- remet les éléments de chaque inscription dans l'ordre du schéma (l'export FFCO brut n'y est pas conforme),
  et ajoute `punchingSystem="SI"` à la puce ;
- `--category-in-name` : ajoute la catégorie d'âge au prénom, « Aurore (D40) » ;
- `--mode couleur` (défaut) : la classe reste celle de l'export (le circuit) ;
  `--mode categorie` : la classe devient la catégorie D/H calculée (identifiants via `--class-ids`) et la classe
  d'origine devient le parcours ;
- `--event-name`, `--event-id` remplacent le nom et l'identifiant de l'événement (facultatif).

Il réutilise les fonctions de `csv_to_iof_meos.py` : garde les deux fichiers dans le même dossier.

## Colonnes HelloAsso utilisées

Les colonnes sont repérées par mots-clés dans l'en-tête (accents et casse ignorés), pas par position.

| Rôle | En-tête reconnu (contient) | XML produit |
| --- | --- | --- |
| Statut | « statut » + « commande » | seules les commandes « Validé » sont converties |
| Nom / Prénom | « nom participant » / « prénom participant » | `Person/Name/Family`, `Given` (obligatoires) |
| Naissance + sexe | « naissance » (JJ/MM/AAAA) ; « Femme/Homme » ou « sexe » | `Person/BirthDate`, `Person/@sex` (F ou M) ; en mode `categorie`, la catégorie `Class/Name` (D14, H21...) calculée. Sans l'un des deux : pas de classe, signalé |
| Circuit | « circuit » | mode `couleur` : `Class/Name` ; mode `categorie` : `Class/RaceClass/Course/Name`. Texte avant la première parenthèse (« Bleu ( 2,5 km … ) » → « Bleu ») |
| Club | « club » | `Organisation` (Id, Name, ShortName, Country) ; club vide ou « Sans club » : aucun `Organisation` dans le XML |
| Puce | « puce » + « numéro » | `ControlCard` (`punchingSystem="SI"`), chiffres seulement |
| Prêt de puce | « prêt » + « puce » | uniquement pour détecter une incohérence |
| Téléphone (facultatif) | « téléphone », « portable » ou « mobile » | `Person/Contact type="MobilePhoneNumber"` |
| Licence (facultative) | « licence » | `Person/Id type="FFCO"` |

Le script affiche un rapport : lignes ignorées (commande non validée, nom manquant),
coureurs sans puce, catégories sans identifiant, dates ou sexes illisibles.

## Clubs : fournir la liste officielle

MeOS ne reprend pas un club qu'il ne reconnaît pas dans sa base. Avec `--clubs liste.xml`, le script
retrouve chaque club par son nom (casse et accents ignorés, fautes légères tolérées, avec avertissement)
et écrit son identifiant FFCO, son sigle et son pays, comme l'export FFCO. Le fichier peut être une
`OrganisationList` IOF XML 3.0 (ex. export de la base de clubs de MeOS) ou un export FFCO d'inscriptions
(on y lit les clubs présents). Les clubs absents de la liste sont écrits par nom et signalés dans le rapport.

## Correspondances FFCO intégrées

Sans option, le script utilise :
- la **liste officielle des clubs FFCO** (`ffco_clubs.xml`, état au 11/11/2026, à remplacer par une version plus
  récente si besoin) : le club saisi dans HelloAsso est retrouvé par son nom ou son sigle (casse, accents et
  ponctuation ignorés ; faute légère ou nom abrégé unique tolérés avec avertissement) et reçoit son identifiant
  FFCO, son nom officiel, son sigle et son pays. Les noms partagés par plusieurs clubs (« INDIVIDUEL », un par
  département) sont ambigus et ne sont pas rapprochés. Deux alias relevés dans les exports FFCO (« ABSOLU RAID »,
  « CENT VALLEES ORIENTATION 12 ») complètent la liste ;
- les **circuits couleur** de l'événement 107534 : classes (Bleu 200, Jaune 201, Vert 202, Violet Court 203,
  Violet Long 204) et parcours (41724 à 41728), constantes `BUILTIN_*` en tête du script. Aucun identifiant de
  catégorie d'âge n'est intégré : il vient de `--class-ids`.

`--clubs` et `--class-ids` complètent ou remplacent ces valeurs, `--no-builtin` les désactive. Les identifiants de
circuit sont probablement propres à l'événement : pour un autre événement, passe un export FFCO de cet événement
avec `--class-ids`.

## Identifiants de catégories et de circuits

MeOS crée une nouvelle catégorie si son identifiant diffère de celui de l'export FFCO. Avec
`--class-ids`, le script écrit `Class/Id` (catégorie) et `Class/RaceClass/Course/Id` (circuit) repris d'un export FFCO
d'inscriptions, en rapprochant par nom. Le fichier de catégories FFCO (CSV `Nr catg.` / `Catg. Court`, ex.
`categories39132.csv`) est aussi accepté : il donne les identifiants de catégories (pas ceux des circuits). Une
catégorie absente du fichier est écrite sans identifiant et listée une fois dans le rapport.

## Tests

```
python -m unittest discover -s tests -v
```

Les tests de schéma sont ignorés si lxml est absent.

## Limites connues

- Pas de surclassement en mode `categorie` : la catégorie est toujours celle de l'âge et du sexe.
- Sans `--class-ids`, les catégories sont écrites sans identifiant : MeOS rattache par nom (à confirmer par un import test).
- Une seule course, inscriptions individuelles (pas d'équipes ni de relais).
- Le sexe est lu tel que saisi dans le formulaire (« Femme » / « Homme »).
