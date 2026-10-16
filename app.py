import os
import sqlite3
import math
import json
from datetime import datetime, timezone
from db import save_local_observation
from dotenv import load_dotenv
import requests
import streamlit as st
from auth import get_bmkg_credentials
from metar import convert_synop_to_metar_peraturan
from dict import (
    CLOUD_COVER_OKTAS,
    CLOUD_DIRECTION,
    CLOUD_HIGH_TYPE_CH,
    CLOUD_LOW_TYPE_CL,
    CLOUD_MED_TYPE_CM,
    HIGH_CLOUD_GENUS,
    LAYER_OKTAS,
    LOW_CLOUD_GENUS,
    MED_CLOUD_GENUS,
    PRESENT_WEATHER_WW,
    PAST_WEATHER_W,
)

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
  ww = st.selectbox(
    "Cuaca Saat Pengamatan (ww)",
    options=list(PRESENT_WEATHER_WW.keys()),
    format_func=lambda x: PRESENT_WEATHER_WW.get(x, ""),
  )
  w1 = st.selectbox(
      "Cuaca Yang Lalu 1 (W1) ℹ️",
      options=list(PAST_WEATHER_W.keys()),
      format_func=lambda x: PAST_WEATHER_W.get(x, ""),
      index=0,
      help="Fenomena cuaca paling signifikan pada periode jam sebelumnya (W1 ≥ W2)",
  )
  w2= st.selectbox(
      "Cuaca Yang Lalu 2 (W2) ℹ️",
      options=list(PAST_WEATHER_W.keys()),
      format_func=lambda x: PAST_WEATHER_W.get(x, ""),
      index=0,
      help="Fenomena cuaca signifikan kedua pada periode jam sebelumnya",
  )
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
      options=list(CLOUD_COVER_OKTAS.keys()),
      format_func=lambda x: CLOUD_COVER_OKTAS.get(x, ""),
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
with col_low:
  st.markdown("### ☁️ AWAN RENDAH")
  cloud_low_type_cl = st.selectbox(
    label="CL",
    options=list(CLOUD_LOW_TYPE_CL.keys()),
    format_func=lambda code: CLOUD_LOW_TYPE_CL.get(code, ""),
    index=0,
  )
  cloud_low_cover_oktas = st.selectbox(
    "NCL",
    options=list(LAYER_OKTAS.keys()),
    format_func=lambda x: LAYER_OKTAS.get(x, ""),
  )
  
  st.markdown("`Detail Utama (Layer 1)`")
  cloud_low_type_1 = st.selectbox(
    "Jenis CL (1)",
    options=list(LOW_CLOUD_GENUS.keys()),
    format_func=lambda code: LOW_CLOUD_GENUS[code],
    index=0,
  )
  cloud_low_cover_1 = st.selectbox(
    "Jumlah CL (1)",
    options=list(LAYER_OKTAS.keys()),
    format_func=lambda x: LAYER_OKTAS.get(x, ""),
  )
  cloud_low_base_1 = st.number_input("Tinggi Dasar (m) 1", value=None)
  cloud_low_peak_1 = st.number_input("Tinggi Puncak (m) 1", value=None)
  cloud_low_dir_1 = st.selectbox(
    "Arah Gerak CL (1)",
    options=list(CLOUD_DIRECTION.keys()),
    format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
  )
  cloud_elevation_angle_ec_1 = st.number_input("Sudut Elevasi 1", value=None)
  cloud_low_dir_true_da_1 = st.number_input("Arah Sebenarnya 1", value=None)

  with st.expander("➕ Tambah Layer (2)"):
    st.caption("Layer 2")
    cloud_low_type_2 = st.selectbox(
      "Jenis CL (2)",
      options=list(LOW_CLOUD_GENUS.keys()),
      format_func=lambda code: LOW_CLOUD_GENUS[code],
      index=0,
    )
    cloud_low_cover_2 = st.selectbox(
      "Jumlah CL (2)",
      options=list(LAYER_OKTAS.keys()),
      format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )
    cloud_low_base_2 = st.number_input("Tinggi Dasar (m) 2", value=None)
    cloud_low_peak_2 = st.number_input("Tinggi Puncak (m) 2", value=None)
    cloud_low_dir_2 = st.selectbox(
      "Arah Gerak CL (2)",
      options=list(CLOUD_DIRECTION.keys()),
      format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
    )
    cloud_elevation_angle_ec_2 = st.number_input("Sudut Elevasi 2", value=None)
    cloud_low_dir_true_da_2 = st.number_input("Arah Sebenarnya 2", value=None)

    with st.expander("➕ Tambah Layer (3)"):
      st.caption("Layer 3")
      cloud_low_type_3 = st.selectbox(
        "Jenis CL (3)",
        options=list(LOW_CLOUD_GENUS.keys()),
        format_func=lambda code: LOW_CLOUD_GENUS[code],
        index=0,
      )
      cloud_low_cover_3 = st.selectbox(
        "Jumlah CL (3)",
        options=list(LAYER_OKTAS.keys()),
        format_func=lambda x: LAYER_OKTAS.get(x, ""),
      )
      cloud_low_base_3 = st.number_input("Tinggi Dasar (m) 3", value=None)
      cloud_low_dir_3 = st.selectbox(
        "Arah Gerak CL (3)",
        options=list(CLOUD_DIRECTION.keys()),
        format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
      )

