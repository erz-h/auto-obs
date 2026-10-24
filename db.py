"""
db.py
Local SQLite persistence for BMKG ME-48 observations, Pan Evaporation, and METAR logs.
Features WAL mode for thread safety, declarative schema mapping, atomic transactions,
and indexing for high-frequency queries.
"""

from contextlib import contextmanager
import sqlite3
from typing import Any, Dict, Generator, List, Optional
import pandas as pd

DB_PATH = "station_me48.db"

# ==============================================================================
# SCHEMA DEFINITIONS
# ==============================================================================

ME48_COLUMNS: Dict[str, str] = {
    # Observation Metadata
    "data_timestamp": "TEXT PRIMARY KEY",
    "bmkgsoft_id": "TEXT",
    "observer_id": "INTEGER",
    # Surface Wind & Visibility
    "wind_dir_deg_dd": "REAL",
    "wind_indicator_iw": "INTEGER DEFAULT 4",
    "wind_speed_ff": "REAL",
    "visibility_vv": "REAL",
    # Present & Past Weather
    "present_weather_ww": "INTEGER",
    "past_weather_w1": "INTEGER",
    "past_weather_w2": "INTEGER",
    "weather_indicator_ix": "INTEGER DEFAULT 1",
    # Temperature & Psychrometrics
    "temp_drybulb_c_tttttt": "REAL",
    "temp_wetbulb_c": "REAL",
    "temp_dewpoint_c_tdtdtd": "REAL",
    "relative_humidity_pc": "REAL",
    "temp_max_c_txtxtx": "REAL",
    "temp_min_c_tntntn": "REAL",
    # Barometric Pressure
    "pressure_reading_mb": "REAL",
    "pressure_temp_c": "REAL",
    "pressure_qff_mb_derived": "REAL",
    "pressure_qfe_mb_derived": "REAL",
    "pressure_3h_diff_mb_ppp": "REAL",
    # Precipitation
    "rainfall_last_mm": "REAL",
    "rainfall_indicator_ir": "INTEGER",
    # Overall Cloud Cover
    "cloud_cover_oktas_m": "TEXT",
    "cloud_vertical_vis": "REAL",
    # Low Clouds (CL)
    "cloud_low_type_cl": "TEXT",
    "cloud_low_cover_oktas": "TEXT",
    "cloud_low_type_1": "TEXT",
    "cloud_low_type_2": "TEXT",
    "cloud_low_type_3": "TEXT",
    "cloud_low_cover_1": "TEXT",
    "cloud_low_cover_2": "TEXT",
    "cloud_low_cover_3": "TEXT",
    "cloud_low_base_1": "REAL",
    "cloud_low_base_2": "REAL",
    "cloud_low_base_3": "REAL",
    "cloud_low_peak_1": "REAL",
    "cloud_low_peak_2": "REAL",
    "cloud_low_dir_1": "INTEGER",
    "cloud_low_dir_2": "INTEGER",
    "cloud_low_dir_3": "INTEGER",
    "cloud_elevation_angle_ec_1": "REAL",
    "cloud_elevation_angle_ec_2": "REAL",
    "cloud_low_dir_true_da_1": "TEXT",
    "cloud_low_dir_true_da_2": "TEXT",
    # Medium Clouds (CM)
    "cloud_med_type_cm": "TEXT",
    "cloud_med_cover_oktas": "TEXT",
    "cloud_med_type_1": "TEXT",
    "cloud_med_type_2": "TEXT",
    "cloud_med_cover_1": "TEXT",
    "cloud_med_cover_2": "TEXT",
    "cloud_med_base_1": "REAL",
    "cloud_med_base_2": "REAL",
    "cloud_med_dir_1": "INTEGER",
    "cloud_med_dir_2": "INTEGER",
    # High Clouds (CH)
    "cloud_high_type_ch": "TEXT",
    "cloud_high_cover_oktas": "TEXT",
    "cloud_high_type_1": "TEXT",
    "cloud_high_type_2": "TEXT",
    "cloud_high_cover_1": "TEXT",
    "cloud_high_cover_2": "TEXT",
    "cloud_high_base_1": "REAL",
    "cloud_high_base_2": "REAL",
    "cloud_high_dir_1": "INTEGER",
    "cloud_high_dir_2": "INTEGER",
    # Radiation, Evaporation & Soil
    "solar_rad_24h_jcm2_f24": "REAL",
    "sunshine_h_sss": "REAL",
    "evaporation_24hours_mm_eee": "REAL",
    "evaporation_eq_indicator_ie": "TEXT",
    "land_cond": "TEXT",
    "land_note": "TEXT",
    # Encoded Bulletins & Sync State
    "encoded_synop": "TEXT",
    "encoded_metar": "TEXT",
    "synced_to_bmkg": "INTEGER DEFAULT 0",
    "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
}

