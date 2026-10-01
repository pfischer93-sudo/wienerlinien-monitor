import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


# ============================================================
# WIENER LINIEN MONITOR
#
# Datenquelle:
# Wiener Linien Open Data
# https://www.wienerlinien.at/ogd_realtime/
#
# Die Daten werden über die Open-Data-Schnittstelle
# der Wiener Linien abgerufen.
# ============================================================


# ============================================================
# EINSTELLUNGEN
# ============================================================

LINES = {
    "U1", "U3", "11", "25", "26", "27", "71",
    "16A", "17A", "19A", "26A", "26E", "27A",
    "S1", "S2", "S3", "S4", "S7", "S45", "S80", "R81"
}

API_URL = "https://www.wienerlinien.at/ogd_realtime/trafficInfoList"

STATE_FILE = Path("state.json")

STATE_VERSION = 3

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

if not NTFY_TOPIC:
    raise RuntimeError(
        "Das GitHub Secret NTFY_TOPIC wurde nicht gefunden."
    )


# ============================================================
# LINIENREIHENFOLGE
# ============================================================

LINE_ORDER = {
    "U1": 1,
    "U3": 2,
    "11": 10,
    "25": 20,
    "26": 21,
    "27": 22,
    "71": 30,
    "16A": 40,
    "17A": 41,
    "19A": 42,
    "26A": 43,
    "26E": 44,
    "27A": 45,
    "S1": 50,
    "S2": 51,
    "S3": 52,
    "S4": 53,
    "S7": 54,
    "S45": 55,
    "S80": 56,
    "R81": 57
}


# ============================================================
# WIENER LINIEN ABFRAGEN
# ============================================================

def get_traffic_infos(message_type):

    params = [
        ("name", message_type)
    ]

    for line in sorted(LINES):
        params.append(("relatedLine", line))

    url = API_URL + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "WienerLinienMonitor/3.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:

        data = json.loads(
            response.read().decode("utf-8")
        )

    infos = data.get(
        "data",
        {}
    ).get(
        "trafficInfos",
        []
    )

    # Wir speichern mit ab, aus welchem API-Filter
    # die Meldung stammt.
    for info in infos:

        info["_message_type"] = message_type

    return infos


# ============================================================
# ALLE MELDUNGEN ABRUFEN
# ============================================================

def get_all_traffic_infos():

    short_infos = get_traffic_infos(
        "stoerungkurz"
    )

    long_infos = get_traffic_infos(
        "stoerunglang"
    )

    print(
        f"stoerungkurz: {len(short_infos)} Meldungen"
    )

    print(
        f"stoerunglang: {len(long_infos)} Meldungen"
    )

    return short_infos, long_infos


# ============================================================
# LINIEN AUS EINER MELDUNG
# ============================================================

def get_lines(info):

    related_lines = info.get(
        "relatedLines",
        []
    )

    result = []

    for line in related_lines:

        if line in LINES and line not in result:
            result.append(line)

    return sort_lines(result)


# ============================================================
# LINIEN SORTIEREN
# ============================================================

def sort_lines(lines):

    return sorted(
        lines,
        key=lambda x: LINE_ORDER.get(
            x,
            999
        )
    )


# ============================================================
# TEXT BEREINIGEN
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = str(text)

    text = text.replace(
        "\r\n",
        "\n"
    )

    text = text.replace(
        "\r",
        "\n"
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n+",
        "\n",
        text
    )

    return text.strip()


# ============================================================
# LINIENNUMMER AUS TITEL ENTFERNEN
#
# Beispiele:
#
# "U1: Vandalismus"
#     ->
# "Vandalismus"
#
# "11, 71: Verkehrsunfall"
#     ->
# "Verkehrsunfall"
# ============================================================

def clean_title(title):

    title = clean_text(title)

    if not title:
        return "Wiener Linien"

    title = re.sub(
        r"^(?:Linien?\s+)?"
        r"(?:(?:U\d+|S\d+|R\d+|\d+[A-Z]?)"
        r"(?:\s*,\s*(?:U\d+|S\d+|R\d+|\d+[A-Z]?))*)"
        r"\s*:\s*",
        "",
        title,
        flags=re.IGNORECASE
    )

    return title.strip()


# ============================================================
# BESCHREIBUNG FÜR VERGLEICHE NORMALISIEREN
# ============================================================

