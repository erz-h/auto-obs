"""synop_monthly_report.py.

Laporan Bulanan Sinoptik & Rekapitulasi ME-48 Stasiun WAGB (96655).
Menghasilkan:
  1. Tabel Ringkasan Harian (Daily Synoptic Summary Table)
  2. Tabel Ekstrem & Statistik Iklim Bulanan
  3. Grafik Kombo Suhu (Tx, Tn, Tavg) & Curah Hujan Harian
  4. Grafik Tren Tekanan Barometer (QFF & QFE)
  5. Grafik Fluktuasi Kelembapan Relatif (RH) & Tutupan Awan
  6. Diagram Mawar Angin Sinoptik (Synoptic Wind Rose)
"""

import os
import sqlite3
from typing import Dict, Tuple
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DB_PATH = "station_me48.db"

plt.style.use(
    "seaborn-v0_8-whitegrid"
    if "seaborn-v0_8-whitegrid" in plt.style.available
    else "default"
)
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.size"] = 10


class SynopMonthlyReport:

  def __init__(self, db_path: str = DB_PATH):
    self.db_path = db_path

  def fetch_monthly_data(self, year: int, month: int) -> pd.DataFrame:
    """Mengambil seluruh data observasi sinoptik me48_observations untuk bulan target."""
    month_pattern = f"{year:04d}-{month:02d}%"
    with sqlite3.connect(self.db_path) as conn:
      query = """
                SELECT 
                    data_timestamp,
                    temp_drybulb_c_tttttt as tt,
                    temp_dewpoint_c_tdtdtd as td,
                    relative_humidity_pc as rh,
                    temp_max_c_txtxtx as tx,
                    temp_min_c_tntntn as tn,
                    pressure_qfe_mb_derived as qfe,
                    pressure_qff_mb_derived as qff,
                    wind_dir_deg_dd as wind_dir,
                    wind_speed_ff as wind_spd,
                    rainfall_last_mm as rain,
                    cloud_cover_oktas_m as cloud_n,
                    present_weather_ww as ww,
                    encoded_synop
                FROM me48_observations
                WHERE data_timestamp LIKE ?
                ORDER BY data_timestamp ASC
            """
      df = pd.read_sql_query(query, conn, params=[month_pattern])

    if df.empty:
      return pd.DataFrame()

    df["dt"] = pd.to_datetime(df["data_timestamp"])
    df["day"] = df["dt"].dt.day
    df["hour"] = df["dt"].dt.hour

    # Konversi numerik
    num_cols = ["tt", "td", "rh", "tx", "tn", "qfe", "qff", "wind_spd", "rain"]
    for col in num_cols:
      df[col] = pd.to_numeric(df[col], errors="coerce")

    return df

  def build_daily_summary(self, df: pd.DataFrame) -> pd.DataFrame:
    """Menyusun Tabel Rekapitulasi Harian Sinoptik (1 bulan penuh)."""
    if df.empty:
      return pd.DataFrame()

    daily_rows = []
    for day, group in df.groupby("day"):
      # Suhu Maksimum: utamakan kolom tx, jika null ambil max(tt)
      tx_val = group["tx"].dropna()
      tx = tx_val.max() if not tx_val.empty else group["tt"].max()

      # Suhu Minimum: utamakan kolom tn, jika null ambil min(tt)
      tn_val = group["tn"].dropna()
      tn = tn_val.min() if not tn_val.empty else group["tt"].min()

      t_avg = group["tt"].mean()
      rh_avg = group["rh"].mean()
      rh_min = group["rh"].min()
      qff_avg = group["qff"].mean()
      qfe_avg = group["qfe"].mean()

      # Curah hujan harian (akumulasi rain > 0)
      rain_daily = group["rain"].dropna().sum()

      # Kecepatan & arah angin terbanyak
      w_spd_avg = group["wind_spd"].mean()
      w_dirs = group["wind_dir"].dropna()
      prevailing_dir = int(w_dirs.mode()[0]) if not w_dirs.empty else 0

      daily_rows.append({
          "Tanggal": int(day),
          "T_Max (°C)": round(tx, 1) if pd.notna(tx) else None,
          "T_Min (°C)": round(tn, 1) if pd.notna(tn) else None,
          "T_Rata (°C)": round(t_avg, 1) if pd.notna(t_avg) else None,
          "RH_Rata (%)": round(rh_avg, 1) if pd.notna(rh_avg) else None,
          "RH_Min (%)": round(rh_min, 1) if pd.notna(rh_min) else None,
          "QFF_Rata (hPa)": round(qff_avg, 1) if pd.notna(qff_avg) else None,
          "QFE_Rata (hPa)": round(qfe_avg, 1) if pd.notna(qfe_avg) else None,
          "Hujan (mm)": round(rain_daily, 1),
          "Angin_Rata (kt)": (
              round(w_spd_avg, 1) if pd.notna(w_spd_avg) else 0.0
          ),
          "Arah_Dominan (deg)": prevailing_dir,
      })

    return pd.DataFrame(daily_rows)

  def build_monthly_extremes(
      self, daily_df: pd.DataFrame, raw_df: pd.DataFrame
  ) -> pd.DataFrame:
    """Menyusun Tabel Ringkasan Ekstrem & Statistik Iklim Bulanan."""
    if daily_df.empty:
      return pd.DataFrame()

    total_rain = daily_df["Hujan (mm)"].sum()
    rain_days_05 = (daily_df["Hujan (mm)"] >= 0.5).sum()
    rain_days_20 = (daily_df["Hujan (mm)"] >= 20.0).sum()
    max_daily_rain = daily_df["Hujan (mm)"].max()

    stats = [
        (
            "Suhu Rata-rata Bulanan",
            f"{daily_df['T_Rata (°C)'].mean():.1f} °C",
            "-",
        ),
        (
            "Suhu Maksimum Absolut (Tx)",
            f"{daily_df['T_Max (°C)'].max():.1f} °C",
            f"Tgl {daily_df.loc[daily_df['T_Max (°C)'].idxmax(), 'Tanggal']}",
        ),
        (
            "Suhu Minimum Absolut (Tn)",
            f"{daily_df['T_Min (°C)'].min():.1f} °C",
            f"Tgl {daily_df.loc[daily_df['T_Min (°C)'].idxmin(), 'Tanggal']}",
        ),
        (
            "Kelembapan Rata-rata Bulanan",
            f"{daily_df['RH_Rata (%)'].mean():.1f} %",
            "-",
        ),
        (
            "Kelembapan Terendah Absolut",
            f"{daily_df['RH_Min (%)'].min():.1f} %",
            f"Tgl {daily_df.loc[daily_df['RH_Min (%)'].idxmin(), 'Tanggal']}",
        ),
        (
            "Tekanan QFF Rata-rata",
            f"{daily_df['QFF_Rata (hPa)'].mean():.1f} hPa",
            "-",
        ),
        ("Total Curah Hujan Bulanan", f"{total_rain:.1f} mm", "-"),
        (
            "Curah Hujan Harian Maksimum",
            f"{max_daily_rain:.1f} mm",
            f"Tgl {daily_df.loc[daily_df['Hujan (mm)'].idxmax(), 'Tanggal']}",
        ),
        ("Jumlah Hari Hujan (>= 0.5 mm)", f"{rain_days_05} hari", "-"),
        ("Jumlah Hari Hujan Lebat (>= 20 mm)", f"{rain_days_20} hari", "-"),
        (
            "Kecepatan Angin Rata-rata",
            f"{daily_df['Angin_Rata (kt)'].mean():.1f} knot",
            "-",
        ),
    ]

    return pd.DataFrame(stats, columns=["Parameter", "Nilai", "Keterangan"])


