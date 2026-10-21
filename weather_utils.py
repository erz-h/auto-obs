"""weather_utils.py

Meteorological calculations, conversions, and BMKG sky condition rules.
"""

import math


def derive_dew_point(
    t_dry: float, t_wet: float, p_hpa: float = 1013.25
) -> float:
  """Calculates psychrometric dew point using the Magnus-Tetens formula."""
  try:
    ew_tw = 6.1078 * (10 ** ((7.5 * t_wet) / (237.3 + t_wet)))
    e = ew_tw - 0.000662 * p_hpa * (t_dry - t_wet)
    if e <= 0:
      return t_wet
    log_e = math.log10(e / 6.1078)
    return round((237.3 * log_e) / (7.5 - log_e), 1)
  except Exception:
    return t_wet


def normalize_visibility_meters(visibility_val) -> float:
  """Converts visibility input (km or m) to standard METAR meters."""
  if visibility_val is None:
    return 9999.0
  val = float(visibility_val)
  return val * 1000.0 if val <= 50.0 else val


def parse_metar_cloud_layers(
    cloud_cover_oktas, vertical_vis, low_cover_1, low_base_1, low_type_1
) -> list:
  """Builds layer tuples or vertical visibility codes for METAR generation."""
  layers = []
  c_ok = str(cloud_cover_oktas).strip()

  if c_ok in ("/", "9"):
    if vertical_vis not in (None, "", "None", "/"):
      vv_ft = float(vertical_vis) * 3.28084
      layers.append(f"VV{int(math.ceil(vv_ft / 100.0)):03d}")
    else:
      layers.append("VV///")
  elif c_ok not in ("0", "0.0"):
    if low_cover_1 is not None and low_base_1 is not None:
      try:
        ok_val = int(str(low_cover_1).strip())
        if ok_val > 0:
          layers.append((ok_val, float(low_base_1), low_type_1))
      except (ValueError, TypeError):
        pass

  return layers


def apply_sky_condition_rules(payload: dict, c_oktas: str) -> None:
  """Enforces standard BMKG rules for clear sky (0), obscured (9), or indiscernible (/)."""
  c_oktas = str(c_oktas).strip()
  if c_oktas == "/":
    val, dir_val, c_type = "/", 9, "/"
  elif c_oktas == "9":
    val, dir_val, c_type = 9, 9, "/"
  elif c_oktas in ("0", "0.0"):
    val, dir_val, c_type = 0, 0, 0
  else:
    return

  for prefix, key_type in [
      ("cloud_low", "cl"),
      ("cloud_med", "cm"),
      ("cloud_high", "ch"),
  ]:
    payload[f"{prefix}_type_{key_type}"] = c_type
    payload[f"{prefix}_cover_oktas"] = val
    payload[f"{prefix}_type_1"] = c_type
    payload[f"{prefix}_cover_1"] = val
    payload[f"{prefix}_dir_1"] = dir_val