def normalize_for_compare(text):

    text = clean_text(text)

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# LINIENPRÄFIX AUS BESCHREIBUNG ENTFERNEN
#
# Wird für Vergleiche verwendet.
# Der originale Text bleibt unverändert.
# ============================================================

def normalized_description(description):

    description = clean_text(
        description
    )

    description = re.sub(
        r"^Linie\s+"
        r"(?:U\d+|S\d+|R\d+|\d+[A-Z]?)"
        r"\s*:\s*",
        "",
        description,
        flags=re.IGNORECASE
    )

    return description.strip()


# ============================================================
# WORTMENGE FÜR ÄHNLICHKEITSVERGLEICH
# ============================================================

def get_words(text):

    text = normalize_for_compare(
        text
    )

    words = re.findall(
        r"[a-z0-9äöüß]+",
        text
    )

    # Sehr allgemeine Wörter ignorieren.
    ignored = {
        "linie",
        "linien",
        "in",
        "der",
        "die",
        "das",
        "zu",
        "und",
        "von",
        "im",
        "am",
        "auf",
        "es",
        "ist",
        "ein",
        "eine",
        "einer",
        "einem",
        "einen",
        "kommt",
        "nach",
        "wegen"
    }

    return {
        word
        for word in words
        if word not in ignored
    }


# ============================================================
# ZEITSTEMPEL
# ============================================================

def get_lastupdate(info):

    time_data = info.get(
        "time",
        {}
    )

    return str(
        time_data.get(
            "lastupdate",
            ""
        )
    )


# ============================================================
# STABILE QUELL-ID
# ============================================================

def get_source_name(info):

    name = info.get(
        "name"
    )

    if name:
        return str(name)

    # Falls die API einmal keine name-ID liefert,
    # erzeugen wir eine Ersatz-ID.
    return json.dumps(
        {
            "title": clean_title(
                info.get("title", "")
            ),
            "lines": get_lines(info),
            "description": normalized_description(
                info.get("description", "")
            )
        },
        ensure_ascii=False,
        sort_keys=True
    )


# ============================================================
# ÄHNLICHKEIT ZWISCHEN KURZ- UND LANGMELDUNG
# ============================================================

def calculate_match_score(short_info, long_info):

    short_lines = set(
        get_lines(short_info)
    )

    long_lines = set(
        get_lines(long_info)
    )

    if not short_lines or not long_lines:
        return 0

    common_lines = (
        short_lines.intersection(
            long_lines
        )
    )

    if not common_lines:
        return 0

    score = 0

    # --------------------------------------------------------
    # Gleiche Linien sind das wichtigste Kriterium.
    # --------------------------------------------------------

    score += len(common_lines) * 50

    # --------------------------------------------------------
    # Gleicher name = sehr starke Zuordnung.
    # --------------------------------------------------------

    short_name = short_info.get(
        "name"
    )

    long_name = long_info.get(
        "name"
    )

    if short_name and long_name and short_name == long_name:

        score += 500

    # --------------------------------------------------------
    # Titel vergleichen.
    # --------------------------------------------------------

    short_title = clean_title(
        short_info.get("title", "")
    )

    long_title = clean_title(
        long_info.get("title", "")
    )

    short_title_normalized = normalize_for_compare(
        short_title
    )

    long_title_normalized = normalize_for_compare(
        long_title
    )

    if (
        short_title_normalized
        and long_title_normalized
        and short_title_normalized == long_title_normalized
    ):

        score += 150

    else:

        short_words = get_words(
            short_title
        )

        long_words = get_words(
            long_title
        )

        common_words = short_words.intersection(
            long_words
        )

        score += len(common_words) * 20

    # --------------------------------------------------------
    # Beschreibung vergleichen.
    # --------------------------------------------------------

    short_description = normalized_description(
        short_info.get(
            "description",
            ""
        )
    )

    long_description = normalized_description(
        long_info.get(
            "description",
            ""
        )
    )

    short_words = get_words(
        short_description
    )

    long_words = get_words(
        long_description
    )

    common_words = short_words.intersection(
        long_words
    )

    score += len(common_words) * 3

    return score


# ============================================================
# LANGMELDUNG ZU KURZMELDUNG FINDEN
# ============================================================

