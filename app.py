from datetime import date, datetime, timezone
import json
import os
from dotenv import load_dotenv
import numpy as np
import pandas as pd
import streamlit as st

# Custom Internal Modules
from api_client import (
    STATION_ID,
    broadcast_to_gts,
    fetch_preview_calculations,
    get_api_headers,
    submit_observation_entry,
)
from auth import get_bmkg_credentials, is_jwt_expired, load_stored_tokens
from autopilot_engine import BMKGAutopilot
from data_manager import compute_pan_evaporation, render_data_manager
from data_model import (
    STATION_LAT,
    STATION_LON,
    fetch_hybrid_ensemble_forecast,
    get_current_synoptic_target,
    parse_ensemble_hourly_table,
)
from db import (
    log_metar_bulletin,
    save_local_observation,
    save_pan_evaporation_record,
)
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
    PAST_WEATHER_W,
    PRESENT_WEATHER_WW,
)
from metar import convert_synop_to_metar_peraturan, get_safe_metar_iso_timestamp
from weather_utils import (
    apply_sky_condition_rules,
    derive_dew_point,
    normalize_visibility_meters,
    parse_metar_cloud_layers,
)

# --- STATION CONFIGURATION ---
load_dotenv()
DEFAULT_USER = os.getenv("BMKG_USERNAME", "96595")
DEFAULT_PASS = os.getenv("BMKG_PASSWORD", "opr96595")

OBSERVER_ROSTER = {
    "Adrian Renaldi R": 6480,
    "Arief Fansius": 6479,
    "Ayu Vista": 2276,
    "Destion Fajar P.": 5881,
    "Dhimaz Bhaskara": 2273,
    "Emir Hazam FH": 5882,
    "Ivan Auyudy": 531,
    "Martua V. Putra": 5880,
    "Nelly Handayani": 2278,
    "Qomar Maulidi": 528,
    "Reni Susilowati": 532,
    "Renysa Lidiano": 2274,
    "Rovin Mahardika": 5883,
    "Sulia Mulia": 524,
    "Sunardi": 513,
    "Other / Custom ID": None,
}

