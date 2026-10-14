import os
import sqlite3
from datetime import datetime, timezone
from dotenv import load_dotenv
import requests
import streamlit as st
from auth import get_bmkg_credentials
from metar import convert_synop_to_metar_peraturan

# Load credentials from .env
load_dotenv()
DEFAULT_USER = os.getenv("BMKG_USERNAME", "96595")
DEFAULT_PASS = os.getenv("BMKG_PASSWORD", "opr96595")

st.set_page_config(page_title="BMKG Station ME 48 Entry", layout="wide")
st.title("Station ME 48 Observation & BMKGSoft Sync")

# --- STATION CONFIGURATION ---
BASE_URL = "https://bmkgsatu.bmkg.go.id/api/v21"
STATION_ID = 54  # WAGB / Station 96595
PRIMARY_SYNOP_HOURS = [0, 3, 6, 9, 12, 15, 18, 21]

# Station Observer Roster
OBSERVER_ROSTER = {
    "Emir Hazam": 5882,
    "Dhimaz": 2273,
    "Adrian": 6480,
    "Other / Custom ID": None,
}

# Alias for compatibility with form sections
OBSERVER_DICT = OBSERVER_ROSTER

DIGI_FLAG_KEYS = [
    "wind_dir_deg_dd_digi_flag",
    "wind_speed_ff_digi_flag",
    "rainfall_last_mm_digi_flag",
    "temp_drybulb_c_tttttt_digi_flag",
    "temp_max_c_txtxtx_digi_flag",
    "temp_min_c_tntntn_digi_flag",
    "temp_wetbulb_c_digi_flag",
    "solar_rad_24h_jcm2_f24_digi_flag",
    "sunshine_h_sss_digi_flag",
    "evaporation_24hours_mm_eee_digi_flag",
    "pressure_qff_mb_derived_digi_flag",
    "pressure_qfe_mb_derived_digi_flag",
]

# --- HELPER FUNCTIONS ---
def extract_bmkg_synop(response_json):
  """Robustly extracts the server-generated SYNOP string from BMKGSoft API responses."""
  if not response_json or not isinstance(response_json, dict):
    return ""

  # 1. Direct key checks
  data_block = response_json.get("data")
  if isinstance(data_block, dict):
    if data_block.get("encoded_synop"):
      return data_block["encoded_synop"]

    manual = data_block.get("manual_entry")
    if isinstance(manual, dict):
      if manual.get("edited_encoded_synop"):
        return manual["edited_encoded_synop"]
      if manual.get("encoded_synop"):
        return manual["encoded_synop"]

  # 2. Recursive fallback search for any string containing 'AAXX'
  def deep_search(obj):
    if isinstance(obj, dict):
      for val in obj.values():
        res = deep_search(val)
        if res:
          return res
    elif isinstance(obj, list):
      for item in obj:
        res = deep_search(item)
        if res:
          return res
    elif isinstance(obj, str) and ("AAXX" in obj or "SIID" in obj or "SMID" in obj):
      return obj
    return ""

  return deep_search(response_json)


def get_bmkg_preview_synop(headers, payload, iso_utc_timestamp):
  """Calls BMKGSoft /entry/preview endpoint using the station and date URL parameters."""
  preview_url = f"{BASE_URL}/sinoptik/entry/preview/station/{STATION_ID}/date/{iso_utc_timestamp}"

  try:
    res = requests.post(preview_url, json=payload, headers=headers, timeout=10)
    try:
      res_json = res.json()
    except Exception:
      res_json = {"raw_response": res.text}

    if res.status_code in [200, 201]:
      data_block = res_json.get("data", {})
      synop = ""
      if isinstance(data_block, dict):
        synop = data_block.get("encoded_synop") or ""
        if not synop:
          manual = data_block.get("manual_entry", {})
          if isinstance(manual, dict):
            synop = manual.get("edited_encoded_synop") or ""
      return synop, res_json, res.status_code
    else:
      return "", res_json, res.status_code

  except Exception as err:
    return "", {"error": str(err)}, 0

