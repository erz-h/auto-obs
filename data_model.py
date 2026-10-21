from datetime import datetime, timezone
import math
from typing import Any, Dict, Optional
import pandas as pd
import requests

# ==============================================================================
# KONFIGURASI STASIUN WAGB (BANDARA BERINGIN, MUARA TEWEH)
# ==============================================================================
STATION_LAT = -0.941
STATION_LON = 114.895

# Offset elevasi barometer terkalibrasi (Model - Aktual = +0.5 hPa)
# Dikurangkan agar QFE model identik dengan barometer raksa/digital stasiun
QFE_ELEVATION_BIAS_OFFSET = 0.5


def calculate_psychrometrics(tt: float, td: float) -> tuple[float, float]:
  """Menghitung Relative Humidity (RH) dan estimasi Wet Bulb (Tw).

  Menggunakan formula Magnus-Tetens dan aproksimasi empiris Stull.
  """
  # 1. Relative Humidity (%)
  e = 6.112 * math.exp((17.67 * td) / (td + 243.5))
  es = 6.112 * math.exp((17.67 * tt) / (tt + 243.5))
  rh = min(100.0, max(1.0, (e / es) * 100.0))

  # 2. Wet Bulb Temperature (Tw) - Formula Empiris Roland Stull (2011)
  # Presisi tinggi untuk tekanan permukaan dekat muka laut
  tw = (
      tt * math.atan(0.151977 * math.sqrt(rh + 8.313659))
      + math.atan(tt + rh)
      - math.atan(rh - 1.676331)
      + 0.00391838 * (rh**1.5) * math.atan(0.023101 * rh)
      - 4.686035
  )

  return round(rh, 1), round(tw, 1)


def fetch_hybrid_ensemble_forecast(
    lat: float = STATION_LAT,
    lon: float = STATION_LON,
    forecast_days: int = 1,
) -> Optional[Dict[str, Any]]:
  """Mengambil data multi-model dari Open-Meteo dan menghitung ensemble optimal:

  - TT  : 60% DWD ICON + 40% CMC GEM (menahan panas radiasi kanopi)
  - Td  : 100% ECMWF IFS (akurasi uap air terbaik)
  - QFF : 100% ECMWF IFS (akurasi fase pasang surut atmosfer ekuatorial)
  - QFE : Rerata ECMWF & ICON dikurangi koreksi elevasi stasiun (-0.5 hPa)
  """
  url = "https://api.open-meteo.com/v1/forecast"
  params = {
      "latitude": lat,
      "longitude": lon,
      "hourly": (
          "temperature_2m,dew_point_2m,surface_pressure,pressure_msl,wind_speed_10m,wind_direction_10m"
      ),
      "models": "ecmwf_ifs025,icon_seamless,gem_seamless",
      "timezone": "UTC",
      "forecast_days": forecast_days,
  }

  try:
    response = requests.get(url, params=params, timeout=12)
    response.raise_for_status()
    raw_json = response.json()
    return raw_json.get("hourly", {})
  except requests.RequestException as exc:
    print(f"[ERROR] Gagal menghubungi endpoint cuaca: {exc}")
    return None


def parse_ensemble_hourly_table(hourly_data: Dict[str, Any]) -> pd.DataFrame:
  """Memproses parallel array dari API menjadi DataFrame ensemble per jam."""
  times = hourly_data.get("time", [])
  records = []

  for i, t_str in enumerate(times):
    # --- Ekstraksi Nilai Model Mentah ---
    t_icon = hourly_data.get("temperature_2m_icon_seamless", [None])[i]
    t_gem = hourly_data.get("temperature_2m_gem_seamless", [None])[i]
    t_ecmwf = hourly_data.get("temperature_2m_ecmwf_ifs025", [None])[i]

    td_ecmwf = hourly_data.get("dew_point_2m_ecmwf_ifs025", [None])[i]
    qff_ecmwf = hourly_data.get("pressure_msl_ecmwf_ifs025", [None])[i]

    qfe_ecmwf = hourly_data.get("surface_pressure_ecmwf_ifs025", [None])[i]
    qfe_icon = hourly_data.get("surface_pressure_icon_seamless", [None])[i]

    wind_dir = hourly_data.get("wind_direction_10m_icon_seamless", [None])[i]
    wind_spd_ms = hourly_data.get("wind_speed_10m_icon_seamless", [None])[i]

    # --- Kalkulasi Ensemble Hibrida ---
    # 1. Suhu Kering (TT)
    if t_icon is not None and t_gem is not None:
      tt_ens = round(0.6 * t_icon + 0.4 * t_gem, 1)
    else:
      tt_ens = round(t_icon or t_gem or t_ecmwf or 30.0, 1)

    # 2. Titik Embun (Td)
    td_ens = round(td_ecmwf, 1) if td_ecmwf is not None else 24.5

    # Guardrail Termodinamika: Td tidak boleh melebihi TT
    if td_ens > tt_ens:
      td_ens = tt_ens

    # 3. Tekanan Permukaan Laut (QFF) & Tekanan Stasiun (QFE)
    qff_ens = round(qff_ecmwf, 1) if qff_ecmwf is not None else 1008.5

    if qfe_ecmwf is not None and qfe_icon is not None:
      qfe_raw_avg = (qfe_ecmwf + qfe_icon) / 2.0
    else:
      qfe_raw_avg = qfe_icon or qfe_ecmwf or (qff_ens - 4.6)

    # Terapkan offset kalibrasi elevasi barometer WAGB
    qfe_ens = round(qfe_raw_avg - QFE_ELEVATION_BIAS_OFFSET, 1)

    # 4. Parameter Turunan Psikrometrik (RH & Tw)
    rh_ens, tw_ens = calculate_psychrometrics(tt_ens, td_ens)

    # 5. Angin (Knots)
    wind_kt = (
        int(round(wind_spd_ms * 1.94384)) if wind_spd_ms is not None else 0
    )

    # Konversi Format Jam (UTC -> WIB)
    utc_str = t_str.split("T")[1][:5]
    utc_hour = int(utc_str[:2])
    wib_hour = f"{(utc_hour + 7) % 24:02d}:00"

    records.append({
        "time_utc": t_str,
        "jam_utc": utc_str,
        "jam_wib": wib_hour,
        "tt_c": tt_ens,
        "tw_c": tw_ens,
        "td_c": td_ens,
        "rh_pc": rh_ens,
        "qfe_mb": qfe_ens,
        "qff_mb": qff_ens,
        "wind_dir_deg": int(wind_dir) if wind_dir is not None else None,
        "wind_spd_kt": wind_kt,
    })

  return pd.DataFrame(records)


def get_current_synoptic_target(df: pd.DataFrame) -> Dict[str, Any]:
  """Mengambil 1 baris observasi yang paling dekat dengan jam UTC saat ini."""
  now_utc = datetime.now(timezone.utc)
  target_iso = f"{now_utc.strftime('%Y-%m-%d')}T{now_utc.hour:02d}:00"

  matched = df[df["time_utc"] == target_iso]
  if not matched.empty:
    return matched.iloc[0].to_dict()
  return df.iloc[0].to_dict()