# --- AWAN MENENGAH ---
with col_med:
  st.markdown("### ☁️ AWAN MENENGAH")
  cloud_med_type_cm = st.selectbox(
    label="CL",
    options=list(CLOUD_MED_TYPE_CM.keys()),
    format_func=lambda code: CLOUD_MED_TYPE_CM.get(code, ""),
    index=0,
  )
  cloud_med_cover_oktas = st.selectbox(
    "NCM",
    options=list(LAYER_OKTAS.keys()),
    format_func=lambda x: LAYER_OKTAS.get(x, ""),
      )
  st.markdown("`Detail Utama (Layer 1)`")
  cloud_med_type_1 = st.selectbox(
    "Jenis CM (1)",
    options=list(MED_CLOUD_GENUS.keys()),
    format_func=lambda code: MED_CLOUD_GENUS[code],
    index=0,
  )
  cloud_med_cover_1 = st.selectbox(
    "Jumlah CM (1)",
    options=list(LAYER_OKTAS.keys()),
    format_func=lambda x: LAYER_OKTAS.get(x, ""),
      )
  cloud_med_base_1 = st.number_input("Tinggi Dasar CM (m) 1", value=None)
  cloud_med_dir_1 = st.selectbox(
    "Arah  Gerak CM (1)",
    options=list(CLOUD_DIRECTION.keys()),
    format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
  )

  with st.expander("➕ Tambah Layer (2)"):
    st.caption("Layer 2")
    cloud_med_type_2 = st.selectbox(
      "Jenis CM (2)",
      options=list(MED_CLOUD_GENUS.keys()),
      format_func=lambda code: MED_CLOUD_GENUS[code],
      index=0,
    )
    cloud_med_cover_2 = st.selectbox(
      "Jumlah CM (2)",
      options=list(LAYER_OKTAS.keys()),
      format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )
    cloud_med_base_2 = st.number_input("Tinggi Dasar CM (m) 2", value=None)
    cloud_med_dir_2 = st.selectbox(
      "Arah  Gerak CM (2)",
      options=list(CLOUD_DIRECTION.keys()),
      format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
    )

