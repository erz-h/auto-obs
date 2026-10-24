from datetime import datetime, timezone
import json
import logging
import re
import sqlite3
import threading
import time
from typing import Any, Dict, Optional, Tuple
import pandas as pd

# Modul Transmisi & Autentikasi Stasiun
from api_client import (
    STATION_ID,
    broadcast_to_gts,
    get_api_headers,
    submit_observation_entry,
)
from auth import load_stored_tokens
from data_model import (
    STATION_LAT,
    STATION_LON,
    fetch_hybrid_ensemble_forecast,
    get_current_synoptic_target,
    parse_ensemble_hourly_table,
)
from db import DB_PATH, init_db, log_metar_bulletin, save_local_observation

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("AutopilotEngine")

DEFAULT_FALLBACK_RECORD = {
    "data_timestamp": "2026-01-01T00:00:00Z",
    "bmkgsoft_id": "54",
    "observer_id": 531,
    "visibility_vv": 8.0,
    "present_weather_ww": 2,
    "past_weather_w1": 2,
    "past_weather_w2": 2,
    "weather_indicator_ix": 1,
    "land_cond": "0",
    "cloud_cover_oktas_m": "4",
    "cloud_low_type_cl": "1",
    "cloud_med_type_cm": "/",
    "cloud_high_type_ch": "/",
    "encoded_synop": "AAXX 17124 96655 41580 40000 10314 20252 30048 40094 70222 841//=",
    "encoded_metar": "METAR WAGB 171200Z 00000KT 8000 FEW015 31/25 Q1009 NOSIG=",
}

def splice_metar(
    prev_metar: str,
    now_utc: datetime,
    target_hour: int,
    target_min: int,
    obs: Dict[str, Any],
) -> str:
  """Memperbarui waktu, suhu/embun, dan QNH dari sandi METAR sebelumnya."""
  day_str = now_utc.strftime("%d")
  time_str = f"{target_hour:02d}{target_min:02d}Z"
  wind_str = "00000KT"

  t_rnd = int(round(obs["tt_c"]))
  td_rnd = int(round(obs["td_c"]))
  t_str = f"M{abs(t_rnd):02d}" if t_rnd < 0 else f"{t_rnd:02d}"
  td_str = f"M{abs(td_rnd):02d}" if td_rnd < 0 else f"{td_rnd:02d}"
  temp_dew_str = f"{t_str}/{td_str}"
  qnh_str = f"Q{int(round(obs['qff_mb'])):04d}"

  match = re.search(
      r"\b\d{5}(?:G\d{2})?KT\s+(.+?)\s+(?:M?\d{2}/M?\d{2})\b", prev_metar or ""
  )
  visual_part = match.group(1).strip() if match else "8000 FEW015"

  return (
      f"METAR WAGB {day_str}{time_str} {wind_str} {visual_part} {temp_dew_str}"
      f" {qnh_str} NOSIG="
  )

