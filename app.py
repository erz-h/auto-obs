import os
from datetime import date, datetime, timezone
from dotenv import load_dotenv
import streamlit as st
from autopilot_engine import BMKGAutopilot
from data_manager import render_data_manager
from data_model import (
    STATION_LAT,
    STATION_LON,
    fetch_hybrid_ensemble_forecast,
    get_current_synoptic_target,
    parse_ensemble_hourly_table,
)

# Custom Internal Modules
from api_client import (
    STATION_ID,
    broadcast_to_gts,
    fetch_preview_calculations,
    get_api_headers,
    submit_observation_entry,
)
from auth import get_bmkg_credentials
from db import get_historical_records, save_local_observation
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
from metar import convert_synop_to_metar_peraturan
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
    "Emir Hazam": 5882,
    "Dhimaz": 2273,
    "Adrian": 6480,
    "Other / Custom ID": None,
}

st.set_page_config(page_title="BMKG Station ME 48 Entry", layout="wide")
st.title("Station ME 48 Observation & BMKGSoft Sync")

# --- SIDEBAR: AUTHORIZATION ---
st.sidebar.header("Station Authorization")
if "bearer_token" not in st.session_state:
  st.session_state["bearer_token"] = ""
if "cf_clearance" not in st.session_state:
  st.session_state["cf_clearance"] = ""

st_user = st.sidebar.text_input("BMKG Username", value=DEFAULT_USER)
st_pass = st.sidebar.text_input(
    "BMKG Password", value=DEFAULT_PASS, type="password"
)

if st.sidebar.button("🔑 Auto-Fetch Session Tokens"):
  if not st_user or not st_pass:
    st.sidebar.error("Masukkan Username dan Password BMKG.")
  else:
    with st.sidebar.status(
        "Logging in ke BMKGSoft...", expanded=True
    ) as status:
      try:
        token, cookie = get_bmkg_credentials(st_user, st_pass, headless=False)
        if not token:
          raise ValueError("Token kosong. Periksa koneksi atau kredensial.")
        st.session_state["bearer_token"] = token
        st.session_state["cf_clearance"] = cookie or ""
        status.update(label="Token berhasil diambil!", state="complete")
        st.rerun()
      except Exception as err:
        status.update(label=f"Gagal: {err}", state="error")

BEARER_TOKEN = st.sidebar.text_input(
    "Bearer Token", value=st.session_state["bearer_token"], type="password"
)
CF_CLEARANCE = st.sidebar.text_input(
    "cf_clearance Cookie",
    value=st.session_state["cf_clearance"],
    type="password",
)
REQ_HEADERS = get_api_headers(BEARER_TOKEN, CF_CLEARANCE)

# ==============================================================================
# SIDEBAR: MODEL & LIVE FORECAST
# ==============================================================================
with st.sidebar:
  # CSS untuk memperkecil seluruh metric khusus di dalam sidebar
  st.markdown(
      """
        <style>
        [data-testid="stSidebar"] [data-testid="stMetricValue"] {
            font-size: 1.15rem !important;
        }
        [data-testid="stSidebar"] [data-testid="stMetricDelta"] {
            font-size: 0.8rem !important;
        }
        [data-testid="stSidebar"] [data-testid="stMetricLabel"] {
            font-size: 0.85rem !important;
        }
        </style>
    """,
      unsafe_allow_html=True,
  )

  st.header("📊 Live Forecast")
  st.subheader("Model Hibrida Saat Ini")
  st.caption(
      "Kombinasi ICON (60%) + GEM (40%) untuk TT, ECMWF untuk Td & Baro."
  )

  try:
    raw_weather = fetch_hybrid_ensemble_forecast(STATION_LAT, STATION_LON)
    if raw_weather:
      df_fc = parse_ensemble_hourly_table(raw_weather)
      current_obs = get_current_synoptic_target(df_fc)

      col_m1, col_m2 = st.columns(2)

      # Baris 1: Suhu & Kelembapan
      col_m1.metric("Suhu (TT)", f"{current_obs['tt_c']} °C")
      col_m2.metric("Kelembapan", f"{int(round(current_obs['rh_pc']))} %")

      # Baris 2: Dew Point / Wet Bulb & Tekanan
      col_m1.metric(
          "Titik Embun",
          f"{current_obs['td_c']} °C",
          f"Tw: {current_obs['tw_c']} °C",
          delta_color="off",
      )
      col_m2.metric(
          "Tekanan (hPa)",
          f"{current_obs['qff_mb']}",
          f"QFE: {current_obs['qfe_mb']}",
          delta_color="off",
      )
  except Exception as e:
    st.warning(f"Gagal memuat preview model langsung: {e}")
  except Exception as e:
    st.warning(f"Gagal memuat preview model langsung: {e}")