# --- AWAN TINGGI ---
with col_high:
  st.markdown("### ☁️ AWAN TINGGI")
  cloud_high_type_ch = st.selectbox(
    label="CL",
    options=list(CLOUD_HIGH_TYPE_CH.keys()),
    format_func=lambda code: CLOUD_HIGH_TYPE_CH.get(code, ""),
    index=0,
  )
  cloud_high_cover_oktas = st.selectbox(
      "NCH", options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8"], index=None
  )
  
  st.markdown("`Detail Utama (Layer 1)`")
  cloud_high_type_1 = st.selectbox(
    "Jenis CH (1)",
    options=list(HIGH_CLOUD_GENUS.keys()),
    format_func=lambda code: HIGH_CLOUD_GENUS[code],
    index=0,
  )
  cloud_high_cover_1 = st.selectbox(
    "Jumlah CH (1)",
    options=list(LAYER_OKTAS.keys()),
    format_func=lambda x: LAYER_OKTAS.get(x, ""),
  )
  cloud_high_base_1 = st.number_input("Tinggi Dasar CH (m) 1", value=None)
  cloud_high_dir_1 = st.selectbox(
    "Arah  Gerak CH (1)",
    options=list(CLOUD_DIRECTION.keys()),
    format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
  )

  with st.expander("➕ Tambah Layer (2)"):
    st.caption("Layer 2")
    cloud_high_type_2 = st.selectbox(
      "Jenis CH (2)",
      options=list(HIGH_CLOUD_GENUS.keys()),
      format_func=lambda code: HIGH_CLOUD_GENUS[code],
      index=0,
    )
    cloud_high_cover_2 = st.selectbox(
      "Jumlah CH (2)",
      options=list(LAYER_OKTAS.keys()),
      format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )
    cloud_high_base_2 = st.number_input("Tinggi Dasar CH (m) 2", value=None)
    cloud_high_dir_2 = st.selectbox(
      "Arah  Gerak CH (2)",
      options=list(CLOUD_DIRECTION.keys()),
      format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
    )

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
submit_btn = st.button("Save Locally & Push to BMKGSoft")