def splice_synop(
    prev_synop: str,
    now_utc: datetime,
    target_hour: int,
    obs: Dict[str, Any],
    is_synoptic: bool,
) -> str:
  """Memperbarui grup sinoptik dan termodinamika dari model hibrida."""
  if not prev_synop or "96655" not in prev_synop:
    return ""

  tokens = prev_synop.strip().rstrip("=").split()
  if len(tokens) < 4:
    return prev_synop

  day_str = now_utc.strftime("%d")
  tokens[1] = f"{day_str}{target_hour:02d}4"

  t_val = obs["tt_c"]
  td_val = obs["td_c"]
  qfe_val = obs["qfe_mb"]
  qff_val = obs["qff_mb"]

  g_temp = f"1{1 if t_val < 0 else 0}{int(round(abs(t_val) * 10)):03d}"
  g_dew = f"2{1 if td_val < 0 else 0}{int(round(abs(td_val) * 10)):03d}"
  g_qfe = f"3{int(round(qfe_val * 10)) % 10000:04d}"
  g_qff = f"4{int(round(qff_val * 10)) % 10000:04d}"
  g_rain = "60001"

  new_tokens = []
  rain_handled = False

  for i, tok in enumerate(tokens):
    if i == 4 and len(tok) == 5:
      new_tokens.append(f"{tok[0]}0000")
    elif tok.startswith("1") and len(tok) == 5 and tok[1:].isdigit():
      new_tokens.append(g_temp)
    elif tok.startswith("2") and len(tok) == 5 and tok[1:].isdigit():
      new_tokens.append(g_dew)
    elif tok.startswith("3") and len(tok) == 5 and tok[1:].isdigit():
      new_tokens.append(g_qfe)
    elif tok.startswith("4") and len(tok) == 5 and tok[1:].isdigit():
      new_tokens.append(g_qff)
    elif tok.startswith("6") and len(tok) == 5 and tok[1:].isdigit():
      if is_synoptic:
        new_tokens.append(g_rain)
      rain_handled = True
    else:
      new_tokens.append(tok)

  if is_synoptic and not rain_handled:
    try:
      idx_4 = [i for i, t in enumerate(new_tokens) if t.startswith("4")][0]
      new_tokens.insert(idx_4 + 1, g_rain)
    except IndexError:
      new_tokens.append(g_rain)

  return " ".join(new_tokens) + "="


