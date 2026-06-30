"""
app.py – Streamlit-Oberfläche für den Auftragsplaner.

Reiter: Disposition · Aufträge · Kalender · Mitarbeiter · Stammdaten
Start:  streamlit run app.py
"""

import calendar
from datetime import date, timedelta

import streamlit as st
import core

st.set_page_config(page_title="Disponent", page_icon="🗂️", layout="wide")


# --------------------------------------------------------------------------
# Passwort-Schutz
# --------------------------------------------------------------------------
def passwort_ok():
    if st.session_state.get("auth_ok"):
        return True
    st.title("Disponent")
    st.caption("Bitte Team-Passwort eingeben.")
    eingabe = st.text_input("Passwort", type="password")
    if eingabe:
        if eingabe == st.secrets["app_passwort"]:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Falsches Passwort.")
    return False


if not passwort_ok():
    st.stop()

core.init_db()

# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
      :root { --schiefer: #2b3440; --bernstein: #c8861d; }
      .stApp { background: #f5f6f7; }
      [data-testid="stHeader"] { background: #f5f6f7; }
      .stApp, .stApp p, .stApp span, .stApp label, .stApp li,
      .stMarkdown, [data-testid="stMarkdownContainer"] { color: var(--schiefer); }
      h1,h2,h3,h4 { color: var(--schiefer) !important; letter-spacing: -0.01em; }
      .stApp small { color: #5a6573; }
      input, textarea, [data-baseweb="select"] > div {
        background:#fff !important; color: var(--schiefer) !important;
      }
      .stButton button { border-radius:4px; border:1px solid var(--schiefer);
        background:#fff; color:var(--schiefer); }
      .stButton button:hover { border-color:var(--bernstein); color:var(--bernstein); }
      .vorschlag { border:1px solid #d9dde2; border-left:4px solid var(--bernstein);
        border-radius:4px; padding:0.8rem 1rem; margin-bottom:0.6rem; background:#fff; }
      .pill { display:inline-block; background:#eef1f4; color:#2b3440;
        border-radius:10px; padding:1px 8px; margin:1px 2px; font-size:0.8rem; }
      .cal td, .cal th { border:1px solid #e2e6ea; padding:4px 6px; text-align:center;
        font-size:0.8rem; vertical-align:top; }
      .cal th { background:#eef1f4; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Disponent")

tab_dispo, tab_auftraege, tab_kalender, tab_mitarbeiter, tab_stamm = st.tabs(
    ["Disposition", "Aufträge", "Kalender", "Mitarbeiter", "Stammdaten"]
)


# ==========================================================================
# Tab: Stammdaten (Gruppen, Vorgangstypen, Fähigkeiten)
# ==========================================================================
with tab_stamm:
    sp1, sp2, sp3 = st.columns(3)

    with sp1:
        st.subheader("Gruppen")
        with st.form("gr_form", clear_on_submit=True):
            gn = st.text_input("Neue Gruppe")
            if st.form_submit_button("Hinzufügen") and gn.strip():
                core.gruppe_anlegen(gn)
                st.rerun()
        for g in core.gruppen_liste():
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"<span class='pill'>{g['name']}</span>", unsafe_allow_html=True)
            if c2.button("✕", key=f"delg_{g['id']}"):
                core.gruppe_loeschen(g["id"])
                st.rerun()

    with sp2:
        st.subheader("Vorgangstypen")
        gruppen = core.gruppen_liste()
        with st.form("vt_form", clear_on_submit=True):
            vn = st.text_input("Neuer Vorgangstyp")
            gsel = st.selectbox(
                "Gehört zu Gruppe",
                options=[g["id"] for g in gruppen],
                format_func=lambda gid: next(g["name"] for g in gruppen if g["id"] == gid),
            ) if gruppen else None
            if st.form_submit_button("Hinzufügen") and vn.strip():
                core.vorgangstyp_anlegen(vn, gsel)
                st.rerun()
        for t in core.vorgangstypen_liste():
            c1, c2 = st.columns([4, 1])
            c1.markdown(
                f"<span class='pill'>{t['name']} → {t['gruppe_name'] or '—'}</span>",
                unsafe_allow_html=True,
            )
            if c2.button("✕", key=f"delt_{t['id']}"):
                core.vorgangstyp_loeschen(t["id"])
                st.rerun()

    with sp3:
        st.subheader("Fähigkeiten")
        with st.form("sk_form", clear_on_submit=True):
            sn = st.text_input("Neue Fähigkeit")
            if st.form_submit_button("Hinzufügen") and sn.strip():
                core.skill_anlegen(sn)
                st.rerun()
        for s in core.skills_liste():
            st.markdown(f"<span class='pill'>{s['name']}</span>", unsafe_allow_html=True)


# ==========================================================================
# Tab: Mitarbeiter
# ==========================================================================
with tab_mitarbeiter:
    st.subheader("Mitarbeiter anlegen")
    skills = core.skills_liste()
    gruppen = core.gruppen_liste()

    if not gruppen:
        st.warning("Lege zuerst im Tab „Stammdaten“ mindestens eine Gruppe an.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("Name", key="nm_name")
        stunden = c2.number_input("Wochenstunden", 1.0, 80.0, 40.0, 0.5, key="nm_std")
        eff = c3.number_input("Effektivität %", 10.0, 100.0, 80.0, 5.0, key="nm_eff",
                              help="Anteil der Arbeitszeit, der auftragsbezogen verfügbar ist")
        gsel = c4.selectbox("Gruppe", options=[g["id"] for g in gruppen],
                            format_func=lambda gid: next(g["name"] for g in gruppen if g["id"] == gid),
                            key="nm_grp")

        level_map = {}
        if skills:
            st.markdown("**Fähigkeiten & Level** (1–5)")
            ausw = st.multiselect("Fähigkeiten", options=[s["id"] for s in skills],
                                  format_func=lambda sid: next(s["name"] for s in skills if s["id"] == sid),
                                  key="nm_skills")
            for sid in ausw:
                sname = next(s["name"] for s in skills if s["id"] == sid)
                level_map[sid] = st.slider(f"Level: {sname}", 1, 5, 3, key=f"nm_lvl_{sid}")

        if st.button("Mitarbeiter speichern", key="nm_save"):
            if name.strip():
                core.mitarbeiter_anlegen(name, stunden, eff, gsel, level_map)
                st.success(f"„{name}“ gespeichert.")
                st.rerun()
            else:
                st.error("Bitte einen Namen eingeben.")

    st.divider()
    st.subheader("Team")
    for m in core.mitarbeiter_liste():
        c1, c2, c3, c4 = st.columns([3, 2, 2, 4])
        c1.markdown(f"**{m['name']}**")
        c2.markdown(f"<span class='pill'>{m['gruppe_name'] or 'ohne Gruppe'}</span>", unsafe_allow_html=True)
        c3.markdown(f"{m['effektivitaet']:.0f}% · {m['tageskapazitaet']:.1f} h/Tag")
        pills = " ".join(f"<span class='pill'>{s['name']} · {s['level']}</span>" for s in m["skills"]) \
                or "<span class='pill'>keine Fähigkeiten</span>"
        c4.markdown(pills, unsafe_allow_html=True)

        with st.expander("Bearbeiten"):
            e1, e2, e3, e4 = st.columns(4)
            en = e1.text_input("Name", value=m["name"], key=f"em_name_{m['id']}")
            es = e2.number_input("Wochenstunden", 1.0, 80.0, float(m["wochenstunden"]), 0.5, key=f"em_std_{m['id']}")
            ee = e3.number_input("Effektivität %", 10.0, 100.0, float(m["effektivitaet"]), 5.0, key=f"em_eff_{m['id']}")
            grp_ids = [g["id"] for g in gruppen]
            cur_idx = grp_ids.index(m["gruppe_id"]) if m["gruppe_id"] in grp_ids else 0
            eg = e4.selectbox("Gruppe", options=grp_ids, index=cur_idx,
                              format_func=lambda gid: next(g["name"] for g in gruppen if g["id"] == gid),
                              key=f"em_grp_{m['id']}") if gruppen else None

            vorhanden = {s["id"]: s["level"] for s in m["skills"]}
            elm = {}
            if skills:
                eausw = st.multiselect("Fähigkeiten", options=[s["id"] for s in skills],
                                       default=[sid for sid in vorhanden if sid in [s["id"] for s in skills]],
                                       format_func=lambda sid: next(s["name"] for s in skills if s["id"] == sid),
                                       key=f"em_skills_{m['id']}")
                for sid in eausw:
                    sname = next(s["name"] for s in skills if s["id"] == sid)
                    elm[sid] = st.slider(f"Level: {sname}", 1, 5, int(vorhanden.get(sid, 3)),
                                         key=f"em_lvl_{m['id']}_{sid}")

            b1, b2 = st.columns(2)
            if b1.button("Speichern", key=f"em_save_{m['id']}"):
                if en.strip():
                    core.mitarbeiter_aktualisieren(m["id"], en, es, ee, eg, elm)
                    st.rerun()
                else:
                    st.error("Bitte einen Namen eingeben.")
            if b2.button("Löschen", key=f"em_del_{m['id']}"):
                core.mitarbeiter_loeschen(m["id"])
                st.rerun()


# ==========================================================================
# Tab: Aufträge
# ==========================================================================
def _vorgang_editor(prefix, typen, skills, default=None):
    """Eingabefelder für einen Vorgang. Gibt dict mit den Werten zurück."""
    d = default or {}
    c1, c2, c3, c4 = st.columns(4)
    typ_ids = [t["id"] for t in typen]
    if typ_ids:
        idx = typ_ids.index(d["typ_id"]) if d.get("typ_id") in typ_ids else 0
        typ = c1.selectbox("Vorgangstyp", options=typ_ids, index=idx,
                           format_func=lambda tid: next(t["name"] for t in typen if t["id"] == tid),
                           key=f"{prefix}_typ")
    else:
        typ = None
        c1.info("Erst Vorgangstypen anlegen")
    std = c2.number_input("Stunden", 0.0, 9999.0, float(d.get("stunden", 8.0)), 0.5, key=f"{prefix}_std")
    start = c3.date_input("Start", value=d.get("start_datum") or date.today(), key=f"{prefix}_start")
    ende = c4.date_input("Ende", value=d.get("end_datum") or date.today(), key=f"{prefix}_ende")

    minlevel = {}
    if skills:
        vorhanden = {s["id"]: s["min_level"] for s in d.get("skills", [])}
        ausw = st.multiselect("Benötigte Fähigkeiten", options=[s["id"] for s in skills],
                              default=[sid for sid in vorhanden if sid in [s["id"] for s in skills]],
                              format_func=lambda sid: next(s["name"] for s in skills if s["id"] == sid),
                              key=f"{prefix}_skills")
        for sid in ausw:
            sname = next(s["name"] for s in skills if s["id"] == sid)
            minlevel[sid] = st.slider(f"Mindest-Level: {sname}", 1, 5, int(vorhanden.get(sid, 1)),
                                      key=f"{prefix}_lvl_{sid}")
    return {"typ_id": typ, "stunden": std, "start": start, "ende": ende, "minlevel": minlevel}


with tab_auftraege:
    st.subheader("Auftrag anlegen")
    typen = core.vorgangstypen_liste()
    skills = core.skills_liste()

    c1, c2, c3 = st.columns(3)
    a_nr = c1.text_input("Auftragsnummer", key="au_nr")
    a_titel = c2.text_input("Titel", key="au_titel")
    a_kunde = c3.text_input("Kunde", key="au_kunde")
    c4, c5 = st.columns([1, 2])
    a_liefer = c4.date_input("Geplanter Liefertermin", value=date.today(), key="au_liefer")
    a_kommentar = c5.text_input("Kommentar", key="au_kommentar")

    if st.button("Auftrag anlegen", key="au_save"):
        if a_titel.strip():
            core.auftrag_anlegen(a_nr, a_titel, a_kunde, a_liefer, a_kommentar)
            st.success(f"Auftrag „{a_titel}“ angelegt. Füge unten Vorgänge hinzu.")
            st.rerun()
        else:
            st.error("Bitte mindestens einen Titel eingeben.")

    st.divider()
    st.subheader("Alle Aufträge")
    auftraege = core.auftraege_liste()
    if not auftraege:
        st.info("Noch keine Aufträge.")

    for a in auftraege:
        kopf = f"**{a['titel']}**"
        if a["auftragsnummer"]:
            kopf = f"**{a['auftragsnummer']} · {a['titel']}**"
        meta = []
        if a["kunde"]:
            meta.append(a["kunde"])
        if a["liefertermin"]:
            meta.append(f"Liefertermin {a['liefertermin']}")
        with st.expander(f"{a['auftragsnummer'] or ''} {a['titel']}  ·  {a['kunde'] or ''}".strip()):
            st.markdown(kopf)
            if meta:
                st.caption(" · ".join(meta))
            if a["kommentar"]:
                st.markdown(f"_{a['kommentar']}_")

            # Auftrag bearbeiten
            with st.expander("Auftragsdaten bearbeiten"):
                e1, e2, e3 = st.columns(3)
                en = e1.text_input("Auftragsnummer", value=a["auftragsnummer"] or "", key=f"ea_nr_{a['id']}")
                et = e2.text_input("Titel", value=a["titel"], key=f"ea_titel_{a['id']}")
                ek = e3.text_input("Kunde", value=a["kunde"] or "", key=f"ea_kunde_{a['id']}")
                e4, e5 = st.columns([1, 2])
                el = e4.date_input("Liefertermin", value=a["liefertermin"] or date.today(), key=f"ea_liefer_{a['id']}")
                eko = e5.text_input("Kommentar", value=a["kommentar"] or "", key=f"ea_kom_{a['id']}")
                b1, b2 = st.columns(2)
                if b1.button("Speichern", key=f"ea_save_{a['id']}"):
                    if et.strip():
                        core.auftrag_aktualisieren(a["id"], en, et, ek, el, eko)
                        st.rerun()
                if b2.button("Auftrag löschen", key=f"ea_del_{a['id']}"):
                    core.auftrag_loeschen(a["id"])
                    st.rerun()

            # Vorgänge auflisten
            st.markdown("**Vorgänge**")
            if not a["vorgaenge"]:
                st.caption("Noch keine Vorgänge.")
            for v in a["vorgaenge"]:
                zeile = f"{v['typ_name'] or 'Vorgang'} · {v['stunden']:.1f} h"
                if v["start_datum"] and v["end_datum"]:
                    zeile += f" · {v['start_datum']} → {v['end_datum']}"
                if v["status"] == "zugewiesen":
                    zeile += f" · **{v['mitarbeiter_name']}**"
                else:
                    zeile += " · _offen_"
                st.markdown(zeile)
                with st.expander("Vorgang bearbeiten"):
                    werte = _vorgang_editor(f"ev_{v['id']}", typen, skills, default=v)
                    cc1, cc2 = st.columns(2)
                    if cc1.button("Speichern", key=f"ev_save_{v['id']}"):
                        core.vorgang_aktualisieren(v["id"], werte["typ_id"], werte["stunden"],
                                                   werte["start"], werte["ende"], werte["minlevel"])
                        st.rerun()
                    if cc2.button("Vorgang löschen", key=f"ev_del_{v['id']}"):
                        core.vorgang_loeschen(v["id"])
                        st.rerun()

            # Neuen Vorgang hinzufügen
            st.markdown("**Vorgang hinzufügen**")
            neu = _vorgang_editor(f"nv_{a['id']}", typen, skills)
            if st.button("Vorgang hinzufügen", key=f"nv_save_{a['id']}"):
                core.vorgang_anlegen(a["id"], neu["typ_id"], neu["stunden"],
                                     neu["start"], neu["ende"], neu["minlevel"])
                st.rerun()


# ==========================================================================
# Tab: Disposition (offene Vorgänge zuweisen)
# ==========================================================================
with tab_dispo:
    st.subheader("Offene Vorgänge zuweisen")
    offene = core.offene_vorgaenge()
    if not offene:
        st.info("Keine offenen Vorgänge. Lege im Tab „Aufträge“ Vorgänge an.")

    for v in offene:
        with st.container(border=True):
            kopf = f"**{v['auftrag_titel']}** · {v['typ_name'] or 'Vorgang'} · {v['stunden']:.1f} h"
            st.markdown(kopf)
            unten = []
            if v["auftragsnummer"]:
                unten.append(f"Nr. {v['auftragsnummer']}")
            if v["kunde"]:
                unten.append(v["kunde"])
            if v["gruppe_name"]:
                unten.append(f"Gruppe: {v['gruppe_name']}")
            if v["start_datum"] and v["end_datum"]:
                unten.append(f"{v['start_datum']} → {v['end_datum']}")
            if v["liefertermin"]:
                unten.append(f"Liefertermin {v['liefertermin']}")
            if unten:
                st.caption(" · ".join(str(x) for x in unten))
            if v["skills"]:
                req = " ".join(f"<span class='pill'>{s['name']} ≥ {s['min_level']}</span>" for s in v["skills"])
                st.markdown("Benötigt: " + req, unsafe_allow_html=True)

            # Terminwarnung: Vorgang endet nach dem Liefertermin des Auftrags
            if v["liefertermin"] and v["end_datum"] and v["end_datum"] > v["liefertermin"]:
                tage = (v["end_datum"] - v["liefertermin"]).days
                st.warning(
                    f"⚠️ Terminkonflikt: Der Vorgang endet am {v['end_datum']}, "
                    f"also {tage} Tag(e) nach dem Liefertermin ({v['liefertermin']})."
                )

            vors = core.vorschlaege_fuer_vorgang(v["id"], top_n=5)
            if not vors:
                st.warning("Kein passender Mitarbeiter (Gruppe oder Fähigkeiten/Level).")
            else:
                for rang, vo in enumerate(vors, start=1):
                    m = vo["mitarbeiter"]; b = vo["begruendung"]
                    cols = st.columns([4, 2, 1])
                    txt = " · ".join(f"{k}: {val:.2f}" for k, val in b.items())
                    cols[0].markdown(
                        f"<div class='vorschlag'><b>{rang}. {m['name']}</b> "
                        f"<span style='color:#c8861d'>Score {vo['score']:.2f}</span><br>"
                        f"<small>{txt}</small></div>", unsafe_allow_html=True)
                    cols[1].markdown(f"<br>frei danach: **{vo['frei_nach']:.1f} h**", unsafe_allow_html=True)
                    if cols[2].button("Zuweisen", key=f"as_{v['id']}_{m['id']}"):
                        core.vorgang_zuweisen(v["id"], m["id"])
                        st.rerun()

                    # Überbuchungswarnung im Zeitraum (kein Ausschluss, nur Hinweis)
                    if vo["ueberbuchung"]:
                        n = len(vo["ueberbuchung"])
                        beispiele = ", ".join(
                            f"{d.strftime('%d.%m.')}: {g:.1f}/{kap:.1f} h"
                            for d, g, kap in vo["ueberbuchung"][:3]
                        )
                        mehr = " …" if n > 3 else ""
                        cols[0].markdown(
                            f"<small style='color:#b3451f'>⚠️ an {n} Tag(en) über Kapazität "
                            f"({beispiele}{mehr})</small>",
                            unsafe_allow_html=True,
                        )

    st.divider()
    st.subheader("Zugewiesene Vorgänge")
    for a in core.auftraege_liste():
        for v in a["vorgaenge"]:
            if v["status"] == "zugewiesen":
                c1, c2 = st.columns([5, 1])
                txt = f"**{a['titel']}** · {v['typ_name'] or 'Vorgang'} · {v['stunden']:.1f} h → {v['mitarbeiter_name']}"
                if v["start_datum"] and v["end_datum"]:
                    txt += f"  ({v['start_datum']} → {v['end_datum']})"
                c1.markdown(txt)
                if c2.button("Zurücknehmen", key=f"rel_{v['id']}"):
                    core.vorgang_freigeben(v["id"])
                    st.rerun()


# ==========================================================================
# Tab: Kalender
# ==========================================================================
with tab_kalender:
    st.subheader("Auslastungskalender")
    heute = date.today()
    c1, c2 = st.columns(2)
    jahr = c1.selectbox("Jahr", options=list(range(heute.year - 1, heute.year + 3)),
                        index=1, key="cal_jahr")
    monat = c2.selectbox("Monat", options=list(range(1, 13)), index=heute.month - 1,
                         format_func=lambda mo: ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"][mo-1],
                         key="cal_monat")

    daten = core.tagesauslastung(jahr, monat)
    feiertage = daten["feiertage"]

    if feiertage:
        st.caption("Feiertage (BW): " + " · ".join(f"{d.day}. {n}" for d, n in sorted(feiertage.items())))

    tage_im_monat = calendar.monthrange(jahr, monat)[1]
    alle_tage = [date(jahr, monat, t) for t in range(1, tage_im_monat + 1)]
    wochentage = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    st.markdown("Auslastung je Mitarbeiter und Tag. Farbe zeigt das Verhältnis zur effektiven Tageskapazität.")

    def farbe(stunden, kapazitaet):
        if stunden <= 0:
            return "#ffffff"
        if kapazitaet <= 0:
            return "#f6c0bf"
        q = stunden / kapazitaet
        if q <= 0.75:
            return "#d7ecd6"   # grün: locker
        if q <= 1.0:
            return "#fbe9c4"   # gelb: voll
        return "#f6c0bf"       # rot: überlastet

    # Kopfzeile
    header = "<tr><th>Mitarbeiter</th>"
    for t in alle_tage:
        wt = wochentage[t.weekday()]
        ist_feiertag = t in feiertage
        ist_we = t.weekday() >= 5
        bg = "#e9ecef" if (ist_we or ist_feiertag) else "#eef1f4"
        header += f"<th style='background:{bg}'>{t.day}<br><small>{wt}</small></th>"
    header += "</tr>"

    zeilen = ""
    for m in daten["mitarbeiter"]:
        zeile = f"<tr><td style='text-align:left'><b>{m['name']}</b><br><small>{m['tageskapazitaet']:.1f} h/Tag</small></td>"
        for t in alle_tage:
            info = m["tage"].get(t)
            ist_feiertag = t in feiertage
            ist_we = t.weekday() >= 5
            if ist_feiertag or ist_we:
                zelle = "<td style='background:#e9ecef'></td>"
            elif info and info["stunden"] > 0:
                bg = farbe(info["stunden"], m["tageskapazitaet"])
                deadline = "🚩" if info["deadlines"] else ""
                titel = " | ".join(info["vorgaenge"])
                zelle = (f"<td style='background:{bg}' title='{titel}'>"
                         f"{info['stunden']:.1f}{deadline}</td>")
            else:
                zelle = "<td></td>"
            zeile += zelle
        zeile += "</tr>"
        zeilen += zeile

    if daten["mitarbeiter"]:
        st.markdown(
            f"<div style='overflow-x:auto'><table class='cal'>{header}{zeilen}</table></div>",
            unsafe_allow_html=True,
        )
        st.caption("🚩 = Vorgangs-Deadline (Ende) an diesem Tag. "
                   "Grün = locker, Gelb = voll, Rot = über Kapazität. "
                   "Mit der Maus über eine Zelle: zugehörige Vorgänge.")
    else:
        st.info("Noch keine Mitarbeiter angelegt.")