# --- SUBMISSION EXECUTION (SAVE & SUBMIT TO WEB ONLY) ---
if submit_btn:
  hour_int = int(obs_hour.split(":")[0])
  iso_utc_timestamp = f"{obs_date.strftime('%Y-%m-%d')}T{hour_int:02d}:00:00Z"

  headers = {
      "Authorization": f"Bearer {BEARER_TOKEN}",
      "Content-Type": "application/json",
      "Cookie": f"cf_clearance={CF_CLEARANCE}",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://bmkgsatu.bmkg.go.id/meteorologi/sinoptik",
  }

  # 1. Determine rainfall indicator
  if st.session_state.get("rainfall_indicator_ir") is not None:
    rainfall_indicator_ir = int(st.session_state["rainfall_indicator_ir"])
  else:
    rainfall_indicator_ir = (
        0
        if (rainfall_last_mm is not None and float(rainfall_last_mm) > 0)
        else 4
    )

  # 2. Build payload
  full_payload = {
    # 1. Metadata
    "data_timestamp": iso_utc_timestamp,
    "bmkgsoft_id": int(STATION_ID),
    "observer_id": int(OBSERVER_ID),
    # 2. Wind & Visibility
    "wind_dir_deg_dd": wind_dir,
    "wind_indicator_iw": 4,
    "wind_speed_ff": wind_speed,
    "visibility_vv": visibility,
    # 3. Weather Codes (Converted to string)
    "past_weather_w1": str(w1) if w1 is not None else "",
    "past_weather_w2": str(w2) if w2 is not None else "",
    "present_weather_ww": ww,
    # 4. Temperatures & Pressures
    "temp_drybulb_c_tttttt": temp_dry,
    "temp_wetbulb_c": temp_wet,
    "temp_max_c_txtxtx": temp_max,
    "temp_min_c_tntntn": temp_min,
    "pressure_reading_mb": None,
    "pressure_temp_c": None,
    "pressure_qff_mb_derived": qff,
    "pressure_qfe_mb_derived": qfe,
    "rainfall_last_mm": rainfall_last_mm,
    # 5. Cloud Cover & Bases
    "cloud_cover_oktas_m": cloud_cover_oktas_m,
    "cloud_vertical_vis": cloud_vertical_vis,
    # Low Clouds (Unused sub-layers set to "")
    "cloud_low_type_cl": cloud_low_type_cl,
    "cloud_low_cover_oktas": cloud_low_cover_oktas,
    "cloud_low_type_1": cloud_low_type_1,
    "cloud_low_type_2": str(cloud_low_type_2 or ""),
    "cloud_low_type_3": str(cloud_low_type_3 or ""),
    "cloud_low_cover_1": cloud_low_cover_1,
    "cloud_low_cover_2": str(cloud_low_cover_2 or ""),
    "cloud_low_cover_3": str(cloud_low_cover_3 or ""),
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
    # Medium Clouds (Unused sub-layers set to "")
    "cloud_med_type_cm": cloud_med_type_cm,
    "cloud_med_cover_oktas": cloud_med_cover_oktas,
    "cloud_med_type_1": cloud_med_type_1,
    "cloud_med_type_2": str(cloud_med_type_2 or ""),
    "cloud_med_cover_1": cloud_med_cover_1,
    "cloud_med_cover_2": str(cloud_med_cover_2 or ""),
    "cloud_med_base_1": cloud_med_base_1,
    "cloud_med_base_2": cloud_med_base_2,
    "cloud_med_dir_1": (
        int(cloud_med_dir_1) if cloud_med_dir_1 is not None else None
    ),
    "cloud_med_dir_2": (
        int(cloud_med_dir_2) if cloud_med_dir_2 is not None else None
    ),
    # High Clouds (Unused sub-layers set to "")
    "cloud_high_type_ch": cloud_high_type_ch,
    "cloud_high_cover_oktas": cloud_high_cover_oktas,
    "cloud_high_type_1": cloud_high_type_1,
    "cloud_high_type_2": str(cloud_high_type_2 or ""),
    "cloud_high_cover_1": cloud_high_cover_1,
    "cloud_high_cover_2": str(cloud_high_cover_2 or ""),
    "cloud_high_base_1": cloud_high_base_1,
    "cloud_high_base_2": cloud_high_base_2,
    "cloud_high_dir_1": (
        int(cloud_high_dir_1) if cloud_high_dir_1 is not None else None
    ),
    "cloud_high_dir_2": (
        int(cloud_high_dir_2) if cloud_high_dir_2 is not None else None
    ),
    # 6. Radiation, Evaporation & Land
    "solar_rad_24h_jcm2_f24": solar_rad_24h_jcm2_f24,
    "sunshine_h_sss": sunshine_h_sss,
    "evaporation_24hours_mm_eee": evaporation_24hours_mm_eee,
    "evaporation_eq_indicator_ie": evaporation_eq_indicator_ie,
    "land_cond": land_cond,
    "land_note": land_note,
  }
  
  # Insert this directly after constructing full_payload in `if submit_btn:`

  c_oktas = str(cloud_cover_oktas_m).strip()

  # --------------------------------------------------------------------------
  # Rule 1: Indiscernible (oktas = "/")[cite: 8]
  # --------------------------------------------------------------------------
  if c_oktas == "/":  #[cite: 8]
    # Low Cloud[cite: 8]
    full_payload["cloud_low_type_cl"] = "/"  #[cite: 8]
    full_payload["cloud_low_cover_oktas"] = "/"  #[cite: 8]
    full_payload["cloud_low_type_1"] = "/"  #[cite: 8]
    full_payload["cloud_low_cover_1"] = "/"  #[cite: 8]
    full_payload["cloud_low_dir_1"] = 9  #[cite: 8]

    # Medium Cloud (CM)[cite: 8]
    full_payload["cloud_med_type_cm"] = "/"  #[cite: 8]
    full_payload["cloud_med_cover_oktas"] = "/"  #[cite: 8]
    full_payload["cloud_med_type_1"] = "/"  #[cite: 8]
    full_payload["cloud_med_cover_1"] = "/"  #[cite: 8]
    full_payload["cloud_med_dir_1"] = 9  #[cite: 8]

    # High Cloud (CH)[cite: 8]
    full_payload["cloud_high_type_ch"] = "/"  #[cite: 8]
    full_payload["cloud_high_cover_oktas"] = "/"  #[cite: 8]
    full_payload["cloud_high_type_1"] = "/"  #[cite: 8]
    full_payload["cloud_high_cover_1"] = "/"  #[cite: 8]
    full_payload["cloud_high_dir_1"] = 9  #[cite: 8]

  # --------------------------------------------------------------------------
  # Rule 2: Obscured / Fog (oktas = "9")[cite: 8]
  # --------------------------------------------------------------------------
  elif c_oktas == "9":  #[cite: 8]
    # Low Cloud[cite: 8]
    full_payload["cloud_low_type_cl"] = "/"  #[cite: 8]
    full_payload["cloud_low_cover_oktas"] = 9  #[cite: 8]
    full_payload["cloud_low_type_1"] = "/"  #[cite: 8]
    full_payload["cloud_low_cover_1"] = 9  #[cite: 8]
    full_payload["cloud_low_dir_1"] = 9  #[cite: 8]

    # Medium Cloud (CM)[cite: 8]
    full_payload["cloud_med_type_cm"] = "/"  #[cite: 8]
    full_payload["cloud_med_cover_oktas"] = 9  #[cite: 8]
    full_payload["cloud_med_type_1"] = "/"  #[cite: 8]
    full_payload["cloud_med_cover_1"] = 9  #[cite: 8]
    full_payload["cloud_med_dir_1"] = 9  #[cite: 8]

    # High Cloud (CH)[cite: 8]
    full_payload["cloud_high_type_ch"] = "/"  #[cite: 8]
    full_payload["cloud_high_cover_oktas"] = 9  #[cite: 8]
    full_payload["cloud_high_type_1"] = "/"  #[cite: 8]
    full_payload["cloud_high_cover_1"] = 9  #[cite: 8]
    full_payload["cloud_high_dir_1"] = 9  #[cite: 8]

  # --------------------------------------------------------------------------
  # Rule 3: Clear Sky (oktas = 0)[cite: 8]
  # --------------------------------------------------------------------------
  elif c_oktas in ["0", "0.0"]:  #[cite: 8]
    # Low Cloud[cite: 8]
    full_payload["cloud_low_type_cl"] = 0  #[cite: 8]
    full_payload["cloud_low_cover_oktas"] = 0  #[cite: 8]
    full_payload["cloud_low_type_1"] = 0  #[cite: 8]
    full_payload["cloud_low_cover_1"] = 0  #[cite: 8]
    full_payload["cloud_low_dir_1"] = 0  #[cite: 8]

    # Medium Cloud (CM)[cite: 8]
    full_payload["cloud_med_type_cm"] = 0  #[cite: 8]
    full_payload["cloud_med_cover_oktas"] = 0  #[cite: 8]
    full_payload["cloud_med_type_1"] = 0  #[cite: 8]
    full_payload["cloud_med_cover_1"] = 0  #[cite: 8]
    full_payload["cloud_med_dir_1"] = 0  #[cite: 8]

    # High Cloud (CH)[cite: 8]
    full_payload["cloud_high_type_ch"] = 0  #[cite: 8]
    full_payload["cloud_high_cover_oktas"] = 0  #[cite: 8]
    full_payload["cloud_high_type_1"] = 0  #[cite: 8]
    full_payload["cloud_high_cover_1"] = 0  #[cite: 8]
    full_payload["cloud_high_dir_1"] = 0  #[cite: 8]


  fallback_synop = globals().get("synop_text", "")

  try:
    # -------------------------------------------------------------
    # STEP 1: Fetch Calculations & Official SYNOP from Preview
    # -------------------------------------------------------------
    preview_url = f"{BASE_URL}/sinoptik/entry/preview/station/{STATION_ID}/date/{iso_utc_timestamp}"

    # Sanitize payload for BMKG validator
    final_payload = full_payload.copy()
    final_payload.pop("rainfall_indicator_ir", None)
    final_payload.pop("edited_encoded_synop", None)

    calc_data = {}
    generated_synop = ""

    # Request calculation from server preview engine
    preview_res = requests.post(
        preview_url, json=final_payload, headers=headers, timeout=12
    )

    if preview_res.status_code in [200, 201]:
      preview_json = preview_res.json()
      calc_data = preview_json.get("data") or {}
      generated_synop = calc_data.get("encoded_synop", "")

      server_ir = calc_data.get("rainfall_indicator_ir")
      if server_ir is not None:
        st.session_state["rainfall_indicator_ir"] = int(server_ir)

    # Store synop for GTS broadcast section
    official_synop = generated_synop if generated_synop else fallback_synop
    st.session_state["latest_synop_code"] = official_synop
    st.session_state["latest_iso_timestamp"] = iso_utc_timestamp

    # -------------------------------------------------------------
    # STEP 2: Submit Entry Form to BMKGSoft Web
    # -------------------------------------------------------------
    submit_url = f"{BASE_URL}/sinoptik/entry/station/{STATION_ID}/date/{iso_utc_timestamp}"

    if hour_int in PRIMARY_SYNOP_HOURS:
      submit_res = requests.put(
          submit_url, json=final_payload, headers=headers, timeout=12
      )
    else:
      submit_res = requests.post(
          submit_url, json=final_payload, headers=headers, timeout=12
      )
      if submit_res.status_code not in [200, 201]:
        submit_res = requests.put(
            submit_url, json=final_payload, headers=headers, timeout=12
        )

    # -------------------------------------------------------------
    # STEP 3: Merge & Save to SQLite
    # -------------------------------------------------------------
    current_metar = st.session_state.get("latest_metar_code", "")

    # Merge form input with server-calculated fields (Td, RH, ppp)
    combined_record = {
        **full_payload,
        **calc_data.get("manual_entry", {}),
        **calc_data,
    }

    if submit_res.status_code in [200, 201]:
      save_local_observation(
          combined_record,
          encoded_synop=official_synop,
          encoded_metar=current_metar,
          synced=1,
      )
      st.balloons()
      st.success(
          "✅ Terkirim ke BMKGSoft & tersimpan lengkap dengan perhitungan"
          " server di SQLite!"
      )
    else:
      save_local_observation(
          combined_record,
          encoded_synop=official_synop,
          encoded_metar=current_metar,
          synced=0,
      )
      st.warning(
          f"⚠️ Gagal kirim ke server ({submit_res.status_code}). Tersimpan di"
          " SQLite (synced=0)."
      )

  except Exception as err:
    # Network / DNS / Timeout fallback
    current_metar = st.session_state.get("latest_metar_code", "")
    save_local_observation(
        full_payload,
        encoded_synop=fallback_synop,
        encoded_metar=current_metar,
        synced=0,
    )
    st.error(
        f"📡 Gagal terhubung ke BMKGSoft: {err}. Data lokal tersimpan di"
        " SQLite (synced=0)."
    )

