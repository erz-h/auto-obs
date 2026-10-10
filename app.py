import os
import sqlite3
from datetime import datetime, timezone
from auth import get_bmkg_credentials
from dotenv import load_dotenv
import requests
import streamlit as st

# Load credentials from .env
load_dotenv()
DEFAULT_USER = os.getenv("BMKG_USERNAME", "96595")
DEFAULT_PASS = os.getenv("BMKG_PASSWORD", "opr96595")

st.set_page_config(page_title="BMKG Station ME 48 Entry", layout="wide")
st.title("Station ME 48 Observation & BMKGSoft Sync")

# --- STATION CONFIGURATION ---
BASE_URL = "https://bmkgsatu.bmkg.go.id/api/v21"
STATION_ID = 54  # WAGB / Station 96595

# Station Observer Roster
OBSERVER_ROSTER = {
    "Emir Hazam": 5882,
    "Dhimaz": 2273,
    "Adrian": 6480,
    "Other / Custom ID": None,
}

PRIMARY_SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

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
with st.form("me48_entry_form"):
  st.subheader("1. Date, Time & Observer (UTC)")
  col_t1, col_t2, col_t3 = st.columns(3)
  with col_t1:
    obs_date = st.date_input("Observation Date UTC")
  with col_t2:
    obs_hour = st.selectbox(
        "Observation Hour UTC",
        options=[f"{h:02d}:00" for h in range(24)],
        index=15,
    )
  with col_t3:
    selected_observer = st.selectbox(
        "Duty Observer Name", options=list(OBSERVER_ROSTER.keys())
    )
    if selected_observer == "Other / Custom ID":
      OBSERVER_ID = st.number_input("Enter BMKG Observer ID", value=5882, step=1)
    else:
      OBSERVER_ID = OBSERVER_ROSTER[selected_observer]

  st.subheader("2. Temperatures & Pressure")
  col1, col2 = st.columns(2)
  with col1:
    temp_dry = st.number_input("Dry Bulb (°C)", value=26.6, step=0.1)
    temp_wet = st.number_input("Wet Bulb (°C)", value=25.3, step=0.1)
    temp_max = st.number_input("Max Temp (°C)", value=None)
    temp_min = st.number_input("Min Temp (°C)", value=None)
  with col2:
    qff = st.number_input("QFF Pressure (hPa)", value=1013.6, step=0.1)
    qfe = st.number_input("QFE Pressure (hPa)", value=1009.0, step=0.1)
    rainfall = st.number_input("Rainfall (mm)", value=0.0, step=0.1)

  st.subheader("3. Wind, Weather & Clouds")
  col3, col4 = st.columns(2)
  with col3:
    wind_dir = st.number_input("Wind Direction (degrees)", value=0, step=10)
    wind_speed = st.number_input("Wind Speed (knots)", value=0, step=1)
    visibility = st.number_input("Visibility (km)", value=0.1, step=0.1)
    ww = st.number_input("Present Weather (ww)", value=4, step=1)
    w1 = st.text_input("Past Weather (W1)", value="4")
    w2 = st.text_input("Past Weather (W2)", value="4")
  with col4:
    cloud_m = st.text_input("Total Cloud Cover (oktas)", value="/")
    cloud_cl = st.text_input("Low Cloud (CL)", value="/")
    cloud_cm = st.text_input("Medium Cloud (CM)", value="/")
    cloud_ch = st.text_input("High Cloud (CH)", value="/")

  st.subheader("4. Encoded SYNOP String")
  synop_text = st.text_area(
      "SYNOP Code",
      value=(
          "SIID73 WAGB 071500\nAAXX 07154\n96595 31/01 /0000 10266 20248 30090"
          " 40136 51011 70444\n  333 56999="
      ),
  )

  submit_btn = st.form_submit_button("Save Locally & Push to BMKGSoft")


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
      "rainfall_last_mm": rainfall if rainfall is not None else 0,
      "temp_drybulb_c_tttttt": temp_dry,
      "temp_max_c_txtxtx": temp_max,
      "temp_min_c_tntntn": temp_min,
      "temp_wetbulb_c": temp_wet,
      "cloud_cover_oktas_m": cloud_m,
      "cloud_low_type_cl": cloud_cl,
      "cloud_med_type_cm": cloud_cm,
      "cloud_high_type_ch": cloud_ch,
      "cloud_low_cover_oktas": "/",
      "cloud_med_cover_oktas": "/",
      "cloud_high_cover_oktas": "/",
      "cloud_low_type_1": "/",
      "cloud_low_type_2": "",
      "cloud_low_type_3": "",
      "cloud_med_type_1": "/",
      "cloud_med_type_2": "",
      "cloud_high_type_1": "/",
      "cloud_high_type_2": "",
      "cloud_low_base_1": None,
      "cloud_low_base_2": None,
      "cloud_low_base_3": None,
      "cloud_med_base_1": None,
      "cloud_med_base_2": None,
      "cloud_high_base_1": None,
      "cloud_high_base_2": None,
      "cloud_low_peak_1": None,
      "cloud_low_peak_2": None,
      "cloud_low_cover_1": "/",
      "cloud_low_cover_2": "",
      "cloud_low_cover_3": "",
      "cloud_med_cover_1": "/",
      "cloud_med_cover_2": "",
      "cloud_high_cover_1": "/",
      "cloud_high_cover_2": "",
      "cloud_low_dir_1": 9,
      "cloud_low_dir_2": None,
      "cloud_low_dir_3": None,
      "cloud_med_dir_1": 9,
      "cloud_med_dir_2": None,
      "cloud_high_dir_1": 9,
      "cloud_high_dir_2": None,
      "cloud_elevation_angle_ec_1": None,
      "cloud_elevation_angle_ec_2": None,
      "cloud_low_dir_true_da_1": None,
      "cloud_low_dir_true_da_2": None,
      "cloud_vertical_vis": None,
      "solar_rad_24h_jcm2_f24": None,
      "sunshine_h_sss": None,
      "evaporation_24hours_mm_eee": None,
      "evaporation_eq_indicator_ie": None,
      "land_cond": 0,
      "land_note": "",
      "pressure_qff_mb_derived": qff,
      "pressure_qfe_mb_derived": qfe,
  }

  save_local_observation(full_payload, synop_text)
  st.info("Observation recorded locally in SQLite (`station_me48.db`).")

  try:
    if hour_int in PRIMARY_SYNOP_HOURS:
      st.text("Primary Synoptic Hour detected. Sending GTS broadcast...")
      gts_url = f"{BASE_URL}/gts/entry"
      gts_payload = {"sandi": synop_text, "only_save": False}
      gts_res = requests.post(gts_url, json=gts_payload, headers=headers)

      if gts_res.status_code in [200, 201]:
        st.success("GTS Broadcast Successful (200 OK).")
      else:
        st.error(
            f"GTS Broadcast Failed ({gts_res.status_code}): {gts_res.text}"
        )

    st.text("Executing observation submission to BMKGSoft...")
    submit_url = (
        f"{BASE_URL}/sinoptik/entry/station/{STATION_ID}/date/{iso_utc_timestamp}"
    )

    final_payload = full_payload.copy()
    final_payload["edited_encoded_synop"] = synop_text
    for flag in DIGI_FLAG_KEYS:
      final_payload[flag] = False

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

    if submit_res.status_code in [200, 201]:
      set_synced_status(iso_utc_timestamp)
      st.balloons()
      st.success(
          f"Successfully submitted for {selected_observer} (ID: {OBSERVER_ID})"
          f" to BMKGSoft (`{iso_utc_timestamp}`)!"
      )
    else:
      st.warning(
          "Saved locally, but submission to BMKGSoft returned status"
          f" {submit_res.status_code}: {submit_res.text}"
      )

  except Exception as err:
    st.error(
        f"Network Connection Exception: {err}. Entry saved safely in local"
        " station database."
    )