class BMKGAutopilot:
  """Autopilot engine terintegrasi API BMKGSoft dan database station_me48.db."""

  def __init__(self, db_path: str = DB_PATH):
    self.db_path = db_path
    self._stop_event = threading.Event()
    self._thread: Optional[threading.Thread] = None

    # Teks sandi / status terbaca manusia untuk tampilan antarmuka
    self.last_me48_sent: Optional[str] = None
    self.last_metar_sent: Optional[str] = None

    # Pengenal siklus pengiriman internal (mencegah trigger ganda pada menit yang sama)
    self._last_me48_trigger_id: Optional[str] = None
    self._last_metar_trigger_id: Optional[str] = None

    init_db(self.db_path)

  def is_running(self) -> bool:
    return self._thread is not None and self._thread.is_alive()

  def start(self):
    if self.is_running():
      logger.warning("Autopilot sudah aktif.")
      return
    self._stop_event.clear()
    self._thread = threading.Thread(
        target=self._run_loop, name="WAGB_SQL_Worker", daemon=True
    )
    self._thread.start()
    logger.info("=== AUTOPILOT ENGINE STARTED (EXACT :00 & :30 TRIGGER) ===")

  def stop(self):
    self._stop_event.set()
    if self._thread:
      self._thread.join(timeout=3)
    logger.info("=== AUTOPILOT ENGINE STOPPED ===")

  def _get_active_headers(self) -> Dict[str, str]:
    token, cookie = load_stored_tokens()
    return get_api_headers(token, cookie)

  def _fetch_latest_from_sql(self) -> Dict[str, Any]:
    try:
      with sqlite3.connect(self.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM me48_observations ORDER BY data_timestamp DESC"
            " LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
          return dict(row)
    except Exception as err:
      logger.warning(
          f"Gagal membaca record database ({err}). Menggunakan record fallback."
      )
    return DEFAULT_FALLBACK_RECORD

  def _build_payload(
      self, target_hour: int, target_min: int = 0
  ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    latest_record = self._fetch_latest_from_sql()

    raw_weather = fetch_hybrid_ensemble_forecast(STATION_LAT, STATION_LON)
    if not raw_weather:
      raise RuntimeError("Gagal mengambil data cuaca numerik hibrida.")

    df = parse_ensemble_hourly_table(raw_weather)
    obs = get_current_synoptic_target(df)

    is_synoptic_hour = (target_hour % 3) == 0 and target_min == 0
    rainfall_val = 0.0 if is_synoptic_hour else None

    now_utc = datetime.now(timezone.utc)
    target_timestamp = (
        f"{now_utc.strftime('%Y-%m-%d')}T{target_hour:02d}:{target_min:02d}:00Z"
    )

    prev_metar_str = latest_record.get("encoded_metar") or ""
    new_metar_str = splice_metar(
        prev_metar_str, now_utc, target_hour, target_min, obs
    )

    prev_synop_str = latest_record.get("encoded_synop") or ""
    new_synop_str = splice_synop(
        prev_synop_str, now_utc, target_hour, obs, is_synoptic_hour
    )

    payload = {
        **latest_record,
        "data_timestamp": target_timestamp,
        "temp_drybulb_c_tttttt": obs["tt_c"],
        "temp_wetbulb_c": obs["tw_c"],
        "temp_dewpoint_c_tdtdtd": obs["td_c"],
        "relative_humidity_pc": obs["rh_pc"],
        "pressure_qfe_mb_derived": obs["qfe_mb"],
        "pressure_qff_mb_derived": obs["qff_mb"],
        "wind_dir_deg_dd": 0,
        "wind_speed_ff": 0,
        "wind_indicator_iw": 4,
        "rainfall_last_mm": rainfall_val,
        "rainfall_indicator_ir": 4,
        "encoded_metar": new_metar_str,
        "encoded_synop": new_synop_str,
    }

    return payload, obs

  def _run_loop(self):
    while not self._stop_event.is_set():
      now_utc = datetime.now(timezone.utc)
      minute = now_utc.minute
      current_hour = now_utc.hour
      date_str = now_utc.strftime("%Y%m%d")

      # 1. Pemicu Menit :00 (Jendela menit 0-1): Kirim ME-48 + METAR :00 sekaligus
      target_me48_id = f"{date_str}_{current_hour:02d}00"
      if minute in (0, 1) and self._last_me48_trigger_id != target_me48_id:
        p_hourly, _ = self._execute_hourly_observation(now_utc, current_hour)
        self._last_me48_trigger_id = target_me48_id

        # Mengoper p_hourly agar tidak memanggil fetch model dua kali
        target_metar_00_id = f"{date_str}_{current_hour:02d}00"
        self._execute_metar_transmission(
            now_utc, current_hour, 0, prebuilt_payload=p_hourly
        )
        self._last_metar_trigger_id = target_metar_00_id

      # 2. Pemicu Menit :30 (Jendela menit 30-31): Khusus transmisi METAR :30
      elif minute in (30, 31):
        target_metar_30_id = f"{date_str}_{current_hour:02d}30"
        if self._last_metar_trigger_id != target_metar_30_id:
          self._execute_metar_transmission(now_utc, current_hour, 30)
          self._last_metar_trigger_id = target_metar_30_id

      time.sleep(10)

  def _execute_hourly_observation(
      self, now_utc: datetime, target_hour: int
  ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    is_main_synop = (target_hour % 3) == 0
    cycle_label = "SINOPTIK" if is_main_synop else "BIASA"
    logger.info(
        f"[TRIGGER ME-48] Memproses laporan {target_hour:02d}:00 UTC"
        f" [{cycle_label}]..."
    )

    try:
      headers = self._get_active_headers()
      payload, obs = self._build_payload(target_hour, target_min=0)
      target_ts = payload["data_timestamp"]

      api_payload = {
          k: v
          for k, v in payload.items()
          if k
          not in (
              "created_at",
              "synced_to_bmkg",
              "encoded_synop",
              "encoded_metar",
          )
      }

      # 1. Transmisi ke BMKGSoft
      synced_flag = 0
      try:
        is_success, status_code, resp_text = submit_observation_entry(
            api_payload, target_ts, target_hour, headers
        )
        if is_success:
          synced_flag = 1
          logger.info(
              f"✅ ME-48 terkirim ke BMKGSoft (HTTP {status_code}):"
              f" TT={obs['tt_c']}°C, QFF={obs['qff_mb']} hPa"
          )
        else:
          logger.warning(
              f"⚠️ BMKGSoft menolak ME-48 (HTTP {status_code}): {resp_text}"
          )
      except Exception as api_err:
        logger.error(f"Error HTTP submit_observation_entry: {api_err}")

      # 2. Siarkan GTS SYNOP jika jam sinoptik
      if is_main_synop and payload.get("encoded_synop"):
        try:
          gts_ok, gts_msg = broadcast_to_gts(payload["encoded_synop"], headers)
          if gts_ok:
            logger.info(
                f"✅ GTS SYNOP {target_hour:02d}Z tersiar: {payload['encoded_synop']}"
            )
          else:
            logger.warning(f"⚠️ GTS SYNOP gagal tersiar: {gts_msg}")
        except Exception as gts_err:
          logger.error(f"Error broadcast GTS SYNOP: {gts_err}")

      # 3. Simpan ke SQLite lokal
      save_local_observation(
          record=payload,
          encoded_synop=payload.get("encoded_synop") or "",
          encoded_metar=payload.get("encoded_metar") or "",
          synced=synced_flag,
          db_path=self.db_path,
      )
      logger.info(f"💾 Record ME-48 berhasil disimpan ke SQLite ({target_ts}).")

      # Perbarui string status tampilan
      self.last_me48_sent = (
          f"[{target_hour:02d}:00Z] "
          + (
              payload.get("encoded_synop")
              or f"TT {obs['tt_c']}°C / QFF {obs['qff_mb']} hPa"
          )
      )
      return payload, obs

    except Exception as e:
      logger.error(
          f"Gagal memproses ME-48 jam {target_hour:02d}:00 UTC: {e}",
          exc_info=True,
      )
      return None, None

  def _execute_metar_transmission(
      self,
      now_utc: datetime,
      target_hour: int,
      target_min: int,
      prebuilt_payload: Optional[Dict[str, Any]] = None,
  ):
    time_str = f"{target_hour:02d}{target_min:02d}Z"
    target_iso = (
        f"{now_utc.strftime('%Y-%m-%d')}T{target_hour:02d}:{target_min:02d}:00Z"
    )
    logger.info(f"[TRIGGER METAR] Merakit sandi METAR untuk {time_str}...")

    try:
      headers = self._get_active_headers()

      if prebuilt_payload:
        payload = prebuilt_payload
      else:
        payload, _ = self._build_payload(target_hour, target_min)

      metar_code = payload.get("encoded_metar", "")

      # Format Buletin WMO GTS (Standar SAID40)
      ddhhmm = f"{now_utc.strftime('%d')}{target_hour:02d}{target_min:02d}"
      wmo_bulletin = f"SAID40 WAGB {ddhhmm}\n{metar_code}"

      # 1. Siarkan buletin ke GTS
      sent_status = 0
      try:
        gts_ok, gts_msg = broadcast_to_gts(wmo_bulletin, headers)
        if gts_ok:
          sent_status = 1
          logger.info(f"✅ METAR {time_str} terkirim ke GTS: {metar_code}")
        else:
          logger.warning(f"⚠️ GTS METAR gagal terkirim: {gts_msg}")
      except Exception as gts_err:
        logger.error(f"Error broadcast GTS METAR: {gts_err}")

      # 2. Catat riwayat transmisi ke SQLite tabel metar_logs
      log_metar_bulletin(
          bulletin_ts=target_iso,
          metar_code=metar_code,
          wmo_bulletin=wmo_bulletin,
          sent_status=sent_status,
          station_icao="WAGB",
          db_path=self.db_path,
      )
      logger.info(f"💾 Riwayat METAR {time_str} tersimpan di tabel metar_logs.")

      # Perbarui string status tampilan
      self.last_metar_sent = f"[{time_str}] {metar_code}"

    except Exception as e:
      logger.error(f"Gagal memproses METAR {time_str}: {e}", exc_info=True)