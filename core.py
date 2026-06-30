"""
core.py – Datenhaltung (PostgreSQL) und Zuordnungslogik (Scoring).

Verbindung wird aus st.secrets["db_url"] gelesen (lokal: .streamlit/secrets.toml,
in der Cloud: über die Secrets-Oberfläche von Streamlit).

Trennt die Geschäftslogik sauber von der Oberfläche (app.py).
"""

from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.extras
import streamlit as st


def _db_url():
    # In der Cloud und lokal identisch: aus den Streamlit-Secrets.
    return st.secrets["db_url"]


# --------------------------------------------------------------------------
# Datenbank-Setup
# --------------------------------------------------------------------------

@contextmanager
def get_conn():
    conn = psycopg2.connect(_db_url())
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_cursor():
    """Cursor, der Zeilen als dict-artige Objekte liefert."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
        finally:
            cur.close()


def init_db():
    """Legt alle Tabellen an, falls sie noch nicht existieren."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS mitarbeiter (
                id              SERIAL PRIMARY KEY,
                name            TEXT NOT NULL,
                wochenstunden   REAL NOT NULL DEFAULT 40
            );

            CREATE TABLE IF NOT EXISTS skills (
                id    SERIAL PRIMARY KEY,
                name  TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS mitarbeiter_skills (
                mitarbeiter_id  INTEGER NOT NULL REFERENCES mitarbeiter(id) ON DELETE CASCADE,
                skill_id        INTEGER NOT NULL REFERENCES skills(id)       ON DELETE CASCADE,
                level           INTEGER NOT NULL DEFAULT 3,
                PRIMARY KEY (mitarbeiter_id, skill_id)
            );

            CREATE TABLE IF NOT EXISTS auftraege (
                id              SERIAL PRIMARY KEY,
                titel           TEXT NOT NULL,
                stunden         REAL NOT NULL,
                status          TEXT NOT NULL DEFAULT 'offen',
                mitarbeiter_id  INTEGER REFERENCES mitarbeiter(id) ON DELETE SET NULL,
                erstellt_am     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auftrag_skills (
                auftrag_id   INTEGER NOT NULL REFERENCES auftraege(id) ON DELETE CASCADE,
                skill_id     INTEGER NOT NULL REFERENCES skills(id)    ON DELETE CASCADE,
                min_level    INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (auftrag_id, skill_id)
            );
            """
        )
        conn.commit()
        cur.close()


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------

def skill_anlegen(name):
    name = name.strip()
    if not name:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO skills (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
        conn.commit()
        cur.close()


def skills_liste():
    with get_cursor() as cur:
        cur.execute("SELECT * FROM skills ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Mitarbeiter
# --------------------------------------------------------------------------

def mitarbeiter_anlegen(name, wochenstunden, skill_level_map):
    """skill_level_map: dict {skill_id: level}"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mitarbeiter (name, wochenstunden) VALUES (%s, %s) RETURNING id",
            (name.strip(), float(wochenstunden)),
        )
        mid = cur.fetchone()[0]
        for skill_id, level in skill_level_map.items():
            cur.execute(
                "INSERT INTO mitarbeiter_skills (mitarbeiter_id, skill_id, level) "
                "VALUES (%s, %s, %s)",
                (mid, skill_id, int(level)),
            )
        conn.commit()
        cur.close()
        return mid


def mitarbeiter_loeschen(mid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM mitarbeiter WHERE id = %s", (mid,))
        conn.commit()
        cur.close()


def mitarbeiter_liste():
    with get_cursor() as cur:
        cur.execute("SELECT * FROM mitarbeiter ORDER BY name")
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            cur.execute(
                "SELECT s.id, s.name, ms.level "
                "FROM mitarbeiter_skills ms "
                "JOIN skills s ON s.id = ms.skill_id "
                "WHERE ms.mitarbeiter_id = %s ORDER BY s.name",
                (r["id"],),
            )
            r["skills"] = [dict(s) for s in cur.fetchall()]
            cur.execute(
                "SELECT COALESCE(SUM(stunden), 0) AS s FROM auftraege "
                "WHERE mitarbeiter_id = %s AND status = 'zugewiesen'",
                (r["id"],),
            )
            r["verplant"] = cur.fetchone()["s"]
            r["frei"] = r["wochenstunden"] - r["verplant"]
        return rows


# --------------------------------------------------------------------------
# Auftraege
# --------------------------------------------------------------------------

def auftrag_anlegen(titel, stunden, skill_minlevel_map):
    """skill_minlevel_map: dict {skill_id: min_level}"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auftraege (titel, stunden, status, erstellt_am) "
            "VALUES (%s, %s, 'offen', %s) RETURNING id",
            (titel.strip(), float(stunden), datetime.now().isoformat(timespec="seconds")),
        )
        aid = cur.fetchone()[0]
        for skill_id, min_level in skill_minlevel_map.items():
            cur.execute(
                "INSERT INTO auftrag_skills (auftrag_id, skill_id, min_level) "
                "VALUES (%s, %s, %s)",
                (aid, skill_id, int(min_level)),
            )
        conn.commit()
        cur.close()
        return aid


def auftrag_zuweisen(aid, mid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE auftraege SET mitarbeiter_id = %s, status = 'zugewiesen' WHERE id = %s",
            (mid, aid),
        )
        conn.commit()
        cur.close()


def auftrag_freigeben(aid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE auftraege SET mitarbeiter_id = NULL, status = 'offen' WHERE id = %s",
            (aid,),
        )
        conn.commit()
        cur.close()


def auftrag_loeschen(aid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM auftraege WHERE id = %s", (aid,))
        conn.commit()
        cur.close()


def auftraege_liste(status=None):
    with get_cursor() as cur:
        if status:
            cur.execute(
                "SELECT * FROM auftraege WHERE status = %s ORDER BY erstellt_am DESC",
                (status,),
            )
        else:
            cur.execute("SELECT * FROM auftraege ORDER BY erstellt_am DESC")
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            cur.execute(
                "SELECT s.id, s.name, a.min_level "
                "FROM auftrag_skills a JOIN skills s ON s.id = a.skill_id "
                "WHERE a.auftrag_id = %s ORDER BY s.name",
                (r["id"],),
            )
            r["skills"] = [dict(s) for s in cur.fetchall()]
            if r["mitarbeiter_id"]:
                cur.execute(
                    "SELECT name FROM mitarbeiter WHERE id = %s", (r["mitarbeiter_id"],)
                )
                m = cur.fetchone()
                r["mitarbeiter_name"] = m["name"] if m else "—"
            else:
                r["mitarbeiter_name"] = None
        return rows


# --------------------------------------------------------------------------
# Zuordnungslogik (Scoring)
# --------------------------------------------------------------------------

# Gewichte – bestimmen, wie stark die einzelnen Faktoren ins Ranking eingehen.
GEWICHT_SKILL = 0.5        # Wie gut passen die Faehigkeiten?
GEWICHT_KAPAZITAET = 0.3   # Bleibt nach dem Auftrag noch Luft?
GEWICHT_AUSGLEICH = 0.2    # Werden gering ausgelastete bevorzugt?


def vorschlaege(auftrag_id, top_n=5):
    """
    Liefert eine sortierte Liste von Vorschlaegen fuer einen Auftrag.

    Jeder Eintrag enthaelt den Mitarbeiter, einen Score (0..1) und eine
    nachvollziehbare Begruendung der Teil-Scores.
    """
    auftraege = {a["id"]: a for a in auftraege_liste()}
    auftrag = auftraege.get(auftrag_id)
    if not auftrag:
        return []

    benoetigt = {s["id"]: s["min_level"] for s in auftrag["skills"]}
    aufwand = auftrag["stunden"]

    kandidaten = []
    for m in mitarbeiter_liste():
        skill_map = {s["id"]: s["level"] for s in m["skills"]}

        erfuellt = all(
            skill_map.get(sid, 0) >= minlvl for sid, minlvl in benoetigt.items()
        )
        if not erfuellt:
            continue

        if m["frei"] < aufwand:
            continue

        if benoetigt:
            reserven = []
            for sid, minlvl in benoetigt.items():
                spielraum = (skill_map[sid] - minlvl) / 4.0
                reserven.append(max(0.0, min(1.0, spielraum)))
            score_skill = sum(reserven) / len(reserven)
        else:
            score_skill = 1.0

        if m["wochenstunden"] > 0:
            rest_nach = (m["frei"] - aufwand) / m["wochenstunden"]
            score_kapazitaet = max(0.0, min(1.0, rest_nach))
        else:
            score_kapazitaet = 0.0

        if m["wochenstunden"] > 0:
            auslastung = m["verplant"] / m["wochenstunden"]
            score_ausgleich = max(0.0, min(1.0, 1.0 - auslastung))
        else:
            score_ausgleich = 0.0

        score = (
            GEWICHT_SKILL * score_skill
            + GEWICHT_KAPAZITAET * score_kapazitaet
            + GEWICHT_AUSGLEICH * score_ausgleich
        )

        kandidaten.append(
            {
                "mitarbeiter": m,
                "score": round(score, 3),
                "begruendung": {
                    "Skill-Passung": round(score_skill, 2),
                    "Kapazität": round(score_kapazitaet, 2),
                    "Auslastungsausgleich": round(score_ausgleich, 2),
                },
                "frei_nach": round(m["frei"] - aufwand, 1),
            }
        )

    kandidaten.sort(key=lambda k: k["score"], reverse=True)
    return kandidaten[:top_n]
