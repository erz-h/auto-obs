import sqlite3
import numpy as np
import pandas as pd


def get_daily_prevailing_wind_active_only(daily_wind_df):
  """Menghitung arah angin terbanyak harian dari observasi aktif (kecepatan > 0).

  Jika sepanjang hari kecepatan = 0 (Calm), menghasilkan 'C'.
  """
  if daily_wind_df.empty:
    return "C"

  active_wind = daily_wind_df[
      (daily_wind_df["wind_speed"] > 0) & (daily_wind_df["wind_dir"].notna())
  ].copy()

  if active_wind.empty:
    return "C"

  sectors = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

  def deg_to_sector(deg):
    idx = int((deg / 45.0) + 0.5) % 8
    return sectors[idx]

  active_wind["sector"] = active_wind["wind_dir"].apply(deg_to_sector)
  counts = active_wind["sector"].value_counts()
  if counts.empty:
    return "C"

  max_freq = counts.max()
  top_dirs = counts[counts == max_freq].index.tolist()
  return ";".join(top_dirs)


def generate_fklim71(
    year: int, month: int, db_path: str = "station_me48.db"
) -> pd.DataFrame:
  """Menghasilkan satu tabel rekapitulasi utuh Fklim 71 (raw tabular) dari tanggal 1 sampai akhir bulan."""
  month_pattern = f"{year:04d}-{month:02d}%"

  with sqlite3.connect(db_path) as conn:
    query = """
            SELECT 
                datetime(data_timestamp, '+7 hours') as local_time,
                temp_drybulb_c_tttttt as temp,
                temp_max_c_txtxtx as temp_max,
                temp_min_c_tntntn as temp_min,
                rainfall_last_mm as rain,
                pressure_qfe_mb_derived as qfe,
                relative_humidity_pc as rh,
                wind_speed_ff as wind_speed,
                wind_dir_deg_dd as wind_dir
            FROM me48_observations
            WHERE data_timestamp LIKE ?
        """
    df = pd.read_sql_query(query, conn, params=[month_pattern])

  if df.empty:
    return pd.DataFrame()

  df["local_time"] = pd.to_datetime(df["local_time"])
  df["day"] = df["local_time"].dt.day
  df["hour"] = df["local_time"].dt.hour

  num_cols = [
      "temp",
      "temp_max",
      "temp_min",
      "rain",
      "qfe",
      "rh",
      "wind_speed",
      "wind_dir",
  ]
  for col in num_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

  days_in_month = pd.Period(f"{year}-{month}").days_in_month
  daily_idx = range(1, days_in_month + 1)

  # Inisialisasi DataFrame tunggal dengan indeks tanggal
  fklim = pd.DataFrame(index=daily_idx)
  fklim.index.name = "TGL"

  # 1. Unsur Suhu Udara (°C)
  t07 = df[df["hour"] == 7].groupby("day")["temp"].mean().reindex(daily_idx)
  t13 = df[df["hour"] == 13].groupby("day")["temp"].mean().reindex(daily_idx)
  t18 = df[df["hour"] == 18].groupby("day")["temp"].mean().reindex(daily_idx)

  fklim["TEMP_07"] = t07.round(1)
  fklim["TEMP_13"] = t13.round(1)
  fklim["TEMP_18"] = t18.round(1)
  fklim["TEMP_RATA2"] = ((2 * t07 + t13 + t18) / 4).round(1)
  fklim["TEMP_MAX"] = (
      df.groupby("day")["temp_max"].max().reindex(daily_idx).round(1)
  )
  fklim["TEMP_MIN"] = (
      df.groupby("day")["temp_min"].min().reindex(daily_idx).round(1)
  )

  # 2. Curah Hujan (mm) ditakar jam 07.00
  fklim["CURAH_HUJAN_07"] = (
      df.groupby("day")["rain"].sum().reindex(daily_idx).round(1).fillna(0.0)
  )

  # Kolom pelengkap format cetak (Penyinaran & Cuaca Khusus)
  fklim["PENYINARAN_PERSEN"] = np.nan
  fklim["CUACA_KHUSUS"] = ""

  # 3. Tekanan Udara (mb/hPa)
  fklim["TEKANAN_UDARA_MB"] = (
      df.groupby("day")["qfe"].mean().reindex(daily_idx).round(1)
  )

  # 4. Kelembaban Relatif (%)
  rh07 = df[df["hour"] == 7].groupby("day")["rh"].mean().reindex(daily_idx)
  rh13 = df[df["hour"] == 13].groupby("day")["rh"].mean().reindex(daily_idx)
  rh18 = df[df["hour"] == 18].groupby("day")["rh"].mean().reindex(daily_idx)

  fklim["RH_07"] = rh07.round(0)
  fklim["RH_13"] = rh13.round(0)
  fklim["RH_18"] = rh18.round(0)
  fklim["RH_RATA2"] = ((2 * rh07 + rh13 + rh18) / 4).round(0)

  # 5. Kecepatan Angin Rata-rata (km/jam)
  fklim["ANGIN_KECEPATAN_RATA2_KMJ"] = (
      (df.groupby("day")["wind_speed"].mean() * 1.852)
      .reindex(daily_idx)
      .round(1)
  )

  # 6. Analisis Arah Terbanyak & Kecepatan Maksimum
  sectors = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

  def deg_to_dir(deg):
    if pd.isna(deg):
      return "C"
    return sectors[int((deg / 45.0) + 0.5) % 8]

  most_freq_dir = []
  max_speed_knots = []
  max_speed_dir = []

  for day in daily_idx:
    daily_wind = df[df["day"] == day].dropna(subset=["wind_speed"])

    if daily_wind.empty:
      most_freq_dir.append("C")
      max_speed_knots.append(0.0)
      max_speed_dir.append("C")
      continue

    # Arah terbanyak hanya dari observasi aktif (> 0 knot)
    most_freq_dir.append(get_daily_prevailing_wind_active_only(daily_wind))

    # Kecepatan terbesar dan arahnya
    max_idx = daily_wind["wind_speed"].idxmax()
    max_s = daily_wind.loc[max_idx, "wind_speed"] if pd.notna(max_idx) else 0.0

    if pd.isna(max_s) or max_s == 0:
      max_speed_knots.append(0.0)
      max_speed_dir.append("C")
    else:
      max_speed_knots.append(round(max_s, 1))
      max_speed_dir.append(deg_to_dir(daily_wind.loc[max_idx, "wind_dir"]))

  fklim["ANGIN_ARAH_TERBANYAK"] = most_freq_dir
  fklim["ANGIN_KECEPATAN_MAX_KTS"] = max_speed_knots
  fklim["ANGIN_ARAH_MAX"] = max_speed_dir

  return fklim

