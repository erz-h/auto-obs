"""acs_reporter.py.

Aerodrome Climatological Summary (ACS) Generator for Aviation (WAGB / 96655).
Parses standard ICAO/BMKG 'encoded_metar' strings from SQLite and compiles:
  1. Table A: Visibility vs Cloud Ceiling Operational Distribution
  2. Table B: Bivariate Surface Wind Direction vs Speed (Wind Rose Matrix)
  3. Table C: Hourly/Diurnal Temperature, Dewpoint, and QNH Climatology
  4. Table D: Significant Weather Phenomena Frequency (TS, RA, FG, BR, HZ)
"""

from datetime import datetime
import re
import sqlite3
from typing import Any, Dict, List, Optional
import pandas as pd

DB_PATH = "station_me48.db"


class METARParser:
  """Robust regex parser strictly for ICAO Annex 3 standard METAR strings."""

  WIND_REGEX = re.compile(
      r"\b(00000KT|VRB\d{2}KT|\d{3}\d{2,3}(?:G\d{2,3})?KT)\b"
  )
  VIS_REGEX = re.compile(r"\b(\d{4}|CAVOK)\b")
  WX_REGEX = re.compile(
      r"\b(-|\+|VC)?(TS|SH|FZ|DZ|RA|SN|SG|IC|PL|GR|GS|BR|FG|FU|VA|DU|SA|HZ|SQ|PO|FC|SS|DS)+\b"
  )
  CLOUD_REGEX = re.compile(
      r"\b((?:FEW|SCT|BKN|OVC|VV)\d{3}(?:CB|TCU)?|NSC|SKC|NCD)\b"
  )
  TEMP_REGEX = re.compile(r"\b(M?\d{2})/(M?\d{2})\b")
  QNH_REGEX = re.compile(r"\bQ(\d{4})\b")

  @staticmethod
  def parse(metar_str: str) -> Optional[Dict[str, Any]]:
    if not metar_str or "METAR" not in metar_str:
      return None

    data = {
        "raw": metar_str,
        "day": None,
        "hour": None,
        "minute": None,
        "wind_dir": None,
        "wind_speed_kt": 0,
        "is_calm": False,
        "vis_meters": None,
        "weather": [],
        "ceiling_feet": None,
        "temp_c": None,
        "dew_c": None,
        "qnh_hpa": None,
    }

    tokens = metar_str.strip().rstrip("=").split()

    # 1. Parse Identitas Tanggal & Jam: WAGB DDHHMMZ
    for tok in tokens:
      m_time = re.match(r"^(\d{2})(\d{2})(\d{2})Z$", tok)
      if m_time:
        data["day"] = int(m_time.group(1))
        data["hour"] = int(m_time.group(2))
        data["minute"] = int(m_time.group(3))
        break

    # 2. Parse Angin
    m_wind = METARParser.WIND_REGEX.search(metar_str)
    if m_wind:
      w_str = m_wind.group(1)
      if w_str == "00000KT":
        data["is_calm"] = True
        data["wind_dir"] = "CALM"
        data["wind_speed_kt"] = 0
      elif w_str.startswith("VRB"):
        data["wind_dir"] = "VRB"
        data["wind_speed_kt"] = int(w_str[3:5])
      else:
        deg = int(w_str[0:3])
        spd = int(w_str[3:5])
        data["wind_speed_kt"] = spd
        # Konversi ke 8 Mata Angin Utama
        data["wind_dir"] = METARParser._deg_to_cardinal(deg)

    # 3. Parse Jarak Pandang (Visibility)
    if "CAVOK" in metar_str:
      data["vis_meters"] = 9999
      data["ceiling_feet"] = 9999  # Awan di atas 5000ft
    else:
      m_vis = METARParser.VIS_REGEX.search(metar_str)
      if m_vis:
        data["vis_meters"] = int(m_vis.group(1))

    # 4. Parse Significant Weather
    wx_matches = METARParser.WX_REGEX.findall(metar_str)
    for intensity, phenom in wx_matches:
      full_wx = f"{intensity}{phenom}"
      data["weather"].append(full_wx)

    # 5. Parse Awan & Hitung Ceiling (Dasar awan BKN / OVC pertama)
    clouds = METARParser.CLOUD_REGEX.findall(metar_str)
    ceilings = []
    for c in clouds:
      if c.startswith(("BKN", "OVC")):
        h_feet = int(c[3:6]) * 100
        ceilings.append(h_feet)
    if ceilings:
      data["ceiling_feet"] = min(ceilings)
    elif "CAVOK" not in metar_str and data["ceiling_feet"] is None:
      data["ceiling_feet"] = 9999  # Tidak ada awan operasional (No ceiling)

    # 6. Parse Suhu dan Titik Embun (TT/Td)
    m_temp = METARParser.TEMP_REGEX.search(metar_str)
    if m_temp:
      t_raw, td_raw = m_temp.group(1), m_temp.group(2)
      data["temp_c"] = (
          -int(t_raw[1:]) if t_raw.startswith("M") else int(t_raw)
      )
      data["dew_c"] = (
          -int(td_raw[1:]) if td_raw.startswith("M") else int(td_raw)
      )

    # 7. Parse Tekanan Altimeter (QNH)
    m_qnh = METARParser.QNH_REGEX.search(metar_str)
    if m_qnh:
      data["qnh_hpa"] = int(m_qnh.group(1))

    return data

  @staticmethod
  def _deg_to_cardinal(deg: int) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = round(deg / 45) % 8
    return dirs[ix]


