# csv_to_iof : export HelloAsso → IOF XML 3.0 pour MeOS

Convertit l'export CSV des participants HelloAsso en `EntryList` IOF XML 3.0,
importable dans MeOS (Événement → Importer des inscriptions) et validé contre
le schéma officiel `IOF.xsd` (fourni ici, source : international-orienteering-federation/datastandard-v3).

L'export FFCO est déjà au format IOF : il n'a pas besoin de ce script. MeOS
accepte plusieurs imports successifs sans écrasement.

## Utilisation

```
python csv_to_iof.py export.csv --event-name "Absolu O MD 2026" -o inscriptions.xml
```

Python 3.9+ ; la conversion n'utilise que la bibliothèque standard. La validation
XSD (automatique) demande `pip install lxml` ; sans lxml elle est ignorée avec un message.
Options : `--event-id`, `--nationality` (défaut `FRA`), `--class-map classes.json`
(`{"Violet": "Violet Long"}` pour renommer un circuit en classe MeOS), `--classes "Violet Long;Violet Court;Jaune;Bleu;Vert;Initiation"` (normalise la casse et signale tout circuit inconnu), `--clubs clubs.xml` et `--class-ids export_ffco.xml` (voir ci-dessous), `--no-validate`.

## Colonnes HelloAsso utilisées

Les colonnes sont repérées par mots-clés dans l'en-tête (accents et casse ignorés), pas par position.

| Rôle | En-tête reconnu (contient) | XML produit |
| --- | --- | --- |
| Statut | « statut » + « commande » | seules les commandes « Validé » sont converties |
| Nom / Prénom | « nom participant » / « prénom participant » | `Person/Name/Family`, `Given` (obligatoires) |
| Circuit | « circuit » | `Class/Name` (catégorie) et `Class/RaceClass/Course/Name` (circuit, comme l'export FFCO) : texte avant la première parenthèse (« Bleu ( 2,5 km … ) » → « Bleu ») |
| Naissance | « naissance » (JJ/MM/AAAA) | `Person/BirthDate` |
| Sexe | « Femme/Homme » ou « sexe » | `Person/@sex` (F ou M) |
| Club | « club » | `Organisation` (Id, Name, ShortName, Country) ; club vide ou « Sans club » : aucun `Organisation` dans le XML |
| Puce | « puce » + « numéro » | `ControlCard` (`punchingSystem="SI"`), chiffres seulement |
| Prêt de puce | « prêt » + « puce » | uniquement pour détecter une incohérence |
| Téléphone (facultatif) | « téléphone », « portable » ou « mobile » | `Person/Contact type="MobilePhoneNumber"` |
| Licence (facultative) | « licence » | `Person/Id type="FFCO"` |

Le script affiche un rapport : lignes ignorées (commande non validée, nom manquant),
coureurs sans puce, dates ou sexes illisibles.

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
- les **catégories** (Bleu 200, Jaune 201, Vert 202, Violet Court 203, Violet Long 204) et les **circuits** de
  l'événement 107534 (41724 à 41728), constantes `BUILTIN_*` en tête du script.

`--clubs` et `--class-ids` complètent ou remplacent ces valeurs, `--no-builtin` les désactive. Les identifiants de
circuit sont probablement propres à l'événement : pour un autre événement, passe un export FFCO de cet événement
avec `--class-ids`. « Initiation » n'a pas d'identifiant connu.

## Identifiants de catégories et de circuits

MeOS crée une nouvelle catégorie si son identifiant diffère de celui de l'export FFCO. Avec
`--class-ids export_ffco.xml` (un export FFCO d'inscriptions contenant toutes tes catégories), le script
écrit `Class/Id` et `Class/RaceClass/Course/Id` repris de ce fichier, en rapprochant par nom. Le fichier de catégories FFCO (CSV `Nr catg.` / `Catg. Court`, ex. `categories39132.csv`) est aussi accepté : il
donne les identifiants de catégories (pas ceux des circuits). Une catégorie
absente du fichier est écrite sans identifiant et signalée. Mets donc dans l'export FFCO de référence au
moins un inscrit par catégorie.

## Tests

```
python -m unittest discover -s tests -v
```

Les tests de schéma sont ignorés si lxml est absent.

## Limites connues

- Pas d'identifiants de classe ni de club : MeOS rattache par nom (à confirmer par un import test).
- Une seule course, inscriptions individuelles (pas d'équipes ni de relais).
- Le sexe est lu tel que saisi dans le formulaire.
