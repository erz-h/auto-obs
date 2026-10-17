"""db.py

Direct local SQLite persistence for ME48 observations.
Schema strictly mirrors BMKGSoft manual_entry + server response + encoded METAR.
"""

import sqlite3
import pandas as pd

DB_PATH = "station_me48.db"


def init_db():
  with sqlite3.connect(DB_PATH) as conn:
    cursor = conn.cursor()
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS me48_observations (
                -- Observation Metadata
                data_timestamp TEXT PRIMARY KEY,
                bmkgsoft_id TEXT,
                observer_id INTEGER,
                
                -- Surface Wind & Visibility
                wind_dir_deg_dd REAL,
                wind_indicator_iw INTEGER,
                wind_speed_ff REAL,
                visibility_vv REAL,
                
                -- Present & Past Weather
                present_weather_ww INTEGER,
                past_weather_w1 INTEGER,
                past_weather_w2 INTEGER,
                weather_indicator_ix INTEGER,
                
                -- Temperature & Psychrometrics (From Server Response)
                temp_drybulb_c_tttttt REAL,
                temp_wetbulb_c REAL,
                temp_dewpoint_c_tdtdtd REAL,
                relative_humidity_pc REAL,
                temp_max_c_txtxtx REAL,
                temp_min_c_tntntn REAL,
                
                -- Pressure (From manual_entry & Server Response)
                pressure_reading_mb REAL,
                pressure_temp_c REAL,
                pressure_qff_mb_derived REAL,
                pressure_qfe_mb_derived REAL,
                pressure_3h_diff_mb_ppp REAL,
                
                -- Precipitation
                rainfall_last_mm REAL,
                rainfall_indicator_ir INTEGER,
                
                -- Overall Cloud Cover
                cloud_cover_oktas_m TEXT,
                cloud_vertical_vis REAL,
                
                -- Low Clouds
                cloud_low_type_cl TEXT,
                cloud_low_cover_oktas TEXT,
                cloud_low_type_1 TEXT,
                cloud_low_type_2 TEXT,
                cloud_low_type_3 TEXT,
                cloud_low_cover_1 TEXT,
                cloud_low_cover_2 TEXT,
                cloud_low_cover_3 TEXT,
                cloud_low_base_1 REAL,
                cloud_low_base_2 REAL,
                cloud_low_base_3 REAL,
                cloud_low_peak_1 REAL,
                cloud_low_peak_2 REAL,
                cloud_low_dir_1 INTEGER,
                cloud_low_dir_2 INTEGER,
                cloud_low_dir_3 INTEGER,
                cloud_elevation_angle_ec_1 REAL,
                cloud_elevation_angle_ec_2 REAL,
                cloud_low_dir_true_da_1 TEXT,
                cloud_low_dir_true_da_2 TEXT,
                
                -- Medium Clouds
                cloud_med_type_cm TEXT,
                cloud_med_cover_oktas TEXT,
                cloud_med_type_1 TEXT,
                cloud_med_type_2 TEXT,
                cloud_med_cover_1 TEXT,
                cloud_med_cover_2 TEXT,
                cloud_med_base_1 REAL,
                cloud_med_base_2 REAL,
                cloud_med_dir_1 INTEGER,
                cloud_med_dir_2 INTEGER,
                
                -- High Clouds
                cloud_high_type_ch TEXT,
                cloud_high_cover_oktas TEXT,
                cloud_high_type_1 TEXT,
                cloud_high_type_2 TEXT,
                cloud_high_cover_1 TEXT,
                cloud_high_cover_2 TEXT,
                cloud_high_base_1 REAL,
                cloud_high_base_2 REAL,
                cloud_high_dir_1 INTEGER,
                cloud_high_dir_2 INTEGER,
                
                -- Radiation, Evaporation & Soil
                solar_rad_24h_jcm2_f24 REAL,
                sunshine_h_sss REAL,
                evaporation_24hours_mm_eee REAL,
                evaporation_eq_indicator_ie TEXT,
                land_cond TEXT,
                land_note TEXT,
                
                -- Encoded Bulletins & Sync State
                encoded_synop TEXT,
                encoded_metar TEXT,
                synced_to_bmkg INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Auto-add columns to existing databases if they are missing
    new_cols = [
        ("temp_dewpoint_c_tdtdtd", "REAL"),
        ("relative_humidity_pc", "REAL"),
        ("pressure_3h_diff_mb_ppp", "REAL"),
        ("weather_indicator_ix", "INTEGER"),
        ("encoded_metar", "TEXT"),
    ]
    for col_name, col_type in new_cols:
      try:
        cursor.execute(
            f"ALTER TABLE me48_observations ADD COLUMN {col_name} {col_type}"
        )
      except sqlite3.OperationalError:
        pass

    conn.commit()


def save_local_observation(
    record: dict,
    encoded_synop: str = "",
    encoded_metar: str = "",
    synced: int = 0,
):
  """Saves observation by extracting directly from the combined server response or fallback payload."""
  init_db()

  data = (
      record.get("data_timestamp") or record.get("timestamp"),
      record.get("bmkgsoft_id"),
      record.get("observer_id"),
      record.get("wind_dir_deg_dd") or record.get("wind_direction"),
      record.get("wind_indicator_iw", 4),
      record.get("wind_speed_ff") or record.get("wind_speed"),
      record.get("visibility_vv") or record.get("visibility"),
      record.get("present_weather_ww") or record.get("present_weather"),
      record.get("past_weather_w1") or record.get("past_weather_1"),
      record.get("past_weather_w2") or record.get("past_weather_2"),
      record.get("weather_indicator_ix", 1),
      record.get("temp_drybulb_c_tttttt") or record.get("temp_dry"),
      record.get("temp_wetbulb_c") or record.get("temp_wet"),
      record.get("temp_dewpoint_c_tdtdtd")
      or record.get("temp_dewpoint_c"),  # from server preview
      record.get("relative_humidity_pc")
      or record.get("humidity_rel_percent"),  # from server preview
      record.get("temp_max_c_txtxtx"),
      record.get("temp_min_c_tntntn"),
      record.get("pressure_reading_mb"),
      record.get("pressure_temp_c"),
      record.get("pressure_qff_mb_derived"),
      record.get("pressure_qfe_mb_derived"),
      record.get("pressure_3h_diff_mb_ppp"),  # from server preview
      record.get("rainfall_last_mm"),
      record.get("rainfall_indicator_ir"),
      record.get("cloud_cover_oktas_m"),
      record.get("cloud_vertical_vis"),
      record.get("cloud_low_type_cl"),
      record.get("cloud_low_cover_oktas"),
      record.get("cloud_low_type_1"),
      record.get("cloud_low_type_2"),
      record.get("cloud_low_type_3"),
      record.get("cloud_low_cover_1"),
      record.get("cloud_low_cover_2"),
      record.get("cloud_low_cover_3"),
      record.get("cloud_low_base_1"),
      record.get("cloud_low_base_2"),
      record.get("cloud_low_base_3"),
      record.get("cloud_low_peak_1"),
      record.get("cloud_low_peak_2"),
      record.get("cloud_low_dir_1"),
      record.get("cloud_low_dir_2"),
      record.get("cloud_low_dir_3"),
      record.get("cloud_elevation_angle_ec_1"),
      record.get("cloud_elevation_angle_ec_2"),
      record.get("cloud_low_dir_true_da_1"),
      record.get("cloud_low_dir_true_da_2"),
      record.get("cloud_med_type_cm"),
      record.get("cloud_med_cover_oktas"),
      record.get("cloud_med_type_1"),
      record.get("cloud_med_type_2"),
      record.get("cloud_med_cover_1"),
      record.get("cloud_med_cover_2"),
      record.get("cloud_med_base_1"),
      record.get("cloud_med_base_2"),
      record.get("cloud_med_dir_1"),
      record.get("cloud_med_dir_2"),
      record.get("cloud_high_type_ch"),
      record.get("cloud_high_cover_oktas"),
      record.get("cloud_high_type_1"),
      record.get("cloud_high_type_2"),
      record.get("cloud_high_cover_1"),
      record.get("cloud_high_cover_2"),
      record.get("cloud_high_base_1"),
      record.get("cloud_high_base_2"),
      record.get("cloud_high_dir_1"),
      record.get("cloud_high_dir_2"),
      record.get("solar_rad_24h_jcm2_f24"),
      record.get("sunshine_h_sss"),
      record.get("evaporation_24hours_mm_eee"),
      record.get("evaporation_eq_indicator_ie"),
      record.get("land_cond"),
      record.get("land_note"),
      record.get("encoded_synop") or encoded_synop,
      record.get("encoded_metar") or encoded_metar,
      synced,
  )

  placeholders = ", ".join(["?"] * len(data))

  with sqlite3.connect(DB_PATH) as conn:
    conn.execute(
        f"""
            INSERT OR REPLACE INTO me48_observations (
                data_timestamp, bmkgsoft_id, observer_id,
                wind_dir_deg_dd, wind_indicator_iw, wind_speed_ff, visibility_vv,
                present_weather_ww, past_weather_w1, past_weather_w2, weather_indicator_ix,
                temp_drybulb_c_tttttt, temp_wetbulb_c, temp_dewpoint_c_tdtdtd, relative_humidity_pc,
                temp_max_c_txtxtx, temp_min_c_tntntn,
                pressure_reading_mb, pressure_temp_c, pressure_qff_mb_derived, pressure_qfe_mb_derived, pressure_3h_diff_mb_ppp,
                rainfall_last_mm, rainfall_indicator_ir,
                cloud_cover_oktas_m, cloud_vertical_vis,
                cloud_low_type_cl, cloud_low_cover_oktas,
                cloud_low_type_1, cloud_low_type_2, cloud_low_type_3,
                cloud_low_cover_1, cloud_low_cover_2, cloud_low_cover_3,
                cloud_low_base_1, cloud_low_base_2, cloud_low_base_3,
                cloud_low_peak_1, cloud_low_peak_2,
                cloud_low_dir_1, cloud_low_dir_2, cloud_low_dir_3,
                cloud_elevation_angle_ec_1, cloud_elevation_angle_ec_2,
                cloud_low_dir_true_da_1, cloud_low_dir_true_da_2,
                cloud_med_type_cm, cloud_med_cover_oktas,
                cloud_med_type_1, cloud_med_type_2,
                cloud_med_cover_1, cloud_med_cover_2,
                cloud_med_base_1, cloud_med_base_2,
                cloud_med_dir_1, cloud_med_dir_2,
                cloud_high_type_ch, cloud_high_cover_oktas,
                cloud_high_type_1, cloud_high_type_2,
                cloud_high_cover_1, cloud_high_cover_2,
                cloud_high_base_1, cloud_high_base_2,
                cloud_high_dir_1, cloud_high_dir_2,
                solar_rad_24h_jcm2_f24, sunshine_h_sss, evaporation_24hours_mm_eee, evaporation_eq_indicator_ie,
                land_cond, land_note,
                encoded_synop, encoded_metar, synced_to_bmkg
            ) VALUES ({placeholders})
        """,
        data,
    )
    conn.commit()


def get_historical_records(
    start_date: str = None, end_date: str = None
) -> pd.DataFrame:
  """Queries all historical ME-48 observations with all 75 parameters."""
  init_db()
  with sqlite3.connect(DB_PATH) as conn:
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
    return pd.read_sql_query(query, conn, params=params)


if __name__ == "__main__":
  init_db()
  print("Database initialized successfully.")