# --- LOCAL DATABASE FUNCTIONS ---
def save_local_observation(payload, synop_code):
  conn = sqlite3.connect("station_me48.db")
  cursor = conn.cursor()
  cursor.execute(
      """
        INSERT OR REPLACE INTO me48_observations (
            data_timestamp, bmkgsoft_id, observer_id,
            temp_drybulb_c, temp_wetbulb_c, temp_max_c, temp_min_c,
            pressure_qff_mb, pressure_qfe_mb, wind_dir_deg, wind_speed_ff,
            visibility_vv, present_weather_ww, past_weather_w1, past_weather_w2,
            rainfall_last_mm, cloud_cover_oktas, cloud_low_type, cloud_med_type, cloud_high_type,
            encoded_synop, synced_to_bmkg
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """,
      (
          payload["data_timestamp"],
          STATION_ID,
          payload["observer_id"],
          payload["temp_drybulb_c_tttttt"],
          payload["temp_wetbulb_c"],
          payload["temp_max_c_txtxtx"],
          payload["temp_min_c_tntntn"],
          payload["pressure_qff_mb_derived"],
          payload["pressure_qfe_mb_derived"],
          payload["wind_dir_deg_dd"],
          payload["wind_speed_ff"],
          payload["visibility_vv"],
          payload["present_weather_ww"],
          payload["past_weather_w1"],
          payload["past_weather_w2"],
          payload["rainfall_last_mm"],
          payload["cloud_cover_oktas_m"],
          payload["cloud_low_type_cl"],
          payload["cloud_med_type_cm"],
          payload["cloud_high_type_ch"],
          synop_code,
      ),
  )
  conn.commit()
  conn.close()


def set_synced_status(timestamp_str):
  conn = sqlite3.connect("station_me48.db")
  cursor = conn.cursor()
  cursor.execute(
      "UPDATE me48_observations SET synced_to_bmkg = 1 WHERE data_timestamp ="
      " ?",
      (timestamp_str,),
  )
  conn.commit()
  conn.close()


# --- SIDEBAR CONFIGURATION ---
st.sidebar.header("Station Authorization")

if "bearer_token" not in st.session_state:
  st.session_state["bearer_token"] = ""
if "cf_clearance" not in st.session_state:
  st.session_state["cf_clearance"] = ""

st_user = st.sidebar.text_input("BMKG Username", value=DEFAULT_USER)
st_pass = st.sidebar.text_input(
    "BMKG Password", value=DEFAULT_PASS, type="password"
)

# --------------------------------------------------------------------------
# HERE IS THE BUTTON LOGIC WHERE get_bmkg_credentials IS CALLED:
# --------------------------------------------------------------------------
if st.sidebar.button("🔑 Auto-Fetch Session Tokens"):
  if not st_user or not st_pass:
    st.sidebar.error("Enter both Username and Password.")
  else:
    with st.sidebar.status(
        "Logging into BMKGSoft in background...", expanded=True
    ) as status:
      try:
        token, cookie = get_bmkg_credentials(st_user, st_pass, headless=False)

        if not token:
          raise ValueError(
              "Token returned empty. Check credentials or network connection."
          )

        st.session_state["bearer_token"] = token
        st.session_state["cf_clearance"] = cookie or ""
        status.update(
            label="Tokens retrieved successfully!",
            state="complete",
            expanded=False,
        )
        st.rerun()  # Forces Streamlit to refresh and display newly fetched tokens in the sidebar

      except Exception as err:
        status.update(label=f"Failed: {err}", state="error", expanded=True)

BEARER_TOKEN = st.sidebar.text_input(
    "Bearer Token", value=st.session_state["bearer_token"], type="password"
)
CF_CLEARANCE = st.sidebar.text_input(
    "cf_clearance Cookie",
    value=st.session_state["cf_clearance"],
    type="password",
)


# --- ENTRY FORM ---
st.subheader("1. Date, Time & Observer (UTC)")
col_t1, col_t2, col_t3 = st.columns(3)
with col_t1:
  obs_date = st.date_input("Tanggal Pengamatan", value=datetime.utcnow())
with col_t2:
  utc_hours = [f"{h:02d}:00" for h in range(24)]
  current_utc_hour = datetime.now(timezone.utc).hour
  obs_hour = st.selectbox(
      "Jam Pengamatan (UTC)",
      options=utc_hours,
      index=current_utc_hour,
  )
with col_t3:
  selected_observer = st.selectbox(
      "Pengamat", options=list(OBSERVER_ROSTER.keys())
  )
  raw_id = OBSERVER_ROSTER[selected_observer]
  if raw_id is None:
    OBSERVER_ID = st.number_input("Masukkan Observer ID", value=None, step=1)
  else:
    OBSERVER_ID = raw_id