FIELD_ALIASES: Dict[str, List[str]] = {
    "data_timestamp": ["timestamp"],
    "wind_dir_deg_dd": ["wind_direction"],
    "wind_speed_ff": ["wind_speed"],
    "visibility_vv": ["visibility"],
    "present_weather_ww": ["present_weather"],
    "past_weather_w1": ["past_weather_1"],
    "past_weather_w2": ["past_weather_2"],
    "temp_drybulb_c_tttttt": ["temp_dry"],
    "temp_wetbulb_c": ["temp_wet"],
    "temp_dewpoint_c_tdtdtd": ["temp_dewpoint_c"],
    "relative_humidity_pc": ["humidity_rel_percent"],
}

DEFAULT_VALUES: Dict[str, Any] = {
    "wind_indicator_iw": 4,
    "weather_indicator_ix": 1,
    "synced_to_bmkg": 0,
}

_DB_INITIALIZED = False


# ==============================================================================
# DATABASE CONNECTION & INITIALIZATION
# ==============================================================================

@contextmanager
def get_db_connection(
    db_path: str = DB_PATH,
) -> Generator[sqlite3.Connection, None, None]:
  """Context manager for thread-safe SQLite operations with WAL mode and extended timeout."""
  conn = sqlite3.connect(db_path, timeout=30.0)
  conn.execute("PRAGMA journal_mode=WAL;")
  conn.execute("PRAGMA synchronous=NORMAL;")
  try:
    yield conn
  finally:
    conn.close()