# ==============================================================================
# FUNGSI GRAFIK BULANAN SINOPTIK
# ==============================================================================


def plot_temperature_and_rain(
    daily_df: pd.DataFrame, year: int, month: int
) -> plt.Figure:
  """Grafik 1: Kurva Suhu (Tx, Tn, Tavg) dipadu Hyetograf Curah Hujan Harian."""
  fig, ax1 = plt.subplots(figsize=(12, 5), dpi=300)
  days = daily_df["Tanggal"]

  # Garis Suhu
  ax1.plot(
      days,
      daily_df["T_Max (°C)"],
      color="#d9534f",
      marker="^",
      linewidth=1.8,
      label="Suhu Max (Tx)",
  )
  ax1.plot(
      days,
      daily_df["T_Rata (°C)"],
      color="#f0ad4e",
      marker="o",
      linewidth=2.0,
      label="Suhu Rata-rata",
  )
  ax1.plot(
      days,
      daily_df["T_Min (°C)"],
      color="#0275d8",
      marker="v",
      linewidth=1.8,
      label="Suhu Min (Tn)",
  )
  ax1.set_xlabel("Tanggal", fontweight="bold")
  ax1.set_ylabel("Suhu Udara (°C)", fontweight="bold")
  ax1.set_xticks(days)
  ax1.grid(True, linestyle=":", alpha=0.6)

  # Batang Curah Hujan (Axis Kanan)
  ax2 = ax1.twinx()
  ax2.bar(
      days,
      daily_df["Hujan (mm)"],
      color="#5bc0de",
      alpha=0.45,
      width=0.6,
      label="Curah Hujan (mm)",
  )
  ax2.set_ylabel("Curah Hujan (mm)", fontweight="bold", color="#0275d8")
  ax2.set_ylim(0, max(daily_df["Hujan (mm)"].max() * 1.5, 10))
  ax2.grid(False)

  lines1, labels1 = ax1.get_legend_handles_labels()
  lines2, labels2 = ax2.get_legend_handles_labels()
  ax1.legend(
      lines1 + lines2, labels1 + labels2, loc="upper right", ncol=4, frameon=True
  )

  plt.title(
      f"Fluktuasi Suhu Udara & Curah Hujan Harian - WAGB ({year:04d}/{month:02d})",
      fontsize=12,
      fontweight="bold",
      pad=14,
  )
  plt.tight_layout()
  return fig


