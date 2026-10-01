import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

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

STATE_VERSION = 2

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

if not NTFY_TOPIC:
    raise RuntimeError("Das GitHub Secret NTFY_TOPIC wurde nicht gefunden.")


# ============================================================
# WIENER LINIEN ABFRAGEN
# ============================================================

def get_traffic_infos():

    params = [
        ("name", "stoerungkurz")
    ]

    for line in sorted(LINES):
        params.append(("relatedLine", line))

    url = API_URL + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "WienerLinienMonitor/2.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    return data.get("data", {}).get("trafficInfos", [])


# ============================================================
# LINIEN
# ============================================================

def get_lines(info):

    related_lines = info.get("relatedLines", [])

    result = []

    for line in related_lines:

        if line in LINES and line not in result:
            result.append(line)

    return result


def sort_lines(lines):

    order = {
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

    return sorted(lines, key=lambda x: order.get(x, 999))


# ============================================================
# TEXT BEREINIGEN
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = str(text)

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(r"[ \t]+", " ", text)

    text = re.sub(r"\n+", "\n", text)

    return text.strip()


# ============================================================
# LINIENNUMMER AUS TITEL ENTFERNEN
#
# Beispiele:
# "U1: Vandalismus" -> "Vandalismus"
# "25: Baustelle"   -> "Baustelle"
# ============================================================

def clean_title(title):

    title = clean_text(title)

    if not title:
        return "Wiener Linien"

    pattern = r"^(?:Linie\s+)?(?:U\d+|S\d+|R\d+|(?:\d+[A-Z]?))\s*:\s*"

    return re.sub(
        pattern,
        "",
        title,
        flags=re.IGNORECASE
    ).strip()


# ============================================================
# LINIENPRÄFIX AUS BESCHREIBUNG ENTFERNEN
#
# Wird nur für die Gruppierung verwendet.
# Die originale Beschreibung bleibt für die Push-Nachricht
# erhalten.
# ============================================================

def normalized_description(description):

    description = clean_text(description)

    description = re.sub(
        r"^Linie\s+(?:U\d+|S\d+|R\d+|\d+[A-Z]?)\s*:\s*",
        "",
        description,
        flags=re.IGNORECASE
    )

    return description.strip()


# ============================================================
# GRUPPENSCHLÜSSEL
#
# Wenn 25, 26 und 27 exakt dieselbe Störung melden,
# werden sie zu einer Push-Meldung zusammengefasst.
# ============================================================

def get_group_key(info):

    title = clean_title(info.get("title", ""))

    description = normalized_description(
        info.get("description", "")
    )

    return json.dumps(
        {
            "title": title,
            "description": description
        },
        ensure_ascii=False,
        sort_keys=True
    )


# ============================================================
# PUSH-NACHRICHT
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
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://ntfy.sh/",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:

        if response.status not in (200, 201):

            raise RuntimeError(
                f"ntfy Fehler: HTTP {response.status}"
            )


# ============================================================
# PUSH-TEXT ERSTELLEN
# ============================================================

def create_message(group):

    lines = sort_lines(
        group["lines"]
    )

    description = group["description"]

    if len(lines) == 1:

        prefix = f"Linie {lines[0]}:"

    else:

        prefix = f"Linien {', '.join(lines)}:"

    return f"{prefix} {description}"


# ============================================================
# MELDUNGSGRUPPEN ERSTELLEN
# ============================================================

def build_groups(infos):

    groups = {}

    for info in infos:

        lines = get_lines(info)

        if not lines:
            continue

        title = clean_title(
            info.get("title", "")
        )

        description = normalized_description(
            info.get("description", "")
        )

        if not title and not description:
            continue

        group_key = get_group_key(info)

        if group_key not in groups:

            groups[group_key] = {
                "title": title,
                "description": description,
                "lines": set(),
                "lastupdate": "",
                "source_names": []
            }

        group = groups[group_key]

        for line in lines:
            group["lines"].add(line)

        name = info.get("name")

        if name:
            group["source_names"].append(name)

        time_data = info.get("time", {})

        lastupdate = time_data.get(
            "lastupdate",
            ""
        )

        if lastupdate > group["lastupdate"]:

            group["lastupdate"] = lastupdate

    # Sets in normale Listen umwandeln
    for group in groups.values():

        group["lines"] = sort_lines(
            list(group["lines"])
        )

        group["source_names"] = sorted(
            set(group["source_names"])
        )

    return groups


# ============================================================
# FINGERPRINT FÜR GRUPPEN
# ============================================================

def get_group_fingerprint(group):

    data = {
        "title": group["title"],
        "description": group["description"],
        "lines": group["lines"],
        "lastupdate": group["lastupdate"]
    }

    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True
    )


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    print("Wiener Linien werden abgefragt...")

    # --------------------------------------------------------
    # Aktuelle Daten abrufen
    # --------------------------------------------------------

    traffic_infos = get_traffic_infos()

    print(
        f"API liefert {len(traffic_infos)} Meldungen."
    )

    # --------------------------------------------------------
    # Meldungen gruppieren
    # --------------------------------------------------------

    current_groups = build_groups(
        traffic_infos
    )

    print(
        f"Daraus entstehen {len(current_groups)} Meldungsgruppen."
    )

    # --------------------------------------------------------
    # Alten Stand laden
    # --------------------------------------------------------

    first_run = False

    if not STATE_FILE.exists():

        first_run = True
        old_state = {}

    else:

        try:

            stored_state = json.loads(
                STATE_FILE.read_text(
                    encoding="utf-8"
                )
            )

            if stored_state.get("version") != STATE_VERSION:

                print(
                    "Neue State-Version erkannt. "
                    "Aktuellen Stand ohne Push übernehmen."
                )

                first_run = True
                old_state = {}

            else:

                old_state = stored_state.get(
                    "groups",
                    {}
                )

        except Exception:

            print(
                "state.json konnte nicht gelesen werden. "
                "Aktuellen Stand ohne Push übernehmen."
            )

            first_run = True
            old_state = {}

    # --------------------------------------------------------
    # Neue / geänderte Meldungen
    # --------------------------------------------------------

    changes = []

    if first_run:

        print(
            "Erster Lauf dieser Version."
        )

        print(
            "Es werden keine Push-Nachrichten gesendet."
        )

    else:

        for group_key, group in current_groups.items():

            fingerprint = get_group_fingerprint(
                group
            )

            if group_key not in old_state:

                changes.append(
                    {
                        "type": "new",
                        "group": group
                    }
                )

            elif old_state[group_key].get(
                "fingerprint"
            ) != fingerprint:

                changes.append(
                    {
                        "type": "changed",
                        "group": group
                    }
                )

    # --------------------------------------------------------
    # Push-Nachrichten
    # --------------------------------------------------------

    print(
        f"Neue/geänderte Gruppen: {len(changes)}"
    )

    for change in changes:

        group = change["group"]

        if change["type"] == "new":

            title = (
                ", ".join(group["lines"])
                + ": "
                + group["title"]
            )

            is_update = False

        else:

            title = (
                ", ".join(group["lines"])
                + ": "
                + group["title"]
            )

            is_update = True

        message = create_message(
            group
        )

        print()
        print(
            "Push:",
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
    # Neuen Stand speichern
    # --------------------------------------------------------

    new_groups = {}

    for group_key, group in current_groups.items():

        new_groups[group_key] = {
            "fingerprint": get_group_fingerprint(
                group
            )
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

    print()
    print(
        "Aktueller Stand wurde gespeichert."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