st.subheader("2. Angin, Cuaca, Tekanan & Suhu")
col_angin, col_cuaca, col_tekanan, col_suhu = st.columns(4)

with col_angin:
  st.markdown("`ANGIN`")
  wind_indicator_iw = st.selectbox(
      "Pengenal Data Angin (iw)", options=[4, 1, 0, 3], index=0
  )
  wind_dir = st.number_input(
      "Arah Angin (derajat)", min_value=0, max_value=360, value=None
  )
  wind_speed = st.number_input(
      "Kecepatan Angin (knot)", min_value=0, value=None
  )
  st.write("")
  visibility = st.number_input(
      "Jarak penglihatan mendatar (km)",
      min_value=0.0,
      value=None,
      format="%.1f",
  )

with col_cuaca:
  st.markdown("`CUACA`")
  weather_indicator_ix = st.text_input(
      "Pengenal Data Cuaca (ix)", value=None, disabled=True
  )
  ww = st.number_input("Cuaca Saat Pengamatan (ww)", value=None, min_value=0)
  w1 = st.selectbox(
      "Cuaca yang lalu (W1)",
      options=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
      index=None,
  )
  w2 = st.selectbox(
      "Cuaca yang lalu (W2)",
      options=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
      index=None,
  )
  st.caption("`IR = 4`")

with col_tekanan:
  st.markdown("`TEKANAN`")
  st.caption("🔵 **Barometer Air Raksa**")
  pressure_temp = st.text_input(
      "Derajat Panas (°C)", value=None, disabled=True, placeholder="N/A"
  )
  pressure_reading = st.text_input(
      "Tekanan dibaca (mb)", value=None, disabled=True, placeholder="N/A"
  )
  st.caption("🔵 **Barometer Digital**")
  qff = st.number_input("Tekanan QFF", value=None, format="%.1f")
  qfe = st.number_input("Tekanan QFE", value=None, format="%.1f")

with col_suhu:
  st.markdown("`SUHU`")
  temp_dry = st.number_input(
      "Suhu Bola Kering (°C)", value=None, format="%.1f"
  )
  temp_wet = st.number_input(
      "Suhu Bola Basah (°C)", value=None, format="%.1f"
  )
  temp_max = st.number_input(
      "Suhu Maksimum (°C)", value=None, placeholder="Opsional"
  )
  temp_min = st.number_input(
      "Suhu Minimum (°C)", value=None, placeholder="Opsional"
  )

# --------------------------------------------------------------------------
# SEKSI 3: WEATHER & DETAILED CLOUD OBSERVATION
# --------------------------------------------------------------------------
st.subheader("3. Weather & Detailed Cloud Observation")

col_top1, col_top2, col_top3 = st.columns(3)
with col_top1:
  cloud_cover_oktas_m = st.selectbox(
      "Bagian Langit Tertutup Awan (oktas)",
      options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8"],
      index=None,
  )
with col_top2:
  rainfall_last_mm = st.number_input(
      "Hujan takaran terakhir (mm)",
      min_value=0.0,
      value=None,
      step=0.1,
      placeholder="Kosong",
  )
with col_top3:
  cloud_vertical_vis = st.number_input(
      "Jarak Penglihatan Vertikal (m)", min_value=0, value=None, placeholder="Kosong"
  )

st.markdown("---")

col_low, col_med, col_high = st.columns(3)

# --- AWAN RENDAH ---
CL_OPTIONS = {
    None: "-- Pilih CL --",
    0: "0 - tidak ada awan Cl",  #[cite: 50]
    1: "1 - cumulus humilis atau fracto cumulus atau kedua-duanya",  #[cite: 50]
    2: (
        "2 - cumulus mediocris atau congestus, disertai atau tidak disertai"
        " fractocumulus..."
    ),  #[cite: 50]
    3: (
        "3 - cumulonimbus tanpa landasan, disertai atau tidak disertai cumulus,"
        " stratocumulus..."
    ),  #[cite: 50]
    4: "4 - stratocumulus yang terjadi dari bentangan cumulus",  #[cite: 50]
    5: "5 - stratocumulus yang tidak terjadi dari bentangan cumulus",  #[cite: 50]
    6: "6 - stratus",  #
    7: (
        "7 - fraktostratus atau fraktocumulus yang menyertai cuaca buruk,"
        " biasanya dibawah..."
    ),  #[cite: 49]
    8: (
        "8 - cumulus dan stratocumulus yang tidak terjadi dari bentangan"
        " cumulus, dengan..."
    ),  #[cite: 49]
    9: (
        "9 - cumulonimbus, biasanya berlandasan disertai atau tidak disertai"
        " cumulus..."
    ),  #[cite: 49]
    "/": (
        "/ - Cl tidak kelihatan disebabkan oleh kabut, badai debu, badai pasir"
        " atau lain-lain..."
    ),  #[cite: 49]
}