def init_db(db_path: str = DB_PATH, force: bool = False) -> None:
  """Initializes database tables, migrations, and performance indexes."""
  global _DB_INITIALIZED
  if _DB_INITIALIZED and not force:
    return

  with get_db_connection(db_path) as conn:
    with conn:
      cursor = conn.cursor()

      # 1. Main Observations Table (ME-48)
      columns_sql = ",\n    ".join(
          f"{col} {dtype}" for col, dtype in ME48_COLUMNS.items()
      )
      cursor.execute(
          f"CREATE TABLE IF NOT EXISTS me48_observations (\n    {columns_sql}\n)"
      )

      # 2. Dynamic Migration
      existing_cols = {
          row[1]
          for row in cursor.execute(
              "PRAGMA table_info(me48_observations)"
          ).fetchall()
      }
      for col, dtype in ME48_COLUMNS.items():
        if col not in existing_cols and "PRIMARY KEY" not in dtype:
          cursor.execute(
              f"ALTER TABLE me48_observations ADD COLUMN {col} {dtype}"
          )

      # 3. Pan Evaporation Table
      cursor.execute("""
                CREATE TABLE IF NOT EXISTS pan_evaporation (
                    obs_date TEXT PRIMARY KEY,
                    scale_1 REAL,
                    scale_2 REAL DEFAULT 20.0,
                    diff_h REAL,
                    rainfall_r REAL DEFAULT 0.0,
                    evaporation_ev REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

      # 4. METAR Dissemination Logs (tracks :30, :00, and SPECI broadcasts)
      cursor.execute("""
                CREATE TABLE IF NOT EXISTS metar_logs (
                    bulletin_timestamp TEXT PRIMARY KEY,
                    station_icao TEXT DEFAULT 'WAGB',
                    metar_code TEXT,
                    wmo_bulletin TEXT,
                    sent_to_gts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

      # 5. Performance Indexes
      cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_me48_timestamp 
                ON me48_observations (data_timestamp DESC);
            """)
      cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_metar_timestamp 
                ON metar_logs (bulletin_timestamp DESC);
            """)

  _DB_INITIALIZED = True


def init_evaporation_table(db_path: str = DB_PATH) -> None:
  """Backwards-compatible alias."""
  init_db(db_path)


# ==============================================================================
# OBSERVATION PERSISTENCE (ME-48)
# ==============================================================================

def save_local_observation(
    record: Dict[str, Any],
    encoded_synop: str = "",
    encoded_metar: str = "",
    synced: int = 0,
    db_path: str = DB_PATH,
) -> None:
  """Normalizes and saves an observation record with atomic commit/rollback."""
  init_db(db_path)

  target_cols = [c for c in ME48_COLUMNS if c != "created_at"]
  payload: Dict[str, Any] = {}

  for col in target_cols:
    val = record.get(col)
    if val is None:
      for alias in FIELD_ALIASES.get(col, []):
        val = record.get(alias)
        if val is not None:
          break
    if val is None:
      val = DEFAULT_VALUES.get(col, None)
    payload[col] = val

  payload["encoded_synop"] = record.get("encoded_synop") or encoded_synop
  payload["encoded_metar"] = record.get("encoded_metar") or encoded_metar
  payload["synced_to_bmkg"] = (
      synced if synced is not None else record.get("synced_to_bmkg", 0)
  )

  if not payload.get("data_timestamp"):
    raise ValueError(
        "Cannot save observation: 'data_timestamp' is missing or None."
    )

  col_names = ", ".join(target_cols)
  named_placeholders = ", ".join(f":{c}" for c in target_cols)
  query = f"INSERT OR REPLACE INTO me48_observations ({col_names}) VALUES ({named_placeholders})"

  with get_db_connection(db_path) as conn:
    with conn:
      conn.execute(query, payload)


def get_historical_records(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
  """Queries historical ME-48 observations with optional date range filter."""
  init_db(db_path)

  query = "SELECT * FROM me48_observations"
  conditions = []
  params = []

  if start_date:
    conditions.append("date(data_timestamp) >= date(?)")
    params.append(start_date)
  if end_date:
    conditions.append("date(data_timestamp) <= date(?)")
    params.append(end_date)

  if conditions:
    query += " WHERE " + " AND ".join(conditions)

  query += " ORDER BY data_timestamp DESC"

  with get_db_connection(db_path) as conn:
    return pd.read_sql_query(query, conn, params=params)


# ==============================================================================
# HELPER OPERATIONS: METAR LOGS & EVAPORATION
# ==============================================================================

def log_metar_bulletin(
    bulletin_ts: str,
    metar_code: str,
    wmo_bulletin: str,
    sent_status: int = 1,
    station_icao: str = "WAGB",
    db_path: str = DB_PATH,
) -> None:
  """Stores transmitted METAR bulletins (both :00 and :30) for auditing."""
  init_db(db_path)
  query = """
        INSERT OR REPLACE INTO metar_logs (
            bulletin_timestamp, station_icao, metar_code, wmo_bulletin, sent_to_gts
        ) VALUES (?, ?, ?, ?, ?)
    """
  with get_db_connection(db_path) as conn:
    with conn:
      conn.execute(
          query,
          (bulletin_ts, station_icao, metar_code, wmo_bulletin, sent_status),
      )


def get_metar_records(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: str = DB_PATH,
) -> pd.DataFrame:
  """Queries historical METAR dissemination logs (:00, :30, and SPECI)."""
  init_db(db_path)

  query = """
        SELECT 
            bulletin_timestamp,
            station_icao,
            metar_code,
            sent_to_gts,
            wmo_bulletin,
            created_at
        FROM metar_logs
    """
  conditions = []
  params = []

  if start_date:
    conditions.append("date(bulletin_timestamp) >= date(?)")
    params.append(start_date)
  if end_date:
    conditions.append("date(bulletin_timestamp) <= date(?)")
    params.append(end_date)

  if conditions:
    query += " WHERE " + " AND ".join(conditions)

  query += " ORDER BY bulletin_timestamp DESC"

  if limit and int(limit) > 0:
    query += f" LIMIT {int(limit)}"

  with get_db_connection(db_path) as conn:
    return pd.read_sql_query(query, conn, params=params)


def save_pan_evaporation_record(
    obs_date: str,
    scale_1: Optional[float],
    scale_2: float,
    diff_h: Optional[float],
    rainfall_r: float,
    evaporation_ev: Optional[float],
    db_path: str = DB_PATH,
) -> None:
  """Saves or updates daily pan evaporation calculation results."""
  init_db(db_path)
  query = """
        INSERT OR REPLACE INTO pan_evaporation (
            obs_date, scale_1, scale_2, diff_h, rainfall_r, evaporation_ev
        ) VALUES (?, ?, ?, ?, ?, ?)
    """
  with get_db_connection(db_path) as conn:
    with conn:
      conn.execute(
          query,
          (obs_date, scale_1, scale_2, diff_h, rainfall_r, evaporation_ev),
      )