def find_long_description(short_info, long_infos):

    best_info = None
    best_score = 0

    for long_info in long_infos:

        score = calculate_match_score(
            short_info,
            long_info
        )

        if score > best_score:

            best_score = score
            best_info = long_info

    # Eine Zuordnung muss zumindest gemeinsame Linien
    # besitzen. Dadurch verhindern wir komplett falsche
    # Zuordnungen.
    if best_score < 50:

        return ""

    if best_info is None:

        return ""

    description = clean_text(
        best_info.get(
            "description",
            ""
        )
    )

    return description


# ============================================================
# STÖRUNGSGRUPPE AUS KURZMELDUNG ERSTELLEN
# ============================================================

def create_group(short_info, long_infos):

    lines = get_lines(
        short_info
    )

    title = clean_title(
        short_info.get(
            "title",
            ""
        )
    )

    short_description = clean_text(
        short_info.get(
            "description",
            ""
        )
    )

    long_description = find_long_description(
        short_info,
        long_infos
    )

    if not long_description:

        long_description = short_description

    source_name = get_source_name(
        short_info
    )

    lastupdate = get_lastupdate(
        short_info
    )

    # Falls die Langmeldung einen neueren
    # Änderungszeitpunkt besitzt, verwenden wir diesen.
    for long_info in long_infos:

        if not set(lines).intersection(
            set(get_lines(long_info))
        ):
            continue

        score = calculate_match_score(
            short_info,
            long_info
        )

        if score >= 50:

            long_lastupdate = get_lastupdate(
                long_info
            )

            if long_lastupdate > lastupdate:

                lastupdate = long_lastupdate

    return {
        "title": title,
        "short_description": short_description,
        "long_description": long_description,
        "lines": lines,
        "source_names": [source_name],
        "lastupdate": lastupdate
    }


# ============================================================
# GLEICHE KURZMELDUNGEN GRUPPIEREN
#
# Beispiel:
#
# 25: Baustelle
# 26: Baustelle
# 27: Baustelle
#
# wird zu einer Meldung:
#
# 25, 26, 27: Baustelle
# ============================================================

def build_groups(short_infos, long_infos):

    groups = {}

    for short_info in short_infos:

        lines = get_lines(
            short_info
        )

        if not lines:
            continue

        title = clean_title(
            short_info.get(
                "title",
                ""
            )
        )

        description = normalized_description(
            short_info.get(
                "description",
                ""
            )
        )

        if not title and not description:
            continue

        # ----------------------------------------------------
        # Gruppenschlüssel:
        #
        # Nicht die Linien verwenden!
        #
        # Dadurch können 25, 26 und 27 mit demselben
        # Inhalt zusammengefasst werden.
        # ----------------------------------------------------

        group_key = json.dumps(
            {
                "title": normalize_for_compare(
                    title
                ),
                "description": normalize_for_compare(
                    description
                )
            },
            ensure_ascii=False,
            sort_keys=True
        )

        if group_key not in groups:

            groups[group_key] = create_group(
                short_info,
                long_infos
            )

        else:

            group = groups[group_key]

            # Weitere Linien hinzufügen.
            for line in lines:

                if line not in group["lines"]:

                    group["lines"].append(
                        line
                    )

            # Weitere Quell-ID hinzufügen.
            source_name = get_source_name(
                short_info
            )

            if source_name not in group["source_names"]:

                group["source_names"].append(
                    source_name
                )

            # Neueren Änderungszeitpunkt übernehmen.
            lastupdate = get_lastupdate(
                short_info
            )

            if lastupdate > group["lastupdate"]:

                group["lastupdate"] = lastupdate

    # --------------------------------------------------------
    # Linien sortieren
    # --------------------------------------------------------

    for group in groups.values():

        group["lines"] = sort_lines(
            group["lines"]
        )

        group["source_names"] = sorted(
            set(group["source_names"])
        )

    return groups


# ============================================================
# STABILER GRUPPEN-SCHLÜSSEL
#
# Dieser Schlüssel darf sich bei einer Textänderung NICHT
# verändern.
#
# Genau dadurch erkennen wir:
#
# alt -> geändert
#
# und nicht:
#
# alt -> gelöscht
# neu -> neue Meldung
# ============================================================

def get_stable_group_key(group):

    data = {
        "title": normalize_for_compare(
            group["title"]
        ),
        "lines": group["lines"]
    }

    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True
    )


