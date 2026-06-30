"""
app.py – Streamlit-Oberfläche für den Auftragsplaner.

Start:  streamlit run app.py
"""

import streamlit as st
import core

st.set_page_config(page_title="Disponent", page_icon="🗂️", layout="wide")


# --------------------------------------------------------------------------
# Passwort-Schutz – gemeinsames Team-Passwort aus den Secrets
# --------------------------------------------------------------------------
def passwort_ok():
    """Zeigt ein Passwortfeld und gibt True zurueck, sobald es stimmt."""
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
# Styling – ruhige, technische Disposition-Anmutung
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
      :root {
        --schiefer: #2b3440;
        --bernstein: #c8861d;
      }
      /* Hintergruende hell erzwingen, unabhaengig vom System-/Browser-Theme */
      .stApp { background: #f5f6f7; }
      [data-testid="stHeader"] { background: #f5f6f7; }
      section[data-testid="stSidebar"] { background: #ffffff; }

      /* Textfarben explizit setzen, damit Dark-Mode nicht weisse Schrift erbt */
      .stApp, .stApp p, .stApp span, .stApp label, .stApp li,
      .stMarkdown, [data-testid="stMarkdownContainer"] {
        color: var(--schiefer);
      }
      h1, h2, h3, h4 { color: var(--schiefer) !important; letter-spacing: -0.01em; }
      .stApp small { color: #5a6573; }

      /* Eingabefelder hell halten */
      input, textarea, [data-baseweb="select"] > div {
        background: #ffffff !important;
        color: var(--schiefer) !important;
      }

      /* Buttons */
      .stButton button {
        border-radius: 4px;
        border: 1px solid var(--schiefer);
        background: #ffffff;
        color: var(--schiefer);
      }
      .stButton button:hover {
        border-color: var(--bernstein);
        color: var(--bernstein);
      }

      div[data-testid="stMetricValue"] { color: var(--schiefer); }

      .vorschlag {
        border: 1px solid #d9dde2;
        border-left: 4px solid var(--bernstein);
        border-radius: 4px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.6rem;
        background: #ffffff;
        color: var(--schiefer);
      }
      .pill {
        display: inline-block;
        background: #eef1f4;
        color: #2b3440;
        border-radius: 10px;
        padding: 1px 8px;
        margin: 1px 2px;
        font-size: 0.8rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Disponent")
st.caption("Aufträge anlegen, passenden Mitarbeiter vorschlagen lassen, bestätigen.")

tab_dispo, tab_auftraege, tab_mitarbeiter, tab_skills = st.tabs(
    ["Disposition", "Aufträge", "Mitarbeiter", "Fähigkeiten"]
)


# --------------------------------------------------------------------------
# Tab: Fähigkeiten
# --------------------------------------------------------------------------
with tab_skills:
    st.subheader("Fähigkeiten verwalten")
    with st.form("skill_form", clear_on_submit=True):
        neuer_skill = st.text_input("Neue Fähigkeit", placeholder="z. B. Schweißen, CAD, Buchhaltung")
        if st.form_submit_button("Hinzufügen") and neuer_skill.strip():
            core.skill_anlegen(neuer_skill)
            st.success(f"„{neuer_skill}“ hinzugefügt.")

    skills = core.skills_liste()
    if skills:
        st.markdown(
            " ".join(f"<span class='pill'>{s['name']}</span>" for s in skills),
            unsafe_allow_html=True,
        )
    else:
        st.info("Noch keine Fähigkeiten angelegt. Leg zuerst hier welche an – sie werden bei Mitarbeitern und Aufträgen gebraucht.")


# --------------------------------------------------------------------------
# Tab: Mitarbeiter
# --------------------------------------------------------------------------
with tab_mitarbeiter:
    st.subheader("Mitarbeiter anlegen")
    skills = core.skills_liste()

    if not skills:
        st.warning("Lege zuerst im Tab „Fähigkeiten“ mindestens eine Fähigkeit an.")
    else:
        # Bewusst KEIN st.form: so erscheinen die Slider sofort beim Auswaehlen
        # einer Faehigkeit, nicht erst nach dem Speichern.
        col1, col2 = st.columns(2)
        name = col1.text_input("Name", key="neu_name")
        stunden = col2.number_input(
            "Wochenstunden", min_value=1.0, max_value=80.0, value=40.0, step=0.5,
            key="neu_stunden",
        )

        st.markdown("**Fähigkeiten & Level** (1 = Anfänger … 5 = Experte)")
        ausgewaehlt = st.multiselect(
            "Welche Fähigkeiten hat diese Person?",
            options=[s["id"] for s in skills],
            format_func=lambda sid: next(s["name"] for s in skills if s["id"] == sid),
            key="neu_skills",
        )
        level_map = {}
        for sid in ausgewaehlt:
            sname = next(s["name"] for s in skills if s["id"] == sid)
            level_map[sid] = st.slider(f"Level: {sname}", 1, 5, 3, key=f"neu_lvl_{sid}")

        if st.button("Mitarbeiter speichern", key="neu_speichern"):
            if name.strip():
                core.mitarbeiter_anlegen(name, stunden, level_map)
                st.success(f"„{name}“ gespeichert.")
                st.rerun()
            else:
                st.error("Bitte einen Namen eingeben.")

    st.divider()
    st.subheader("Team")
    ma = core.mitarbeiter_liste()
    if not ma:
        st.info("Noch keine Mitarbeiter angelegt.")
    for m in ma:
        c1, c2, c3 = st.columns([3, 2, 4])
        c1.markdown(f"**{m['name']}**")
        c2.markdown(f"{m['frei']:.1f} / {m['wochenstunden']:.0f} h frei")
        skill_pills = " ".join(
            f"<span class='pill'>{s['name']} · {s['level']}</span>" for s in m["skills"]
        ) or "<span class='pill'>keine Fähigkeiten</span>"
        c3.markdown(skill_pills, unsafe_allow_html=True)

        # --- Bearbeiten / Loeschen im aufklappbaren Bereich ---
        with st.expander("Bearbeiten"):
            if not skills:
                st.info("Erst Fähigkeiten anlegen, um Skills zuweisen zu können.")
            e1, e2 = st.columns(2)
            e_name = e1.text_input("Name", value=m["name"], key=f"edit_name_{m['id']}")
            e_stunden = e2.number_input(
                "Wochenstunden", min_value=1.0, max_value=80.0,
                value=float(m["wochenstunden"]), step=0.5, key=f"edit_std_{m['id']}",
            )

            vorhandene = {s["id"]: s["level"] for s in m["skills"]}
            e_auswahl = st.multiselect(
                "Fähigkeiten",
                options=[s["id"] for s in skills],
                default=[sid for sid in vorhandene if sid in [s["id"] for s in skills]],
                format_func=lambda sid: next(s["name"] for s in skills if s["id"] == sid),
                key=f"edit_skills_{m['id']}",
            )
            e_level_map = {}
            for sid in e_auswahl:
                sname = next(s["name"] for s in skills if s["id"] == sid)
                e_level_map[sid] = st.slider(
                    f"Level: {sname}", 1, 5, int(vorhandene.get(sid, 3)),
                    key=f"edit_lvl_{m['id']}_{sid}",
                )

            b1, b2 = st.columns(2)
            if b1.button("Änderungen speichern", key=f"edit_save_{m['id']}"):
                if e_name.strip():
                    core.mitarbeiter_aktualisieren(m["id"], e_name, e_stunden, e_level_map)
                    st.success("Gespeichert.")
                    st.rerun()
                else:
                    st.error("Bitte einen Namen eingeben.")
            if b2.button("Mitarbeiter löschen", key=f"del_ma_{m['id']}"):
                core.mitarbeiter_loeschen(m["id"])
                st.rerun()


# --------------------------------------------------------------------------
# Tab: Aufträge
# --------------------------------------------------------------------------
with tab_auftraege:
    st.subheader("Auftrag anlegen")
    skills = core.skills_liste()

    with st.form("auftrag_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        titel = col1.text_input("Titel", placeholder="z. B. Wartung Anlage B")
        stunden = col2.number_input("Geschätzte Stunden", min_value=0.5, value=8.0, step=0.5)

        benoetigt_ids = st.multiselect(
            "Benötigte Fähigkeiten",
            options=[s["id"] for s in skills],
            format_func=lambda sid: next(s["name"] for s in skills if s["id"] == sid),
        )
        minlevel_map = {}
        for sid in benoetigt_ids:
            sname = next(s["name"] for s in skills if s["id"] == sid)
            minlevel_map[sid] = st.slider(f"Mindest-Level: {sname}", 1, 5, 1, key=f"min_{sid}")

        if st.form_submit_button("Auftrag anlegen"):
            if titel.strip():
                core.auftrag_anlegen(titel, stunden, minlevel_map)
                st.success(f"Auftrag „{titel}“ angelegt.")
                st.rerun()
            else:
                st.error("Bitte einen Titel eingeben.")

    st.divider()
    st.subheader("Alle Aufträge")
    auftraege = core.auftraege_liste()
    if not auftraege:
        st.info("Noch keine Aufträge.")
    for a in auftraege:
        c1, c2, c3, c4 = st.columns([3, 1, 2, 1])
        c1.markdown(f"**{a['titel']}**")
        c2.markdown(f"{a['stunden']:.1f} h")
        if a["status"] == "zugewiesen":
            c3.markdown(f"→ {a['mitarbeiter_name']}")
        else:
            c3.markdown("_offen_")
        if c4.button("Löschen", key=f"del_a_{a['id']}"):
            core.auftrag_loeschen(a["id"])
            st.rerun()


# --------------------------------------------------------------------------
# Tab: Disposition (Kernfunktion)
# --------------------------------------------------------------------------
with tab_dispo:
    st.subheader("Offene Aufträge zuweisen")
    offene = core.auftraege_liste(status="offen")

    if not offene:
        st.info("Keine offenen Aufträge. Leg im Tab „Aufträge“ welche an.")
    else:
        for a in offene:
            with st.container(border=True):
                kopf = f"**{a['titel']}** · {a['stunden']:.1f} h"
                req = " ".join(
                    f"<span class='pill'>{s['name']} ≥ {s['min_level']}</span>"
                    for s in a["skills"]
                )
                st.markdown(kopf)
                if req:
                    st.markdown("Benötigt: " + req, unsafe_allow_html=True)

                vors = core.vorschlaege(a["id"], top_n=5)
                if not vors:
                    st.warning(
                        "Kein passender Mitarbeiter: entweder fehlen Fähigkeiten/Level "
                        "oder es ist nicht genug freie Kapazität vorhanden."
                    )
                else:
                    for rang, v in enumerate(vors, start=1):
                        m = v["mitarbeiter"]
                        b = v["begruendung"]
                        cols = st.columns([4, 2, 1])
                        empfehlung = " · ".join(f"{k}: {val:.2f}" for k, val in b.items())
                        cols[0].markdown(
                            f"<div class='vorschlag'><b>{rang}. {m['name']}</b> "
                            f"&nbsp;<span style='color:#c8861d'>Score {v['score']:.2f}</span><br>"
                            f"<small>{empfehlung}</small></div>",
                            unsafe_allow_html=True,
                        )
                        cols[1].markdown(
                            f"<br>frei danach: **{v['frei_nach']:.1f} h**",
                            unsafe_allow_html=True,
                        )
                        if cols[2].button("Zuweisen", key=f"assign_{a['id']}_{m['id']}"):
                            core.auftrag_zuweisen(a["id"], m["id"])
                            st.success(f"„{a['titel']}“ an {m['name']} zugewiesen.")
                            st.rerun()

    st.divider()
    st.subheader("Bereits zugewiesen")
    zug = core.auftraege_liste(status="zugewiesen")
    if not zug:
        st.caption("Noch nichts zugewiesen.")
    for a in zug:
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.markdown(f"**{a['titel']}** · {a['stunden']:.1f} h → {a['mitarbeiter_name']}")
        if c3.button("Zurücknehmen", key=f"release_{a['id']}"):
            core.auftrag_freigeben(a["id"])
            st.rerun()
