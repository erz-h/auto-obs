from datetime import date, datetime
import math
import re
from typing import Any, List, Optional, Tuple


def _safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
  """Safely converts string, float, or None to an int."""
  if val is None or val == "":
    return default
  try:
    return int(float(val))
  except (ValueError, TypeError):
    return default


def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
  """Safely converts string, int, or None to a float."""
  if val is None or val == "":
    return default
  try:
    return float(val)
  except (ValueError, TypeError):
    return default


def _parse_hour_str(obs_hour: Any) -> str:
  """Extracts a two-digit hour string regardless of input format.

  Handles ints (0 -> '00'), strings ('06', '06 UTC', '06:00'), or None.
  """
  if obs_hour is None:
    return "00"
  if isinstance(obs_hour, int):
    return f"{obs_hour:02d}"

  # Extract leading digits if format is '06 UTC' or '06:00'
  match = re.search(r"\d+", str(obs_hour))
  if match:
    val = int(match.group())
    return f"{val:02d}"
  return "00"


def _parse_day_str(obs_date: Any) -> str:
  """Extracts a two-digit day string from datetime, date, or ISO string."""
  if hasattr(obs_date, "strftime"):
    return obs_date.strftime("%d")
  if isinstance(obs_date, str):
    match = re.findall(r"\d+", obs_date)
    if match:
      # Assume last or middle element is day
      return f"{int(match[-1]):02d}"
  return datetime.utcnow().strftime("%d")


def round_metar_temp(val: Any) -> str:
  """Rounds temperature to full integer per Peraturan BMKG No. 001/2009 Section A.12.

  Values exactly at 0.5 round up algebraically. Negative values are prefixed
  with 'M'.
  """
  f_val = _safe_float(val)
  if f_val is None:
    return ""

  rounded = math.floor(f_val + 0.5)
  if rounded < 0:
    return f"M{abs(rounded):02d}"
  return f"{rounded:02d}"


def round_metar_vis(vis_m: Any) -> str:
  """Rounds visibility downwards per Peraturan BMKG No. 001/2009 Section A.7.1."""
  v_val = _safe_float(vis_m)
  if v_val is None:
    return "9999"

  v = int(v_val)
  if v >= 10000:
    return "9999"
  elif v >= 5000:
    return f"{(v // 1000) * 1000:04d}"
  elif v >= 800:
    return f"{(v // 100) * 100:04d}"
  else:
    return f"{(v // 50) * 50:04d}"