# ============================================================
# FINGERPRINT
#
# Der Fingerprint enthält den kompletten aktuellen Inhalt.
# Wenn sich der Text oder lastupdate ändert, wird die Meldung
# als geändert erkannt.
# ============================================================

def get_group_fingerprint(group):

    data = {
        "title": group["title"],
        "short_description": group["short_description"],
        "long_description": group["long_description"],
        "lines": group["lines"],
        "lastupdate": group["lastupdate"]
    }

    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True
    )


# ============================================================
# PUSH AN NTFY
# ============================================================

def send_push(title, message, is_update):

    if is_update:

        emoji = "🟡"
        priority = 4

    else:

        emoji = "❗"
        priority = 5

    full_title = f"{emoji} {title}"

    payload = {
        "topic": NTFY_TOPIC,
        "title": full_title,
        "message": message,
        "priority": priority
    }

    body = json.dumps(
        payload,
        ensure_ascii=False
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        "https://ntfy.sh/",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        if response.status not in (200, 201):

            raise RuntimeError(
                f"ntfy Fehler: HTTP {response.status}"
            )


# ============================================================
# PUSH-TITEL
# ============================================================

def create_push_title(group):

    lines = group["lines"]

    if len(lines) == 1:

        line_text = lines[0]

    else:

        line_text = ", ".join(
            lines
        )

    return (
        f"{line_text}: "
        f"{group['title']}"
    )


# ============================================================
# PUSH-TEXT
#
# WICHTIG:
#
# Hier wird jetzt NICHT mehr künstlich
# "Linien 11, 71:" davor geschrieben.
#
# Wir verwenden den ausführlichen Text der
# Wiener Linien unverändert.
# ============================================================

def create_message(group):

    return group["long_description"]


# ============================================================
# ALTEN STATE LADEN
# ============================================================

def load_state():

    if not STATE_FILE.exists():

        print(
            "Keine state.json vorhanden."
        )

        return {}, True

    try:

        stored_state = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception as ex:

        print(
            "state.json konnte nicht gelesen werden:"
        )

        print(
            str(ex)
        )

        return {}, True

    version = stored_state.get(
        "version"
    )

    if version != STATE_VERSION:

        print(
            f"State-Version {version} "
            f"gefunden. Benötigt wird {STATE_VERSION}."
        )

        print(
            "Aktueller Stand wird ohne Push übernommen."
        )

        return {}, True

    return (
        stored_state.get(
            "groups",
            {}
        ),
        False
    )


# ============================================================
# STATE SPEICHERN
# ============================================================

def save_state(groups):

    new_groups = {}

    for stable_key, group in groups.items():

        new_groups[stable_key] = {
            "fingerprint": get_group_fingerprint(
                group
            ),
            "title": group["title"],
            "lines": group["lines"],
            "source_names": group["source_names"],
            "lastupdate": group["lastupdate"]
        }

    state = {
        "version": STATE_VERSION,
        "groups": new_groups
    }

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# ÄNDERUNG SUCHEN
#
# Zusätzlich zum stabilen Gruppenschlüssel prüfen wir
# die source_names.
#
# Dadurch können kleinere Änderungen bei der Zuordnung
# weiterhin als Update erkannt werden.
# ============================================================

def find_old_group(
    current_group,
    stable_key,
    old_groups
):

    # --------------------------------------------------------
    # 1. Exakter stabiler Schlüssel
    # --------------------------------------------------------

    if stable_key in old_groups:

        return stable_key, old_groups[stable_key]

    # --------------------------------------------------------
    # 2. Gleiche Quell-ID
    # --------------------------------------------------------

    current_sources = set(
        current_group.get(
            "source_names",
            []
        )
    )

    if current_sources:

        for old_key, old_group in old_groups.items():

            old_sources = set(
                old_group.get(
                    "source_names",
                    []
                )
            )

            if current_sources.intersection(
                old_sources
            ):

                return old_key, old_group

    # --------------------------------------------------------
    # 3. Gleiche Linien + ähnlicher Titel
    # --------------------------------------------------------

    current_lines = set(
        current_group["lines"]
    )

    current_title = normalize_for_compare(
        current_group["title"]
    )

    best_key = None
    best_group = None
    best_score = 0

    for old_key, old_group in old_groups.items():

        old_lines = set(
            old_group.get(
                "lines",
                []
            )
        )

        common_lines = current_lines.intersection(
            old_lines
        )

        if not common_lines:
            continue

        old_title = normalize_for_compare(
            old_group.get(
                "title",
                ""
            )
        )

        score = len(common_lines) * 50

        if current_title == old_title:

            score += 100

        else:

            current_words = get_words(
                current_title
            )

            old_words = get_words(
                old_title
            )

            score += len(
                current_words.intersection(
                    old_words
                )
            ) * 20

        if score > best_score:

            best_score = score
            best_key = old_key
            best_group = old_group

    if best_score >= 50:

        return best_key, best_group

    return None, None


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    print()
    print(
        "=========================================="
    )
    print(
        "Wiener Linien Monitor"
    )
    print(
        "=========================================="
    )
    print()

    # --------------------------------------------------------
    # API
    # --------------------------------------------------------

    print(
        "Wiener Linien werden abgefragt..."
    )

    short_infos, long_infos = get_all_traffic_infos()

    # --------------------------------------------------------
    # Gruppen
    # --------------------------------------------------------

    current_groups_raw = build_groups(
        short_infos,
        long_infos
    )

    print(
        f"Es wurden "
        f"{len(current_groups_raw)} Meldungsgruppen "
        f"erstellt."
    )

    # --------------------------------------------------------
    # Stable Keys erzeugen
    # --------------------------------------------------------

    current_groups = {}

    for group in current_groups_raw.values():

        stable_key = get_stable_group_key(
            group
        )

        # Falls zwei Gruppen denselben stabilen Schlüssel
        # bekommen, werden sie zusammengeführt.
        if stable_key not in current_groups:

            current_groups[stable_key] = group

        else:

            existing = current_groups[
                stable_key
            ]

            for line in group["lines"]:

                if line not in existing["lines"]:

                    existing["lines"].append(
                        line
                    )

            for source_name in group["source_names"]:

                if source_name not in existing["source_names"]:

                    existing["source_names"].append(
                        source_name
                    )

            existing["lines"] = sort_lines(
                existing["lines"]
            )

            existing["source_names"] = sorted(
                set(existing["source_names"])
            )

            if group["lastupdate"] > existing["lastupdate"]:

                existing["lastupdate"] = group["lastupdate"]

    # --------------------------------------------------------
    # Alten State laden
    # --------------------------------------------------------

    old_groups, first_run = load_state()

    # --------------------------------------------------------
    # Änderungen
    # --------------------------------------------------------

    changes = []

    if first_run:

        print()
        print(
            "Erster Lauf dieser State-Version."
        )

        print(
            "Es werden keine Push-Nachrichten "
            "für den vorhandenen Bestand gesendet."
        )

    else:

        for stable_key, current_group in current_groups.items():

            current_fingerprint = get_group_fingerprint(
                current_group
            )

            old_key, old_group = find_old_group(
                current_group,
                stable_key,
                old_groups
            )

            # ------------------------------------------------
            # Neue Meldung
            # ------------------------------------------------

            if old_group is None:

                changes.append(
                    {
                        "type": "new",
                        "group": current_group
                    }
                )

                continue

            # ------------------------------------------------
            # Änderung
            # ------------------------------------------------

            old_fingerprint = old_group.get(
                "fingerprint",
                ""
            )

            if old_fingerprint != current_fingerprint:

                changes.append(
                    {
                        "type": "changed",
                        "group": current_group
                    }
                )

    # --------------------------------------------------------
    # Änderungen ausgeben
    # --------------------------------------------------------

    print()
    print(
        f"Neue/geänderte Meldungen: {len(changes)}"
    )

    # --------------------------------------------------------
    # Push senden
    # --------------------------------------------------------

    for change in changes:

        group = change["group"]

        title = create_push_title(
            group
        )

        message = create_message(
            group
        )

        is_update = (
            change["type"] == "changed"
        )

        if is_update:

            print()
            print(
                "🟡 UPDATE:"
            )

        else:

            print()
            print(
                "🔴 NEU:"
            )

        print(
            title
        )

        print(
            message
        )

        send_push(
            title,
            message,
            is_update
        )

    # --------------------------------------------------------
    # State speichern
    # --------------------------------------------------------

    save_state(
        current_groups
    )

    print()
    print(
        "Aktueller Stand wurde gespeichert."
    )

    print()
    print(
        "Fertig."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
