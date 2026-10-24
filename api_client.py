"""api_client.py

HTTP client for BMKGSoft REST endpoints (/preview, /entry, /gts).
Features bidirectional HTTP method fallback, robust payload sanitization,
and safe header construction.
"""

import os
from typing import Any, Dict, Optional, Tuple
import requests

BASE_URL = "https://bmkgsatu.bmkg.go.id/api/v21"
STATION_ID = int(os.getenv("BMKG_STATION_ID", "54"))
PRIMARY_SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

# Kolom internal aplikasi / database lokal yang dilarang dikirim ke server API
EXCLUDED_PAYLOAD_KEYS = {
    "rainfall_indicator_ir",
    "edited_encoded_synop",
    "encoded_synop",
    "encoded_metar",
    "synced_to_bmkg",
    "created_at",
    "manual_entry",
}


def get_api_headers(token: str, clearance: Optional[str] = None) -> Dict[str, str]:
  """Membuat header request resmi BMKGSoft.

  Hanya menyematkan cookie jika cf_clearance tersedia.
  """
  clean_token = token.strip() if token else ""
  headers = {
      "Authorization": f"Bearer {clean_token}",
      "Content-Type": "application/json",
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      ),
      "Referer": "https://bmkgsatu.bmkg.go.id/meteorologi/sinoptik",
  }

  if clearance and clearance.strip():
    headers["Cookie"] = f"cf_clearance={clearance.strip()}"

  return headers


def _sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
  """Membersihkan atribut payload dari metadata database lokal."""
  return {k: v for k, v in payload.items() if k not in EXCLUDED_PAYLOAD_KEYS}


def fetch_preview_calculations(
    payload: Dict[str, Any], iso_timestamp: str, headers: Dict[str, str]
) -> Tuple[Dict[str, Any], str, int, str]:
  """Meminta kalkulasi server BMKGSoft (/entry/preview/) untuk RH, Td, dan sandi SYNOP."""
  url = f"{BASE_URL}/sinoptik/entry/preview/station/{STATION_ID}/date/{iso_timestamp}"
  clean_payload = _sanitize_payload(payload)

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
    payload: Dict[str, Any],
    iso_timestamp: str,
    hour_int: int,
    headers: Dict[str, str],
) -> Tuple[bool, int, str]:
  """Mengirimkan entri pengamatan ME-48 dengan fallback dinamis POST/PUT."""
  url = f"{BASE_URL}/sinoptik/entry/station/{STATION_ID}/date/{iso_timestamp}"
  clean_payload = _sanitize_payload(payload)

  primary_method = (
      requests.put if hour_int in PRIMARY_SYNOP_HOURS else requests.post
  )
  fallback_method = (
      requests.post if hour_int in PRIMARY_SYNOP_HOURS else requests.put
  )

  try:
    res = primary_method(url, json=clean_payload, headers=headers, timeout=15)

    # Jika metode utama ditolak (misal slot butuh POST bukan PUT atau sebaliknya)
    if res.status_code not in (200, 201):
      res_fallback = fallback_method(
          url, json=clean_payload, headers=headers, timeout=15
      )
      if res_fallback.status_code in (200, 201):
        return True, res_fallback.status_code, res_fallback.text
      # Kembalikan status dari percobaan pertama jika fallback juga gagal
      return False, res.status_code, res.text

    return True, res.status_code, res.text
  except Exception as e:
    return False, 0, str(e)


def broadcast_to_gts(
    sandi_text: str, headers: Dict[str, str]
) -> Tuple[bool, str]:
  """Menyiarkan buletin resmi (SYNOP atau METAR) ke gateway GTS BMKG."""
  if not sandi_text or not sandi_text.strip():
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
    if res.status_code in (401, 403):
      return (
          False,
          f"Sesi ditolak ({res.status_code}): Token kedaluwarsa atau cookie"
          " Cloudflare tidak valid.",
      )
    return False, f"Server menolak ({res.status_code}): {res.text}"
  except Exception as e:
    return False, f"Koneksi GTS terputus: {e}"