# --- INDEPENDENT GTS BROADCAST SECTION ---
st.markdown("---")
st.subheader("📡 GTS Broadcast Center")

current_synop = st.session_state.get("latest_synop_code", "")

if current_synop:
  # Display editable text area so you can inspect before sending
  synop_to_send = st.text_area(
      "Sandi SYNOP (Ready to Broadcast)", value=current_synop, height=100
  )

  col_gts_btn, col_info = st.columns([1, 3])
  with col_gts_btn:
    send_gts_btn = st.button("🚀 Kirim ke GTS", type="secondary")

  if send_gts_btn:
    if not synop_to_send.strip():
      st.warning("Sandi SYNOP kosong. Submit form terlebih dahulu.")
    else:
      with st.spinner("Mengirim sandi ke GTS BMKG..."):
        try:
          headers = {
              "Authorization": f"Bearer {BEARER_TOKEN}",
              "Content-Type": "application/json",
              "Cookie": f"cf_clearance={CF_CLEARANCE}",
              "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
              "Referer": "https://bmkgsatu.bmkg.go.id/meteorologi/sinoptik",
          }
          gts_url = f"{BASE_URL}/gts/entry"
          gts_payload = {"sandi": synop_to_send.strip(), "only_save": False}

          gts_res = requests.post(
              gts_url, json=gts_payload, headers=headers, timeout=15
          )

          if gts_res.status_code in [200, 201]:
            st.success("✅ GTS Broadcast Berhasil (200 OK)!")
          else:
            st.error(
                f"❌ GTS Broadcast Gagal ({gts_res.status_code}): {gts_res.text}"
            )
        except Exception as e:
          st.error(f"❌ Gagal koneksi GTS: {e}")
