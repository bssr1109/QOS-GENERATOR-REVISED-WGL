"""
BSNL QoS Certificate Generator (Streamlit)
========================================
Download-only Streamlit app to create QoS certificates (two per A4 page)
for each TIP under a Broadband Manager (BBM).
"""

from __future__ import annotations
import os
import base64
from datetime import datetime, date
from io import BytesIO
from typing import Dict

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

st.set_page_config(page_title="QoS Cert Generator", layout="centered")

# ---------------- CONFIG & ASSET PATHS -----------------
CSV_PATH = "bbm_data.csv"
SIGN_DIR = "signatures"
MT_FILE = os.path.join(SIGN_DIR, "mt_sign.b64")

# map default pins if not in CSV
PIN_MAP = {
    "9891055443": "3848",
    "9493432333": "3667",
    "9441131108": "2675",
}

# --------------- UTIL: LOAD A BASE-64 IMAGE ------------

def load_b64_image(path: str) -> BytesIO | None:
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        try:
            return BytesIO(base64.b64decode(f.read()))
        except Exception:
            return None

MT_IMG = load_b64_image(MT_FILE)

# -------------------- LOAD ROSTER ----------------------

def load_roster() -> Dict[str, Dict]:
    if not os.path.isfile(CSV_PATH):
        st.error(f"Roster file '{CSV_PATH}' not found.")
        st.stop()

    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            df = pd.read_csv(CSV_PATH, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        st.error("Unable to decode roster CSV – save it as UTF-8.")
        st.stop()

    users: Dict[str, Dict] = {}
    for _, row in df.iterrows():
        raw_mobile = str(row.get("mobile", row.iloc[0])).strip()
        if not raw_mobile or not raw_mobile[0].isdigit():
            continue
        try:
            mobile = str(int(float(raw_mobile)))
        except ValueError:
            continue

        name = str(row.get("bbm_name", row.iloc[1])).strip()
        tip = str(row.get("tip_name", row.iloc[2])).strip()
        mt_name = str(row.get("mt_name", "")).strip() or "Manager(MT)"
        pin = str(row.get("pin", "")).strip() or PIN_MAP.get(mobile, "0000")

        if mobile not in users:
            users[mobile] = {"name": name, "pin": pin, "mt_name": mt_name, "tips": []}
        users[mobile]["tips"].append(tip)
    return users

ROSTER = load_roster()

# -------------------- PDF HELPERS ----------------------

def wrap_text(c: Canvas, text: str, x: float, y: float, max_w: float, font: str = "Helvetica", size: int = 12) -> float:
    c.setFont(font, size)
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if stringWidth(trial, font, size) <= max_w:
            line = trial
        else:
            c.drawString(x, y, line)
            y -= 0.5 * cm
            line = word
    if line:
        c.drawString(x, y, line)
    return y


def draw_certificate(c: Canvas, cert: Dict, top_cm: float, gen_ts: str):
    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(A4[0] / 2, top_cm * cm, "QoS Certificate")

    # --- Timestamp beside title (top-right corner) ---
    c.setFont("Helvetica", 10)
    c.drawRightString(A4[0] - 2 * cm, top_cm * cm, gen_ts)

    # -------- BODY ---------
    tip_raw = str(cert.get("tip_name", "")).replace("_", " ").strip()
    if not tip_raw:
        tip_raw = "TIP"
    if not tip_raw.lower().startswith("m/s"):
        tip_raw = f"M/S. {tip_raw}"

    body = (
        f"It is to certify that the services provided by {tip_raw}, "
        f"from {cert['from_date'].strftime('%d-%m-%Y')} to {cert['to_date'].strftime('%d-%m-%Y')} "
        f"is satisfactory."
    )
    new_y = wrap_text(c, body, 2 * cm, (top_cm - 1.5) * cm, A4[0] - 4 * cm)

    # Penalty line
    penalty = "NIL" if not cert["penalty_yes"] else f"₹{cert['penalty_amount']:.2f}"
    c.setFont("Helvetica", 12)
    c.drawString(2 * cm, new_y - 1 * cm, f"Penalty: {penalty}")

    # ---------- SIGNATURES ----------
    sig_y = new_y - 5 * cm

    # BBM signature (left)
    if cert.get("bbm_img"):
        c.drawImage(
            ImageReader(cert["bbm_img"]),
            2 * cm,
            sig_y,
            width=4 * cm,
            preserveAspectRatio=True,
            mask="auto",
        )
    c.setFont("Helvetica", 12)
    c.drawString(2 * cm, sig_y - 0.6 * cm, cert["bbm_name"].upper())

    # --- Timestamp below BBM signature ---
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(2 * cm, sig_y - 1.2 * cm, f"Generated: {gen_ts}")

    # Manager(MT) signature (right of BBM)
    if MT_IMG:
        bbm_block_w = 4 * cm if cert.get("bbm_img") else stringWidth(cert["bbm_name"].upper(), "Helvetica", 12)
        gap = 2 * cm
        mt_x = 4 * cm + bbm_block_w + gap
        reader = ImageReader(MT_IMG)
        iw, ih = reader.getSize()
        draw_w = 4 * cm
        draw_h = draw_w * (ih / iw)
        img_y = sig_y - draw_h - 4 * cm
        c.drawImage(reader,
            mt_x,
            img_y,
            width=4 * cm,
            preserveAspectRatio=True,
            mask="auto",
        )

# -------------------- STREAMLIT APP --------------------

def main():
    st.title("QoS Certificate Generator")

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    # ---------- LOGIN ----------
    if not st.session_state.logged_in:
        st.subheader("Login as BBM")
        mobile_in = st.text_input("Mobile number")
        pin_in = st.text_input("PIN", type="password")
        if st.button("Login"):
            user = ROSTER.get(mobile_in.strip())
            if user and pin_in == user["pin"]:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.session_state.mobile = mobile_in.strip()
                st.session_state.todo_tips = user["tips"].copy()
                st.rerun()
            else:
                st.error("Invalid mobile or PIN")
        st.stop()

    user = st.session_state.user

    # ---------- CERT FORM ----------
    st.write(f"**Logged in as:** {user['name']}")
    col1, col2 = st.columns(2)
    from_dt = col1.date_input("From date", value=date.today())
    to_dt = col2.date_input("To date", value=date.today())

    tip = st.selectbox("Select TIP", options=st.session_state.todo_tips)
    pen_yes = st.selectbox("Penalty applicable?", options=["No", "Yes"]) == "Yes"
    pen_amt = 0.0
    if pen_yes:
        pen_amt = st.number_input("Penalty amount (₹)", min_value=0.0, step=0.01)

    add_disabled = not bool(st.session_state.todo_tips)
    if st.button("Add certificate", disabled=add_disabled):
        cert = {
            "tip_name": tip,
            "from_date": from_dt,
            "to_date": to_dt,
            "penalty_yes": pen_yes,
            "penalty_amount": pen_amt,
            "bbm_name": user["name"],
            "mt_name": user["mt_name"],
            "bbm_img": load_b64_image(os.path.join(SIGN_DIR, f"{st.session_state.mobile}.b64")),
        }
        st.session_state.setdefault("certs", []).append(cert)
        if tip in st.session_state.todo_tips:
            st.session_state.todo_tips.remove(tip)
        st.success("Certificate added.")
        st.rerun()

    # ---------- FINISH & DOWNLOAD ----------
    if st.session_state.get("todo_tips") is not None and not st.session_state.todo_tips:
        if st.button("Finish & Download PDF"):
            buffer = BytesIO()
            c = Canvas(buffer, pagesize=A4)

            # fixed generation timestamp for all certificates
            gen_ts = datetime.now().strftime("%d-%m-%Y %H:%M")

            for cert in st.session_state.get("certs", []):
                draw_certificate(c, cert, 27, gen_ts)
                c.showPage()

            c.save()
            pdf_data = buffer.getvalue()
            buffer.close()

            st.download_button(
                "Download PDF",
                pdf_data,
                file_name=f"QoS_Certificates_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf"
            )
            st.balloons()
            st.session_state.clear()
            st.stop()

    # ---------- LOGOUT ----------
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()

if __name__ == "__main__":
    main()
