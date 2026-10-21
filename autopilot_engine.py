from datetime import datetime, timezone
import logging
import re
import sqlite3
import threading
import time
from typing import Any, Dict, Optional, Tuple
import pandas as pd

from data_model import (
    STATION_LAT,
    STATION_LON,
    fetch_hybrid_ensemble_forecast,
    get_current_synoptic_target,
    parse_ensemble_hourly_table,
)
from db import DB_PATH, init_db, save_local_observation

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("AutopilotEngine")

# Fallback default jika tabel me48_observations masih kosong
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
    "encoded_metar": "METAR WAGB 171200Z 00000KT 8000 FEW015 31/25 Q1009=",
}


def splice_metar(
    prev_metar: str,
    now_utc: datetime,
    target_hour: int,
    target_min: int,
    obs: Dict[str, Any],
) -> str:
    """Memperbarui waktu, suhu/Td, dan QNH dari sandi METAR sebelumnya.

    Grup visual (jarak pandang, cuaca, lapisan awan) dipertahankan utuh.
    """
    day_str = now_utc.strftime("%d")
    time_str = f"{target_hour:02d}{target_min:02d}Z"
    wind_str = "00000KT"

    # Suhu & Titik Embun Model
    t_rnd = int(round(obs["tt_c"]))
    td_rnd = int(round(obs["td_c"]))
    t_str = f"M{abs(t_rnd):02d}" if t_rnd < 0 else f"{t_rnd:02d}"
    td_str = f"M{abs(td_rnd):02d}" if td_rnd < 0 else f"{td_rnd:02d}"
    temp_dew_str = f"{t_str}/{td_str}"

    # QNH Barometrik
    qnh_str = f"Q{int(round(obs['qff_mb'])):04d}"

    # Ambil payload visual di antara grup angin dan grup suhu
    match = re.search(
        r"\b\d{5}(?:G\d{2})?KT\s+(.+?)\s+(?:M?\d{2}/M?\d{2})\b", prev_metar or ""
    )
    if match:
        visual_part = match.group(1).strip()
    else:
        visual_part = "8000 FEW015"

    return f"METAR WAGB {day_str}{time_str} {wind_str} {visual_part} {temp_dew_str} {qnh_str}="


def splice_synop(
    prev_synop: str,
    now_utc: datetime,
    target_hour: int,
    obs: Dict[str, Any],
    is_synoptic: bool,
) -> str:
    """Memperbarui grup YYGGiw, N0000 (calm), 1snTTT, 2snTdTdTd, 3P0P0P0P0, 4PPPP,

    dan 6RRRtR (60001 = 0.0mm) dari sandi SYNOP sebelumnya.
    """
    if not prev_synop or "96655" not in prev_synop:
        return ""

    tokens = prev_synop.strip().rstrip("=").split()
    if len(tokens) < 4:
        return prev_synop

    # 1. Update YYGGiw (iw = 4: knots anemometer)
    day_str = now_utc.strftime("%d")
    tokens[1] = f"{day_str}{target_hour:02d}4"

    # 2. Siapkan format sandi grup model
    t_val = obs["tt_c"]
    td_val = obs["td_c"]
    qfe_val = obs["qfe_mb"]
    qff_val = obs["qff_mb"]

    g_temp = f"1{1 if t_val < 0 else 0}{int(round(abs(t_val) * 10)):03d}"
    g_dew = f"2{1 if td_val < 0 else 0}{int(round(abs(td_val) * 10)):03d}"
    g_qfe = f"3{int(round(qfe_val * 10)) % 10000:04d}"
    g_qff = f"4{int(round(qff_val * 10)) % 10000:04d}"
    g_rain = "60001"  # 0.0 mm pada interval sinoptik

    new_tokens = []
    rain_handled = False

    for i, tok in enumerate(tokens):
        # Grup Angin Nddff (token ke-4 setelah 96655 dan iRixhVV) -> kunci ke calm: N0000
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

    # Sisipkan grup 60001 jika sebelumnya belum ada dan saat ini jam sinoptik
    if is_synoptic and not rain_handled:
        try:
            idx_4 = [i for i, t in enumerate(new_tokens) if t.startswith("4")][0]
            new_tokens.insert(idx_4 + 1, g_rain)
        except IndexError:
            new_tokens.append(g_rain)

    return " ".join(new_tokens) + "="


