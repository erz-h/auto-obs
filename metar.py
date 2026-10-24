from datetime import date, datetime, timezone
import math
import re
from typing import Any, List, Optional, Tuple, Union


# =============================================================================
# HELPER FUNCTIONS (Must be at the top of the file)
# =============================================================================
def _safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
  if val is None or str(val).strip() in ["", "None", "/"]:
    return default
  try:
    return int(float(str(val).strip()))
  except (ValueError, TypeError):
    return default


def _safe_float(
    val: Any, default: Optional[float] = None
) -> Optional[float]:
  if val is None or str(val).strip() in ["", "None", "/"]:
    return default
  try:
    return float(str(val).strip())
  except (ValueError, TypeError):
    return default


def _parse_day_str(obs_date: Any) -> str:
  if hasattr(obs_date, "strftime"):
    return obs_date.strftime("%d")
  s = str(obs_date).strip()
  if "-" in s:
    return s.split("-")[-1].zfill(2)
  return s.zfill(2)[-2:]


def _parse_hour_str(obs_hour: Any) -> str:
  s = str(obs_hour).strip()
  if ":" in s:
    return s.split(":")[0].zfill(2)
  val = _safe_int(s, 0)
  return f"{val:02d}"


def round_metar_vis(visibility_m: Any) -> str:
  v = _safe_float(visibility_m, default=9999.0)
  if v >= 10000:
    return "9999"
  if v >= 5000:
    return f"{int(math.floor(v / 1000.0) * 1000):04d}"
  if v >= 800:
    return f"{int(math.floor(v / 100.0) * 100):04d}"
  return f"{int(math.floor(v / 50.0) * 50):04d}"


def round_metar_temp(temp_c: Any) -> str:
  val = _safe_float(temp_c)
  if val is None:
    return ""
  rounded = int(round(val))
  if rounded < 0:
    return f"M{abs(rounded):02d}"
  return f"{abs(rounded):02d}"