def plot_pressure_trend(
    daily_df: pd.DataFrame, year: int, month: int
) -> plt.Figure:
  """Grafik 2: Fluktuasi Tekanan Barometer Permukaan Laut (QFF) & Stasiun (QFE)."""
  fig, ax = plt.subplots(figsize=(11, 4.5), dpi=300)
  days = daily_df["Tanggal"]

  ax.plot(
      days,
      daily_df["QFF_Rata (hPa)"],
      color="#6f42c1",
      marker="s",
      linewidth=2,
      label="QFF (Mean Sea Level)",
  )
  ax.plot(
      days,
      daily_df["QFE_Rata (hPa)"],
      color="#20c997",
      marker="o",
      linewidth=1.8,
      linestyle="--",
      label="QFE (Station Level)",
  )

  ax.set_title(
      f"Tren Tekanan Udara Rata-rata Harian - WAGB ({year:04d}/{month:02d})",
      fontsize=12,
      fontweight="bold",
      pad=12,
  )
  ax.set_xlabel("Tanggal", fontweight="bold")
  ax.set_ylabel("Tekanan Udara (hPa)", fontweight="bold")
  ax.set_xticks(days)
  ax.grid(True, linestyle=":", alpha=0.6)
  ax.legend(loc="best", frameon=True)
  plt.tight_layout()
  return fig


def plot_rh_and_clouds(
    daily_df: pd.DataFrame, raw_df: pd.DataFrame, year: int, month: int
) -> plt.Figure:
  """Grafik 3: Kelembapan Relatif (RH) Harian dan Rata-rata Tutupan Awan."""
  fig, ax = plt.subplots(figsize=(11, 4.5), dpi=300)
  days = daily_df["Tanggal"]

  ax.plot(
      days,
      daily_df["RH_Rata (%)"],
      color="#0275d8",
      marker="o",
      linewidth=2,
      label="RH Rata-rata (%)",
  )
  ax.plot(
      days,
      daily_df["RH_Min (%)"],
      color="#d9534f",
      marker="x",
      linestyle=":",
      label="RH Minimum (%)",
  )

  ax.set_title(
      f"Profil Kelembapan Relatif (RH) Harian - WAGB ({year:04d}/{month:02d})",
      fontsize=12,
      fontweight="bold",
      pad=12,
  )
  ax.set_xlabel("Tanggal", fontweight="bold")
  ax.set_ylabel("Kelembapan Relatif (%)", fontweight="bold")
  ax.set_ylim(20, 105)
  ax.set_xticks(days)
  ax.grid(True, linestyle=":", alpha=0.6)
  ax.legend(loc="lower left", frameon=True)
  plt.tight_layout()
  return fig


