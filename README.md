# Disponent – Auftragsplaner mit Skill-Matching (Online-Version)

Aufträge anlegen, geschätzte Stunden erfassen, passenden Mitarbeiter
**vorschlagen** lassen und per Klick bestätigen. Diese Version läuft online und
ist von jedem Rechner aus erreichbar – mit gemeinsamem Team-Passwort und
dauerhafter Datenbank.

---

## Überblick: drei kostenlose Bausteine

1. **GitHub** – hier liegt dein Code.
2. **Neon** – die PostgreSQL-Datenbank (speichert deine Daten dauerhaft).
3. **Streamlit Community Cloud** – führt die App aus und gibt dir eine feste URL.

Die Reihenfolge unten ist so gewählt, dass du jeden Wert genau einmal kopierst.

---

## Schritt 1 – Datenbank bei Neon anlegen

1. Auf https://neon.tech mit E-Mail oder GitHub registrieren.
2. **Create project** klicken, Namen vergeben (z. B. „mitarbeiter-tool“), Region
   in der Nähe wählen (z. B. Frankfurt/Europe), bestätigen.
3. Nach dem Anlegen zeigt Neon einen **Connection string** an. Der sieht so aus:
   `postgresql://benutzer:passwort@ep-xyz.eu-central-1.aws.neon.tech/neondb?sslmode=require`
4. **Diese komplette Zeile kopieren** und für Schritt 4 bereithalten.

> Die Tabellen musst du nicht selbst anlegen – die App erstellt sie beim ersten
> Start automatisch.

---

## Schritt 2 – Code zu GitHub bringen

1. Auf https://github.com einen kostenlosen Account anlegen.
2. Oben rechts **+ → New repository**.
3. Name z. B. `mitarbeiter-tool`, Sichtbarkeit auf **Private** stellen,
   **Create repository**.
4. Auf der nächsten Seite **„uploading an existing file“** anklicken und diese
   Dateien per Drag & Drop hochladen:
   - `app.py`
   - `core.py`
   - `requirements.txt`
   - den Ordner `.streamlit` **nur mit `config.toml`** darin
   - `.gitignore`

   **Nicht hochladen:** `secrets.toml` (enthält Passwörter – die trägst du
   später direkt in Streamlit ein). Die `.gitignore` verhindert das ohnehin.
5. Unten **Commit changes** klicken.

---

## Schritt 3 – Auf Streamlit Cloud deployen

1. Auf https://share.streamlit.io mit deinem GitHub-Account anmelden.
2. **Create app → Deploy a public app from GitHub** (auch private Repos gehen).
3. Repository `mitarbeiter-tool` wählen, Branch `main`, Main file `app.py`.
4. Noch **nicht** auf Deploy klicken – erst die Secrets eintragen (Schritt 4).

---

## Schritt 4 – Secrets eintragen (Passwörter & Datenbank)

Im Deploy-Dialog auf **Advanced settings → Secrets**. Dort dieses Format
eintragen (Werte durch deine eigenen ersetzen):

```toml
db_url = "DEIN_NEON_CONNECTION_STRING_AUS_SCHRITT_1"
app_passwort = "EIN_GUTES_TEAM_PASSWORT"
```

Beispiel:

```toml
db_url = "postgresql://benutzer:passwort@ep-xyz.eu-central-1.aws.neon.tech/neondb?sslmode=require"
app_passwort = "Werkstatt2025!"
```

Speichern, dann **Deploy** klicken. Nach ein bis zwei Minuten ist die App unter
einer Adresse wie `mitarbeiter-tool.streamlit.app` erreichbar.

---

## Schritt 5 – Team einladen

Gib deinen Kollegen einfach die `…streamlit.app`-URL **und** das
`app_passwort`. Mehr brauchen sie nicht – kein Account, keine Installation.

Passwort ändern: in Streamlit Cloud unter **Manage app → Settings → Secrets**
den Wert anpassen und speichern.

---

## Lokal testen (optional)

Wenn du vorher auf deinem Rechner testen willst:

1. `pip install -r requirements.txt`
2. Im Ordner `.streamlit` die Datei `secrets.toml.beispiel` zu `secrets.toml`
   kopieren und echte Werte eintragen (du kannst denselben Neon-String nutzen).
3. `streamlit run app.py`

Die `secrets.toml` bleibt dank `.gitignore` lokal und wird nie hochgeladen.

---

## Erste Schritte in der App

1. Mit dem Team-Passwort anmelden.
2. **Fähigkeiten** anlegen (z. B. Schweißen, CAD, Buchhaltung).
3. **Mitarbeiter** anlegen, Fähigkeiten + Level (1–5) und Wochenstunden setzen.
4. **Aufträge** anlegen mit Stundenschätzung und benötigten Fähigkeiten.
5. Im Tab **Disposition** Vorschläge ansehen und mit „Zuweisen“ bestätigen.

---

## Wie der Vorschlag entsteht

Zuerst hartes Filtern: nur wer **alle** geforderten Fähigkeiten mindestens auf
dem geforderten Level hat **und** genug freie Stunden übrig hat, erscheint.

Die übrigen Kandidaten werden gewichtet sortiert:

| Faktor | Gewicht | Bedeutung |
|---|---|---|
| Skill-Passung | 50 % | Wie weit liegt das Können über dem Mindest-Level? |
| Kapazität | 30 % | Wie viel Luft bleibt nach dem Auftrag? |
| Auslastungsausgleich | 20 % | Wenig ausgelastete Personen bevorzugen |

Die Gewichte stehen oben in `core.py` (`GEWICHT_SKILL` usw.).

---

## Dateien

- `app.py` – Oberfläche (Streamlit) inkl. Passwort-Gate
- `core.py` – Datenbank (PostgreSQL) + Zuordnungslogik
- `requirements.txt` – Abhängigkeiten
- `.streamlit/config.toml` – erzwingt das helle Theme (gute Lesbarkeit)
- `.streamlit/secrets.toml.beispiel` – Vorlage für die Geheimnisse
- `.gitignore` – schützt Passwörter und lokale Dateien vor dem Hochladen

---

## Hinweis zu Datenschutz

Es werden Mitarbeiterdaten verarbeitet. Das gemeinsame Passwort schützt vor
zufälligem Zugriff, ist aber kein vollwertiges Rechtesystem. Für sensiblere
Daten oder größere Teams lässt sich später ein echter Login (z. B. `st.login`
mit Google/Microsoft) ergänzen.

## Mögliche Erweiterungen

- Tages-/Wochenkalender statt nur Wochenstunden-Summe
- Mehrere Aufträge gleichzeitig optimal verteilen → Google OR-Tools
- Optionale (statt Pflicht-) Skills, Prioritäten, Deadlines
- Export nach Excel/CSV
- Echter Login pro Person statt gemeinsamem Passwort
