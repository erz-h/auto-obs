"""api_client.py

HTTP client for BMKGSoft REST endpoints (/preview, /entry, /gts).
"""

import requests

BASE_URL = "https://bmkgsatu.bmkg.go.id/api/v21"
STATION_ID = 54
PRIMARY_SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}


def get_api_headers(token: str, clearance: str) -> dict:
  """Builds required BMKGSoft request headers with bearer token and cloudflare cookie."""
  return {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
      "Cookie": f"cf_clearance={clearance}",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://bmkgsatu.bmkg.go.id/meteorologi/sinoptik",
  }


def fetch_preview_calculations(
    payload: dict, iso_timestamp: str, headers: dict
) -> tuple[dict, str, int, str]:
  """Calls BMKGSoft /entry/preview/ to compute dew point, RH, ppp, and server SYNOP."""
  url = f"{BASE_URL}/sinoptik/entry/preview/station/{STATION_ID}/date/{iso_timestamp}"
  clean_payload = {
      k: v
      for k, v in payload.items()
      if k not in ("rainfall_indicator_ir", "edited_encoded_synop")
  }

  try:
    res = requests.post(url, json=clean_payload, headers=headers, timeout=12)
    if res.status_code in (200, 201):
      data = res.json().get("data") or {}
      synop = data.get("encoded_synop", "")
      return data, synop, res.status_code, ""
    return {}, "", res.status_code, res.text
  except Exception as e:
    return {}, "", 0, str(e)


def submit_observation_entry(
    payload: dict, iso_timestamp: str, hour_int: int, headers: dict
) -> tuple[bool, int, str]:
  """Submits finalized observation payload to the BMKGSoft logbook database."""
  url = (
      f"{BASE_URL}/sinoptik/entry/station/{STATION_ID}/date/{iso_timestamp}"
  )
  clean_payload = {
      k: v
      for k, v in payload.items()
      if k not in ("rainfall_indicator_ir", "edited_encoded_synop")
  }

  method = requests.put if hour_int in PRIMARY_SYNOP_HOURS else requests.post
  try:
    res = method(url, json=clean_payload, headers=headers, timeout=12)
    # Fallback to PUT if POST is rejected for an existing slot
    if hour_int not in PRIMARY_SYNOP_HOURS and res.status_code not in (
        200,
        201,
    ):
      res = requests.put(
          url, json=clean_payload, headers=headers, timeout=12
      )

    is_success = res.status_code in (200, 201)
    return is_success, res.status_code, res.text
  except Exception as e:
    return False, 0, str(e)


def broadcast_to_gts(sandi_text: str, headers: dict) -> tuple[bool, str]:
  """Sends bulletin text (SYNOP/METAR) directly to the BMKG GTS entry gateway."""
  if not sandi_text.strip():
    return False, "Sandi tidak boleh kosong."

  url = f"{BASE_URL}/gts/entry"
  try:
    res = requests.post(
        url,
        json={"sandi": sandi_text.strip(), "only_save": False},
        headers=headers,
        timeout=15,
    )
    if res.status_code in (200, 201):
      return True, "Broadcast berhasil terkirim ke GTS (200 OK)!"
    return False, f"Server menolak ({res.status_code}): {res.text}"
  except Exception as e:
    return False, f"Koneksi GTS terputus: {e}"