def plot_synoptic_wind_rose(
    raw_df: pd.DataFrame, year: int, month: int
) -> plt.Figure:
  """Grafik 4: Diagram Mawar Angin Sinoptik (8 Sektor)."""
  directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
  angles = np.deg2rad(np.arange(0, 360, 45))

  total_obs = len(raw_df)
  calm_count = (raw_df["wind_spd"] == 0).sum()
  calm_pct = (calm_count / total_obs * 100) if total_obs > 0 else 0

  # Mapping sektor derajat
  def deg_to_sector(d):
    if pd.isna(d):
      return None
    return directions[round(d / 45) % 8]

  df_wind = raw_df[raw_df["wind_spd"] > 0].copy()
  df_wind["sector"] = df_wind["wind_dir"].apply(deg_to_sector)

  bins = [
      (
          "1 - 3 kt",
          (df_wind["wind_spd"] >= 1) & (df_wind["wind_spd"] <= 3),
          "#85c1e9",
      ),
      (
          "4 - 6 kt",
          (df_wind["wind_spd"] >= 4) & (df_wind["wind_spd"] <= 6),
          "#3498db",
      ),
      (
          "7 - 10 kt",
          (df_wind["wind_spd"] >= 7) & (df_wind["wind_spd"] <= 10),
          "#f39c12",
      ),
      ("> 10 kt", df_wind["wind_spd"] > 10, "#e74c3c"),
  ]

  fig, ax = plt.subplots(
      figsize=(6, 6), subplot_kw={"projection": "polar"}, dpi=300
  )
  ax.set_theta_zero_location("N")
  ax.set_theta_direction(-1)

  bottom = np.zeros(8)
  for label, mask, color in bins:
    subset = df_wind[mask]
    counts = np.array(
        [(subset["sector"] == d).sum() / total_obs * 100 for d in directions]
    )
    ax.bar(
        angles,
        counts,
        width=np.deg2rad(38),
        bottom=bottom,
        color=color,
        edgecolor="black",
        linewidth=0.5,
        label=label,
    )
    bottom += counts

  ax.set_xticks(angles)
  ax.set_xticklabels(directions, fontweight="bold")
  ax.set_title(
      f"Mawar Angin Sinoptik - WAGB\nCalm: {calm_pct:.1f}%"
      f" ({year:04d}/{month:02d})",
      fontsize=11,
      fontweight="bold",
      pad=18,
  )
  ax.legend(
      loc="lower right", bbox_to_anchor=(1.25, 0.0), frameon=True, fontsize=8
  )
  plt.tight_layout()
  return fig


# ==============================================================================
# FUNGSI EKSEKUSI & EKSPOR
# ==============================================================================


def generate_synoptic_monthly_package(
    year: int, month: int, output_dir: str = "reports/synoptic"
):
  """Membuat seluruh tabel dan grafik sinoptik bulanan serta menyimpannya."""
  os.makedirs(output_dir, exist_ok=True)
  reporter = SynopMonthlyReport()

  raw_df = reporter.fetch_monthly_data(year, month)
  if raw_df.empty:
    print(f"[!] Tidak ada data observasi untuk {year:04d}-{month:02d}.")
    return None

  daily_df = reporter.build_daily_summary(raw_df)
  extremes_df = reporter.build_monthly_extremes(daily_df, raw_df)

  # Simpan Grafik ke PNG 300 DPI
  fig_t_rain = plot_temperature_and_rain(daily_df, year, month)
  fig_t_rain.savefig(f"{output_dir}/grafik_suhu_hujan_{year}_{month:02d}.png")

  fig_press = plot_pressure_trend(daily_df, year, month)
  fig_press.savefig(f"{output_dir}/grafik_tekanan_{year}_{month:02d}.png")

  fig_rh = plot_rh_and_clouds(daily_df, raw_df, year, month)
  fig_rh.savefig(f"{output_dir}/grafik_kelembapan_{year}_{month:02d}.png")

  fig_wind = plot_synoptic_wind_rose(raw_df, year, month)
  fig_wind.savefig(f"{output_dir}/grafik_mawar_angin_{year}_{month:02d}.png")

  # Simpan Tabel ke Excel Multi-Sheet
  excel_file = f"{output_dir}/Laporan_Sinoptik_WAGB_{year}_{month:02d}.xlsx"
  with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
    daily_df.to_excel(writer, sheet_name="Rekap_Harian", index=False)
    extremes_df.to_excel(writer, sheet_name="Ringkasan_Ekstrem", index=False)
    raw_df.to_excel(writer, sheet_name="Data_Mentah_ME48", index=False)

  print(f"[OK] Laporan Sinoptik Bulanan selesai disusun:")
  print(f"  -> File Excel: {excel_file}")
  print(f"  -> 4 Grafik PNG disimpan di: {output_dir}/")

  return {
      "daily": daily_df,
      "extremes": extremes_df,
      "fig_t_rain": fig_t_rain,
      "fig_press": fig_press,
      "fig_rh": fig_rh,
      "fig_wind": fig_wind,
  }


if __name__ == "__main__":
  now = datetime.now()
  generate_synoptic_monthly_package(year=now.year, month=now.month)