else:
  st.info(
      "ℹ️ Belum ada sandi SYNOP. Isi formulir lalu klik tombol submit untuk"
      " generate sandi."
  )

# ==============================================================================
# GTS DIRECT BROADCAST & METAR GENERATOR (WITH DEBUG SUITE)
# ==============================================================================
st.markdown("---")
st.subheader("✈️ WAGB METAR Generator & GTS Direct Entry")

# 1. Initialize text box key directly
if "manual_sandi_input" not in st.session_state:
  st.session_state["manual_sandi_input"] = ""


# Helper: Safely query session_state first, then globals
def _get_var(keys, default=None):
  if isinstance(keys, str):
    keys = [keys]
  for k in keys:
    if k in st.session_state and st.session_state[k] is not None:
      return st.session_state[k]
    if k in globals() and globals()[k] is not None:
      return globals()[k]
  return default


# Calculate Dew Point from Dry and Wet Bulb
def _derive_dew_point(t_dry, t_wet, p_hpa=1013.25):
  try:
    t = float(t_dry)
    tw = float(t_wet)
    p = float(p_hpa) if p_hpa else 1013.25
    ew_tw = 6.1078 * (10 ** ((7.5 * tw) / (237.3 + tw)))
    e = ew_tw - 0.000662 * p * (t - tw)
    if e <= 0:
      return tw
    log_e = math.log10(e / 6.1078)
    return round((237.3 * log_e) / (7.5 - log_e), 1)
  except Exception:
    return tw