class BMKGAutopilot:
    """Autopilot engine terintegrasi station_me48.db.

    Menyuntikkan model ensemble ke data ME-48, METAR, dan SYNOP berbasis record
    sebelumnya.
    """

    def __init__(
        self, db_path: str = DB_PATH, api_client: Optional[Any] = None
    ):
        self.db_path = db_path
        self.api_client = api_client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_me48_sent: Optional[str] = None
        self.last_metar_sent: Optional[str] = None

        init_db()

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

    def _fetch_latest_from_sql(self) -> Dict[str, Any]:
        """Mengambil record pengamatan terakhir dari tabel me48_observations."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                query = (
                    "SELECT * FROM me48_observations ORDER BY data_timestamp DESC"
                    " LIMIT 1"
                )
                cursor.execute(query)
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

        # Model Termodinamika Hibrida
        raw_weather = fetch_hybrid_ensemble_forecast(STATION_LAT, STATION_LON)
        if not raw_weather:
            raise RuntimeError(
                "Gagal mengambil data cuaca numerik dari Open-Meteo."
            )

        df = parse_ensemble_hourly_table(raw_weather)
        obs = get_current_synoptic_target(df)

        is_synoptic_hour = (target_hour % 3) == 0 and target_min == 0
        rainfall_val = 0.0 if is_synoptic_hour else None

        now_utc = datetime.now(timezone.utc)
        target_timestamp = (
            f"{now_utc.strftime('%Y-%m-%d')}T{target_hour:02d}:{target_min:02d}:00Z"
        )

        # 1. Update Sandi METAR dari record sebelumnya
        prev_metar_str = latest_record.get("encoded_metar") or ""
        new_metar_str = splice_metar(
            prev_metar_str, now_utc, target_hour, target_min, obs
        )

        # 2. Update Sandi SYNOP dari record sebelumnya
        prev_synop_str = latest_record.get("encoded_synop") or ""
        new_synop_str = splice_synop(
            prev_synop_str, now_utc, target_hour, obs, is_synoptic_hour
        )

        payload = {
            **latest_record,
            "data_timestamp": target_timestamp,
            # Injeksi Nilai Fisik Model
            "temp_drybulb_c_tttttt": obs["tt_c"],
            "temp_wetbulb_c": obs["tw_c"],
            "temp_dewpoint_c_tdtdtd": obs["td_c"],
            "relative_humidity_pc": obs["rh_pc"],
            "pressure_qfe_mb_derived": obs["qfe_mb"],
            "pressure_qff_mb_derived": obs["qff_mb"],
            # Angin Calm
            "wind_dir_deg_dd": 0,
            "wind_speed_ff": 0,
            "wind_indicator_iw": 4,
            # Curah Hujan
            "rainfall_last_mm": rainfall_val,
            "rainfall_indicator_ir": 4,
            # Sandi Terekstrak Baru
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

            # 1. ME-48 & SYNOP: Trigger tepat di menit :00 (Window menit 0-1)
            target_me48_id = f"{date_str}_{current_hour:02d}"
            if minute in (0, 1) and self.last_me48_sent != target_me48_id:
                self._execute_hourly_observation(now_utc, current_hour)
                self.last_me48_sent = target_me48_id

            # 2. METAR: Trigger tepat di menit :00 dan :30 (Window menit 0-1 dan 30-31)
            target_metar_min = None
            if minute in (0, 1):
                target_metar_min = 0
            elif minute in (30, 31):
                target_metar_min = 30

            if target_metar_min is not None:
                target_metar_id = (
                    f"{date_str}_{current_hour:02d}{target_metar_min:02d}"
                )
                if self.last_metar_sent != target_metar_id:
                    self._execute_metar_transmission(
                        now_utc, current_hour, target_metar_min
                    )
                    self.last_metar_sent = target_metar_id

            time.sleep(10)

    def _execute_hourly_observation(self, now_utc: datetime, target_hour: int):
        is_main_synop = (target_hour % 3) == 0
        cycle_label = "SINOPTIK" if is_main_synop else "BIASA"

        logger.info(
            f"[TRIGGER ME-48] Memproses laporan {target_hour:02d}:00 UTC"
            f" [{cycle_label}]..."
        )

        try:
            payload, obs = self._build_payload(target_hour, target_min=0)
            rain_str = (
                f"{payload['rainfall_last_mm']} mm"
                if payload["rainfall_last_mm"] is not None
                else "null"
            )

            synced_flag = 0
            if self.api_client:
                self.api_client.save_me48(payload)
                synced_flag = 1
                logger.info(
                    f"-> ME-48 terkirim ke BMKGSoft: TT={obs['tt_c']}°C,"
                    f" QFF={obs['qff_mb']} hPa, Rain={rain_str}"
                )
            else:
                logger.info(
                    f"[MOCK SAVE] ME-48 @ {target_hour:02d}Z: TT={obs['tt_c']}°C,"
                    f" QFF={obs['qff_mb']} hPa, Rain={rain_str}"
                )

            # Transmisi GTS SYNOP hanya pada jam sinoptik
            if is_main_synop and payload.get("encoded_synop"):
                logger.info(
                    f"-> [GTS SYNOP] {target_hour:02d}:00 UTC ->"
                    f" {payload['encoded_synop']}"
                )
                if self.api_client:
                    self.api_client.send_synop_to_gts(payload["encoded_synop"])
                logger.info("-> Sandi SYNOP berhasil disiarkan.")

            # Simpan observasi terbaru ke SQLite lokal
            save_local_observation(
                record=payload,
                encoded_synop=payload.get("encoded_synop") or "",
                encoded_metar=payload.get("encoded_metar") or "",
                synced=synced_flag,
            )
            logger.info("-> Data berhasil disimpan ke database lokal station_me48.db.")

        except Exception as e:
            logger.error(
                f"Gagal memproses ME-48 jam {target_hour:02d}:00 UTC: {e}",
                exc_info=True,
            )

    def _execute_metar_transmission(
        self, now_utc: datetime, target_hour: int, target_min: int
    ):
        time_str = f"{target_hour:02d}{target_min:02d}Z"
        logger.info(f"[TRIGGER METAR] Merakit sandi METAR untuk {time_str}...")

        try:
            payload, _ = self._build_payload(target_hour, target_min)
            metar_code = payload.get("encoded_metar")

            logger.info(f"-> Sandi METAR Dihasilkan: {metar_code}")

            if self.api_client:
                self.api_client.send_metar_to_gts(metar_code)
            logger.info(f"-> METAR {time_str} berhasil dikirim ke GTS.")

        except Exception as e:
            logger.error(
                f"Gagal memproses METAR {time_str}: {e}", exc_info=True
            )