def generate_climat_from_fklim(
    df_or_csv, year: int, month: int, station_wmo: str = "96655"
) -> str:
  """Membuat teks sandi resmi WMO CLIMAT (FM 71) langsung dari tabel rekap Fklim 71."""
  if isinstance(df_or_csv, str):
    df = pd.read_csv(df_or_csv, index_col="TGL")
  else:
    df = df_or_csv.copy()

  cols = [
      "TEMP_RATA2",
      "TEMP_MAX",
      "TEMP_MIN",
      "CURAH_HUJAN_07",
      "TEKANAN_UDARA_MB",
      "RH_RATA2",
  ]
  for c in cols:
    if c in df.columns:
      df[c] = pd.to_numeric(df[c], errors="coerce")

  # 1. Header
  header = f"CLIMAT {month:02d}{year % 1000:03d} {station_wmo}"

  # 2. Seksi 1: Rata-rata Bulanan
  qfe_mean = df["TEKANAN_UDARA_MB"].mean()
  p0_code = (
      f"{int(round(qfe_mean * 10)) % 10000:04d}"
      if pd.notna(qfe_mean)
      else "////"
  )
  p_code = (
      f"{int(round((qfe_mean + 5.0) * 10)) % 10000:04d}"
      if pd.notna(qfe_mean)
      else "////"
  )

  t_mean = df["TEMP_RATA2"].mean()
  t_sn = "1" if t_mean < 0 else "0"
  t_code = (
      f"1{t_sn}{int(round(abs(t_mean) * 10)):03d}"
      if pd.notna(t_mean)
      else "1////"
  )

  tx_mean = df["TEMP_MAX"].mean()
  tx_sn = "1" if tx_mean < 0 else "0"
  tx_code = (
      f"2{tx_sn}{int(round(abs(tx_mean) * 10)):03d}"
      if pd.notna(tx_mean)
      else "2////"
  )

  tn_mean = df["TEMP_MIN"].mean()
  tn_sn = "1" if tn_mean < 0 else "0"
  tn_code = (
      f"3{tn_sn}{int(round(abs(tn_mean) * 10)):03d}"
      if pd.notna(tn_mean)
      else "3////"
  )

  # Tekanan uap air (e) dengan formula Tetens
  rh_mean = df["RH_RATA2"].mean()
  if pd.notna(t_mean) and pd.notna(rh_mean):
    es = 6.112 * (10 ** ((7.5 * t_mean) / (237.3 + t_mean)))
    e_val = es * (rh_mean / 100.0)
    e_code = f"4{int(round(e_val * 10)):04d}"
  else:
    e_code = "4////"

  total_rain = df["CURAH_HUJAN_07"].sum()
  rain_code = (
      f"6{int(round(total_rain)):04d}/" if pd.notna(total_rain) else "6/////"
  )

  sec_1 = (
      f"111 {p0_code} {p_code} {t_code} {tx_code} {tn_code} {e_code} {rain_code}"
  )

  # 3. Seksi 4: Ekstrem Bulanan & Hari Hujan
  max_tx = df["TEMP_MAX"].max()
  day_tx = int(df["TEMP_MAX"].idxmax())
  tx_abs_sn = "1" if max_tx < 0 else "0"
  tx_abs_code = (
      f"1{tx_abs_sn}{int(round(abs(max_tx) * 10)):03d} {day_tx:02d}"
      if pd.notna(max_tx)
      else "1///// //"
  )

  min_tn = df["TEMP_MIN"].min()
  day_tn = int(df["TEMP_MIN"].idxmin())
  tn_abs_sn = "1" if min_tn < 0 else "0"
  tn_abs_code = (
      f"2{tn_abs_sn}{int(round(abs(min_tn) * 10)):03d} {day_tn:02d}"
      if pd.notna(min_tn)
      else "2///// //"
  )

  max_rain = df["CURAH_HUJAN_07"].max()
  day_rain = int(df["CURAH_HUJAN_07"].idxmax())
  rx_code = (
      f"3{int(round(max_rain)):04d} {day_rain:02d}"
      if pd.notna(max_rain) and max_rain > 0
      else "30000 //"
  )

  rain_days_1mm = int((df["CURAH_HUJAN_07"] >= 1.0).sum())
  days_code = f"4{rain_days_1mm:02d}//"

  sec_4 = f"444 {tx_abs_code} {tn_abs_code} {rx_code} {days_code}"

  return f"{header}\n{sec_1}\n{sec_4}="