# 2. Bridge function with full try-catch & terminal print logging
def convert_synop_to_metar():
  try:
    print("\n--- [METAR GENERATION TRIGGERED] ---")

    # 1. Capture base parameters with multi-key fallbacks
    v_date = _get_var(["obs_date"])
    v_hour = _get_var(["obs_hour"])
    v_wdir = _get_var(["wind_dir", "wind_dir_deg_dd"], default=0)
    v_wspd = _get_var(["wind_speed", "wind_speed_ff"], default=0)
    v_wgst = _get_var(["wind_gust"])
    v_vis = _get_var(["visibility", "visibility_vv"], default=9999)
    v_ww = _get_var(["ww", "ww_present", "present_weather_ww"])
    v_tdry = _get_var(["temp_dry", "temp_drybulb_c_tttttt"])
    v_twet = _get_var(["temp_wet", "temp_wetbulb_c"])
    v_tdew = _get_var(["temp_dew"])
    v_qff = _get_var(
        ["live_qnh", "qff", "pressure_qff_mb_derived"], default=1013.25
    )

    # 2. Derive Dew Point if missing
    if v_tdew is None and v_tdry is not None and v_twet is not None:
      v_tdew = _derive_dew_point(v_tdry, v_twet, v_qff)

    # 3. Visibility unit normalization (km to meters)
    if v_vis is not None:
      raw_vis = float(v_vis)
      vis_in_meters = raw_vis * 1000.0 if raw_vis <= 50.0 else raw_vis
    else:
      vis_in_meters = 9999.0

    layers = []
    c_oktas = str(_get_var(["cloud_cover_oktas_m", "c_oktas"], "")).strip()
    vert_vis = _get_var(["cloud_vertical_vis"])

    # 4. Handle Obscured Sky ("/" or "9") vs Cloud Layers
    if c_oktas in ["/", "9"]:
      if vert_vis is not None and str(vert_vis).strip() not in [
          "",
          "None",
          "/",
      ]:
        try:
          vv_ft = float(vert_vis) * 3.28084
          layers.append(f"VV{int(math.ceil(vv_ft / 100.0)):03d}")
        except Exception:
          layers.append("VV///")
      else:
        layers.append("VV///")
    elif c_oktas not in ["0", "0.0"]:
      g_1 = _get_var(["cloud_low_type_1", "cloud_low_type_cl"])
      n_1 = _get_var(["cloud_low_cover_1", "cloud_low_cover_oktas"])
      h_1 = _get_var(["cloud_low_base_1"])

      if n_1 is not None and h_1 is not None:
        try:
          oktas_int = int(str(n_1).strip())
          height_flt = float(h_1)
          if oktas_int > 0:
            layers.append((oktas_int, height_flt, g_1))
        except (ValueError, TypeError):
          pass

    print(
        f"Input: Date={v_date}, Hour={v_hour}, Wind={v_wdir}/{v_wspd}, Vis={vis_in_meters}m, ww={v_ww}, T={v_tdry}/{v_tdew}, QNH={v_qff}"
    )

    # 5. Generate METAR via metar.py
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
        qnh_hpa=float(v_qff) if v_qff is not None else 1013.25,
        cloud_layers=layers,
        station_icao="WAGB",
    )

    print(f"Generated Bulletin:\n{wmo_bulletin}")

    # 6. Populate session state
    st.session_state["manual_sandi_input"] = wmo_bulletin
    st.session_state["last_gen_error"] = None
    st.toast("✅ METAR berhasil dibuat!", icon="⚡")

  except Exception as e:
    import traceback

    traceback.print_exc()
    st.session_state["last_gen_error"] = str(e)
    print(f"❌ METAR ERROR: {e}")