def convert_synop_to_metar_peraturan(
    obs_date: Any,
    obs_hour: Any,
    wind_dir: Any,
    wind_spd: Any,
    wind_gust: Any,
    visibility_m: Any,
    ww_code: Any,
    temp_dry: Any,
    temp_dew: Any,
    qnh_hpa: Any,
    cloud_layers: Optional[List[Tuple[int, float, str]]] = None,
    station_icao: str = "WAGB",
) -> Tuple[str, str]:
  """Translates SYNOP observation variables to a compliant METAR string

  and WMO bulletin following Peraturan KBMKG No. KEP. 001 Tahun 2009.
  """
  # 1. Timestamp (Section A.4)
  day_str = _parse_day_str(obs_date)
  hour_str = _parse_hour_str(obs_hour)
  ts_code = f"{day_str}{hour_str}00"

  # 2. Surface Wind (Section A.6)
  w_dir_raw = _safe_float(wind_dir)
  w_spd_raw = _safe_float(wind_spd)
  w_gst_raw = _safe_float(wind_gust)

  if w_spd_raw is None or w_spd_raw < 1:
    wind_str = "00000KT"  # Calm[cite: 10]
  else:
    # Round direction to nearest 10 degrees[cite: 10]
    w_dir = int(round(w_dir_raw / 10.0) * 10) if w_dir_raw is not None else 0  #[cite: 10]
    if w_dir == 0 and w_spd_raw >= 1:
      w_dir = 360  # True North[cite: 10]

    # Speed & Gust[cite: 10]
    spd_val = int(w_spd_raw)
    spd_str = "P99" if spd_val >= 100 else f"{spd_val:02d}"  #[cite: 10]

    gust_str = ""
    if w_gst_raw is not None and (w_gst_raw - w_spd_raw >= 10):
      gust_str = f"G{int(w_gst_raw):02d}"  #[cite: 10]

    wind_str = f"{w_dir:03d}{spd_str}{gust_str}KT"

  # 3. Horizontal Visibility (Section A.7)[cite: 11, 12]
  vis_part = round_metar_vis(visibility_m)  #[cite: 11, 12]

  # 4. Present Weather (Section A.9 & Table 4678)[cite: 15, 35]
  wx_code = _safe_int(ww_code)
  v_num = _safe_float(visibility_m, default=9999.0)
  wx_str = ""

  if wx_code is not None:
    if wx_code in [4, 5]:
      wx_str = "HZ" if v_num <= 5000 else ""  #[cite: 38, 41]
    elif wx_code == 10:
      wx_str = "BR" if 1000 <= v_num <= 5000 else ""  #[cite: 38, 41]
    elif 40 <= wx_code <= 49:
      wx_str = "FG" if v_num < 1000 else "BR"  #[cite: 38, 41]
    elif 50 <= wx_code <= 55:
      wx_str = "-DZ" if wx_code in [50, 51] else "DZ"  #[cite: 35, 40]
    elif 60 <= wx_code <= 65:
      wx_str = "-RA" if wx_code in [60, 61] else "RA"  #[cite: 35, 40]
    elif wx_code in [66, 67]:
      wx_str = "+RA"  #[cite: 35, 40]
    elif 80 <= wx_code <= 82:
      wx_str = (
          "-SHRA" if wx_code == 80 else ("SHRA" if wx_code == 81 else "+SHRA")
      )  #[cite: 35, 40]
    elif 91 <= wx_code <= 99 or wx_code in [17, 29]:
      wx_str = (
          "TSRA"
          if (60 <= wx_code <= 69 or 80 <= wx_code <= 82)
          else ("+TSRA" if wx_code in [95, 97] else "TS")
      )  #[cite: 35, 37, 40]

  cloud_tokens = []
  if cloud_layers:
        valid_layers = [
            lyr for lyr in cloud_layers 
            if lyr[0] is not None and lyr[1] is not None and _safe_float(lyr[1]) is not None
        ]
        
        for oktas_raw, h_m_raw, genus_raw in valid_layers:
            oktas = _safe_int(oktas_raw)
            h_m = _safe_float(h_m_raw)
            
            if oktas is None or oktas <= 0 or h_m is None:
                continue

            # Amount categories #[cite: 17]
            if 1 <= oktas <= 2:
                amt = "FEW" #[cite: 17]
            elif 3 <= oktas <= 4:
                amt = "SCT" #[cite: 17]
            elif 5 <= oktas <= 7:
                amt = "BKN" #[cite: 17]
            elif oktas >= 8:
                amt = "OVC" #[cite: 17]
            else:
                continue

            # Height: meters to feet, rounded UP (ceil) to hundreds of feet #[cite: 18, 28]
            h_ft = h_m * 3.28084
            if h_ft <= 10000:
                h_code = f"{int(math.ceil(h_ft / 100.0)):03d}" #[cite: 18, 28]
            else:
                h_code = f"{int(math.ceil(h_ft / 1000.0) * 10):03d}" #[cite: 18, 28]

            # Convective Genus Suffix:
            # 9 (Cb) -> CB
            # 8 (Cu) -> TCU
            # 6 (Sc), 7 (St), / -> no suffix
            g_val = str(genus_raw or "").strip().lower()
            convective = ""

            if g_val in ["9", "cb"] or "cumulonimbus" in g_val:  #[cite: 17, 48]
              convective = "CB"  #[cite: 17]
            elif (
                g_val in ["8", "cu", "tcu"] or "cumulus" in g_val
            ) and "strato" not in g_val:  #[cite: 17, 48]
              convective = "TCU"  #[cite: 17]

            # Append the complete layer token[cite: 8]
            cloud_tokens.append(f"{amt}{h_code}{convective}")

  # Blank if no valid cloud layers exist
  cloud_part = " ".join(cloud_tokens) if cloud_tokens else ""


  # 6. Air Temperature / Dew Point (Section A.12)[cite: 19]
  t_str = round_metar_temp(temp_dry)  #[cite: 19]
  td_str = round_metar_temp(temp_dew)  #[cite: 19]
  temp_part = f"{t_str}/{td_str}" if (t_str and td_str) else ""

  # 7. Pressure QNH (Section A.13 - Strictly floored to whole hPa)[cite: 19]
  q_val = _safe_float(qnh_hpa)
  qnh_part = f"Q{int(math.floor(q_val)):04d}" if q_val is not None else ""  #[cite: 19]

  # 8. Assemble METAR tokens (empty tokens are stripped out)
  tokens = [
      "METAR",  #[cite: 8]
      station_icao,  #[cite: 8]
      f"{ts_code}Z",  #[cite: 8]
      wind_str,  #[cite: 8]
      vis_part,  #[cite: 8]
      wx_str,  #[cite: 8]
      cloud_part,  # Blank if none
      temp_part,  #[cite: 8]
      qnh_part,  #[cite: 8]
      "NOSIG=",  #[cite: 8, 25]
  ]

  encoded_metar = " ".join([t for t in tokens if t])
  bulletin_with_header = f"SAID40 {station_icao} {ts_code}\n{encoded_metar}"

  return encoded_metar, bulletin_with_header