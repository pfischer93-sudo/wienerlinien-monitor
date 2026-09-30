import json
import os
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

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

if not NTFY_TOPIC:
    raise RuntimeError("Das GitHub Secret NTFY_TOPIC wurde nicht gefunden.")


# ============================================================
# WIENER LINIEN ABFRAGEN
# ============================================================

def get_traffic_infos():

    params = [
        ("name", "stoerungkurz"),
        ("name", "stoerunglang")
    ]

    for line in sorted(LINES):
        params.append(("relatedLine", line))

    url = API_URL + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "WienerLinienMonitor/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    return data.get("data", {}).get("trafficInfos", [])


# ============================================================
# PUSH MIT NTFY
# ============================================================

def send_push(title, message):

    url = "https://ntfy.sh/" + urllib.parse.quote(NTFY_TOPIC, safe="")

    request = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": "high",
            "Tags": "rotating_light"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"ntfy Fehler: HTTP {response.status}")


# ============================================================
# MELDUNG AUFBEREITEN
# ============================================================

def get_lines(info):

    related_lines = info.get("relatedLines", [])

    return [
        line for line in related_lines
        if line in LINES
    ]


def create_message(info):

    lines = get_lines(info)

    line_text = ", ".join(lines) if lines else "Wiener Linien"

    title = info.get("title", "").strip()
    description = info.get("description", "").strip()

    message_parts = [
        f"Linie: {line_text}"
    ]

    if title:
        message_parts.append(title)

    if description:
        message_parts.append(description)

    return "\n".join(message_parts)


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    current_infos = get_traffic_infos()

    current = {}

    for info in current_infos:

        lines = get_lines(info)

        if not lines:
            continue

        name = info.get("name")

        if not name:
            continue

        # Die ID der Meldung + relevanter Inhalt.
        # Damit erkennen wir auch Änderungen.
        fingerprint_data = {
            "name": name,
            "title": info.get("title", ""),
            "description": info.get("description", ""),
            "relatedLines": sorted(lines),
            "time": info.get("time", {}),
            "attributes": info.get("attributes", {})
        }

        fingerprint = json.dumps(
            fingerprint_data,
            ensure_ascii=False,
            sort_keys=True
        )

        current[name] = {
            "fingerprint": fingerprint,
            "info": info
        }

    # --------------------------------------------------------
    # Alten Stand laden
    # --------------------------------------------------------

    if STATE_FILE.exists():

        try:
            old_state = json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            old_state = {}

    else:
        old_state = {}

    # --------------------------------------------------------
    # Neue / geänderte Meldungen finden
    # --------------------------------------------------------

    changes = []

    for name, item in current.items():

        if name not in old_state:

            changes.append(
                ("new", item["info"])
            )

        elif old_state[name].get("fingerprint") != item["fingerprint"]:

            changes.append(
                ("changed", item["info"])
            )

    # --------------------------------------------------------
    # Push senden
    # --------------------------------------------------------

    for change_type, info in changes:

        lines = get_lines(info)

        line_text = ", ".join(lines)

        if change_type == "new":

            push_title = f"🚨 Neue Störung – {line_text}"

        else:

            push_title = f"🔄 Störung geändert – {line_text}"

        push_message = create_message(info)

        print(push_title)
        print(push_message)
        print()

        send_push(
            push_title,
            push_message
        )

    # --------------------------------------------------------
    # Aktuellen Stand speichern
    # --------------------------------------------------------

    new_state = {
        name: {
            "fingerprint": item["fingerprint"]
        }
        for name, item in current.items()
    }

    STATE_FILE.write_text(
        json.dumps(
            new_state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"Aktive Meldungen: {len(current)} | "
        f"Neue/geänderte Meldungen: {len(changes)}"
    )


if __name__ == "__main__":
    main()