# 3. Action buttons
col_gen, col_clear, col_debug = st.columns([3, 1, 2])
with col_gen:
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

# Display error banner if generation failed
if st.session_state.get("last_gen_error"):
  st.error(f"❌ Error saat membuat METAR: {st.session_state['last_gen_error']}")

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
        "obs_date": repr(_get_var(["obs_date"])),
        "obs_hour": repr(_get_var(["obs_hour"])),
        "wind_dir": repr(_get_var(["wind_dir", "wind_dir_deg_dd"])),
        "wind_speed": repr(_get_var(["wind_speed", "wind_speed_ff"])),
        "wind_gust": repr(_get_var(["wind_gust"])),
        "visibility": repr(_get_var(["visibility", "visibility_vv"])),
        "ww_code": repr(_get_var(["ww", "ww_present", "present_weather_ww"])),
        "temp_dry": repr(_get_var(["temp_dry", "temp_drybulb_c_tttttt"])),
        "temp_wet": repr(_get_var(["temp_wet", "temp_wetbulb_c"])),
        "temp_dew": repr(_get_var(["temp_dew"])),
        "qff/qnh": repr(
            _get_var(["live_qnh", "qff", "pressure_qff_mb_derived"])
        ),
        "cloud_oktas_m": repr(_get_var(["cloud_cover_oktas_m", "c_oktas"])),
        "vertical_vis": repr(_get_var(["cloud_vertical_vis"])),
    }
    st.json(captured_vars)
    st.write(
        "Current `manual_sandi_input` in Session State:",
        [st.session_state.get("manual_sandi_input", "")],
    )

# 6. Send to GTS Button
col_empty, col_send = st.columns([5, 1])
with col_send:
  send_to_gts = st.button("Send", type="primary", use_container_width=True)

if send_to_gts:
  if not sandi_val.strip():
    st.warning("Sandi tidak boleh kosong.")
  else:
    gts_endpoint = f"{BASE_URL}/gts/entry"
    payload = {"sandi": sandi_val.strip(), "only_save": False}
    gts_headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": "application/json",
        "Cookie": f"cf_clearance={CF_CLEARANCE}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://bmkgsatu.bmkg.go.id/meteorologi/sinoptik",
    }
    try:
      with st.spinner("Mengirim sandi ke GTS BMKG..."):
        res = requests.post(
            gts_endpoint, json=payload, headers=gts_headers, timeout=12
        )
        if res.status_code in [200, 201]:
          st.success("✅ Sandi berhasil dikirim ke GTS (200 OK)!")
        else:
          st.error(f"❌ Gagal mengirim ke GTS ({res.status_code}): {res.text}")
    except requests.exceptions.RequestException as err:
      st.error(f"Network error: {err}")