LOW_CLOUD_GENUS = {
    None: "",
    6: "6 - stratocumulus (Sc)",
    7: "7 - stratus (St)",
    8: "8 - cumulus (Cu)",
    9: "9 - cumulonimbus (Cb)",
    "/": "/ - cloud not visible",
}

with col_low:
  st.markdown("### ☁️ AWAN RENDAH")
  cloud_low_type_cl = st.selectbox(
    label="CL",
    options=list(CL_OPTIONS.keys()),
    format_func=lambda code: CL_OPTIONS[code],
    index=0,
  )
  cloud_low_cover_oktas = st.selectbox(
      "NCL", options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8"], index=None
  )
  
  st.markdown("`Detail Utama (Layer 1)`")
  cloud_low_type_1 = st.selectbox(
    "Jenis (1)",
    options=list(LOW_CLOUD_GENUS.keys()),
    format_func=lambda code: LOW_CLOUD_GENUS[code],
    index=0,
)
  cloud_low_cover_1 = st.text_input("Jumlah (1)", value=None)
  cloud_low_base_1 = st.number_input("Tinggi Dasar (m) 1", value=None)
  cloud_low_peak_1 = st.number_input("Tinggi Puncak (m) 1", value=None)
  cloud_low_dir_1 = st.number_input("Arah Gerak 1", value=None)
  cloud_elevation_angle_ec_1 = st.number_input("Sudut Elevasi 1", value=None)
  cloud_low_dir_true_da_1 = st.number_input("Arah Sebenarnya 1", value=None)

  with st.expander("➕ Tambah Layer (2)"):
    st.caption("Layer 2")
    cloud_low_type_2 = st.selectbox(
      "Jenis (2)",
      options=list(LOW_CLOUD_GENUS.keys()),
      format_func=lambda code: LOW_CLOUD_GENUS[code],
      index=0,
    )
    cloud_low_cover_2 = st.text_input("Jumlah (2)", value="")
    cloud_low_base_2 = st.number_input("Tinggi Dasar (m) 2", value=None)
    cloud_low_peak_2 = st.number_input("Tinggi Puncak (m) 2", value=None)
    cloud_low_dir_2 = st.number_input("Arah Gerak 2", value=None)
    cloud_elevation_angle_ec_2 = st.number_input("Sudut Elevasi 2", value=None)
    cloud_low_dir_true_da_2 = st.number_input("Arah Sebenarnya 2", value=None)

    with st.expander("➕ Tambah Layer (3)"):
      st.caption("Layer 3")
      cloud_low_type_3 = st.selectbox(
        "Jenis (3)",
        options=list(LOW_CLOUD_GENUS.keys()),
        format_func=lambda code: LOW_CLOUD_GENUS[code],
        index=0,
      )
      cloud_low_cover_3 = st.text_input("Jumlah (3)", value=None)
      cloud_low_base_3 = st.number_input("Tinggi Dasar (m) 3", value=None)
      cloud_low_dir_3 = st.number_input("Arah Gerak 3", value=None)

# --- AWAN MENENGAH ---
with col_med:
  st.markdown("### ☁️ AWAN MENENGAH")
  cloud_med_type_cm = st.selectbox(
      "CM", options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], index=None
  )
  cloud_med_cover_oktas = st.selectbox(
      "NCM", options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8"], index=None
  )
  
  st.markdown("`Detail Utama (Layer 1)`")
  cloud_med_type_1 = st.text_input("Jenis CM (1)", value=None)
  cloud_med_cover_1 = st.text_input("Jumlah CM (1)", value=None)
  cloud_med_base_1 = st.number_input("Tinggi Dasar CM (m) 1", value=None)
  cloud_med_dir_1 = st.number_input("Arah CM 1", value=None)

  with st.expander("➕ Tambah Layer (2)"):
    st.caption("Layer 2")
    cloud_med_type_2 = st.text_input("Jenis CM (2)", value=None)
    cloud_med_cover_2 = st.text_input("Jumlah CM (2)", value=None)
    cloud_med_base_2 = st.number_input("Tinggi Dasar CM (m) 2", value=None)
    cloud_med_dir_2 = st.number_input("Arah CM 2", value=None)