class ACSGenerator:
  """Mengompilasi tabel-tabel Aerodrome Climatological Summary (ACS)."""

  def __init__(self, db_path: str = DB_PATH):
    self.db_path = db_path

  def fetch_monthly_metars(self, year: int, month: int) -> pd.DataFrame:
    """Mengambil dan mem-parsing seluruh encoded_metar dari station_me48.db."""
    month_str = f"{year:04d}-{month:02d}%"
    with sqlite3.connect(self.db_path) as conn:
      query = """
                SELECT data_timestamp, encoded_metar 
                FROM me48_observations 
                WHERE data_timestamp LIKE ? 
                  AND encoded_metar IS NOT NULL 
                  AND encoded_metar != ''
                ORDER BY data_timestamp ASC
            """
      raw_df = pd.read_sql_query(query, conn, params=[month_str])

    parsed_records = []
    for _, row in raw_df.iterrows():
      parsed = METARParser.parse(row["encoded_metar"])
      if parsed:
        parsed["timestamp"] = row["data_timestamp"]
        parsed_records.append(parsed)

    return pd.DataFrame(parsed_records)

  def table_wind_distribution(self, df: pd.DataFrame) -> pd.DataFrame:
    """Tabel B: Distribusi Arah vs Kecepatan Angin (Model B ICAO)."""
    if df.empty:
      return pd.DataFrame()

    def speed_bracket(spd, is_calm):
      if is_calm or spd == 0:
        return "Calm"
      if 1 <= spd <= 3:
        return "1 - 3 kt"
      if 4 <= spd <= 6:
        return "4 - 6 kt"
      if 7 <= spd <= 10:
        return "7 - 10 kt"
      if 11 <= spd <= 16:
        return "11 - 16 kt"
      return ">= 17 kt"

    df_wind = df.copy()
    df_wind["speed_bin"] = df_wind.apply(
        lambda r: speed_bracket(r["wind_speed_kt"], r["is_calm"]), axis=1
    )

    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "VRB", "CALM"]
    brackets = [
        "Calm",
        "1 - 3 kt",
        "4 - 6 kt",
        "7 - 10 kt",
        "11 - 16 kt",
        ">= 17 kt",
    ]

    ct = pd.crosstab(df_wind["wind_dir"], df_wind["speed_bin"]).reindex(
        index=directions, columns=brackets, fill_value=0
    )
    ct["Total"] = ct.sum(axis=1)

    # Persentase total observasi
    pct = (ct / len(df) * 100).round(2)
    return pct

  def table_vis_ceiling(self, df: pd.DataFrame) -> pd.DataFrame:
    """Tabel A: Matriks Operasional Minima (Jarak Pandang vs Ketinggian Ceiling)."""
    if df.empty:
      return pd.DataFrame()

    def vis_cat(v):
      if v is None:
        return "Unknown"
      if v < 800:
        return "< 800m"
      if v < 1500:
        return "800 - 1499m"
      if v < 5000:
        return "1500 - 4999m"
      if v < 8000:
        return "5000 - 7999m"
      return ">= 8000m"

    def ceil_cat(c):
      if c is None or c >= 9999:
        return "No Ceiling / >= 1500ft"
      if c < 200:
        return "< 200ft"
      if c < 500:
        return "200 - 499ft"
      if c < 1000:
        return "500 - 999ft"
      return "1000 - 1499ft"

    df_vc = df.copy()
    df_vc["vis_bin"] = df_vc["vis_meters"].apply(vis_cat)
    df_vc["ceil_bin"] = df_vc["ceiling_feet"].apply(ceil_cat)

    vis_order = [
        "< 800m",
        "800 - 1499m",
        "1500 - 4999m",
        "5000 - 7999m",
        ">= 8000m",
    ]
    ceil_order = [
        "< 200ft",
        "200 - 499ft",
        "500 - 999ft",
        "1000 - 1499ft",
        "No Ceiling / >= 1500ft",
    ]

    ct = pd.crosstab(df_vc["vis_bin"], df_vc["ceil_bin"]).reindex(
        index=vis_order, columns=ceil_order, fill_value=0
    )
    return ct

  def table_diurnal_stats(self, df: pd.DataFrame) -> pd.DataFrame:
    """Tabel C: Statistik Diurnal Suhu (°C), Titik Embun, dan QNH per Jam UTC."""
    if df.empty:
      return pd.DataFrame()

    hourly = (
        df.groupby("hour")
        .agg(
            Mean_TT=("temp_c", "mean"),
            Max_TT=("temp_c", "max"),
            Min_TT=("temp_c", "min"),
            Mean_Td=("dew_c", "mean"),
            Mean_QNH=("qnh_hpa", "mean"),
            Total_Obs=("hour", "count"),
        )
        .round(1)
    )
    return hourly

  def table_weather_phenomena(self, df: pd.DataFrame) -> pd.DataFrame:
    """Tabel D: Frekuensi Kemunculan Cuaca Signifikan (WMO / ICAO)."""
    if df.empty:
      return pd.DataFrame()

    counts = {
        "TS (Thunderstorm)": 0,
        "RA (Rain / Hujan)": 0,
        "FG (Fog / Kabut)": 0,
        "BR (Mist / Halimun)": 0,
        "HZ (Haze / Asap-Kabur)": 0,
        "VCTS (Vicinity TS)": 0,
    }

    for wx_list in df["weather"]:
      joined = " ".join(wx_list)
      if "TS" in joined and "VCTS" not in joined:
        counts["TS (Thunderstorm)"] += 1
      if "VCTS" in joined:
        counts["VCTS (Vicinity TS)"] += 1
      if "RA" in joined:
        counts["RA (Rain / Hujan)"] += 1
      if "FG" in joined:
        counts["FG (Fog / Kabut)"] += 1
      if "BR" in joined:
        counts["BR (Mist / Halimun)"] += 1
      if "HZ" in joined:
        counts["HZ (Haze / Asap-Kabur)"] += 1

    summary_df = pd.DataFrame(
        list(counts.items()), columns=["Fenomena", "Jumlah Observasi (Frekuensi)"]
    )
    summary_df["Persentase (%)"] = (
        summary_df["Jumlah Observasi (Frekuensi)"] / len(df) * 100
    ).round(2)
    return summary_df


