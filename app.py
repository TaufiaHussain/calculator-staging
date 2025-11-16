from supabase import create_client, Client
import streamlit as st
import pandas as pd
import math

# ------------------------------------------------------------
# PAGE
# ------------------------------------------------------------
st.set_page_config(page_title="Lab Solution Calculator", page_icon="🧪", layout="wide")

st.title("🧪 Versatile Lab Solution Calculator")
st.write("Dilutions, serials, plates, solids, % solutions, OD, master mixes, buffers, DMSO checks — all in one.")


@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)

supabase = get_supabase()

# temporary: pretend this is the logged-in user
DEMO_USER_ID = "e29394b6-5f7a-4aa7-8d30-9155165733e3"

def load_reagents(user_id: str):
    data = (
        supabase.table("reagents")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return data.data or []

if "fav_reagents" not in st.session_state:
    st.session_state["fav_reagents"] = []

reagents_db = load_reagents(DEMO_USER_ID)
for r in reagents_db:
    if r["name"] not in st.session_state["fav_reagents"]:
        st.session_state["fav_reagents"].append(r["name"])

# ------------------------------------------------------------
# 3) Auth helpers
# ------------------------------------------------------------
def login(email: str, password: str):
    """Sign in user with email+password."""
    return supabase.auth.sign_in_with_password({"email": email, "password": password})

def signup(email: str, password: str, full_name: str = ""):
    """Create new user (will trigger your SQL to create profile + subscription=free)."""
    return supabase.auth.sign_up({
        "email": email,
        "password": password,
        "options": {
            "data": {"full_name": full_name}
        }
    })

def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    # clear session stuff
    for key in ["user", "plan"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()
    
def get_subscription_plan(user_id: str) -> str:
    """
    Try to read the user's plan from public.subscriptions.
    If table is protected / empty / missing → fall back to 'free'.
    """
    try:
        resp = (
            supabase
            .table("subscriptions")
            .select("plan")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        if len(data) > 0 and "plan" in data[0]:
            return data[0]["plan"]
        return "free"
    except Exception as e:
        # IMPORTANT: don't crash the app here
        st.info("Could not read subscription from Supabase → using FREE.")
        st.write(e)  # you can remove this later
        return "free"

# ------------------------------------------------------------
# 4) LOGIN GATE
# ------------------------------------------------------------
if "auth_session" not in st.session_state:
    st.session_state["auth_session"] = None
if "user" not in st.session_state:
    st.session_state["user"] = None

if st.session_state["user"] is None:
    st.title("🔐 Lab Solution Calculator (Login required)")

    tab_login, tab_signup = st.tabs(["Login", "Sign up"])

    with tab_login:
        lemail = st.text_input("Email", key="login_email")
        lpass = st.text_input("Password", type="password", key="login_password")
        if st.button("Login"):
            try:
                auth_res = login(lemail, lpass)
                st.session_state["auth_session"] = auth_res.session
                st.session_state["user"] = auth_res.user
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with tab_signup:
        semail = st.text_input("Email (for signup)", key="signup_email")
        sname = st.text_input("Full name", key="signup_name")
        spass = st.text_input("Password (min 6 chars)", type="password", key="signup_password")
        if st.button("Create account"):
            try:
                sres = signup(semail, spass, sname)
                st.success("Account created. Now login from the Login tab.")
            except Exception as e:
                st.error(f"Signup failed: {e}")

    st.stop()  # 👈 do NOT show the app below

# ------------------------------------------------------------
# 5) USER IS LOGGED IN → CHECK SUBSCRIPTION
# ------------------------------------------------------------
user = st.session_state["user"]
plan = get_subscription_plan(user.id)

if plan != "pro":
    st.title("🧪 Lab Solution Calculator")
    st.warning("Your plan is **free**. This tool is for **Pro** users.")
    st.info("Ask admin to upgrade you in Supabase → public.subscriptions, or connect Stripe later.")
    st.stop()


    
# ------------------------------------------------------------
# optional PDF
# ------------------------------------------------------------
try:
    from fpdf import FPDF
    HAS_FPDF = True
except Exception:
    HAS_FPDF = False


def make_pdf_report(title: str, lines: list[str]) -> bytes | None:
    """Small helper to build a PDF from lines. Needs fpdf."""
    if not HAS_FPDF:
        return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, txt=title, ln=1)
    pdf.ln(3)
    for ln in lines:
        pdf.multi_cell(0, 6, txt=ln)
    return pdf.output(dest="S").encode("latin-1")


# ------------------------------------------------------------
# SIDEBAR: user profile / dark mode / presets
# ------------------------------------------------------------
if "fav_reagents" not in st.session_state:
    st.session_state["fav_reagents"] = []
if "username" not in st.session_state:
    st.session_state["username"] = ""

dark_mode = st.sidebar.checkbox("🌙 Dark mode", value=False)

if dark_mode:
    st.markdown(
        """
        <style>
        body, .stApp {
            background: #0f172a;
            color: #ffffff;
        }
        .stButton>button {
            background: #1f2937;
            color: #fff;
        }
        .stDataFrame {
            background: #0f172a;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# lab presets
preset = st.sidebar.selectbox(
    "Lab preset",
    [
        "Custom",
        "Cell culture (0.1% DMSO, 300 µl)",
        "Chemistry (no vehicle, 1000 µl)",
        "qPCR / assay (20 µl)",
    ],
)

st.sidebar.header("Global settings")

# defaults from preset
_default_well = 300.0
_default_max_vehicle = 0.1
_default_vehicle_type = "Aqueous / none"
_default_stock_vehicle_percent = 100.0

if preset == "Cell culture (0.1% DMSO, 300 µl)":
    _default_well = 300.0
    _default_max_vehicle = 0.1
    _default_vehicle_type = "DMSO"
elif preset == "Chemistry (no vehicle, 1000 µl)":
    _default_well = 1000.0
    _default_max_vehicle = 0.0
    _default_vehicle_type = "Aqueous / none"
elif preset == "qPCR / assay (20 µl)":
    _default_well = 20.0
    _default_max_vehicle = 0.5
    _default_vehicle_type = "Aqueous / none"

# actual inputs
well_volume = st.sidebar.number_input("Default well / final volume (µl)", value=_default_well, min_value=1.0)

max_vehicle = st.sidebar.number_input(
    "Max allowed DMSO/EtOH in final (%)",
    value=_default_max_vehicle,
    min_value=0.0,
    step=0.05,
    help="Typical cell culture limit is 0.1–0.5 %."
)

vehicle_type = st.sidebar.selectbox(
    "Stock vehicle",
    ["Aqueous / none", "DMSO", "EtOH"],
    index=["Aqueous / none", "DMSO", "EtOH"].index(_default_vehicle_type),
    help="Select the solvent in which your STOCK is dissolved.",
)

stock_vehicle_percent = st.sidebar.number_input(
    "Stock vehicle % (e.g. 100 for pure DMSO, 50 for 1:1 DMSO:water)",
    value=_default_stock_vehicle_percent,
    min_value=0.0,
    max_value=100.0,
    step=5.0,
)

vehicle_frac = 0.0
if vehicle_type != "Aqueous / none" and stock_vehicle_percent > 0:
    vehicle_frac = stock_vehicle_percent / 100.0

# user profile / favorites
with st.sidebar.expander("👤 User profile / favorites", expanded=False):
    username = st.text_input("Your name", value=st.session_state["username"])
    st.session_state["username"] = username
    if st.session_state["fav_reagents"]:
        st.write("⭐ Saved reagents:")
        for r in st.session_state["fav_reagents"]:
            st.write("- ", r)
    else:
        st.write("No saved reagents yet.")

with st.sidebar:
    user = st.session_state.get("user")
    if user:
        st.markdown(f"**Logged in as:** {user.email}")
        if st.button("Logout"):
            logout()
    else:
        st.info("Please log in to use Pro tools.")

# ------------------------------------------------------------
# MAIN MODE SELECTOR
# ------------------------------------------------------------
mode = st.selectbox(
    "Select calculator mode:",
    [
        "Single dilution (C1V1 = C2V2)",
        "Serial dilutions",
        "Experiment series (plate-like)",
        "From solid (mg → solution)",
        "Unit converter (mg/mL ↔ mM)",
        "% solutions (w/v, v/v)",
        "Molarity from mass & volume",
        "OD / culture dilution",
        "Master mix / qPCR mix",
        "Make X× stock from current stock",
        "Acid / base dilution (common reagents)",
        "Buffer helper (PBS / TBS / Tris)",
        "Beer–Lambert / A280",
        "Cell seeding calculator",
        "Plate DMSO cap checker",
        "Aliquot splitter",
        "Storage / stability helper",
    ]
)

# share calculation (stores mode in URL)
if st.button("🔗 Make this URL shareable for this mode"):
    st.experimental_set_query_params(mode=mode)
    st.success("Query params set. Copy the URL from your browser and share it.")

# ======================================================================
# 1) SINGLE DILUTION
# ======================================================================
if mode == "Single dilution (C1V1 = C2V2)":
    st.subheader("Single dilution")

    col1, col2 = st.columns(2)
    with col1:
        stock_conc = st.number_input("Stock concentration", value=25.0, min_value=0.000001)
        stock_unit = st.selectbox("Stock unit", ["mM", "µM"])
    with col2:
        target_conc = st.number_input("Target concentration", value=4.0, min_value=0.000001)
        target_unit = st.selectbox("Target unit", ["mM", "µM"])

    show_steps = st.checkbox("Show protocol-style steps", value=True)

    if stock_unit != target_unit:
        st.error("For now, keep units the same (mM→mM or µM→µM).")
    else:
        v1_ul = (target_conc * well_volume) / stock_conc
        solvent_ul = well_volume - v1_ul
        if solvent_ul < 0:
            solvent_ul = 0.0
        vehicle_percent = (v1_ul * vehicle_frac / well_volume) * 100

        st.markdown("### Result")
        st.write(f"- Pipette **{v1_ul:.2f} µl** from stock")
        st.write(f"- Add solvent / medium **{solvent_ul:.2f} µl** to reach **{well_volume:.0f} µl**")
        st.write(f"- Final vehicle (DMSO/EtOH): **{vehicle_percent:.4f} %**")

        if vehicle_percent > max_vehicle:
            st.warning(
                f"Vehicle {vehicle_percent:.4f}% > allowed {max_vehicle:.2f}%. "
                "Make a more dilute stock OR increase final volume."
            )

        min_pip = 1.0
        if v1_ul < min_pip:
            c_intermediate = (target_conc * well_volume) / min_pip
            st.warning(
                f"Volume from stock is very small ({v1_ul:.3f} µl). "
                f"👉 Make an intermediate stock ≈ {c_intermediate:.3f} {target_unit} and repeat."
            )

        if show_steps:
            st.markdown("#### Steps")
            st.markdown(f"1. Label a tube with target conc: **{target_conc} {target_unit}**.")
            st.markdown(f"2. Pipette **{v1_ul:.2f} µl** of the stock solution into the tube.")
            st.markdown(f"3. Add **{solvent_ul:.2f} µl** of medium / buffer.")
            st.markdown("4. Mix gently. Protect from light if compound is light-sensitive.")
            st.markdown("5. Use immediately or aliquot / store as protocol allows.")

        # PDF
        if HAS_FPDF:
            if st.button("📄 Export this as PDF"):
                lines = [
                    f"Mode: Single dilution",
                    f"Stock: {stock_conc} {stock_unit}",
                    f"Target: {target_conc} {target_unit}",
                    f"Final volume: {well_volume} µl",
                    f"Take from stock: {v1_ul:.2f} µl",
                    f"Add solvent: {solvent_ul:.2f} µl",
                    f"Vehicle: {vehicle_percent:.4f} %",
                ]
                pdf_bytes = make_pdf_report("Single dilution report", lines)
                st.download_button("⬇ Download PDF", data=pdf_bytes, file_name="single_dilution.pdf")
        else:
            st.info("Install `fpdf` to enable PDF export: `pip install fpdf`")

# ======================================================================
# 2) SERIAL DILUTIONS
# ======================================================================
elif mode == "Serial dilutions":
    st.subheader("Serial dilutions")

    start_conc = st.number_input("Start concentration (mM)", value=25.0, min_value=0.000001)
    n_steps = st.number_input("Number of dilutions", value=5, min_value=1, step=1)
    dil_factor = st.number_input("Dilution factor (e.g. 2 for 1:2)", value=2.0, min_value=1.0001)
    final_vol_each = st.number_input("Final volume for each tube (µl)", value=100.0, min_value=5.0)

    rows = []
    current_conc = start_conc
    min_pip = 1.0
    for i in range(int(n_steps)):
        next_conc = current_conc / dil_factor
        v1_ul = (next_conc * final_vol_each) / current_conc
        solvent_ul = final_vol_each - v1_ul
        vehicle_percent = (v1_ul * vehicle_frac / final_vol_each) * 100

        warning_flag = ""
        if v1_ul < min_pip:
            warning_flag = "<1 µl → make intermediate"

        rows.append({
            "step": i + 1,
            "from (mM)": round(current_conc, 6),
            "to (mM)": round(next_conc, 6),
            "take from prev (µl)": round(v1_ul, 3),
            "add solvent (µl)": round(solvent_ul, 3),
            "vehicle %": round(vehicle_percent, 5),
            "note": warning_flag,
        })

        current_conc = next_conc

    df = pd.DataFrame(rows)
    st.write("### Dilution plan")
    st.dataframe(df)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download CSV", data=csv, file_name="serial_dilutions.csv")

    if HAS_FPDF:
        if st.button("📄 Export as PDF"):
            lines = ["Serial dilution plan:"]
            for r in rows:
                lines.append(str(r))
            pdf_bytes = make_pdf_report("Serial dilutions", lines)
            st.download_button("⬇ Download PDF", data=pdf_bytes, file_name="serial_dilutions.pdf")

# ======================================================================
# 3) EXPERIMENT SERIES (PLATE-LIKE)
# ======================================================================
elif mode == "Experiment series (plate-like)":
    st.subheader("Experiment series (fixed final volume)")

    st.write("Enter final concentrations (µM), separated by commas, e.g. `0.01,0.1,1,3,10`")
    conc_txt = st.text_input("Final concentrations (µM)", value="0.01,0.1,1,3,10")
    stock_conc_uM = st.number_input("Stock concentration (µM)", value=10000.0, min_value=0.0001)

    reps = st.number_input("Replicates per concentration (wells)", value=3, min_value=1, step=1)
    overfill = st.number_input("Overfill factor (1.0 = exact, 1.1 = +10%)", value=1.1, min_value=1.0, step=0.05)

    concs = [float(x.strip()) for x in conc_txt.split(",") if x.strip()]
    table = []
    for c in concs:
        v1_ul = (c * well_volume) / stock_conc_uM
        solvent_ul = well_volume - v1_ul
        vehicle_percent = (v1_ul * vehicle_frac / well_volume) * 100
        total_vol_ul = (v1_ul + solvent_ul) * reps * overfill

        table.append({
            "final conc (µM)": c,
            "add stock (µl) / well": round(v1_ul, 3),
            "add medium (µl) / well": round(solvent_ul, 3),
            "vehicle %": round(vehicle_percent, 5),
            "OK?": "⚠ > limit" if vehicle_percent > max_vehicle else "✅",
            "total vol to prepare (µl)": round(total_vol_ul, 1),
        })

    df = pd.DataFrame(table)
    st.dataframe(df)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇ Download dilution plan as CSV",
        csv,
        "dilution_plan.csv",
        "text/csv"
    )

    if HAS_FPDF:
        if st.button("📄 Export as PDF"):
            lines = ["Experiment series plan:"]
            for row in table:
                lines.append(str(row))
            pdf_bytes = make_pdf_report("Experiment series", lines)
            st.download_button("⬇ Download PDF", data=pdf_bytes, file_name="experiment_series.pdf")

# ======================================================================
# 4) FROM SOLID (MG → SOLUTION)
# ======================================================================
elif mode == "From solid (mg → solution)":
    st.subheader("From solid (mg → solution)")
    st.write("Use this when you only know how many mg you bought and you want a certain µM/mM in a given volume.")

    compound = st.selectbox(
        "Choose compound (optional)",
        ["-- custom --", "Retinal (284.44)", "AMPA (192.17)", "Forskolin (410.5)", "Retinoic acid (300.44)", "GABA (103.12)"]
    )

    light_sensitive_words = ["retinal", "retinoic", "rhodamine", "fitc"]

    if compound == "Retinal (284.44)":
        default_mw = 284.44
        compound_name = "retinal"
    elif compound == "AMPA (192.17)":
        default_mw = 192.17
        compound_name = "ampa"
    elif compound == "Forskolin (410.5)":
        default_mw = 410.5
        compound_name = "forskolin"
    elif compound == "Retinoic acid (300.44)":
        default_mw = 300.44
        compound_name = "retinoic acid"
    elif compound == "GABA (103.12)":
        default_mw = 103.12
        compound_name = "gaba"
    else:
        default_mw = 284.44  # safe default
        compound_name = st.text_input("Compound name (for notes / warnings)", "")

    mass_mg = st.number_input("Mass (mg)", value=50.0, min_value=0.0001)
    mw = st.number_input("Molecular weight (g/mol)", value=default_mw, min_value=1.0)
    target_unit = st.selectbox("Target concentration unit", ["µM", "mM"])
    target_conc = st.number_input("Target concentration", value=100.0, min_value=0.0001)
    final_vol_ml = st.number_input("Final volume to prepare (mL)", value=20.0, min_value=0.1)

    if target_unit == "µM":
        C = target_conc * 1e-6   # mol/L
    else:
        C = target_conc * 1e-3   # mol/L

    V_L = final_vol_ml / 1000.0
    m_needed_g = C * V_L * mw
    m_needed_mg = m_needed_g * 1000

    st.markdown(f"**To make {final_vol_ml:.1f} mL at {target_conc} {target_unit}, you must weigh ≈ {m_needed_mg:.3f} mg.**")

    # if I dissolve everything
    mass_g = mass_mg / 1000.0
    n_mol = mass_g / mw
    stock_if_1ml_mM = (n_mol / 0.001) * 1000   # mol/L → mM
    stock_if_2ml_mM = (n_mol / 0.002) * 1000

    st.write("If you dissolve ALL your powder:")
    st.write(f"- in **1.0 mL** → **{stock_if_1ml_mM:.1f} mM** stock")
    st.write(f"- in **2.0 mL** → **{stock_if_2ml_mM:.1f} mM** stock")

    name_to_check = (compound_name or "").lower()
    if any(word in name_to_check for word in light_sensitive_words):
        st.warning("This compound looks light-sensitive. Protect from light (amber tube / foil), use dry EtOH or DMSO, aliquot, store cold.")

    # save to favorites
    if st.button("⭐ Save this reagent to my favorites"):
       if compound_name:
        # save in session
        if compound_name not in st.session_state["fav_reagents"]:
            st.session_state["fav_reagents"].append(compound_name)

        # save in Supabase
        supabase.table("reagents").insert(
            {
                "user_id": DEMO_USER_ID,
                "name": compound_name,
                "mw": mw,
                "note": "from app",
            }
        ).execute()

        st.success(f"Saved '{compound_name}' to Supabase + session.")
    else:
        st.warning("Give the compound a name first.")

    if HAS_FPDF:
        if st.button("📄 Export this as PDF"):
            lines = [
                f"Compound: {compound_name or compound}",
                f"Mass available: {mass_mg} mg",
                f"MW: {mw} g/mol",
                f"Target: {target_conc} {target_unit} in {final_vol_ml} mL",
                f"Mass needed: {m_needed_mg:.3f} mg",
                f"Stock if all dissolved in 1 mL: {stock_if_1ml_mM:.1f} mM",
                f"Stock if all dissolved in 2 mL: {stock_if_2ml_mM:.1f} mM",
            ]
            pdf_bytes = make_pdf_report("Solid → solution report", lines)
            st.download_button("⬇ Download PDF", data=pdf_bytes, file_name="solid_to_solution.pdf")

# ======================================================================
# 5) UNIT CONVERTER
# ======================================================================
elif mode == "Unit converter (mg/mL ↔ mM)":
    st.subheader("Unit converter (mg/mL ↔ mM)")

    mw = st.number_input("Molecular weight (g/mol)", value=284.44, min_value=1.0)
    direction = st.radio("Convert", ["mg/mL → mM", "mM → mg/mL"])

    if direction == "mg/mL → mM":
        mgml = st.number_input("Concentration (mg/mL)", value=1.0, min_value=0.0)
        mM = (mgml * 1000.0) / mw
        st.success(f"{mgml} mg/mL  →  {mM:.3f} mM")
    else:
        mM = st.number_input("Concentration (mM)", value=1.0, min_value=0.0)
        mgml = (mM * mw) / 1000.0
        st.success(f"{mM} mM  →  {mgml:.3f} mg/mL")

# ======================================================================
# 6) % SOLUTIONS
# ======================================================================
elif mode == "% solutions (w/v, v/v)":
    st.subheader("% solutions (w/v, v/v)")

    percent_type = st.radio("Type", ["w/v (g per 100 mL)", "v/v (mL per 100 mL)"])

    final_vol_ml = st.number_input("Final volume (mL)", value=100.0, min_value=1.0)
    percent = st.number_input("Percent (%)", value=2.0, min_value=0.0)

    if percent_type == "w/v (g per 100 mL)":
        grams_needed = (percent / 100.0) * final_vol_ml
        st.success(f"To make {percent}% w/v, weigh **{grams_needed:.3f} g** and bring volume to {final_vol_ml:.1f} mL.")
    else:
        ml_needed = (percent / 100.0) * final_vol_ml
        st.success(f"To make {percent}% v/v, measure **{ml_needed:.3f} mL** of solute and add solvent to {final_vol_ml:.1f} mL.")

# ======================================================================
# 7) MOLARITY FROM MASS & VOLUME
# ======================================================================
elif mode == "Molarity from mass & volume":
    st.subheader("Molarity from mass & volume")
    st.write("Example: I dissolved 12 mg in 10 mL, what is the molarity?")

    mass_mg = st.number_input("Mass dissolved (mg)", value=12.0, min_value=0.0)
    mw = st.number_input("Molecular weight (g/mol)", value=284.44, min_value=1.0)
    vol_ml = st.number_input("Final volume (mL)", value=10.0, min_value=0.01)

    mass_g = mass_mg / 1000.0
    vol_L = vol_ml / 1000.0
    if vol_L > 0:
        moles = mass_g / mw
        molarity = moles / vol_L
        st.success(f"Molarity = **{molarity:.4f} M** ({molarity*1000:.2f} mM)")
    else:
        st.error("Volume must be > 0")

# ======================================================================
# 8) OD / CULTURE DILUTION
# ======================================================================
elif mode == "OD / culture dilution":
    st.subheader("OD / culture dilution")
    st.write("C1V1 = C2V2, but for cultures.")

    od_start = st.number_input("Starting OD / cell density (C1)", value=1.2, min_value=0.0001)
    od_target = st.number_input("Target OD (C2)", value=0.1, min_value=0.0001)
    final_vol_ml = st.number_input("Final volume to prepare (mL)", value=10.0, min_value=0.1)

    v1_ml = (od_target * final_vol_ml) / od_start
    diluent_ml = final_vol_ml - v1_ml

    st.write(f"- Take **{v1_ml:.2f} mL** of culture")
    st.write(f"- Add **{diluent_ml:.2f} mL** of medium to reach **{final_vol_ml:.2f} mL** at OD {od_target}")

# ======================================================================
# 9) MASTER MIX / qPCR MIX
# ======================================================================
elif mode == "Master mix / qPCR mix":
    st.subheader("Master mix / qPCR mix")

    n_rxn = st.number_input("Number of reactions", value=10, min_value=1, step=1)
    rxn_vol_ul = st.number_input("Reaction volume (µl)", value=20.0, min_value=5.0)
    overfill = st.number_input("Overfill factor (1.0 = exact, 1.1 = +10%)", value=1.1, min_value=1.0, step=0.05)

    st.write("Specify components in µL per reaction:")
    col1, col2, col3 = st.columns(3)
    with col1:
        buf = st.number_input("Buffer / Master mix (µl)", value=10.0, min_value=0.0)
        dntp = st.number_input("dNTP / MgCl2 (µl)", value=0.0, min_value=0.0)
    with col2:
        primer_f = st.number_input("Primer F (µl)", value=0.5, min_value=0.0)
        primer_r = st.number_input("Primer R (µl)", value=0.5, min_value=0.0)
    with col3:
        template = st.number_input("Template (µl)", value=1.0, min_value=0.0)
        polymerase = st.number_input("Polymerase / enzyme (µl)", value=0.2, min_value=0.0)

    per_rxn_sum = buf + dntp + primer_f + primer_r + template + polymerase
    other_needed = rxn_vol_ul - per_rxn_sum
    if other_needed < 0:
        st.error("Sum of components exceeds reaction volume — reduce some components.")
    total_rxn = n_rxn * overfill

    st.markdown("### Total mix to prepare")
    st.write(f"- Buffer / Master mix: **{buf * total_rxn:.2f} µl**")
    st.write(f"- dNTP / MgCl2: **{dntp * total_rxn:.2f} µl**")
    st.write(f"- Primer F: **{primer_f * total_rxn:.2f} µl**")
    st.write(f"- Primer R: **{primer_r * total_rxn:.2f} µl**")
    st.write(f"- Polymerase: **{polymerase * total_rxn:.2f} µl**")
    st.write(f"- Template (add separately if different): **{template * n_rxn:.2f} µl**")
    if other_needed > 0:
        st.write(f"- Nuclease-free water: **{other_needed * total_rxn:.2f} µl**")

# ======================================================================
# 10) MAKE X× STOCK
# ======================================================================
elif mode == "Make X× stock from current stock":
    st.subheader("Make X× stock from current stock")

    current_conc = st.number_input("Current concentration (e.g. 1×)", value=1.0, min_value=0.0001)
    desired_mult = st.number_input("Desired stock multiple (e.g. 10 for 10×)", value=10.0, min_value=1.0)
    final_vol_ml = st.number_input("Final stock volume to make (mL)", value=50.0, min_value=1.0)

    V1 = final_vol_ml / desired_mult
    solvent_ml = final_vol_ml - V1

    st.write(f"- Take **{V1:.2f} mL** of your current solution")
    st.write(f"- Add **{solvent_ml:.2f} mL** solvent to get **{final_vol_ml:.2f} mL** of **{desired_mult:.0f}×**")

# ======================================================================
# 11) ACID / BASE DILUTION
# ======================================================================
elif mode == "Acid / base dilution (common reagents)":
    st.subheader("Acid / base dilution (common reagents)")
    st.write("Compute volume of concentrated reagent (HCl, H₂SO₄, NH₃) to make a given molarity & volume.")

    reagents = {
        "HCl 37%": {"density": 1.19, "purity": 0.37, "mw": 36.46},
        "H2SO4 98%": {"density": 1.84, "purity": 0.98, "mw": 98.08},
        "NH3 25%": {"density": 0.91, "purity": 0.25, "mw": 17.03},
    }

    reagent_name = st.selectbox("Reagent", list(reagents.keys()))
    target_m = st.number_input("Target molarity (M)", value=1.0, min_value=0.0001)
    final_vol_L = st.number_input("Final volume (L)", value=1.0, min_value=0.01)

    r = reagents[reagent_name]
    moles_needed = target_m * final_vol_L
    mass_pure = moles_needed * r["mw"]
    mass_conc = mass_pure / r["purity"]
    vol_conc_L = mass_conc / r["density"]
    vol_conc_ml = vol_conc_L * 1000

    st.success(
        f"For {target_m} M {reagent_name} in {final_vol_L} L:\n"
        f"- Weigh/measure **{vol_conc_ml:.1f} mL** of concentrated {reagent_name}\n"
        f"- Add to water and bring to volume."
    )
    st.info("Always add acid to water, not water to acid.")

# ======================================================================
# 12) BUFFER HELPER
# ======================================================================
elif mode == "Buffer helper (PBS / TBS / Tris)":
    st.subheader("Buffer helper")

    buffer_type = st.selectbox("Buffer", ["PBS 1× (1 L)", "PBS 10× (1 L)", "TBS 1× (1 L)", "Tris 1 M (pH 8.0, 1 L)"])

    if buffer_type == "PBS 1× (1 L)":
        st.write("**PBS 1× (pH 7.4) for 1 L**")
        st.write("- NaCl: 8.0 g")
        st.write("- KCl: 0.2 g")
        st.write("- Na2HPO4 (anhydrous): 1.44 g")
        st.write("- KH2PO4: 0.24 g")
        st.write("- Dissolve in ~800 mL, adjust pH, bring to 1 L.")
    elif buffer_type == "PBS 10× (1 L)":
        st.write("**PBS 10× (pH 7.4) for 1 L**")
        st.write("- NaCl: 80 g")
        st.write("- KCl: 2 g")
        st.write("- Na2HPO4: 14.4 g")
        st.write("- KH2PO4: 2.4 g")
        st.write("- Dissolve, adjust, bring to 1 L.")
    elif buffer_type == "TBS 1× (1 L)":
        st.write("**TBS 1× for 1 L**")
        st.write("- NaCl: 8.0 g")
        st.write("- Tris base: 3.0 g")
        st.write("- Adjust pH to 7.4–7.6 with HCl, bring to 1 L.")
    else:
        st.write("**Tris 1 M pH 8.0 (1 L)**")
        st.write("- Tris base (MW 121.14): 121.14 g")
        st.write("- Dissolve ~800 mL, adjust pH with HCl, bring to 1 L.")

# ======================================================================
# 13) BEER–LAMBERT
# ======================================================================
elif mode == "Beer–Lambert / A280":
    st.subheader("Beer–Lambert / A280")

    absorbance = st.number_input("Absorbance (A)", value=0.5, min_value=0.0)
    epsilon = st.number_input("Extinction coefficient (M⁻¹ cm⁻¹)", value=50000.0, min_value=1.0)
    pathlength = st.number_input("Pathlength (cm)", value=1.0, min_value=0.01)

    if epsilon > 0 and pathlength > 0:
        conc_M = absorbance / (epsilon * pathlength)
        st.success(f"Concentration = {conc_M:.6f} M  ({conc_M*1000:.3f} mM)")
    else:
        st.error("Epsilon and pathlength must be > 0")

# ======================================================================
# 14) CELL SEEDING
# ======================================================================
elif mode == "Cell seeding calculator":
    st.subheader("Cell seeding calculator")

    stock_density = st.number_input("Current cell suspension (cells/mL)", value=1_500_000, min_value=1)
    target_density = st.number_input("Target cells per well/dish", value=200_000, min_value=1)
    final_volume_ml = st.number_input("Final volume per well/dish (mL)", value=2.0, min_value=0.1)

    vol_cells_ml = target_density / stock_density
    vol_medium_ml = final_volume_ml - vol_cells_ml

    st.write(f"- Take **{vol_cells_ml:.3f} mL** of cell suspension")
    st.write(f"- Add **{vol_medium_ml:.3f} mL** of medium to reach {final_volume_ml:.2f} mL with {target_density} cells")

# ======================================================================
# 15) PLATE DMSO CAP CHECKER
# ======================================================================
elif mode == "Plate DMSO cap checker":
    st.subheader("Plate DMSO cap checker")
    st.write("Enter final concentrations (µM) exactly like in the plate-like mode. We'll flag any wells > DMSO limit.")

    conc_txt = st.text_input("Final concentrations (µM)", value="0.01,0.1,1,3,10")
    stock_conc_uM = st.number_input("Stock concentration (µM)", value=10000.0, min_value=0.0001)
    dmso_cap = st.number_input("DMSO cap (%)", value=max_vehicle, min_value=0.0, step=0.05)

    concs = [float(x.strip()) for x in conc_txt.split(",") if x.strip()]
    rows = []
    for c in concs:
        v1_ul = (c * well_volume) / stock_conc_uM
        dmso_percent = (v1_ul * vehicle_frac / well_volume) * 100
        rows.append({
            "final conc (µM)": c,
            "stock vol (µl)": round(v1_ul, 3),
            "DMSO / EtOH %": round(dmso_percent, 5),
            "OK?": "✅" if dmso_percent <= dmso_cap else "⚠ EXCEEDS",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df)

# ======================================================================
# 16) ALIQUOT SPLITTER
# ======================================================================
elif mode == "Aliquot splitter":
    st.subheader("Aliquot splitter")

    total_vol_ml = st.number_input("Total volume you have (mL)", value=2.0, min_value=0.01)
    aliquot_vol_ml = st.number_input("Aliquot size (mL)", value=0.1, min_value=0.001)
    dead_vol_ml = st.number_input("Keep dead volume (mL)", value=0.0, min_value=0.0)

    usable_vol_ml = total_vol_ml - dead_vol_ml
    if usable_vol_ml <= 0:
        st.error("Dead volume is ≥ total volume.")
    else:
        n_aliquots = math.floor(usable_vol_ml / aliquot_vol_ml)
        leftover = usable_vol_ml - n_aliquots * aliquot_vol_ml
        st.write(f"- You can make **{n_aliquots} aliquots** of {aliquot_vol_ml} mL")
        st.write(f"- Leftover (not aliquoted): **{leftover:.3f} mL**")
        if dead_vol_ml > 0:
            st.info(f"{dead_vol_ml} mL reserved as dead volume.")

# ======================================================================
# 17) STORAGE / STABILITY
# ======================================================================
else:  # "Storage / stability helper"
    st.subheader("Storage / stability helper")

    name = st.text_input("Compound / solution name", "")
    storage_dict = {
        "retinal": "Protect from light, dissolve in dry EtOH or DMSO, aliquot, store at -20°C or below.",
        "retinoic": "Light-sensitive, store at -20°C, use fresh aliquots.",
        "ampicillin": "Store stock at -20°C, avoid repeated freeze–thaw.",
        "pbs": "Room temp or 4°C, 1 month.",
        "tris": "Room temp, 1 month.",
        "pfa": "4°C, protected from light, check for precipitate.",
    }

    out = None
    for key, val in storage_dict.items():
        if key in name.lower():
            out = val
            break

    if out:
        st.success(out)
    else:
        st.info("No specific rule found. General rule: store at 4°C for short term, -20°C for long term, protect from light if colored/retinoid.")

# ------------------------------------------------------------
# FOOTER
# ------------------------------------------------------------
st.markdown(
    """
    <style>
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background: #0f172a;
        color: white;
        text-align: center;
        padding: 6px 0;
        font-size: 0.8rem;
        z-index: 9999;
    }
    </style>
    <div class="footer">
        © 2025 DataLens.Tools
    </div>
    """,
    unsafe_allow_html=True,
)