# --- AWAN TINGGI ---
with col_high:
  st.markdown("### ☁️ AWAN TINGGI")
  cloud_high_type_ch = st.selectbox(
      "CH", options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], index=None
  )
  cloud_high_cover_oktas = st.selectbox(
      "NCH", options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8"], index=None
  )
  
  st.markdown("`Detail Utama (Layer 1)`")
  cloud_high_type_1 = st.text_input("Jenis CH (1)", value=None)
  cloud_high_cover_1 = st.text_input("Jumlah CH (1)", value=None)
  cloud_high_base_1 = st.number_input("Tinggi Dasar CH (m) 1", value=None)
  cloud_high_dir_1 = st.number_input("Arah CH 1", value=None)

  with st.expander("➕ Tambah Layer (2)"):
    st.caption("Layer 2")
    cloud_high_type_2 = st.text_input("Jenis CH (2)", value="")
    cloud_high_cover_2 = st.text_input("Jumlah CH (2)", value="")
    cloud_high_base_2 = st.number_input("Tinggi Dasar CH (m) 2", value=None)
    cloud_high_dir_2 = st.number_input("Arah CH 2", value=None)

# --------------------------------------------------------------------------
# SEKSI 4: PENGUAPAN, MATAHARI & TANAH (Opsional)
# --------------------------------------------------------------------------
st.subheader("4. Penguapan, Matahari & Tanah")
col_evap, col_sun, col_land = st.columns(3)

with col_evap:
  st.markdown("`PENGUAPAN`")
  evaporation_24hours_mm_eee = st.number_input(
      "Penguapan (mm)",
      value=None,
      min_value=0.0,
      step=0.1,
      placeholder="Opsional",
  )
  evaporation_eq_indicator_ie = st.selectbox(
      "Pengenal Data Penguapan (iE)",
      options=[None, 0, 1, 2, 3, 4],
      index=0,
      format_func=lambda x: "" if x is None else str(x),
  )

with col_sun:
  st.markdown("`MATAHARI`")
  solar_rad_24h_jcm2_f24 = st.number_input(
      "Radiasi Matahari (Joule/cm2)",
      value=None,
      min_value=0.0,
      placeholder="Opsional",
  )
  sunshine_h_sss = st.number_input(
      "Lama Penyinaran Matahari (jam)",
      value=None,
      min_value=0.0,
      max_value=24.0,
      step=0.1,
      placeholder="Opsional",
  )

with col_land:
  st.markdown("`TANAH`")
  land_cond = st.selectbox(
      "Keadaan Tanah", options=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], index=None
  )
  land_note = st.text_input("Catatan", value="")

# --------------------------------------------------------------------------
# SEKSI 5: ENCODED SYNOP STRING
# --------------------------------------------------------------------------
st.subheader("5. Encoded SYNOP String")
synop_text = st.text_area(
    "AAXX SYNOP Code (Optional / Auto-captured on submit)",
    value=st.session_state.get("last_captured_synop", ""),
    height=100,
)

submit_btn = st.button("Save Locally & Push to BMKGSoft")