if "autopilot" not in st.session_state:
  st.session_state.autopilot = None

is_running = (
    st.session_state.autopilot is not None
    and st.session_state.autopilot.is_running()
)

st.title("Stasiun Meteorologi WAGB (96655) - Muara Teweh")

# Inisialisasi 3 Tab Utama
tab_input, tab_autopilot, tab_db = st.tabs([
    "📝 Input Manual (ME-48 / SYNOP)",
    "🛰️ Autopilot Controller",
    "🗄️ Database ME-48 & Bulletin",
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
    st.write("")
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


  def generate_codes_from_form():
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
        "cloud_low_dir_1": int(cloud_low_dir_1)
        if cloud_low_dir_1 is not None
        else None,
        "cloud_low_dir_2": int(cloud_low_dir_2)
        if cloud_low_dir_2 is not None
        else None,
        "cloud_low_dir_3": int(cloud_low_dir_3)
        if cloud_low_dir_3 is not None
        else None,
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
        "cloud_med_dir_1": int(cloud_med_dir_1)
        if cloud_med_dir_1 is not None
        else None,
        "cloud_med_dir_2": int(cloud_med_dir_2)
        if cloud_med_dir_2 is not None
        else None,
        "cloud_high_type_ch": cloud_high_type_ch,
        "cloud_high_cover_oktas": cloud_high_cover_oktas,
        "cloud_high_type_1": cloud_high_type_1,
        "cloud_high_type_2": str(cloud_high_type_2 or ""),
        "cloud_high_cover_1": cloud_high_cover_1,
        "cloud_high_cover_2": str(cloud_high_cover_2 or ""),
        "cloud_high_base_1": cloud_high_base_1,
        "cloud_high_base_2": cloud_high_base_2,
        "cloud_high_dir_1": int(cloud_high_dir_1)
        if cloud_high_dir_1 is not None
        else None,
        "cloud_high_dir_2": int(cloud_high_dir_2)
        if cloud_high_dir_2 is not None
        else None,
        "solar_rad_24h_jcm2_f24": solar_rad_24h_jcm2_f24,
        "sunshine_h_sss": sunshine_h_sss,
        "evaporation_24hours_mm_eee": evaporation_24hours_mm_eee,
        "evaporation_eq_indicator_ie": evaporation_eq_indicator_ie,
        "land_cond": land_cond,
        "land_note": land_note,
    }
    apply_sky_condition_rules(payload, cloud_cover_oktas_m)

    # 1. Fetch SYNOP from Preview
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

    # 4. Bind directly to widget state
    st.session_state["gts_synop_text"] = official_synop
    st.session_state["gts_metar_text"] = wmo_bulletin
    st.session_state["latest_synop_code"] = official_synop
    st.session_state["latest_metar_code"] = raw_metar
    st.session_state["latest_calc_data"] = calc_data
    st.session_state["latest_payload"] = payload
    st.session_state["latest_iso_ts"] = iso_utc_timestamp
    st.toast("✅ Sandi SYNOP & METAR berhasil digenerate!", icon="⚡")


  if st.button("⚡ Generate Sandi (SYNOP & METAR)", type="primary", use_container_width=True):
    generate_codes_from_form()

  if "gts_synop_text" not in st.session_state:
    st.session_state["gts_synop_text"] = ""
  if "gts_metar_text" not in st.session_state:
    st.session_state["gts_metar_text"] = ""

  tab_synop, tab_metar = st.tabs(["Sandi SYNOP Resmi", "Generator METAR (WAGB)"])

  with tab_synop:
    synop_to_send = st.text_area(
        "Sandi SYNOP (Ready to Broadcast)",
        key="gts_synop_text",
        height=130,
        placeholder="Klik tombol '⚡ Generate Sandi' di atas untuk membuat sandi AAXX otomatis...",
    )
    if st.button("🚀 Broadcast SYNOP ke GTS"):
      success, msg = broadcast_to_gts(synop_to_send, REQ_HEADERS)
      if success:
        st.success(f"✅ {msg}")
      else:
        st.error(f"❌ {msg}")

  with tab_metar:
    metar_to_send = st.text_area(
        "Sandi METAR",
        key="gts_metar_text",
        height=130,
        placeholder="Klik tombol '⚡ Generate Sandi' di atas untuk membuat sandi METAR...",
    )
    if st.button("🚀 Broadcast METAR ke GTS"):
      success, msg = broadcast_to_gts(metar_to_send, REQ_HEADERS)
      if success:
        st.success(f"✅ {msg}")
      else:
        st.error(f"❌ {msg}")


  # --- SECTION 6: SUBMIT & COMMIT TO BMKGSOFT & SQLITE ---
  st.markdown("---")
  st.subheader("6. Simpan ke Database & Submit BMKGSoft")
  submit_btn = st.button("💾 Simpan Lokal & Submit BMKGSoft", use_container_width=True)

  if submit_btn:
    if not st.session_state.get("gts_synop_text"):
      generate_codes_from_form()

    iso_utc_timestamp = st.session_state.get(
        "latest_iso_ts",
        f"{obs_date.strftime('%Y-%m-%d')}T{int(obs_hour.split(':')[0]):02d}:00:00Z",
    )
    hour_int = int(obs_hour.split(":")[0])
    payload = st.session_state.get("latest_payload", {})
    calc_data = st.session_state.get("latest_calc_data", {})
    official_synop = st.session_state.get("gts_synop_text", "")
    current_metar = st.session_state.get("latest_metar_code", "")

    is_success, status_code, resp_text = submit_observation_entry(
        payload, iso_utc_timestamp, hour_int, REQ_HEADERS
    )

    combined_record = {
        **payload,
        **calc_data.get("manual_entry", {}),
        **calc_data,
    }

    if is_success:
      save_local_observation(
          combined_record,
          encoded_synop=official_synop,
          encoded_metar=current_metar,
          synced=1,
      )
      st.balloons()
      st.success("✅ Terkirim ke BMKGSoft & tersimpan lengkap di SQLite!")
    else:
      save_local_observation(
          combined_record,
          encoded_synop=official_synop,
          encoded_metar=current_metar,
          synced=0,
      )
      st.warning(
          f"⚠️ Gagal kirim ({status_code}). Data tersimpan di SQLite (synced=0)."
      )

# ==============================================================================
# TAB 2: AUTOPILOT CONTROLLER (Khusus Menjalankan Engine Otomatis)
# ==============================================================================
with tab_autopilot:
  st.subheader("Kontrol Operasional Autopilot")

  col_ctrl, col_status = st.columns([1, 2], gap="large")

  with col_ctrl:
    with st.container(border=True):
      st.markdown("### Eksekusi Engine")
      st.write("Jadwal Transmisi:")
      st.markdown("""
            * **ME-48**: Tiap jam (menit `:00`)
            * **SEND GTS**: Jam sinoptik (`00, 03, 06... UTC`)
            * **METAR**: Tiap 30 menit (menit `:30` dan `:00`)
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
        st.session_state.autopilot = BMKGAutopilot(api_client=None)
        st.session_state.autopilot.start()
        st.rerun()

      if btn_stop:
        if st.session_state.autopilot:
          st.session_state.autopilot.stop()
        st.rerun()

  with col_status:
    with st.container(border=True):
      st.markdown("### Status Engine Aktif")
      if is_running:
        st.success("🟢 **AUTOPILOT RUNNING**: Worker thread aktif di background")
        last_me48 = (
            st.session_state.autopilot.last_me48_sent
            or "Menunggu menit :00..."
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

  with st.expander("ℹ️ Detail Logika Autopilot Terpasang", expanded=False):
    st.markdown("""
        1. **Carry-Over Otomatis:** Mengambil template visual (awan & jarak pandang) dari record `me48_observations` terakhir di `station_me48.db`.
        2. **Splicing String:** Grup cuaca/awan pada string `encoded_metar` dan `encoded_synop` lama disambung otomatis dengan nilai suhu dan tekanan baru dari model hibrida.
        3. **Wind Calm:** Angin selalu dikunci pada `00000KT` (kecepatan 0 knot, arah 0 derajat).
        4. **Curah Hujan:** Otomatis bernilai `0.0 mm` pada jam sinoptik (`00, 03, 06, 09, 12, 15, 18, 21 UTC`), dan `null` pada jam lainnya.
        """)

# ==============================================================================
# TAB 3: DATABASE ME-48 & BULLETIN INSPECTION (Riwayat Penyimpanan SQLite)
# ==============================================================================
with tab_db:
    render_data_manager()