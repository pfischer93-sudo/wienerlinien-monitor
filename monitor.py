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
# Verwendet wird "stoerunglang", da dieser Datensatz bereits
# Titel und vollständige Beschreibung der Störung enthält.
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

STATE_VERSION = 5

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
# LINIEN SORTIEREN
# ============================================================

def sort_lines(lines):

    return sorted(
        lines,
        key=lambda x: LINE_ORDER.get(x, 999)
    )


# ============================================================
# TEXT BEREINIGEN
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = str(text)

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

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
# API ABFRAGEN
# ============================================================

def get_traffic_infos():

    params = [
        ("name", "stoerunglang")
    ]

    for line in sorted(LINES):
        params.append(
            ("relatedLine", line)
        )

    url = (
        API_URL
        + "?"
        + urllib.parse.urlencode(params)
    )

    print(
        "API:",
        url
    )

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "WienerLinienMonitor/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        data = json.loads(
            response.read().decode("utf-8")
        )

    return (
        data
        .get("data", {})
        .get("trafficInfos", [])
    )


# ============================================================
# BETROFFENE LINIEN
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
# STÖRUNGS-ID
#
# Beispiel:
#
# I20261001-0046
#
# Diese ID bleibt für die konkrete Störung erhalten.
# ============================================================

def get_message_id(info):

    name = info.get(
        "name"
    )

    if name:

        return str(name)

    # Fallback, falls die API einmal keine ID liefert.

    return json.dumps(
        {
            "title": clean_text(
                info.get(
                    "title",
                    ""
                )
            ),
            "description": clean_text(
                info.get(
                    "description",
                    ""
                )
            ),
            "lines": get_lines(info)
        },
        ensure_ascii=False,
        sort_keys=True
    )


# ============================================================
# LAST UPDATE
#
# WICHTIG:
#
# Die API verwendet "lastUpdate" mit großem U.
# ============================================================

def get_last_update(info):

    time_data = info.get(
        "time",
        {}
    )

    return str(
        time_data.get(
            "lastUpdate",
            ""
        )
    )


# ============================================================
# MELDUNG AUFBEREITEN
# ============================================================

def create_message(info):

    return {
        "id": get_message_id(info),

        "title": clean_text(
            info.get(
                "title",
                ""
            )
        ),

        "description": clean_text(
            info.get(
                "description",
                ""
            )
        ),

        "lines": get_lines(info),

        "lastupdate": get_last_update(info),

        "status": str(
            info.get(
                "status",
                ""
            )
        ).lower()
    }


# ============================================================
# MELDUNGEN AUFBEREITEN
# ============================================================

def build_messages(infos):

    messages = {}

    for info in infos:

        # ----------------------------------------------------
        # Nur aktive Meldungen
        # ----------------------------------------------------

        status = str(
            info.get(
                "status",
                ""
            )
        ).lower()

        if status != "active":
            continue

        # ----------------------------------------------------
        # Nur überwachte Linien
        # ----------------------------------------------------

        lines = get_lines(
            info
        )

        if not lines:
            continue

        # ----------------------------------------------------
        # Meldung erstellen
        # ----------------------------------------------------

        message = create_message(
            info
        )

        message_id = message["id"]

        if message_id not in messages:

            messages[message_id] = message

        else:

            # Falls dieselbe ID mehrfach auftaucht,
            # die Linien zusammenführen.

            existing = messages[
                message_id
            ]

            existing["lines"] = sort_lines(
                list(
                    set(
                        existing["lines"]
                        + message["lines"]
                    )
                )
            )

            # Den Datensatz mit dem neuesten Update
            # übernehmen.

            if (
                message["lastupdate"]
                >
                existing["lastupdate"]
            ):

                message["lines"] = existing[
                    "lines"
                ]

                messages[
                    message_id
                ] = message

    return messages


# ============================================================
# FINGERPRINT
#
# Damit erkennen wir jede Änderung an:
#
# - Titel
# - Beschreibung
# - Linien
# - lastUpdate
# ============================================================