# --- SUBMISSION EXECUTION ---
if submit_btn:
  hour_int = int(obs_hour.split(":")[0])
  iso_utc_timestamp = (
      f"{obs_date.strftime('%Y-%m-%d')}T{hour_int:02d}:00:00Z"
  )

  headers = {
      "Authorization": f"Bearer {BEARER_TOKEN}",
      "Content-Type": "application/json",
      "Cookie": f"cf_clearance={CF_CLEARANCE}",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://bmkgsatu.bmkg.go.id/meteorologi/sinoptik",
  }

  full_payload = {
      "data_timestamp": iso_utc_timestamp,
      "bmkgsoft_id": STATION_ID,
      "observer_id": int(OBSERVER_ID),
      "wind_dir_deg_dd": wind_dir,
      "wind_indicator_iw": 4,
      "wind_speed_ff": wind_speed,
      "visibility_vv": visibility,
      "past_weather_w1": w1,
      "past_weather_w2": w2,
      "present_weather_ww": ww,
      "pressure_reading_mb": None,
      "pressure_temp_c": None,
      "rainfall_last_mm": rainfall_last_mm,
      "temp_drybulb_c_tttttt": temp_dry,
      "temp_max_c_txtxtx": temp_max,
      "temp_min_c_tntntn": temp_min,
      "temp_wetbulb_c": temp_wet,
      "cloud_cover_oktas_m": cloud_cover_oktas_m,
      "cloud_vertical_vis": cloud_vertical_vis,
      "cloud_low_type_cl": cloud_low_type_cl,
      "cloud_low_cover_oktas": cloud_low_cover_oktas,
      "cloud_low_type_1": cloud_low_type_1,
      "cloud_low_type_2": cloud_low_type_2,
      "cloud_low_type_3": cloud_low_type_3,
      "cloud_low_cover_1": cloud_low_cover_1,
      "cloud_low_cover_2": cloud_low_cover_2,
      "cloud_low_cover_3": cloud_low_cover_3,
      "cloud_low_base_1": cloud_low_base_1,
      "cloud_low_base_2": cloud_low_base_2,
      "cloud_low_base_3": cloud_low_base_3,
      "cloud_low_peak_1": cloud_low_peak_1,
      "cloud_low_peak_2": cloud_low_peak_2,
      "cloud_low_dir_1": (
          int(cloud_low_dir_1) if cloud_low_dir_1 is not None else None
      ),
      "cloud_low_dir_2": (
          int(cloud_low_dir_2) if cloud_low_dir_2 is not None else None
      ),
      "cloud_low_dir_3": (
          int(cloud_low_dir_3) if cloud_low_dir_3 is not None else None
      ),
      "cloud_elevation_angle_ec_1": cloud_elevation_angle_ec_1,
      "cloud_elevation_angle_ec_2": cloud_elevation_angle_ec_2,
      "cloud_low_dir_true_da_1": cloud_low_dir_true_da_1,
      "cloud_low_dir_true_da_2": cloud_low_dir_true_da_2,
      "cloud_med_type_cm": cloud_med_type_cm,
      "cloud_med_cover_oktas": cloud_med_cover_oktas,
      "cloud_med_type_1": cloud_med_type_1,
      "cloud_med_type_2": cloud_med_type_2,
      "cloud_med_cover_1": cloud_med_cover_1,
      "cloud_med_cover_2": cloud_med_cover_2,
      "cloud_med_base_1": cloud_med_base_1,
      "cloud_med_base_2": cloud_med_base_2,
      "cloud_med_dir_1": (
          int(cloud_med_dir_1) if cloud_med_dir_1 is not None else None
      ),
      "cloud_med_dir_2": (
          int(cloud_med_dir_2) if cloud_med_dir_2 is not None else None
      ),
      "cloud_high_type_ch": cloud_high_type_ch,
      "cloud_high_cover_oktas": cloud_high_cover_oktas,
      "cloud_high_type_1": cloud_high_type_1,
      "cloud_high_type_2": cloud_high_type_2,
      "cloud_high_cover_1": cloud_high_cover_1,
      "cloud_high_cover_2": cloud_high_cover_2,
      "cloud_high_base_1": cloud_high_base_1,
      "cloud_high_base_2": cloud_high_base_2,
      "cloud_high_dir_1": (
          int(cloud_high_dir_1) if cloud_high_dir_1 is not None else None
      ),
      "cloud_high_dir_2": (
          int(cloud_high_dir_2) if cloud_high_dir_2 is not None else None
      ),
      "solar_rad_24h_jcm2_f24": solar_rad_24h_jcm2_f24,
      "sunshine_h_sss": sunshine_h_sss,
      "evaporation_24hours_mm_eee": evaporation_24hours_mm_eee,
      "evaporation_eq_indicator_ie": evaporation_eq_indicator_ie,
      "land_cond": land_cond,
      "land_note": land_note,
      "pressure_qff_mb_derived": qff,
      "pressure_qfe_mb_derived": qfe,
  }

  for flag in DIGI_FLAG_KEYS:
    full_payload[flag] = False

  try:
    # STEP 1: Fetch server SYNOP string from preview endpoint
    st.text("Generating official AAXX SYNOP string from BMKGSoft...")
    generated_synop, _, _ = get_bmkg_preview_synop(
        headers, full_payload, iso_utc_timestamp
    )
    final_synop = generated_synop if generated_synop else synop_text

    # STEP 2: Send GTS Broadcast for primary hours
    if hour_int in PRIMARY_SYNOP_HOURS:
      if final_synop:
        st.text(
            f"Primary Synoptic Hour ({hour_int:02d}:00 UTC) detected."
            " Broadcasting SYNOP to GTS..."
        )
        gts_url = f"{BASE_URL}/gts/entry"
        gts_payload = {"sandi": final_synop, "only_save": False}
        gts_res = requests.post(gts_url, json=gts_payload, headers=headers)

        if gts_res.status_code in [200, 201]:
          st.success("GTS Broadcast Successful (200 OK).")
        else:
          st.error(
              f"GTS Broadcast Failed ({gts_res.status_code}): {gts_res.text}"
          )
      else:
        st.warning("Primary hour detected, but no SYNOP code was generated.")

    # STEP 3: Submit observation entry form to BMKGSoft
    st.text("Submitting observation entry to BMKGSoft...")
    submit_url = (
        f"{BASE_URL}/sinoptik/entry/station/{STATION_ID}/date/{iso_utc_timestamp}"
    )

    final_payload = full_payload.copy()
    final_payload["edited_encoded_synop"] = final_synop

    if hour_int in PRIMARY_SYNOP_HOURS:
      submit_res = requests.put(
          submit_url, json=final_payload, headers=headers
      )
    else:
      submit_res = requests.post(
          submit_url, json=final_payload, headers=headers
      )
      if submit_res.status_code not in [200, 201]:
        submit_res = requests.put(
            submit_url, json=final_payload, headers=headers
        )

    # STEP 4: Save locally & display status
    if submit_res.status_code in [200, 201]:
      save_local_observation(full_payload, final_synop)
      set_synced_status(iso_utc_timestamp)

      st.balloons()
      st.success(
          f"Successfully submitted for {selected_observer} (ID: {OBSERVER_ID})"
          f" to BMKGSoft (`{iso_utc_timestamp}`)!"
      )
      if final_synop:
        st.subheader("Official Captured SYNOP String:")
        st.code(final_synop, language="text")
    else:
      save_local_observation(full_payload, final_synop)
      st.warning(
          "Saved locally to SQLite, but BMKGSoft returned status"
          f" {submit_res.status_code}: {submit_res.text}"
      )

  except Exception as err:
    save_local_observation(full_payload, synop_text)
    st.error(
        f"Network Exception: {err}. Entry saved safely in local station database"
        " (`station_me48.db`)."
    )