st.set_page_config(
    page_title="BMKG WAGB (96655) - Muara Teweh",
    page_icon="🌤️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- CSS INJECTION ---
st.markdown(
    """
    <style>
    h1, h2, h3, h4 {
        font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
        font-weight: 600;
        letter-spacing: -0.3px;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.82rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    [data-testid="stSidebar"] [data-testid="stMetricValue"] {
        font-size: 1.12rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stMetricDelta"] {
        font-size: 0.78rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 6px;
        font-weight: 500;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# --- SIDEBAR: AUTHORIZATION ---
st.sidebar.header("Station Authorization")

# 1. Inisialisasi token dari penyimpanan lokal jika session_state masih kosong
if "bearer_token" not in st.session_state or not st.session_state["bearer_token"]:
  cached_token, cached_cookie = load_stored_tokens()
  st.session_state["bearer_token"] = cached_token
  st.session_state["cf_clearance"] = cached_cookie

# 2. Definisikan input username & password
st_user = st.sidebar.text_input("BMKG Username", value=DEFAULT_USER)
st_pass = st.sidebar.text_input(
    "BMKG Password", value=DEFAULT_PASS, type="password"
)

# 3. Indikator status sesi
token_aktif = st.session_state.get("bearer_token", "")
if token_aktif and not is_jwt_expired(token_aktif):
  st.sidebar.success("🟢 Sesi Aktif (Tersimpan Lokal)")
else:
  st.sidebar.warning("🔴 Sesi Kedaluwarsa / Belum Login")

col_auth1, col_auth2 = st.sidebar.columns(2)

with col_auth1:
  if st.button("🔄 Validasi", use_container_width=True):
    with st.sidebar.status("Memeriksa sesi...", expanded=True) as status:
      try:
        t, c = get_bmkg_credentials(
            st_user, st_pass, headless=True, force_refresh=False
        )
        st.session_state["bearer_token"] = t
        st.session_state["cf_clearance"] = c or ""
        status.update(label="Sesi valid!", state="complete")
        st.rerun()
      except Exception as e:
        status.update(label=f"Gagal: {e}", state="error")

with col_auth2:
  if st.button("🔑 Login Baru", use_container_width=True):
    with st.sidebar.status("Login ulang BMKGSoft...", expanded=True) as status:
      try:
        t, c = get_bmkg_credentials(
            st_user, st_pass, headless=False, force_refresh=True
        )
        st.session_state["bearer_token"] = t
        st.session_state["cf_clearance"] = c or ""
        status.update(label="Token baru disimpan!", state="complete")
        st.rerun()
      except Exception as e:
        status.update(label=f"Gagal: {e}", state="error")

BEARER_TOKEN = st.sidebar.text_input(
    "Bearer Token", value=st.session_state["bearer_token"], type="password"
)
CF_CLEARANCE = st.sidebar.text_input(
    "cf_clearance Cookie",
    value=st.session_state["cf_clearance"],
    type="password",
)
REQ_HEADERS = get_api_headers(BEARER_TOKEN, CF_CLEARANCE)

# --- SIDEBAR: MODEL & LIVE FORECAST ---
with st.sidebar:
  st.markdown("---")
  st.header("📊 Live Forecast")
  st.subheader("Model Hibrida WAGB")
  st.caption(
      "Kombinasi ICON (60%) + GEM (40%) untuk TT, ECMWF untuk Td & Baro."
  )

  try:
    raw_weather = fetch_hybrid_ensemble_forecast(STATION_LAT, STATION_LON)
    if raw_weather:
      df_fc = parse_ensemble_hourly_table(raw_weather)
      current_obs = get_current_synoptic_target(df_fc)

      col_m1, col_m2 = st.columns(2)
      col_m1.metric("Suhu (TT)", f"{current_obs['tt_c']} °C")
      col_m2.metric("Kelembapan", f"{int(round(current_obs['rh_pc']))} %")

      col_m1.metric(
          "Titik Embun",
          f"{current_obs['td_c']} °C",
          f"Tw: {current_obs['tw_c']} °C",
          delta_color="off",
      )
      col_m2.metric(
          "Tekanan (QFF)",
          f"{current_obs['qff_mb']}",
          f"QFE: {current_obs['qfe_mb']}",
          delta_color="off",
      )
  except Exception as e:
    st.warning(f"Gagal memuat preview model: {e}")

if "autopilot" not in st.session_state:
  st.session_state.autopilot = None

is_running = (
    st.session_state.autopilot is not None
    and st.session_state.autopilot.is_running()
)

st.title("Stasiun Meteorologi WAGB (96655) - Muara Teweh")

tab_input, tab_autopilot, tab_evap, tab_db_reports = st.tabs([
    "📝 Input Manual (ME-48 / SYNOP)",
    "🛰️ Autopilot Controller",
    "🪣 Helper Evaporasi",
    "🗄️ Database & Pelaporan Iklim",
])

# ==============================================================================
# TAB 1: Input Manual (ME-48 / SYNOP)
# ==============================================================================
with tab_input:
  # --- SECTION 1: METADATA ---
  st.subheader("1. Date, Time & Observer (UTC)")
  col_t1, col_t2, col_t3 = st.columns(3)
  with col_t1:
    obs_date = st.date_input(
        "Tanggal Pengamatan", value=datetime.now(timezone.utc).date()
    )
  with col_t2:
    utc_hours = [f"{h:02d}:00" for h in range(24)]
    obs_hour = st.selectbox(
        "Jam Pengamatan (UTC)",
        options=utc_hours,
        index=datetime.now(timezone.utc).hour,
    )
  with col_t3:
    selected_observer = st.selectbox(
        "Pengamat", options=list(OBSERVER_ROSTER.keys())
    )
    raw_id = OBSERVER_ROSTER[selected_observer]
    observer_id = (
        st.number_input("Observer ID", value=None, step=1)
        if raw_id is None
        else raw_id
    )

  # --- SECTION 2: WIND, WEATHER, PRESSURE & TEMPERATURE ---
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
    visibility = st.number_input(
        "Jarak Pandang Mendatar (km)", min_value=0.0, value=None, format="%.1f"
    )

  with col_cuaca:
    st.markdown("`CUACA`")
    st.text_input("Pengenal Cuaca (ix)", value="1 (Otomatis)", disabled=True)
    ww = st.selectbox(
        "Cuaca Saat Pengamatan (ww)",
        options=list(PRESENT_WEATHER_WW.keys()),
        format_func=lambda x: PRESENT_WEATHER_WW.get(x, ""),
    )
    w1 = st.selectbox(
        "Cuaca Yang Lalu 1 (W1)",
        options=list(PAST_WEATHER_W.keys()),
        format_func=lambda x: PAST_WEATHER_W.get(x, ""),
        index=0,
        help="Fenomena cuaca paling signifikan (W1 ≥ W2)",
    )
    w2 = st.selectbox(
        "Cuaca Yang Lalu 2 (W2)",
        options=list(PAST_WEATHER_W.keys()),
        format_func=lambda x: PAST_WEATHER_W.get(x, ""),
        index=0,
    )

  with col_tekanan:
    st.markdown("`TEKANAN`")
    st.caption("🔵 Barometer Digital")
    qff = st.number_input("Tekanan QFF (mb)", value=None, format="%.1f")
    qfe = st.number_input("Tekanan QFE (mb)", value=None, format="%.1f")

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

  # --- SECTION 3: CLOUDS & PRECIPITATION ---
  st.subheader("3. Weather & Detailed Cloud Observation")
  col_top1, col_top2, col_top3 = st.columns(3)
  with col_top1:
    cloud_cover_oktas_m = st.selectbox(
        "Tutupan Awan Total (oktas)",
        options=list(CLOUD_COVER_OKTAS.keys()),
        format_func=lambda x: CLOUD_COVER_OKTAS.get(x, ""),
    )
  with col_top2:
    rainfall_last_mm = st.number_input(
        "Curah Hujan (mm)", min_value=0.0, value=None, step=0.1
    )
  with col_top3:
    cloud_vertical_vis = st.number_input(
        "Jarak Pandang Vertikal (m)", min_value=0, value=None
    )

  st.markdown("---")
  col_low, col_med, col_high = st.columns(3)

  # Low Clouds
  with col_low:
    st.markdown("### ☁️ AWAN RENDAH")
    cloud_low_type_cl = st.selectbox(
        "CL",
        options=list(CLOUD_LOW_TYPE_CL.keys()),
        format_func=lambda x: CLOUD_LOW_TYPE_CL.get(x, ""),
    )
    cloud_low_cover_oktas = st.selectbox(
        "NCL",
        options=list(LAYER_OKTAS.keys()),
        format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )

    st.caption("Layer 1 (Utama)")
    cloud_low_type_1 = st.selectbox(
        "Jenis CL (1)",
        options=list(LOW_CLOUD_GENUS.keys()),
        format_func=lambda x: LOW_CLOUD_GENUS.get(x, ""),
    )
    cloud_low_cover_1 = st.selectbox(
        "Jumlah CL (1)",
        options=list(LAYER_OKTAS.keys()),
        format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )
    cloud_low_base_1 = st.number_input("Tinggi Dasar CL (m) 1", value=None)
    cloud_low_peak_1 = st.number_input("Tinggi Puncak CL (m) 1", value=None)
    cloud_low_dir_1 = st.selectbox(
        "Arah Gerak CL (1)",
        options=list(CLOUD_DIRECTION.keys()),
        format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
    )
    cloud_elevation_angle_ec_1 = st.number_input("Sudut Elevasi 1", value=None)
    cloud_low_dir_true_da_1 = st.number_input("Arah Sebenarnya 1", value=None)

    with st.expander("➕ Tambah Layer CL (2)"):
      cloud_low_type_2 = st.selectbox(
          "Jenis CL (2)",
          options=list(LOW_CLOUD_GENUS.keys()),
          format_func=lambda x: LOW_CLOUD_GENUS.get(x, ""),
      )
      cloud_low_cover_2 = st.selectbox(
          "Jumlah CL (2)",
          options=list(LAYER_OKTAS.keys()),
          format_func=lambda x: LAYER_OKTAS.get(x, ""),
      )
      cloud_low_base_2 = st.number_input("Tinggi Dasar (m) 2", value=None)
      cloud_low_peak_2 = st.number_input("Tinggi Puncak (m) 2", value=None)
      cloud_low_dir_2 = st.selectbox(
          "Arah Gerak (2)",
          options=list(CLOUD_DIRECTION.keys()),
          format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
      )
      cloud_elevation_angle_ec_2 = st.number_input("Sudut Elevasi 2", value=None)
      cloud_low_dir_true_da_2 = st.number_input("Arah Sebenarnya 2", value=None)

      with st.expander("➕ Tambah Layer CL (3)"):
        cloud_low_type_3 = st.selectbox(
            "Jenis CL (3)",
            options=list(LOW_CLOUD_GENUS.keys()),
            format_func=lambda x: LOW_CLOUD_GENUS.get(x, ""),
        )
        cloud_low_cover_3 = st.selectbox(
            "Jumlah CL (3)",
            options=list(LAYER_OKTAS.keys()),
            format_func=lambda x: LAYER_OKTAS.get(x, ""),
        )
        cloud_low_base_3 = st.number_input("Tinggi Dasar (m) 3", value=None)
        cloud_low_dir_3 = st.selectbox(
            "Arah Gerak (3)",
            options=list(CLOUD_DIRECTION.keys()),
            format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
        )

  # Medium Clouds
  with col_med:
    st.markdown("### ☁️ AWAN MENENGAH")
    cloud_med_type_cm = st.selectbox(
        "CM",
        options=list(CLOUD_MED_TYPE_CM.keys()),
        format_func=lambda x: CLOUD_MED_TYPE_CM.get(x, ""),
    )
    cloud_med_cover_oktas = st.selectbox(
        "NCM",
        options=list(LAYER_OKTAS.keys()),
        format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )

    st.caption("Layer 1 (Utama)")
    cloud_med_type_1 = st.selectbox(
        "Jenis CM (1)",
        options=list(MED_CLOUD_GENUS.keys()),
        format_func=lambda x: MED_CLOUD_GENUS.get(x, ""),
    )
    cloud_med_cover_1 = st.selectbox(
        "Jumlah CM (1)",
        options=list(LAYER_OKTAS.keys()),
        format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )
    cloud_med_base_1 = st.number_input("Tinggi Dasar CM (m) 1", value=None)
    cloud_med_dir_1 = st.selectbox(
        "Arah Gerak CM (1)",
        options=list(CLOUD_DIRECTION.keys()),
        format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
    )

    with st.expander("➕ Tambah Layer CM (2)"):
      cloud_med_type_2 = st.selectbox(
          "Jenis CM (2)",
          options=list(MED_CLOUD_GENUS.keys()),
          format_func=lambda x: MED_CLOUD_GENUS.get(x, ""),
      )
      cloud_med_cover_2 = st.selectbox(
          "Jumlah CM (2)",
          options=list(LAYER_OKTAS.keys()),
          format_func=lambda x: LAYER_OKTAS.get(x, ""),
      )
      cloud_med_base_2 = st.number_input("Tinggi Dasar CM (m) 2", value=None)
      cloud_med_dir_2 = st.selectbox(
          "Arah Gerak CM (2)",
          options=list(CLOUD_DIRECTION.keys()),
          format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
      )

  # High Clouds
  with col_high:
    st.markdown("### ☁️ AWAN TINGGI")
    cloud_high_type_ch = st.selectbox(
        "CH",
        options=list(CLOUD_HIGH_TYPE_CH.keys()),
        format_func=lambda x: CLOUD_HIGH_TYPE_CH.get(x, ""),
    )
    cloud_high_cover_oktas = st.selectbox(
        "NCH",
        options=["/", "0", "1", "2", "3", "4", "5", "6", "7", "8"],
        index=None,
    )

    st.caption("Layer 1 (Utama)")
    cloud_high_type_1 = st.selectbox(
        "Jenis CH (1)",
        options=list(HIGH_CLOUD_GENUS.keys()),
        format_func=lambda x: HIGH_CLOUD_GENUS.get(x, ""),
    )
    cloud_high_cover_1 = st.selectbox(
        "Jumlah CH (1)",
        options=list(LAYER_OKTAS.keys()),
        format_func=lambda x: LAYER_OKTAS.get(x, ""),
    )
    cloud_high_base_1 = st.number_input("Tinggi Dasar CH (m) 1", value=None)
    cloud_high_dir_1 = st.selectbox(
        "Arah Gerak CH (1)",
        options=list(CLOUD_DIRECTION.keys()),
        format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
    )

    with st.expander("➕ Tambah Layer CH (2)"):
      cloud_high_type_2 = st.selectbox(
          "Jenis CH (2)",
          options=list(HIGH_CLOUD_GENUS.keys()),
          format_func=lambda x: HIGH_CLOUD_GENUS.get(x, ""),
      )
      cloud_high_cover_2 = st.selectbox(
          "Jumlah CH (2)",
          options=list(LAYER_OKTAS.keys()),
          format_func=lambda x: LAYER_OKTAS.get(x, ""),
      )
      cloud_high_base_2 = st.number_input("Tinggi Dasar CH (m) 2", value=None)
      cloud_high_dir_2 = st.selectbox(
          "Arah Gerak CH (2)",
          options=list(CLOUD_DIRECTION.keys()),
          format_func=lambda x: CLOUD_DIRECTION.get(x, ""),
      )

  # --- SECTION 4: EVAPORATION, SUNSHINE & SOIL ---
  st.subheader("4. Penguapan, Matahari & Tanah")
  col_evap, col_sun, col_land = st.columns(3)
  with col_evap:
    st.markdown("`PENGUAPAN`")
    evaporation_24hours_mm_eee = st.number_input(
        "Penguapan 24 Jam (mm)", min_value=0.0, step=0.1, value=None
    )
    evaporation_eq_indicator_ie = st.selectbox(
        "Indikator Alat (iE)",
        options=[None, 0, 1, 2, 3, 4],
        format_func=lambda x: "" if x is None else str(x),
    )

  with col_sun:
    st.markdown("`MATAHARI`")
    solar_rad_24h_jcm2_f24 = st.number_input(
        "Radiasi Matahari (J/cm²)", min_value=0.0, value=None
    )
    sunshine_h_sss = st.number_input(
        "Penyinaran (jam)", min_value=0.0, max_value=24.0, step=0.1, value=None
    )

  with col_land:
    st.markdown("`TANAH`")
    land_cond = st.selectbox(
        "Keadaan Tanah", options=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], index=None
    )
    land_note = st.text_input("Catatan Tanah", value="")

  # --- SECTION 5: GENERATOR & GTS BROADCAST CENTER ---
  st.markdown("---")
  st.subheader("5. Sandi SYNOP & METAR Generator")

  def generate_codes_from_form(update_widgets: bool = True):
    """Coordinates payload construction, server preview call, and METAR synthesis."""
    hour_int = int(obs_hour.split(":")[0])
    iso_utc_timestamp = f"{obs_date.strftime('%Y-%m-%d')}T{hour_int:02d}:00:00Z"

    payload = {
        "data_timestamp": iso_utc_timestamp,
        "bmkgsoft_id": int(STATION_ID),
        "observer_id": int(observer_id) if observer_id else None,
        "wind_dir_deg_dd": wind_dir,
        "wind_indicator_iw": wind_indicator_iw,
        "wind_speed_ff": wind_speed,
        "visibility_vv": visibility,
        "past_weather_w1": str(w1) if w1 is not None else "",
        "past_weather_w2": str(w2) if w2 is not None else "",
        "present_weather_ww": ww,
        "temp_drybulb_c_tttttt": temp_dry,
        "temp_wetbulb_c": temp_wet,
        "temp_max_c_txtxtx": temp_max,
        "temp_min_c_tntntn": temp_min,
        "pressure_reading_mb": None,
        "pressure_temp_c": None,
        "pressure_qff_mb_derived": qff,
        "pressure_qfe_mb_derived": qfe,
        "rainfall_last_mm": rainfall_last_mm,
        "cloud_cover_oktas_m": cloud_cover_oktas_m,
        "cloud_vertical_vis": cloud_vertical_vis,
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
        "cloud_low_dir_1": int(cloud_low_dir_1) if cloud_low_dir_1 is not None else None,
        "cloud_low_dir_2": int(cloud_low_dir_2) if cloud_low_dir_2 is not None else None,
        "cloud_low_dir_3": int(cloud_low_dir_3) if cloud_low_dir_3 is not None else None,
        "cloud_elevation_angle_ec_1": cloud_elevation_angle_ec_1,
        "cloud_elevation_angle_ec_2": cloud_elevation_angle_ec_2,
        "cloud_low_dir_true_da_1": cloud_low_dir_true_da_1,
        "cloud_low_dir_true_da_2": cloud_low_dir_true_da_2,
        "cloud_med_type_cm": cloud_med_type_cm,
        "cloud_med_cover_oktas": cloud_med_cover_oktas,
        "cloud_med_type_1": cloud_med_type_1,
        "cloud_med_type_2": str(cloud_med_type_2 or ""),
        "cloud_med_cover_1": cloud_med_cover_1,
        "cloud_med_cover_2": str(cloud_med_cover_2 or ""),
        "cloud_med_base_1": cloud_med_base_1,
        "cloud_med_base_2": cloud_med_base_2,
        "cloud_med_dir_1": int(cloud_med_dir_1) if cloud_med_dir_1 is not None else None,
        "cloud_med_dir_2": int(cloud_med_dir_2) if cloud_med_dir_2 is not None else None,
        "cloud_high_type_ch": cloud_high_type_ch,
        "cloud_high_cover_oktas": cloud_high_cover_oktas,
        "cloud_high_type_1": cloud_high_type_1,
        "cloud_high_type_2": str(cloud_high_type_2 or ""),
        "cloud_high_cover_1": cloud_high_cover_1,
        "cloud_high_cover_2": str(cloud_high_cover_2 or ""),
        "cloud_high_base_1": cloud_high_base_1,
        "cloud_high_base_2": cloud_high_base_2,
        "cloud_high_dir_1": int(cloud_high_dir_1) if cloud_high_dir_1 is not None else None,
        "cloud_high_dir_2": int(cloud_high_dir_2) if cloud_high_dir_2 is not None else None,
        "solar_rad_24h_jcm2_f24": solar_rad_24h_jcm2_f24,
        "sunshine_h_sss": sunshine_h_sss,
        "evaporation_24hours_mm_eee": evaporation_24hours_mm_eee,
        "evaporation_eq_indicator_ie": evaporation_eq_indicator_ie,
        "land_cond": land_cond,
        "land_note": land_note,
    }
    apply_sky_condition_rules(payload, cloud_cover_oktas_m)

    # 1. Fetch SYNOP dari Preview
    with st.spinner("Mengambil kalkulasi & sandi SYNOP dari BMKGSoft..."):
      calc_data, official_synop, code, err_msg = fetch_preview_calculations(
          payload, iso_utc_timestamp, REQ_HEADERS
      )
      if code in (200, 201):
        if "rainfall_indicator_ir" in calc_data:
          st.session_state["rainfall_indicator_ir"] = int(
              calc_data["rainfall_indicator_ir"]
          )
      else:
        st.warning(f"Preview API status {code}: {err_msg}")

    # 2. Derive Dew Point & METAR Layers
    p_qff = float(qff) if qff else 1013.25
    server_td = calc_data.get("temp_dewpoint_c_tdtdtd")
    t_dew = (
        float(server_td)
        if server_td is not None
        else (
            derive_dew_point(float(temp_dry), float(temp_wet), p_qff)
            if (temp_dry is not None and temp_wet is not None)
            else None
        )
    )

    vis_m = normalize_visibility_meters(visibility)
    metar_layers = parse_metar_cloud_layers(
        cloud_cover_oktas_m,
        cloud_vertical_vis,
        cloud_low_cover_1,
        cloud_low_base_1,
        cloud_low_type_1,
    )

    # 3. Generate METAR String
    try:
      raw_metar, wmo_bulletin = convert_synop_to_metar_peraturan(
          obs_date=obs_date,
          obs_hour=obs_hour,
          wind_dir=wind_dir or 0,
          wind_spd=wind_speed or 0,
          wind_gust=None,
          visibility_m=vis_m,
          ww_code=ww,
          temp_dry=temp_dry,
          temp_dew=t_dew,
          qnh_hpa=p_qff,
          cloud_layers=metar_layers,
          station_icao="WAGB",
      )
    except Exception as err:
      raw_metar, wmo_bulletin = "", f"Gagal generate METAR: {err}"

    # Simpan ke internal state
    st.session_state["latest_synop_code"] = official_synop
    st.session_state["latest_metar_code"] = raw_metar
    st.session_state["latest_calc_data"] = calc_data
    st.session_state["latest_payload"] = payload
    st.session_state["latest_iso_ts"] = iso_utc_timestamp

    if update_widgets:
      st.session_state["gts_synop_text"] = official_synop
      st.session_state["gts_metar_text"] = wmo_bulletin

    st.toast("✅ Sandi SYNOP & METAR berhasil digenerate!", icon="⚡")
    return payload, calc_data, official_synop, raw_metar, wmo_bulletin, iso_utc_timestamp

  if st.button(
      "⚡ Generate Sandi (SYNOP & METAR)",
      type="primary",
      use_container_width=True,
  ):
    generate_codes_from_form(update_widgets=True)

  if "gts_synop_text" not in st.session_state:
    st.session_state["gts_synop_text"] = ""
  if "gts_metar_text" not in st.session_state:
    st.session_state["gts_metar_text"] = ""

  tab_synop, tab_metar = st.tabs(["Sandi SYNOP Resmi", "Generator METAR (WAGB)"])

  with tab_synop:
    synop_area = st.text_area(
        "Sandi SYNOP (Ready to Broadcast)",
        key="gts_synop_text",
        height=130,
        placeholder="Klik tombol '⚡ Generate Sandi' di atas...",
    )
    if st.button("🚀 Broadcast SYNOP ke GTS"):
      text_synop = st.session_state.get("gts_synop_text", "")
      if not text_synop:
        st.error("Teks SYNOP kosong. Klik generate terlebih dahulu.")
      else:
        success, msg = broadcast_to_gts(text_synop, REQ_HEADERS)
        if success:
          st.success(f"✅ {msg}")
        else:
          st.error(f"❌ {msg}")

  with tab_metar:
    metar_area = st.text_area(
        "Sandi METAR",
        key="gts_metar_text",
        height=130,
        placeholder="Klik tombol '⚡ Generate Sandi' di atas...",
    )
    if st.button("🚀 Broadcast METAR ke GTS"):
      text_metar = st.session_state.get("gts_metar_text", "")
      if not text_metar:
        st.error("Teks METAR kosong. Klik generate terlebih dahulu.")
      else:
        target_ts = get_safe_metar_iso_timestamp(text_metar, obs_date)
        success, msg = broadcast_to_gts(text_metar, REQ_HEADERS)

        log_metar_bulletin(
            bulletin_ts=target_ts,
            metar_code=text_metar.strip().split("\n")[-1],
            wmo_bulletin=text_metar,
            sent_status=1 if success else 0,
            station_icao="WAGB",
        )

        if success:
          st.success(f"✅ {msg} (Tersimpan sebagai `{target_ts}` di `metar_logs`)")
        else:
          st.error(f"❌ {msg} (Gagal siar, tercatat sebagai status 0)")

  # --- SECTION 6: SUBMIT & COMMIT TO BMKGSOFT & SQLITE ---
  st.markdown("---")
  st.subheader("6. Simpan ke Database & Submit BMKGSoft")

  if "latest_payload" in st.session_state and st.session_state["latest_payload"]:
    with st.expander(
        "🔍 Live Inspector: Outgoing Payload (Klik untuk melihat)", expanded=False
    ):
      st.caption("Payload JSON yang telah dirakit dan siap dikirim ke BMKGSoft:")
      st.json(st.session_state["latest_payload"])

  submit_btn = st.button(
      "💾 Simpan Lokal & Submit BMKGSoft", use_container_width=True
  )

  if submit_btn:
    (
        payload,
        calc_data,
        official_synop,
        current_metar,
        wmo_bulletin,
        iso_utc_timestamp,
    ) = generate_codes_from_form(update_widgets=False)

    hour_int = int(obs_hour.split(":")[0])
    synop_input = st.session_state.get("gts_synop_text", "")
    final_synop = synop_input.strip() if synop_input and synop_input.strip() else official_synop
    final_metar = current_metar if current_metar else st.session_state.get("latest_metar_code", "")

    print("\n" + "=" * 60)
    print(f"[DEBUG SUBMIT] Timestamp : {iso_utc_timestamp} (Hour: {hour_int})")
    print("[DEBUG SUBMIT] Outgoing Payload:")
    print(json.dumps(payload, indent=2, default=str))
    print("=" * 60 + "\n")

    is_success, status_code, resp_text = submit_observation_entry(
        payload, iso_utc_timestamp, hour_int, REQ_HEADERS
    )

    with st.expander(
        f"🛠️ Debug Console — HTTP Status: {status_code}", expanded=not is_success
    ):
      col_req, col_res = st.columns(2)
      with col_req:
        st.markdown("**Payload Dikirim (`request.body`):**")
        st.json(payload)
      with col_res:
        st.markdown(f"**Respon Server (`HTTP {status_code}`):**")
        try:
          parsed_res = json.loads(resp_text)
          st.json(parsed_res)
        except Exception:
          st.code(
              resp_text or "<Badan respons kosong / Empty body>", language="text"
          )

    combined_record = {
        **payload,
        **calc_data.get("manual_entry", {}),
        **calc_data,
    }

    if is_success:
      save_local_observation(
          combined_record,
          encoded_synop=final_synop,
          encoded_metar=final_metar,
          synced=1,
      )
      st.balloons()
      st.success(
          f"✅ Terkirim ke BMKGSoft (Status {status_code}) & tersimpan lengkap di SQLite!"
      )
    else:
      save_local_observation(
          combined_record,
          encoded_synop=final_synop,
          encoded_metar=final_metar,
          synced=0,
      )
      st.error(
          f"⚠️ Gagal kirim ke BMKGSoft (HTTP {status_code}). Detail kegagalan terlihat pada Debug Console di atas."
      )

# ==============================================================================
# TAB 2: AUTOPILOT CONTROLLER
# ==============================================================================
with tab_autopilot:
  st.subheader("Kontrol Operasional Autopilot")

  col_ctrl, col_status = st.columns([1, 2], gap="large")

  with col_ctrl:
    with st.container(border=True):
      st.markdown("### Eksekusi Engine")
      st.write("Jadwal Transmisi Terjadwal:")
      st.markdown("""
            * **ME-48**: Tiap jam bulat (menit `:00` UTC)
            * **SEND GTS**: Jam sinoptik (`00, 03, 06... UTC`)
            * **METAR**: Tiap 30 menit (menit `:00` & `:30` UTC)
            """)

      btn_start = st.button(
          "🚀 START AUTOPILOT",
          use_container_width=True,
          disabled=is_running,
          type="primary",
      )
      btn_stop = st.button(
          "🛑 STOP AUTOPILOT",
          use_container_width=True,
          disabled=not is_running,
      )

      if btn_start:
        st.session_state.autopilot = BMKGAutopilot()
        st.session_state.autopilot.start()
        st.rerun()

      if btn_stop:
        if st.session_state.autopilot:
          st.session_state.autopilot.stop()
        st.rerun()

      st.markdown("---")
      # Tombol uji coba manual
      btn_test_now = st.button(
          "⚡ Trigger Kirim Sekarang (Uji Coba)",
          use_container_width=True,
          disabled=not is_running,
          help=(
              "Jalankan siklus transmisi ME-48 & METAR sekarang juga tanpa"
              " menunggu menit :00/:30."
          ),
      )

      if btn_test_now and st.session_state.autopilot:
        with st.spinner("Mengeksekusi transmisi autopilot uji coba..."):
          now_test = datetime.now(timezone.utc)
          test_min = 0 if now_test.minute < 30 else 30

          if test_min == 0:
            # Siklus jam bulat: Kirim ME-48 + METAR :00
            p, _ = st.session_state.autopilot._execute_hourly_observation(
                now_test, now_test.hour
            )
            st.session_state.autopilot._execute_metar_transmission(
                now_test, now_test.hour, 0, prebuilt_payload=p
            )
          else:
            # Siklus setengah jam: Khusus buletin METAR :30 saja
            st.session_state.autopilot._execute_metar_transmission(
                now_test, now_test.hour, 30
            )

        st.success(
            f"✅ Uji coba transmisi (menit :{test_min:02d}) selesai! Cek tab"
            " database untuk verifikasi."
        )
        st.rerun()

  with col_status:
    with st.container(border=True):
      st.markdown("### Status Engine Aktif")
      if is_running:
        st.success("🟢 **AUTOPILOT RUNNING**: Worker thread aktif di background")
        last_me48 = (
            st.session_state.autopilot.last_me48_sent or "Menunggu menit :00..."
        )
        last_metar = (
            st.session_state.autopilot.last_metar_sent
            or "Menunggu menit :00 / :30..."
        )

        st.info(f"**ME-48 / SYNOP Terakhir Ditransmisikan:** `{last_me48}`")
        st.info(f"**METAR Terakhir Ditransmisikan:** `{last_metar}`")
      else:
        st.error("🔴 **AUTOPILOT STOPPED / IDLE**")
        st.caption("Engine tidak berjalan. Tidak ada data yang dikirim.")

      if st.button("🔄 Refresh Status", use_container_width=True):
        st.rerun()

  with st.expander("ℹ️ Detail Logika Autopilot Terpasang", expanded=False):
    st.markdown("""
        1. **Carry-Over Otomatis:** Mengambil template visual (awan & jarak pandang) dari record `me48_observations` terakhir di `station_me48.db`.
        2. **Splicing String:** Grup cuaca/awan pada string `encoded_metar` dan `encoded_synop` lama disambung otomatis dengan nilai suhu dan tekanan baru dari model hibrida.
        3. **Wind Calm:** Angin selalu dikunci pada `00000KT` (kecepatan 0 knot, arah 0 derajat).
        4. **Curah Hujan:** Otomatis bernilai `0.0 mm` pada jam sinoptik (`00, 03, 06, 09, 12, 15, 18, 21 UTC`), dan `null` pada jam lainnya.
        """)

# ==============================================================================
# TAB 3: HELPER EVAPORASI PANCI TERBUKA
# ==============================================================================
with tab_evap:
  st.subheader("🪣 Helper Pengukuran Panci Evaporasi")
  st.caption(
      "Perhitungan Beda Tinggi (H) dan Evaporasi Harian (E = H + R <= 7.0) dengan"
      " Penyimpanan SQLite"
  )

  today_dt = datetime.now()
  c_ev1, c_ev2, c_ev3 = st.columns(3)
  with c_ev1:
    ev_year = st.number_input(
        "Tahun", min_value=2020, max_value=2030, value=today_dt.year, key="ev_thn"
    )
  with c_ev2:
    ev_month = st.selectbox(
        "Bulan",
        range(1, 13),
        index=today_dt.month - 1,
        format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
        key="ev_bln",
    )
  with c_ev3:
    ev_init_s2 = st.number_input(
        "Skala 2 Akhir Bulan Lalu", value=20.0, step=0.1, format="%.1f"
    )

  days_in_month = pd.Period(f"{ev_year}-{ev_month}").days_in_month
  default_ev_df = pd.DataFrame({
      "TGL": range(1, days_in_month + 1),
      "scale_1": [np.nan] * days_in_month,
      "scale_2": [20.0] * days_in_month,
      "rainfall_r": [0.0] * days_in_month,
  })

  edited_ev_df = st.data_editor(
      default_ev_df,
      column_config={
          "TGL": st.column_config.NumberColumn("TGL", disabled=True),
          "scale_1": st.column_config.NumberColumn(
              "Skala 1 (Isikan)", step=0.1, format="%.1f"
          ),
          "scale_2": st.column_config.NumberColumn(
              "Skala 2 (Ganti Air)", step=0.1, format="%.1f"
          ),
          "rainfall_r": st.column_config.NumberColumn(
              "Hujan R (mm)", step=0.1, format="%.1f"
          ),
      },
      hide_index=True,
      use_container_width=True,
  )

  if st.button(
      "Hitung & Simpan Evaporasi ke Database",
      type="primary",
      use_container_width=True,
  ):
    ev_res = compute_pan_evaporation(
        edited_ev_df, prev_month_last_scale2=ev_init_s2
    )

    saved_count = 0
    for _, row in ev_res.iterrows():
      if pd.notnull(row["scale_1"]) or pd.notnull(row["evaporation_ev"]):
        date_str = f"{ev_year}-{ev_month:02d}-{int(row['TGL']):02d}"
        save_pan_evaporation_record(
            obs_date=date_str,
            scale_1=float(row["scale_1"]) if pd.notnull(row["scale_1"]) else None,
            scale_2=float(row["scale_2"]) if pd.notnull(row["scale_2"]) else 20.0,
            diff_h=float(row["diff_h"]) if pd.notnull(row["diff_h"]) else None,
            rainfall_r=(
                float(row["rainfall_r"])
                if pd.notnull(row["rainfall_r"])
                else 0.0
            ),
            evaporation_ev=(
                float(row["evaporation_ev"])
                if pd.notnull(row["evaporation_ev"])
                else None
            ),
        )
        saved_count += 1

    st.success(
        f"✅ Perhitungan selesai & {saved_count} rekaman tersimpan di tabel"
        " `pan_evaporation`!"
    )
    st.dataframe(
        ev_res[[
            "TGL",
            "scale_1",
            "scale_2",
            "diff_h",
            "rainfall_r",
            "evaporation_ev",
        ]],
        column_config={
            "diff_h": st.column_config.NumberColumn(
                "H (Beda Tinggi)", format="%.1f"
            ),
            "evaporation_ev": st.column_config.NumberColumn(
                "EV (E=H+R)", format="%.1f"
            ),
        },
        use_container_width=True,
    )
    st.download_button(
        "📥 Unduh CSV Evaporasi",
        ev_res.to_csv(index=False).encode("utf-8"),
        f"evaporasi_{ev_year}_{ev_month:02d}.csv",
        "text/csv",
    )

# ==============================================================================
# TAB 4: DATABASE & PELAPORAN IKLIM
# ==============================================================================
with tab_db_reports:
  render_data_manager()