"""
core.py – Datenhaltung (PostgreSQL) und Logik für den Auftragsplaner.

Datenmodell:
  gruppen            – Mitarbeitergruppen (Konstruktion, Produktion, ...)
  vorgangstypen      – Typen von Vorgängen, je an eine Gruppe gekoppelt
  mitarbeiter        – inkl. gruppe und effektivitaet (%)
  skills             – Fähigkeiten
  mitarbeiter_skills – Skill-Level je Mitarbeiter
  auftraege          – auftragsnummer, kunde, liefertermin, kommentar
  vorgaenge          – mehrere pro Auftrag: typ, start/ende, stunden, zuweisung
  vorgang_skills     – benötigte Fähigkeiten je Vorgang
"""

from contextlib import contextmanager
from datetime import date, timedelta

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st

try:
    import holidays as _holidays_lib
except ImportError:  # Bibliothek fehlt -> Kalender funktioniert ohne Feiertage
    _holidays_lib = None


def _db_url():
    return st.secrets["db_url"]


# --------------------------------------------------------------------------
# Verbindungs-Pool (offen halten statt bei jedem Klick neu verbinden)
# --------------------------------------------------------------------------

@st.cache_resource
def _pool():
    return psycopg2.pool.SimpleConnectionPool(1, 5, dsn=_db_url())


@contextmanager
def get_conn():
    pool = _pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor():
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
        finally:
            cur.close()


# --------------------------------------------------------------------------
# Request-lokaler Cache
#
# Innerhalb EINES Streamlit-Skriptdurchlaufs (also eines Klicks) werden viele
# Funktionen mehrfach mit denselben Daten aufgerufen – z. B. mitarbeiter_liste()
# in jeder Vorschlagsberechnung. Dieser Cache hält solche Ergebnisse für die
# Dauer eines Durchlaufs vor und wird zu dessen Beginn geleert (cache_reset()
# in app.py), sodass jeder Klick garantiert frische Daten aus der DB sieht.
# --------------------------------------------------------------------------

_request_cache = {}


def cache_reset():
    """Zu Beginn jedes Streamlit-Durchlaufs aufrufen (leert den Request-Cache)."""
    _request_cache.clear()


def _cached(key, producer):
    if key not in _request_cache:
        _request_cache[key] = producer()
    return _request_cache[key]


# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gruppen (
                id    SERIAL PRIMARY KEY,
                name  TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS vorgangstypen (
                id        SERIAL PRIMARY KEY,
                name      TEXT NOT NULL UNIQUE,
                gruppe_id INTEGER REFERENCES gruppen(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS skills (
                id    SERIAL PRIMARY KEY,
                name  TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS mitarbeiter (
                id              SERIAL PRIMARY KEY,
                name            TEXT NOT NULL,
                wochenstunden   REAL NOT NULL DEFAULT 40,
                effektivitaet   REAL NOT NULL DEFAULT 100,  -- Prozent
                gruppe_id       INTEGER REFERENCES gruppen(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS mitarbeiter_skills (
                mitarbeiter_id  INTEGER NOT NULL REFERENCES mitarbeiter(id) ON DELETE CASCADE,
                skill_id        INTEGER NOT NULL REFERENCES skills(id)       ON DELETE CASCADE,
                level           INTEGER NOT NULL DEFAULT 3,
                PRIMARY KEY (mitarbeiter_id, skill_id)
            );

            CREATE TABLE IF NOT EXISTS auftraege (
                id              SERIAL PRIMARY KEY,
                auftragsnummer  TEXT,
                titel           TEXT NOT NULL,
                kunde           TEXT,
                liefertermin    DATE,
                kommentar       TEXT,
                prioritaet      TEXT NOT NULL DEFAULT 'Normal',  -- Hoch | Normal | Niedrig
                erstellt_am     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vorgaenge (
                id              SERIAL PRIMARY KEY,
                auftrag_id      INTEGER NOT NULL REFERENCES auftraege(id) ON DELETE CASCADE,
                typ_id          INTEGER REFERENCES vorgangstypen(id) ON DELETE SET NULL,
                stunden         REAL NOT NULL DEFAULT 0,
                anteil_prozent  REAL NOT NULL DEFAULT 100,  -- Richtwert: max. % der Tageskapazität
                start_datum     DATE,
                end_datum       DATE,
                mitarbeiter_id  INTEGER REFERENCES mitarbeiter(id) ON DELETE SET NULL,
                status          TEXT NOT NULL DEFAULT 'offen'
            );

            CREATE TABLE IF NOT EXISTS vorgang_skills (
                vorgang_id   INTEGER NOT NULL REFERENCES vorgaenge(id) ON DELETE CASCADE,
                skill_id     INTEGER NOT NULL REFERENCES skills(id)    ON DELETE CASCADE,
                min_level    INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (vorgang_id, skill_id)
            );

            -- Tagesgenaue Brutto-Arbeitszeit (Ausnahme vom Standard Wochenstunden/5).
            -- Wird jetzt nur noch für MEHRARBEIT/Überstunden genutzt.
            -- Effektivität wird auf diesen Wert noch angewandt.
            CREATE TABLE IF NOT EXISTS tagesarbeitszeit (
                mitarbeiter_id  INTEGER NOT NULL REFERENCES mitarbeiter(id) ON DELETE CASCADE,
                datum           DATE NOT NULL,
                brutto_stunden  REAL NOT NULL,
                PRIMARY KEY (mitarbeiter_id, datum)
            );

            -- Abwesenheitskategorien (Urlaub, Krank, ...), erweiterbar.
            CREATE TABLE IF NOT EXISTS abwesenheitskategorien (
                id    SERIAL PRIMARY KEY,
                name  TEXT NOT NULL UNIQUE
            );

            -- Abwesenheiten: reduzieren die verfügbare Brutto-Zeit eines Tages.
            CREATE TABLE IF NOT EXISTS abwesenheiten (
                id              SERIAL PRIMARY KEY,
                mitarbeiter_id  INTEGER NOT NULL REFERENCES mitarbeiter(id) ON DELETE CASCADE,
                datum           DATE NOT NULL,
                stunden         REAL NOT NULL,
                kategorie_id    INTEGER REFERENCES abwesenheitskategorien(id) ON DELETE SET NULL
            );
            """
        )
        # Migrationen für bereits bestehende Datenbanken (Spalten nachrüsten)
        cur.execute(
            "ALTER TABLE vorgaenge ADD COLUMN IF NOT EXISTS anteil_prozent REAL NOT NULL DEFAULT 100"
        )
        cur.execute(
            "ALTER TABLE auftraege ADD COLUMN IF NOT EXISTS prioritaet TEXT NOT NULL DEFAULT 'Normal'"
        )
        conn.commit()
        cur.close()
    _vorbelegung()


def _vorbelegung():
    """Legt Standard-Gruppen, -Vorgangstypen und Abwesenheitskategorien an."""
    # Abwesenheitskategorien (unabhängig von den Gruppen vorbelegen)
    if not abwesenheitskategorien_liste():
        for k in ["Urlaub", "Gleitzeit", "Berufsschule", "Krank", "Kurzarbeit"]:
            abwesenheitskategorie_anlegen(k)
    if gruppen_liste():
        return
    for g in ["Konstruktion", "Produktion"]:
        gruppe_anlegen(g)
    gmap = {g["name"]: g["id"] for g in gruppen_liste()}
    vorgangstyp_anlegen("Konstruktion", gmap.get("Konstruktion"))
    vorgangstyp_anlegen("Produktion", gmap.get("Produktion"))


# --------------------------------------------------------------------------
# Gruppen
# --------------------------------------------------------------------------

def gruppe_anlegen(name):
    name = name.strip()
    if not name:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO gruppen (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
        conn.commit()
        cur.close()


def gruppe_loeschen(gid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM gruppen WHERE id = %s", (gid,))
        conn.commit()
        cur.close()


def gruppen_liste():
    with get_cursor() as cur:
        cur.execute("SELECT * FROM gruppen ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Vorgangstypen
# --------------------------------------------------------------------------

def vorgangstyp_anlegen(name, gruppe_id):
    name = name.strip()
    if not name:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO vorgangstypen (name, gruppe_id) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET gruppe_id = EXCLUDED.gruppe_id",
            (name, gruppe_id),
        )
        conn.commit()
        cur.close()


def vorgangstyp_loeschen(tid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vorgangstypen WHERE id = %s", (tid,))
        conn.commit()
        cur.close()


def vorgangstypen_liste():
    with get_cursor() as cur:
        cur.execute(
            "SELECT t.*, g.name AS gruppe_name "
            "FROM vorgangstypen t LEFT JOIN gruppen g ON g.id = t.gruppe_id "
            "ORDER BY t.name"
        )
        return [dict(r) for r in cur.fetchall()]


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

def mitarbeiter_anlegen(name, wochenstunden, effektivitaet, gruppe_id, skill_level_map):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mitarbeiter (name, wochenstunden, effektivitaet, gruppe_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (name.strip(), float(wochenstunden), float(effektivitaet), gruppe_id),
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


def mitarbeiter_aktualisieren(mid, name, wochenstunden, effektivitaet, gruppe_id, skill_level_map):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE mitarbeiter SET name=%s, wochenstunden=%s, effektivitaet=%s, gruppe_id=%s "
            "WHERE id=%s",
            (name.strip(), float(wochenstunden), float(effektivitaet), gruppe_id, mid),
        )
        cur.execute("DELETE FROM mitarbeiter_skills WHERE mitarbeiter_id = %s", (mid,))
        for skill_id, level in skill_level_map.items():
            cur.execute(
                "INSERT INTO mitarbeiter_skills (mitarbeiter_id, skill_id, level) "
                "VALUES (%s, %s, %s)",
                (mid, skill_id, int(level)),
            )
        conn.commit()
        cur.close()


def mitarbeiter_loeschen(mid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM mitarbeiter WHERE id = %s", (mid,))
        conn.commit()
        cur.close()


def mitarbeiter_liste():
    return _cached("mitarbeiter_liste", _mitarbeiter_liste_impl)


def _mitarbeiter_liste_impl():
    with get_cursor() as cur:
        cur.execute(
            "SELECT m.*, g.name AS gruppe_name "
            "FROM mitarbeiter m LEFT JOIN gruppen g ON g.id = m.gruppe_id "
            "ORDER BY m.name"
        )
        rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            return rows

        # Skills für ALLE Mitarbeiter in einer Abfrage (statt einer pro Person)
        cur.execute(
            "SELECT ms.mitarbeiter_id, s.id, s.name, ms.level "
            "FROM mitarbeiter_skills ms JOIN skills s ON s.id = ms.skill_id "
            "ORDER BY s.name"
        )
        skills_by_ma = {}
        for s in cur.fetchall():
            skills_by_ma.setdefault(s["mitarbeiter_id"], []).append(
                {"id": s["id"], "name": s["name"], "level": s["level"]}
            )

        # Verplante Stunden für ALLE Mitarbeiter in einer Abfrage
        cur.execute(
            "SELECT mitarbeiter_id, COALESCE(SUM(stunden),0) AS s "
            "FROM vorgaenge WHERE status = 'zugewiesen' AND mitarbeiter_id IS NOT NULL "
            "GROUP BY mitarbeiter_id"
        )
        verplant_by_ma = {r["mitarbeiter_id"]: r["s"] for r in cur.fetchall()}

        for r in rows:
            r["skills"] = skills_by_ma.get(r["id"], [])
            r["verplant"] = verplant_by_ma.get(r["id"], 0)
            r["tageskapazitaet"] = r["wochenstunden"] / 5.0 * (r["effektivitaet"] / 100.0)
        return rows


# --------------------------------------------------------------------------
# Tagesgenaue Arbeitszeit (Ausnahmen vom Standard)
# --------------------------------------------------------------------------

def tagesarbeitszeit_setzen(mitarbeiter_id, datum, brutto_stunden):
    """Legt eine Ausnahme an oder überschreibt sie (Brutto-Stunden für den Tag)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tagesarbeitszeit (mitarbeiter_id, datum, brutto_stunden) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (mitarbeiter_id, datum) "
            "DO UPDATE SET brutto_stunden = EXCLUDED.brutto_stunden",
            (mitarbeiter_id, datum, float(brutto_stunden)),
        )
        conn.commit()
        cur.close()


def tagesarbeitszeit_loeschen(mitarbeiter_id, datum):
    """Entfernt die Ausnahme -> der Standard gilt wieder."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM tagesarbeitszeit WHERE mitarbeiter_id = %s AND datum = %s",
            (mitarbeiter_id, datum),
        )
        conn.commit()
        cur.close()


def tagesarbeitszeit_liste(mitarbeiter_id):
    """Alle Ausnahmen eines Mitarbeiters, nach Datum sortiert."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT datum, brutto_stunden FROM tagesarbeitszeit "
            "WHERE mitarbeiter_id = %s ORDER BY datum",
            (mitarbeiter_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Abwesenheitskategorien
# --------------------------------------------------------------------------

def abwesenheitskategorie_anlegen(name):
    name = name.strip()
    if not name:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO abwesenheitskategorien (name) VALUES (%s) "
            "ON CONFLICT (name) DO NOTHING",
            (name,),
        )
        conn.commit()
        cur.close()


def abwesenheitskategorie_loeschen(kid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM abwesenheitskategorien WHERE id = %s", (kid,))
        conn.commit()
        cur.close()


def abwesenheitskategorien_liste():
    with get_cursor() as cur:
        cur.execute("SELECT * FROM abwesenheitskategorien ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Abwesenheiten
# --------------------------------------------------------------------------

def abwesenheit_setzen(mitarbeiter_id, datum, stunden, kategorie_id):
    """
    Setzt/aktualisiert die Abwesenheit eines Mitarbeiters an einem Tag für eine
    Kategorie. Mehrere Kategorien am selben Tag sind möglich (z. B. halb Urlaub,
    halb Berufsschule). stunden <= 0 entfernt den Eintrag.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        # Bestehenden Eintrag für (Mitarbeiter, Tag, Kategorie) ersetzen
        cur.execute(
            "DELETE FROM abwesenheiten WHERE mitarbeiter_id = %s AND datum = %s "
            "AND kategorie_id IS NOT DISTINCT FROM %s",
            (mitarbeiter_id, datum, kategorie_id),
        )
        if stunden and stunden > 0:
            cur.execute(
                "INSERT INTO abwesenheiten (mitarbeiter_id, datum, stunden, kategorie_id) "
                "VALUES (%s, %s, %s, %s)",
                (mitarbeiter_id, datum, float(stunden), kategorie_id),
            )
        conn.commit()
        cur.close()


def abwesenheit_loeschen(abw_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM abwesenheiten WHERE id = %s", (abw_id,))
        conn.commit()
        cur.close()


def abwesenheiten_liste(mitarbeiter_id=None):
    """Abwesenheiten (optional gefiltert nach Mitarbeiter), mit Kategoriename."""
    with get_cursor() as cur:
        if mitarbeiter_id is not None:
            cur.execute(
                "SELECT a.*, k.name AS kategorie_name, m.name AS mitarbeiter_name "
                "FROM abwesenheiten a "
                "LEFT JOIN abwesenheitskategorien k ON k.id = a.kategorie_id "
                "JOIN mitarbeiter m ON m.id = a.mitarbeiter_id "
                "WHERE a.mitarbeiter_id = %s ORDER BY a.datum",
                (mitarbeiter_id,),
            )
        else:
            cur.execute(
                "SELECT a.*, k.name AS kategorie_name, m.name AS mitarbeiter_name "
                "FROM abwesenheiten a "
                "LEFT JOIN abwesenheitskategorien k ON k.id = a.kategorie_id "
                "JOIN mitarbeiter m ON m.id = a.mitarbeiter_id "
                "ORDER BY a.datum"
            )
        return [dict(r) for r in cur.fetchall()]


def _abwesenheit_alle_mitarbeiter():
    """{mitarbeiter_id: {datum: summe_stunden}} aller Abwesenheiten in einer Abfrage."""
    return _cached("abw_alle", _abwesenheit_alle_impl)


def _abwesenheit_alle_impl():
    with get_cursor() as cur:
        cur.execute("SELECT mitarbeiter_id, datum, stunden FROM abwesenheiten")
        result = {}
        for r in cur.fetchall():
            tag = result.setdefault(r["mitarbeiter_id"], {})
            tag[r["datum"]] = tag.get(r["datum"], 0.0) + r["stunden"]
        return result


def _ausnahmen_map(mitarbeiter_id):
    """{datum: brutto_stunden} der Ausnahmen (Mehrarbeit) eines Mitarbeiters."""
    return {r["datum"]: r["brutto_stunden"] for r in tagesarbeitszeit_liste(mitarbeiter_id)}


def _abwesenheit_map(mitarbeiter_id):
    """{datum: summe_stunden} der Abwesenheiten eines Mitarbeiters."""
    result = {}
    for r in abwesenheiten_liste(mitarbeiter_id):
        result[r["datum"]] = result.get(r["datum"], 0.0) + r["stunden"]
    return result


def effektive_tageskapazitaet(mitarbeiter, datum, ausnahmen=None, abwesenheiten=None):
    """
    Effektive (auftragsbezogene) Kapazität eines Mitarbeiters an einem Tag.

    Brutto verfügbar = (Mehrarbeits-Ausnahme oder Standard Wochenstunden/5)
                       minus Summe der Abwesenheiten an dem Tag (nie unter 0).
    Auf diesen Brutto-Wert wird die Effektivität angewandt.
    """
    if ausnahmen is None:
        ausnahmen = _ausnahmen_map(mitarbeiter["id"])
    if abwesenheiten is None:
        abwesenheiten = _abwesenheit_map(mitarbeiter["id"])

    if datum in ausnahmen:
        brutto = ausnahmen[datum]
    else:
        brutto = mitarbeiter["wochenstunden"] / 5.0

    brutto = max(0.0, brutto - abwesenheiten.get(datum, 0.0))
    return brutto * (mitarbeiter["effektivitaet"] / 100.0)


def verteile_stunden(mitarbeiter, tage, gesamt_stunden, ausnahmen=None,
                     anteil_prozent=100, abwesenheiten=None):
    """
    Verteilt 'gesamt_stunden' auf die Arbeitstage PROPORTIONAL zur effektiven
    Tageskapazität. Ein Tag mit doppelter Kapazität (z. B. Überstunden) bekommt
    doppelt so viele Stunden wie ein normaler Tag.

    'anteil_prozent' ist ein Richtwert und deckelt, wie viel des Tages für DIESEN
    Vorgang genutzt wird: pro Tag höchstens anteil_prozent% der Tageskapazität.
    Passen dadurch nicht alle Stunden in den Zeitraum, werden die restlichen
    Stunden auf den letzten Tag gelegt – die Überbuchungswarnung macht das dann
    sichtbar (der Anteil ist bewusst kein harter Zwang).

    Abwesenheiten reduzieren die Tageskapazität (fließen über
    effektive_tageskapazitaet ein). Fällt die Gesamtkapazität auf 0, wird
    gleichmäßig verteilt, damit keine Stunden verloren gehen.

    Rückgabe: {datum: stunden}
    """
    if not tage:
        return {}
    if ausnahmen is None:
        ausnahmen = _ausnahmen_map(mitarbeiter["id"])
    if abwesenheiten is None:
        abwesenheiten = _abwesenheit_map(mitarbeiter["id"])

    anteil = max(0.0, min(1.0, anteil_prozent / 100.0)) if anteil_prozent else 1.0
    kapazitaeten = {
        d: effektive_tageskapazitaet(mitarbeiter, d, ausnahmen, abwesenheiten) for d in tage
    }
    summe = sum(kapazitaeten.values())

    if summe <= 0:
        gleich = gesamt_stunden / len(tage)
        return {d: gleich for d in tage}

    # Proportional verteilen, aber pro Tag auf anteil% der Kapazität deckeln.
    verteilung = {}
    rest = gesamt_stunden
    for d in tage:
        soll = gesamt_stunden * (kapazitaeten[d] / summe)
        deckel = kapazitaeten[d] * anteil
        wert = min(soll, deckel)
        verteilung[d] = wert
        rest -= wert

    # Wenn durch den Deckel Stunden übrig sind: dem letzten Tag zuschlagen,
    # damit die Gesamtstunden erhalten bleiben (Überbuchung wird gewarnt).
    if rest > 0.01 and tage:
        verteilung[tage[-1]] += rest

    return verteilung


# --------------------------------------------------------------------------
# Aufträge
# --------------------------------------------------------------------------

def auftrag_anlegen(auftragsnummer, titel, kunde, liefertermin, kommentar, prioritaet="Normal"):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auftraege (auftragsnummer, titel, kunde, liefertermin, kommentar, prioritaet, erstellt_am) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                (auftragsnummer or "").strip() or None,
                titel.strip(),
                (kunde or "").strip() or None,
                liefertermin,
                (kommentar or "").strip() or None,
                prioritaet or "Normal",
                date.today().isoformat(),
            ),
        )
        aid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return aid


def auftrag_aktualisieren(aid, auftragsnummer, titel, kunde, liefertermin, kommentar, prioritaet="Normal"):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE auftraege SET auftragsnummer=%s, titel=%s, kunde=%s, liefertermin=%s, "
            "kommentar=%s, prioritaet=%s WHERE id=%s",
            (
                (auftragsnummer or "").strip() or None,
                titel.strip(),
                (kunde or "").strip() or None,
                liefertermin,
                (kommentar or "").strip() or None,
                prioritaet or "Normal",
                aid,
            ),
        )
        conn.commit()
        cur.close()


def auftrag_loeschen(aid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM auftraege WHERE id = %s", (aid,))
        conn.commit()
        cur.close()


# Sortierrang der Prioritätsstufen (Hoch zuerst)
PRIO_RANG = {"Hoch": 0, "Normal": 1, "Niedrig": 2}


def auftraege_liste():
    with get_cursor() as cur:
        cur.execute(
            "SELECT *, CASE prioritaet WHEN 'Hoch' THEN 0 WHEN 'Normal' THEN 1 "
            "WHEN 'Niedrig' THEN 2 ELSE 1 END AS prio_rang "
            "FROM auftraege ORDER BY prio_rang, liefertermin NULLS LAST, erstellt_am DESC, id DESC"
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["vorgaenge"] = vorgaenge_zu_auftrag(r["id"])
        return rows


# --------------------------------------------------------------------------
# Vorgänge
# --------------------------------------------------------------------------

def vorgang_anlegen(auftrag_id, typ_id, stunden, start_datum, end_datum, skill_minlevel_map,
                    anteil_prozent=100):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO vorgaenge (auftrag_id, typ_id, stunden, anteil_prozent, start_datum, end_datum) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (auftrag_id, typ_id, float(stunden), float(anteil_prozent), start_datum, end_datum),
        )
        vid = cur.fetchone()[0]
        for skill_id, min_level in skill_minlevel_map.items():
            cur.execute(
                "INSERT INTO vorgang_skills (vorgang_id, skill_id, min_level) "
                "VALUES (%s, %s, %s)",
                (vid, skill_id, int(min_level)),
            )
        conn.commit()
        cur.close()
        return vid


def vorgang_aktualisieren(vid, typ_id, stunden, start_datum, end_datum, skill_minlevel_map,
                          anteil_prozent=100):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE vorgaenge SET typ_id=%s, stunden=%s, anteil_prozent=%s, "
            "start_datum=%s, end_datum=%s WHERE id=%s",
            (typ_id, float(stunden), float(anteil_prozent), start_datum, end_datum, vid),
        )
        cur.execute("DELETE FROM vorgang_skills WHERE vorgang_id = %s", (vid,))
        for skill_id, min_level in skill_minlevel_map.items():
            cur.execute(
                "INSERT INTO vorgang_skills (vorgang_id, skill_id, min_level) "
                "VALUES (%s, %s, %s)",
                (vid, skill_id, int(min_level)),
            )
        conn.commit()
        cur.close()


def vorgang_loeschen(vid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vorgaenge WHERE id = %s", (vid,))
        conn.commit()
        cur.close()


def vorgang_zuweisen(vid, mid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE vorgaenge SET mitarbeiter_id=%s, status='zugewiesen' WHERE id=%s",
            (mid, vid),
        )
        conn.commit()
        cur.close()


def vorgang_freigeben(vid):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE vorgaenge SET mitarbeiter_id=NULL, status='offen' WHERE id=%s",
            (vid,),
        )
        conn.commit()
        cur.close()


def vorgaenge_zu_auftrag(aid):
    with get_cursor() as cur:
        cur.execute(
            "SELECT v.*, t.name AS typ_name, t.gruppe_id, g.name AS gruppe_name, "
            "       m.name AS mitarbeiter_name "
            "FROM vorgaenge v "
            "LEFT JOIN vorgangstypen t ON t.id = v.typ_id "
            "LEFT JOIN gruppen g ON g.id = t.gruppe_id "
            "LEFT JOIN mitarbeiter m ON m.id = v.mitarbeiter_id "
            "WHERE v.auftrag_id = %s ORDER BY v.start_datum NULLS LAST, v.id",
            (aid,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            cur.execute(
                "SELECT s.id, s.name, vs.min_level "
                "FROM vorgang_skills vs JOIN skills s ON s.id = vs.skill_id "
                "WHERE vs.vorgang_id = %s ORDER BY s.name",
                (r["id"],),
            )
            r["skills"] = [dict(s) for s in cur.fetchall()]
        return rows


def offene_vorgaenge():
    """Alle noch nicht zugewiesenen Vorgänge, mit Auftrags-Kontext."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT v.*, t.name AS typ_name, t.gruppe_id, g.name AS gruppe_name, "
            "       a.titel AS auftrag_titel, a.auftragsnummer, a.kunde, a.liefertermin "
            "FROM vorgaenge v "
            "LEFT JOIN vorgangstypen t ON t.id = v.typ_id "
            "LEFT JOIN gruppen g ON g.id = t.gruppe_id "
            "JOIN auftraege a ON a.id = v.auftrag_id "
            "WHERE v.status = 'offen' "
            "ORDER BY a.liefertermin NULLS LAST, v.start_datum NULLS LAST, v.id"
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            cur.execute(
                "SELECT s.id, s.name, vs.min_level "
                "FROM vorgang_skills vs JOIN skills s ON s.id = vs.skill_id "
                "WHERE vs.vorgang_id = %s ORDER BY s.name",
                (r["id"],),
            )
            r["skills"] = [dict(s) for s in cur.fetchall()]
        return rows


# --------------------------------------------------------------------------
# Zuordnungslogik (Scoring) – jetzt pro Vorgang, mit strikter Gruppenfilterung
# --------------------------------------------------------------------------

GEWICHT_SKILL = 0.5
GEWICHT_KAPAZITAET = 0.3
GEWICHT_AUSGLEICH = 0.2


def _verplante_stunden_pro_tag(mitarbeiter_id, ausser_vorgang_id=None):
    """
    Liefert {date: stunden} der bereits zugewiesenen Vorgänge eines Mitarbeiters,
    proportional zur Tageskapazität über die Arbeitstage verteilt. Optional kann
    ein Vorgang ausgenommen werden.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, stunden, anteil_prozent, start_datum, end_datum FROM vorgaenge "
            "WHERE mitarbeiter_id = %s AND status = 'zugewiesen' "
            "AND start_datum IS NOT NULL AND end_datum IS NOT NULL",
            (mitarbeiter_id,),
        )
        vorgaenge = [dict(r) for r in cur.fetchall()]

    # Mitarbeiterobjekt + Ausnahmen + Abwesenheiten für die Verteilung
    m = next((x for x in mitarbeiter_liste() if x["id"] == mitarbeiter_id), None)
    if m is None:
        return {}
    ausnahmen = _ausnahmen_map(mitarbeiter_id)
    abwesenheiten = _abwesenheit_map(mitarbeiter_id)

    jahre = set()
    for v in vorgaenge:
        jahre.add(v["start_datum"].year)
        jahre.add(v["end_datum"].year)
    feiertage = {}
    for j in jahre:
        feiertage.update(bw_feiertage(j))

    pro_tag = {}
    for v in vorgaenge:
        if ausser_vorgang_id is not None and v["id"] == ausser_vorgang_id:
            continue
        tage = _arbeitstage(v["start_datum"], v["end_datum"], feiertage)
        if not tage:
            continue
        for d, h in verteile_stunden(m, tage, v["stunden"], ausnahmen,
                                     v.get("anteil_prozent", 100), abwesenheiten).items():
            pro_tag[d] = pro_tag.get(d, 0.0) + h
    return pro_tag


def _bestand_alle_mitarbeiter():
    """
    {mitarbeiter_id: {date: stunden}} der zugewiesenen Vorgänge ALLER Mitarbeiter,
    kapazitätsproportional verteilt. Wenige Sammelabfragen statt einer pro Kandidat.
    """
    return _cached("bestand_alle", _bestand_alle_impl)


def _bestand_alle_impl():
    with get_cursor() as cur:
        cur.execute(
            "SELECT mitarbeiter_id, stunden, anteil_prozent, start_datum, end_datum FROM vorgaenge "
            "WHERE status = 'zugewiesen' AND mitarbeiter_id IS NOT NULL "
            "AND start_datum IS NOT NULL AND end_datum IS NOT NULL"
        )
        vorgaenge = [dict(r) for r in cur.fetchall()]

    ma_by_id = {m["id"]: m for m in mitarbeiter_liste()}
    alle_ausnahmen = _ausnahmen_alle_mitarbeiter()
    alle_abwesenheiten = _abwesenheit_alle_mitarbeiter()

    jahre = set()
    for v in vorgaenge:
        jahre.add(v["start_datum"].year)
        jahre.add(v["end_datum"].year)
    feiertage = {}
    for j in jahre:
        feiertage.update(bw_feiertage(j))

    result = {}
    for v in vorgaenge:
        m = ma_by_id.get(v["mitarbeiter_id"])
        if m is None:
            continue
        tage = _arbeitstage(v["start_datum"], v["end_datum"], feiertage)
        if not tage:
            continue
        ausnahmen = alle_ausnahmen.get(v["mitarbeiter_id"], {})
        abwesenheiten = alle_abwesenheiten.get(v["mitarbeiter_id"], {})
        pro_tag = result.setdefault(v["mitarbeiter_id"], {})
        for d, h in verteile_stunden(m, tage, v["stunden"], ausnahmen,
                                     v.get("anteil_prozent", 100), abwesenheiten).items():
            pro_tag[d] = pro_tag.get(d, 0.0) + h
    return result


def _ausnahmen_alle_mitarbeiter():
    """{mitarbeiter_id: {date: brutto_stunden}} aller Ausnahmen in einer Abfrage."""
    return _cached("ausnahmen_alle", _ausnahmen_alle_impl)


def _ausnahmen_alle_impl():
    with get_cursor() as cur:
        cur.execute("SELECT mitarbeiter_id, datum, brutto_stunden FROM tagesarbeitszeit")
        result = {}
        for r in cur.fetchall():
            result.setdefault(r["mitarbeiter_id"], {})[r["datum"]] = r["brutto_stunden"]
        return result


def _ueberbuchung_im_zeitraum(mitarbeiter, start, ende, zusatz_stunden,
                              bestand=None, ausnahmen=None, anteil_prozent=100,
                              abwesenheiten=None):
    """
    Prüft, ob der Mitarbeiter im Zeitraum [start, ende] an Tagen über seine
    effektive Tageskapazität käme, wenn 'zusatz_stunden' hinzukommen.

    bestand/ausnahmen/abwesenheiten können vorab geladen übergeben werden
    (Performance); sonst werden sie für diesen einen Mitarbeiter nachgeladen.

    Rückgabe: Liste von (datum, geplante_stunden, kapazitaet) für Tage über Kapazität.
    """
    if not start or not ende or ende < start:
        return []
    feiertage = {}
    for j in {start.year, ende.year}:
        feiertage.update(bw_feiertage(j))
    tage = _arbeitstage(start, ende, feiertage)
    if not tage:
        return []

    if ausnahmen is None:
        ausnahmen = _ausnahmen_map(mitarbeiter["id"])
    if abwesenheiten is None:
        abwesenheiten = _abwesenheit_map(mitarbeiter["id"])
    if bestand is None:
        bestand = _verplante_stunden_pro_tag(mitarbeiter["id"])

    # Neuen Vorgang ebenfalls kapazitätsproportional verteilen (mit Anteil-Deckel)
    zusatz_pro_tag = verteile_stunden(mitarbeiter, tage, zusatz_stunden, ausnahmen,
                                      anteil_prozent, abwesenheiten)

    konflikte = []
    for d in tage:
        kapazitaet = effektive_tageskapazitaet(mitarbeiter, d, ausnahmen, abwesenheiten)
        geplant = bestand.get(d, 0.0) + zusatz_pro_tag.get(d, 0.0)
        if geplant > kapazitaet + 0.01:
            konflikte.append((d, round(geplant, 1), round(kapazitaet, 1)))
    return konflikte


def _vorgang_by_id(vorgang_id):
    """Lädt genau einen Vorgang samt Kontext und Skills (eine Abfrage + eine für Skills)."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT v.*, t.name AS typ_name, t.gruppe_id, g.name AS gruppe_name, "
            "       a.titel AS auftrag_titel, a.auftragsnummer, a.kunde, a.liefertermin "
            "FROM vorgaenge v "
            "LEFT JOIN vorgangstypen t ON t.id = v.typ_id "
            "LEFT JOIN gruppen g ON g.id = t.gruppe_id "
            "JOIN auftraege a ON a.id = v.auftrag_id "
            "WHERE v.id = %s",
            (vorgang_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        ziel = dict(row)
        cur.execute(
            "SELECT s.id, s.name, vs.min_level "
            "FROM vorgang_skills vs JOIN skills s ON s.id = vs.skill_id "
            "WHERE vs.vorgang_id = %s ORDER BY s.name",
            (vorgang_id,),
        )
        ziel["skills"] = [dict(s) for s in cur.fetchall()]
        return ziel


def vorschlaege_fuer_vorgang(vorgang_id, top_n=5):
    ziel = _vorgang_by_id(vorgang_id)
    if not ziel:
        return []

    benoetigt = {s["id"]: s["min_level"] for s in ziel["skills"]}
    aufwand = ziel["stunden"]
    gruppe_id = ziel.get("gruppe_id")
    start = ziel.get("start_datum")
    ende = ziel.get("end_datum")
    anteil = ziel.get("anteil_prozent", 100)

    # Einmal gebündelt für ALLE Mitarbeiter laden (statt pro Kandidat)
    alle_bestaende = _bestand_alle_mitarbeiter()
    alle_ausnahmen = _ausnahmen_alle_mitarbeiter()
    alle_abwesenheiten = _abwesenheit_alle_mitarbeiter()

    kandidaten = []
    for m in mitarbeiter_liste():
        # Strikte Gruppenfilterung: nur passende Gruppe
        if gruppe_id is not None and m.get("gruppe_id") != gruppe_id:
            continue

        skill_map = {s["id"]: s["level"] for s in m["skills"]}
        if not all(skill_map.get(sid, 0) >= lvl for sid, lvl in benoetigt.items()):
            continue
        frei = m["wochenstunden"] - m["verplant"]
        # Hinweis: Die Wochensumme schließt NICHT mehr hart aus. Ob es im
        # konkreten Zeitraum eng wird, prüft die Überbuchungs-Warnung unten.

        if benoetigt:
            reserven = [max(0.0, min(1.0, (skill_map[sid] - lvl) / 4.0))
                        for sid, lvl in benoetigt.items()]
            score_skill = sum(reserven) / len(reserven)
        else:
            score_skill = 1.0

        if m["wochenstunden"] > 0:
            # Auf 0..1 begrenzt; bei Überbuchung fällt der Kapazitäts-Score auf 0,
            # statt den Kandidaten ganz zu entfernen.
            score_kap = max(0.0, min(1.0, (frei - aufwand) / m["wochenstunden"]))
            score_ausg = max(0.0, min(1.0, 1.0 - m["verplant"] / m["wochenstunden"]))
        else:
            score_kap = score_ausg = 0.0

        score = (GEWICHT_SKILL * score_skill
                 + GEWICHT_KAPAZITAET * score_kap
                 + GEWICHT_AUSGLEICH * score_ausg)

        # Zeitraumbezogene Überbuchung (nur Warnung) – mit vorab geladenen Daten
        konflikte = _ueberbuchung_im_zeitraum(
            m, start, ende, aufwand,
            bestand=alle_bestaende.get(m["id"], {}),
            ausnahmen=alle_ausnahmen.get(m["id"], {}),
            anteil_prozent=anteil,
            abwesenheiten=alle_abwesenheiten.get(m["id"], {}),
        )

        kandidaten.append({
            "mitarbeiter": m,
            "score": round(score, 3),
            "begruendung": {
                "Skill-Passung": round(score_skill, 2),
                "Kapazität": round(score_kap, 2),
                "Auslastungsausgleich": round(score_ausg, 2),
            },
            "frei_nach": round(frei - aufwand, 1),
            "ueberbuchung": konflikte,
        })

    kandidaten.sort(key=lambda k: k["score"], reverse=True)
    return kandidaten[:top_n]


# --------------------------------------------------------------------------
# Kalender / Feiertage / Auslastung
# --------------------------------------------------------------------------

_feiertage_cache = {}


def bw_feiertage(jahr):
    """Dict {date: name} der Feiertage in Baden-Württemberg (pro Jahr gecacht)."""
    if _holidays_lib is None:
        return {}
    if jahr not in _feiertage_cache:
        _feiertage_cache[jahr] = dict(_holidays_lib.Germany(subdiv="BW", years=jahr))
    return _feiertage_cache[jahr]


def _arbeitstage(start, ende, feiertage):
    """Liste der Arbeitstage (Mo–Fr, ohne Feiertage) zwischen start und ende inkl."""
    if not start or not ende or ende < start:
        return []
    tage = []
    d = start
    while d <= ende:
        if d.weekday() < 5 and d not in feiertage:
            tage.append(d)
        d += timedelta(days=1)
    return tage


def tagesauslastung(jahr, monat, tage_davor=0, tage_danach=0):
    """
    Berechnet je Mitarbeiter und Tag die geplanten Stunden im gegebenen Monat,
    optional erweitert um 'tage_davor' Tage vor Monatsanfang und 'tage_danach'
    Tage nach Monatsende (für einen Kalender, der über den Monat hinausschaut).

    Rückgabe:
      {
        "feiertage": {date: name},
        "mitarbeiter": [
            {"id", "name", "tageskapazitaet",
             "tage": {date: {"stunden": float, "vorgaenge": [..], "deadlines": [..], "kapazitaet", "ausnahme"}}}
        ],
        "erster", "letzter"
      }
    """
    monatsanfang = date(jahr, monat, 1)
    if monat == 12:
        monatsende = date(jahr + 1, 1, 1) - timedelta(days=1)
    else:
        monatsende = date(jahr, monat + 1, 1) - timedelta(days=1)

    erster = monatsanfang - timedelta(days=tage_davor)
    letzter = monatsende + timedelta(days=tage_danach)

    # Feiertage über alle Jahre im (evtl. erweiterten) Bereich
    feiertage = {}
    for j in range(erster.year, letzter.year + 1):
        feiertage.update(bw_feiertage(j))

    # Alle zugewiesenen Vorgänge mit Datum holen
    with get_cursor() as cur:
        cur.execute(
            "SELECT v.id, v.stunden, v.anteil_prozent, v.start_datum, v.end_datum, v.mitarbeiter_id, "
            "       t.name AS typ_name, a.titel AS auftrag_titel, a.auftragsnummer, "
            "       a.liefertermin "
            "FROM vorgaenge v "
            "LEFT JOIN vorgangstypen t ON t.id = v.typ_id "
            "JOIN auftraege a ON a.id = v.auftrag_id "
            "WHERE v.status = 'zugewiesen' AND v.mitarbeiter_id IS NOT NULL "
            "AND v.start_datum IS NOT NULL AND v.end_datum IS NOT NULL"
        )
        vorgaenge = [dict(r) for r in cur.fetchall()]

    ma = mitarbeiter_liste()
    alle_abwesenheiten = _abwesenheit_alle_mitarbeiter()
    # Abwesenheiten mit Kategorie je Tag (für Anzeige/Tooltip)
    abw_detail = {}
    for a in abwesenheiten_liste():
        abw_detail.setdefault(a["mitarbeiter_id"], {}).setdefault(a["datum"], []).append(
            (a["kategorie_name"] or "Abwesend", a["stunden"])
        )

    ergebnis = {m["id"]: {
        "id": m["id"], "name": m["name"],
        "tageskapazitaet": m["tageskapazitaet"],  # Standard (Fallback in der Anzeige)
        "_obj": m,
        "_ausnahmen": _ausnahmen_map(m["id"]),
        "_abwesenheiten": alle_abwesenheiten.get(m["id"], {}),
        "_abw_detail": abw_detail.get(m["id"], {}),
        "tage": {}
    } for m in ma}

    for v in vorgaenge:
        mid = v["mitarbeiter_id"]
        if mid not in ergebnis:
            continue
        # Feiertage über die gesamte Vorgangsdauer (kann über Jahreswechsel gehen)
        ft = {}
        for j in {v["start_datum"].year, v["end_datum"].year}:
            ft.update(bw_feiertage(j))
        arbeitstage = _arbeitstage(v["start_datum"], v["end_datum"], ft)
        if not arbeitstage:
            continue
        m_obj = ergebnis[mid]["_obj"]
        m_ausn = ergebnis[mid]["_ausnahmen"]
        m_abw = ergebnis[mid]["_abwesenheiten"]
        # kapazitätsproportional über ALLE Arbeitstage des Vorgangs verteilen
        verteilung = verteile_stunden(m_obj, arbeitstage, v["stunden"], m_ausn,
                                      v.get("anteil_prozent", 100), m_abw)
        for d, h in verteilung.items():
            if d < erster or d > letzter:
                continue
            slot = ergebnis[mid]["tage"].setdefault(
                d, {"stunden": 0.0, "vorgaenge": [], "deadlines": []}
            )
            slot["stunden"] += h
            label = v["typ_name"] or "Vorgang"
            slot["vorgaenge"].append(f"{v['auftrag_titel']} – {label}")
        # Deadline (Vorgangsende) im Monat markieren
        if erster <= v["end_datum"] <= letzter and v["end_datum"] in ergebnis[mid]["tage"]:
            ergebnis[mid]["tage"][v["end_datum"]]["deadlines"].append(
                f"Ende: {v['auftrag_titel']} – {v['typ_name'] or 'Vorgang'}"
            )

    # Tagesgenaue Kapazität ergänzen – für alle Werktage im Bereich, damit auch
    # Ausnahmen/Abwesenheiten ohne geplante Vorgänge sichtbar werden.
    d = erster
    while d <= letzter:
        if d.weekday() < 5 and d not in feiertage:
            for eintrag in ergebnis.values():
                kap = effektive_tageskapazitaet(
                    eintrag["_obj"], d, eintrag["_ausnahmen"], eintrag["_abwesenheiten"]
                )
                slot = eintrag["tage"].setdefault(
                    d, {"stunden": 0.0, "vorgaenge": [], "deadlines": []}
                )
                slot["kapazitaet"] = kap
                slot["ausnahme"] = d in eintrag["_ausnahmen"]
                # Abwesenheitsdetails für Anzeige/Tooltip
                slot["abwesenheit"] = eintrag["_abw_detail"].get(d, [])
        d += timedelta(days=1)

    # interne Hilfsfelder entfernen
    for eintrag in ergebnis.values():
        for k in ("_obj", "_ausnahmen", "_abwesenheiten", "_abw_detail"):
            eintrag.pop(k, None)

    return {
        "feiertage": {d: n for d, n in feiertage.items() if erster <= d <= letzter},
        "mitarbeiter": list(ergebnis.values()),
        "erster": erster,
        "letzter": letzter,
    }