# ==============================================================================
# GTS DIRECT BROADCAST & METAR GENERATOR (WITH DEBUG SUITE)
# ==============================================================================
st.markdown("---")
st.subheader("✈️ WAGB METAR Generator & GTS Direct Entry")

# 1. Initialize text box key directly
if "manual_sandi_input" not in st.session_state:
  st.session_state["manual_sandi_input"] = ""


# 2. Bridge function with full try-catch & debug logging
def convert_synop_to_metar():
  try:
    # 1. Capture base parameters
    v_date = globals().get("obs_date", None)
    v_hour = globals().get("obs_hour", None)
    v_wdir = globals().get("wind_dir", None)
    v_wspd = globals().get("wind_speed", None)
    v_wgst = globals().get("wind_gust", None)
    v_vis = globals().get("visibility", None)
    v_ww = globals().get("ww_present", None)
    v_tdry = globals().get("temp_dry", None)
    v_tdew = globals().get("temp_dew", None)
    v_qff = globals().get("qff", None)

    # 2. Extract Low Cloud Layer 1 using your exact variable names
    g_1 = globals().get("cloud_low_type_1", None)
    n_1 = globals().get("cloud_low_cover_1", None)
    h_1 = globals().get("cloud_low_base_1", None)

    layers = []
    # Verify Layer 1 has non-empty inputs
    if n_1 and h_1 is not None:
      try:
        oktas_int = int(str(n_1).strip())
        height_flt = float(h_1)
        layers.append((oktas_int, height_flt, g_1))
      except (ValueError, TypeError):
        pass

    # 3. Optional: Extract Layer 2 if you added extra layer widgets
    g_2 = globals().get("cloud_low_type_2", None)
    n_2 = globals().get("cloud_low_cover_2", None)
    h_2 = globals().get("cloud_low_base_2", None)

    if n_2 and h_2 is not None:
      try:
        oktas_int_2 = int(str(n_2).strip())
        height_flt_2 = float(h_2)
        layers.append((oktas_int_2, height_flt_2, g_2))
      except (ValueError, TypeError):
        pass

    vis_in_meters = float(v_vis) * 1000 if v_vis is not None else 9999.0

    # 4. Generate METAR via metar.py
    raw_metar, wmo_bulletin = convert_synop_to_metar_peraturan(
        obs_date=v_date,
        obs_hour=v_hour,
        wind_dir=v_wdir,
        wind_spd=v_wspd,
        wind_gust=v_wgst,
        visibility_m=vis_in_meters,
        ww_code=v_ww,
        temp_dry=v_tdry,
        temp_dew=v_tdew,
        qnh_hpa=float(v_qff) if v_qff is not None else None,
        cloud_layers=layers,
        station_icao="WAGB",
    )

    # 5. Populate text area
    st.session_state["manual_sandi_input"] = wmo_bulletin
    st.toast("✅ METAR berhasil dibuat!", icon="⚡")

  except Exception as e:
    st.error(f"❌ Error saat convert_synop_to_metar: {e}")