def convert_ww_to_metar(
    ww_code: Any, visibility_m: Optional[float] = 9999.0
) -> str:
  """Translates WMO Code Table 4677 (SYNOP ww) to WMO Table 4678 / ICAO METAR

  present weather descriptor, enforcing visibility cutoffs per regulations.
  """
  wx_code = _safe_int(ww_code)
  if wx_code is None or wx_code in [0, 1, 2, 3]:
    return ""

  v_num = _safe_float(visibility_m, default=9999.0)

  # 04 - 09: Obscuration / Lithometeors (Requires Vis <= 5000m)
  if wx_code == 4:
    return "FU" if v_num <= 5000 else ""  # Smoke
  if wx_code == 5:
    return "HZ" if v_num <= 5000 else ""  # Haze
  if wx_code in [6, 7]:
    return "DU" if v_num <= 5000 else ""  # Dust / Dust storm
  if wx_code == 8:
    return "PO"  # Dust whirls
  if wx_code == 9:
    return "DS"  # Duststorm

  # 10 - 19: Non-precipitation / Atmospheric phenomena
  if wx_code == 10:
    return "BR" if 1000 <= v_num <= 5000 else ""  # Mist
  if wx_code in [11, 12]:
    return "MIFG"  # Shallow fog
  if wx_code == 13:
    return "VCTS"  # Distant lightning
  if wx_code == 17:
    return "TS"  # Thunder heard, no precipitation at station
  if wx_code == 18:
    return "SQ"  # Squall
  if wx_code == 19:
    return "FC"  # Funnel cloud / Tornado / Waterspout

  # 20 - 29: Recent Weather in past hour (RE prefix)
  recent_map = {
      20: "REDZ",
      21: "RERA",
      22: "RESN",
      23: "RERASN",
      24: "REFZRA",
      25: "RESHRA",
      26: "RESHSN",
      27: "REGR",
      28: "REFG",
      29: "RETS",
  }
  if wx_code in recent_map:
    return recent_map[wx_code]

  # 30 - 39: Dust / Sand / Snow storms
  if 30 <= wx_code <= 35:
    return "+SA" if wx_code in [32, 35] else "SA"

  # 40 - 49: Fog (FG requires Vis < 1000m; if Vis >= 1000m it is BR)
  if wx_code in [40, 41]:
    return "BCFG" if v_num < 1000 else "BR"
  if 42 <= wx_code <= 47:
    return "FG" if v_num < 1000 else "BR"
  if wx_code in [48, 49]:
    return "FZFG" if v_num < 1000 else "BR"

  # 50 - 59: Drizzle (Gerimis)
  if wx_code in [50, 51]:
    return "-DZ"
  if wx_code in [52, 53]:
    return "DZ"
  if wx_code in [54, 55]:
    return "+DZ"
  if wx_code == 56:
    return "-FZDZ"
  if wx_code == 57:
    return "+FZDZ"
  if wx_code in [58, 59]:
    return "DZRA"

  # 60 - 69: Rain (Hujan)
  if wx_code in [60, 61]:
    return "-RA"
  if wx_code in [62, 63]:
    return "RA"
  if wx_code in [64, 65]:
    return "+RA"
  if wx_code == 66:
    return "-FZRA"
  if wx_code == 67:
    return "+FZRA"
  if wx_code in [68, 69]:
    return "-RASN" if wx_code == 68 else "+RASN"

  # 70 - 79: Solid precipitation
  if wx_code in [70, 71]:
    return "-SN"
  if wx_code in [72, 73]:
    return "SN"
  if wx_code in [74, 75]:
    return "+SN"
  if wx_code == 76:
    return "IC"
  if wx_code == 77:
    return "SG"
  if wx_code == 79:
    return "PL"

  # 80 - 90: Showers
  if wx_code == 80:
    return "-SHRA"
  if wx_code == 81:
    return "SHRA"
  if wx_code == 82:
    return "+SHRA"
  if wx_code in [83, 84]:
    return "-SHRASN" if wx_code == 83 else "+SHRASN"
  if wx_code in [85, 86]:
    return "-SHSN" if wx_code == 85 else "+SHSN"
  if wx_code in [87, 88]:
    return "SHGS"
  if wx_code in [89, 90]:
    return "+SHGR" if wx_code == 90 else "-SHGR"

  # 91 - 99: Thunderstorms (Badai Guntur)
  if wx_code == 91:
    return "-RA RETS"
  if wx_code == 92:
    return "RA RETS"
  if wx_code in [93, 94]:
    return "SN RETS"
  if wx_code == 95:
    return "TSRA"  # Moderate TS with rain
  if wx_code == 96:
    return "TSGR"  # Moderate TS with hail
  if wx_code == 97:
    return "+TSRA"  # Severe TS with rain
  if wx_code == 98:
    return "TSSA"  # TS with dust/sand
  if wx_code == 99:
    return "+TSGR"  # Severe TS with hail

  return ""

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
    cloud_layers: Optional[List[Union[Tuple[Any, Any, Any], str]]] = None,
    station_icao: str = "WAGB",
    is_speci: bool = False,
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
    wind_str = "00000KT"  # Calm
  else:
    # Round direction to nearest 10 degrees
    w_dir = int(round(w_dir_raw / 10.0) * 10) if w_dir_raw is not None else 0
    if w_dir == 0 and w_spd_raw >= 1:
      w_dir = 360  # True North

    # Speed & Gust
    spd_val = int(w_spd_raw)
    spd_str = "P99" if spd_val >= 100 else f"{spd_val:02d}"

    gust_str = ""
    if w_gst_raw is not None and (w_gst_raw - w_spd_raw >= 10):
      gust_str = f"G{int(w_gst_raw):02d}"

    wind_str = f"{w_dir:03d}{spd_str}{gust_str}KT"

  # 3. Horizontal Visibility (Section A.7)
  vis_part = round_metar_vis(visibility_m)
  v_num = _safe_float(visibility_m, default=9999.0)

  # 4. Present Weather (Section A.9 & WMO Table 4678)
  v_num = _safe_float(visibility_m, default=9999.0)
  wx_str = convert_ww_to_metar(ww_code, visibility_m=v_num)

  # 5. Cloud Layers / Vertical Visibility (Section A.10)
  cloud_tokens = []
  if cloud_layers:
    for layer in cloud_layers:
      # Direct string tokens (e.g., 'VV003', 'FEW015CB', 'NSC')
      if isinstance(layer, str):
        if layer.strip():
          cloud_tokens.append(layer.strip())
        continue

      # Tuple of (oktas, height_meters, genus)
      if isinstance(layer, (list, tuple)) and len(layer) >= 3:
        oktas_raw, h_m_raw, genus_raw = layer[0], layer[1], layer[2]
        oktas = _safe_int(oktas_raw)
        h_m = _safe_float(h_m_raw)

        if oktas is None or oktas <= 0 or h_m is None:
          continue

        # Okta to Amount Category
        if 1 <= oktas <= 2:
          amt = "FEW"
        elif 3 <= oktas <= 4:
          amt = "SCT"
        elif 5 <= oktas <= 7:
          amt = "BKN"
        elif oktas >= 8:
          amt = "OVC"
        else:
          continue

        # Height: convert meters to feet, rounded UP (ceil) to hundreds of feet
        h_ft = h_m * 3.28084
        if h_ft <= 10000:
          h_code = f"{int(math.ceil(h_ft / 100.0)):03d}"
        else:
          h_code = f"{int(math.ceil(h_ft / 1000.0) * 10):03d}"

        # Convective Suffix (CB / TCU)
        g_val = str(genus_raw or "").strip().lower()
        convective = ""
        if g_val in ["9", "cb"] or "cumulonimbus" in g_val:
          convective = "CB"
        elif (
            g_val in ["8", "cu", "tcu"] or "cumulus" in g_val
        ) and "strato" not in g_val:
          convective = "TCU"

        cloud_tokens.append(f"{amt}{h_code}{convective}")

  cloud_part = " ".join(cloud_tokens) if cloud_tokens else ""

  # 6. Air Temperature / Dew Point (Section A.12)
  t_str = round_metar_temp(temp_dry)
  td_str = round_metar_temp(temp_dew)
  temp_part = f"{t_str}/{td_str}" if (t_str and td_str) else ""

  # 7. Pressure QNH (Section A.13 - Floored to integer hPa per regulations)
  q_val = _safe_float(qnh_hpa)
  qnh_part = f"Q{int(math.floor(q_val)):04d}" if q_val is not None else ""

  # 8. Assemble Message Tokens
  header_ident = "SPECI" if is_speci else "METAR"
  tokens = [
      header_ident,
      station_icao,
      f"{ts_code}Z",
      wind_str,
      vis_part,
      wx_str,
      cloud_part,
      temp_part,
      qnh_part,
      "NOSIG=",
  ]

  encoded_metar = " ".join([t for t in tokens if t])

  # WMO Bulletin Header: SAID40 for routine METAR, SPID40 for SPECI
  bulletin_prefix = "SPID40" if is_speci else "SAID40"
  bulletin_with_header = (
      f"{bulletin_prefix} {station_icao} {ts_code}\n{encoded_metar}"
  )

  return encoded_metar, bulletin_with_header

translate_ww_to_metar = convert_ww_to_metar

def get_safe_metar_iso_timestamp(
    metar_text: str, obs_date_obj: datetime.date
) -> str:
  match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", metar_text)
  if not match:
    # Fallback jika sandi tidak memiliki grup waktu standar
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")

  day = int(match.group(1))
  hour = int(match.group(2))
  minute = int(match.group(3))

  year = obs_date_obj.year
  month = obs_date_obj.month

  # Penyesuaian jika terjadi pergantian bulan
  if obs_date_obj.day >= 28 and day == 1:
    if month == 12:
      month = 1
      year += 1
    else:
      month += 1
  elif obs_date_obj.day == 1 and day >= 28:
    if month == 1:
      month = 12
      year -= 1
    else:
      month -= 1

  return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"