def get_fingerprint(message):

    data = {
        "title": message["title"],
        "description": message["description"],
        "lines": message["lines"],
        "lastupdate": message["lastupdate"]
    }

    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True
    )


# ============================================================
# STATE LADEN
# ============================================================

def load_state():

    if not STATE_FILE.exists():

        print(
            "Keine state.json vorhanden."
        )

        return {}, True

    try:

        state = json.loads(
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

    version = state.get(
        "version"
    )

    if version != STATE_VERSION:

        print(
            f"State-Version {version} gefunden."
        )

        print(
            f"Benötigt wird Version {STATE_VERSION}."
        )

        print(
            "Der aktuelle Bestand wird ohne Push "
            "übernommen."
        )

        return {}, True

    return (
        state.get(
            "messages",
            {}
        ),
        False
    )


# ============================================================
# STATE SPEICHERN
# ============================================================

def save_state(messages):

    state_messages = {}

    for message_id, message in messages.items():

        state_messages[message_id] = {
            "fingerprint": get_fingerprint(
                message
            ),
            "title": message["title"],
            "description": message["description"],
            "lines": message["lines"],
            "lastupdate": message["lastupdate"]
        }

    state = {
        "version": STATE_VERSION,
        "messages": state_messages
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
# PUSH AN NTFY
# ============================================================

def send_push(
    title,
    message,
    is_update
):

    if is_update:

        emoji = "🟡"
        priority = 4

    else:

        emoji = "🔴"
        priority = 5

    full_title = (
        f"{emoji} {title}"
    )

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

        if response.status not in (
            200,
            201
        ):

            raise RuntimeError(
                f"ntfy Fehler: HTTP {response.status}"
            )


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

    traffic_infos = get_traffic_infos()

    print(
        f"API liefert "
        f"{len(traffic_infos)} Meldungen."
    )

    # --------------------------------------------------------
    # MELDUNGEN AUFBEREITEN
    # --------------------------------------------------------

    current_messages = build_messages(
        traffic_infos
    )

    print(
        f"Aktive überwachte Meldungen: "
        f"{len(current_messages)}"
    )

    # --------------------------------------------------------
    # DEBUG:
    # ALLE GEFUNDENEN MELDUNGEN AUSGEBEN
    # --------------------------------------------------------

    for message in current_messages.values():

        print(
            f"[{message['id']}] "
            f"{message['title']} "
            f"| Linien: "
            f"{', '.join(message['lines'])} "
            f"| lastUpdate: "
            f"{message['lastupdate']}"
        )

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    old_messages, first_run = load_state()

    # --------------------------------------------------------
    # ÄNDERUNGEN
    # --------------------------------------------------------

    changes = []

    if first_run:

        print()
        print(
            "Erster Lauf dieser State-Version."
        )

        print(
            "Vorhandene Meldungen werden "
            "ohne Push gespeichert."
        )

    else:

        for message_id, message in current_messages.items():

            fingerprint = get_fingerprint(
                message
            )

            # ------------------------------------------------
            # NEU
            # ------------------------------------------------

            if message_id not in old_messages:

                changes.append(
                    {
                        "type": "new",
                        "message": message
                    }
                )

                continue

            # ------------------------------------------------
            # VERGLEICH
            # ------------------------------------------------

            old_message = old_messages[
                message_id
            ]

            old_fingerprint = old_message.get(
                "fingerprint",
                ""
            )

            # ------------------------------------------------
            # UPDATE
            # ------------------------------------------------

            if old_fingerprint != fingerprint:

                changes.append(
                    {
                        "type": "changed",
                        "message": message
                    }
                )

    # --------------------------------------------------------
    # AUSGABE
    # --------------------------------------------------------

    print()
    print(
        f"Neue/geänderte Meldungen: "
        f"{len(changes)}"
    )

    # --------------------------------------------------------
    # PUSH
    # --------------------------------------------------------

    for change in changes:

        message = change["message"]

        title = message["title"]

        description = message["description"]

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
            description
        )

        send_push(
            title,
            description,
            is_update
        )

    # --------------------------------------------------------
    # STATE SPEICHERN
    # --------------------------------------------------------

    save_state(
        current_messages
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