# 3. Action buttons
col_gen, col_clear, col_debug = st.columns([3, 1, 2])
with col_gen:
  # Using on_click callback guarantees state is set before the text_area renders
  st.button(
      "⚡ Generate METAR dari SYNOP",
      on_click=convert_synop_to_metar,
      use_container_width=True,
  )

with col_clear:
  if st.button("🗑️ Kosongkan", use_container_width=True):
    st.session_state["manual_sandi_input"] = ""
    st.rerun()

with col_debug:
  show_debug = st.checkbox("🔍 Tampilkan Debug Form", value=False)

# 4. Text Area Matching BMKGSoft UI
sandi_val = st.text_area(
    label="Sandi",
    height=140,
    key="manual_sandi_input",
    placeholder="Masukkan sandi yang akan dikirimkan",
)

# 5. Debug Panel: Inspect what SYNOP variables actually exist
if show_debug:
  with st.expander("🛠️ Variable Inspection Inspector", expanded=True):
    captured_vars = {
        "obs_date": repr(globals().get("obs_date")),
        "obs_hour": repr(globals().get("obs_hour")),
        "wind_dir": repr(globals().get("wind_dir")),
        "wind_speed": repr(globals().get("wind_speed")),
        "wind_gust": repr(globals().get("wind_gust")),
        "visibility": repr(globals().get("visibility")),
        "ww_present": repr(globals().get("ww_present")),
        "temp_dry": repr(globals().get("temp_dry")),
        "temp_dew": repr(globals().get("temp_dew")),
        "qfe": repr(globals().get("qfe")),
        "live_qnh (session_state)": repr(st.session_state.get("live_qnh")),
    }
    st.json(captured_vars)
    st.write(
        "Current `manual_sandi_input` in Session State:",
        [st.session_state.get("manual_sandi_input")],
    )

# 6. Send to GTS Button
col_empty, col_send = st.columns([5, 1])
with col_send:
  send_to_gts = st.button("Send", type="primary", use_container_width=True)

if send_to_gts:
  if not sandi_val.strip():
    st.warning("Sandi tidak boleh kosong.")
  else:
    gts_endpoint = "https://bmkgsatu.bmkg.go.id/api/v21/gts/entry"
    payload = {"sandi": sandi_val.strip(), "only_save": False}
    try:
      with st.spinner("Mengirim sandi ke GTS..."):
        res = requests.post(
            gts_endpoint, json=payload, headers=headers, timeout=10
        )
        if res.status_code == 200:
          st.success("✅ Sandi berhasil dikirim ke GTS!")
        else:
          st.error(f"❌ Gagal mengirim ke GTS ({res.status_code}): {res.text}")
    except requests.exceptions.RequestException as err:
      st.error(f"Network error: {err}")