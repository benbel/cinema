# Configuration data for build_page.py

CINEMAS_BY_CODE = {
    "C0026": "bercy",
    "C0144": "nation",
    "C2954": "bibliothèque",
    "C0020": "filmothèque",
    "C0040": "bastille",
    "C0139": "majestic"
}

DAYS_BY_INDEX = {
    0: "Lundi",
    1: "Mardi",
    2: "Mercredi",
    3: "Jeudi",
    4: "Vendredi",
    5: "Samedi",
    6: "Dimanche"
}

# INDEX_BY_DAY can be derived from DAYS_BY_INDEX in the main script
# or defined here if preferred for strict separation.
# For now, let's keep its derivation in the main script
# to show an example of derived configuration.
# If needed, it can be moved here:
# INDEX_BY_DAY = {day: index for index, day in DAYS_BY_INDEX.items()}