def generate_full_acs(year: int, month: int, export_excel: bool = True):
  """Fungsi utama untuk membuat semua tabel ACS."""
  gen = ACSGenerator(DB_PATH)
  df = gen.fetch_monthly_metars(year, month)

  if df.empty:
    print(
        f"[!] Tidak ada record METAR ditemukan untuk periode {year:04d}-{month:02d}."
    )
    return None

  print(
      f"=== AERODROME CLIMATOLOGICAL SUMMARY (WAGB) - {year:04d}/{month:02d} ==="
  )
  print(f"Total METAR Diproses: {len(df)} laporan\n")

  t_wind = gen.table_wind_distribution(df)
  t_vc = gen.table_vis_ceiling(df)
  t_diurnal = gen.table_diurnal_stats(df)
  t_wx = gen.table_weather_phenomena(df)

  print(">>> 1. DISTRIBUSI ANGIN PERMUKAAN (%) <<<")
  print(t_wind.to_string())
  print("\n>>> 2. MINIMA OPERASIONAL: VISIBILITY vs CEILING (COUNT) <<<")
  print(t_vc.to_string())
  print("\n>>> 3. SUHU & TEKANAN PER JAM UTC <<<")
  print(t_diurnal.to_string())
  print("\n>>> 4. FREKUENSI FENOMENA CUACA <<<")
  print(t_wx.to_string())

  if export_excel:
    filename = f"ACS_WAGB_{year:04d}_{month:02d}.xlsx"
    try:
      with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        t_wind.to_excel(writer, sheet_name="Wind_Distribution")
        t_vc.to_excel(writer, sheet_name="Visibility_Ceiling")
        t_diurnal.to_excel(writer, sheet_name="Diurnal_Temp_QNH")
        t_wx.to_excel(writer, sheet_name="Weather_Phenomena")
        df.to_excel(writer, sheet_name="Parsed_Raw_METAR", index=False)
      print(f"\n[OK] Laporan ACS berhasil diekspor ke Excel: {filename}")
    except Exception as e:
      print(
          f"\n[!] Ekspor Excel gagal ({e}), pastikan `openpyxl` terpasang"
          " (pip install openpyxl)."
      )

  return {"wind": t_wind, "vis_ceil": t_vc, "diurnal": t_diurnal, "wx": t_wx}


if __name__ == "__main__":
  # Contoh: Membuat laporan ACS untuk bulan berjalan
  now = datetime.now()
  generate_full_acs(year=now.year, month=now.month, export_excel=True)