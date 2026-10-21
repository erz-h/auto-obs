"""data_manager.py.

Modul antarmuka manajemen database observasi ME-48 dan bulletin sandi.
"""

from datetime import datetime, timezone
import sqlite3
from fklim import generate_fklim71
from fklim import generate_climat_from_fklim
import pandas as pd
import numpy as np
import streamlit as st
from db import DB_PATH, get_historical_records
from acs_reporter import ACSGenerator
from synop_monthly_report import (
    SynopMonthlyReport,
    generate_synoptic_monthly_package,
    plot_pressure_trend,
    plot_rh_and_clouds,
    plot_synoptic_wind_rose,
    plot_temperature_and_rain,
)

def compute_pan_evaporation(
    df_input: pd.DataFrame, prev_month_last_scale2: float = 20.0
) -> pd.DataFrame:
  """Menghitung beda tinggi (H) dan evaporasi (EV) sesuai kaidah lembar kontrol panci terbuka."""
  df = df_input.copy()

  # Pastikan kolom numerik
  for col in ["scale_1", "scale_2", "rainfall_r"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

  diff_h = []
  ev_list = []

  # Nilai acuan awal dari akhir bulan sebelumnya
  prev_scale_2 = prev_month_last_scale2

  for _, row in df.iterrows():
    s1 = row["scale_1"]
    s2 = row["scale_2"]
    rain = row["rainfall_r"] if pd.notna(row["rainfall_r"]) else 0.0

    if pd.isna(s1) or pd.isna(prev_scale_2):
      h = np.nan
      ev = np.nan
    else:
      h = round(prev_scale_2 - s1, 1)
      raw_ev = round(h + rain, 1)
      # Validasi batas penguapan harian
      ev = 7.0 if raw_ev > 7.0 else raw_ev

    diff_h.append(h)
    ev_list.append(ev)

    # Skala 2 hari ini menjadi acuan untuk pengukuran hari berikutnya
    prev_scale_2 = s2 if pd.notna(s2) else prev_scale_2

  df["diff_h"] = diff_h
  df["evaporation_ev"] = ev_list
  return df

def render_data_manager():
  """Merender tampilan utama menu Data Manager di Streamlit."""
  st.subheader("🗄️ Data Manager & Bulletin Inspector")
  st.caption(
      f"Pusat pengelolaan database lokal (`{DB_PATH}`) dan pemantauan sandi"
      " observasi."
  )

  # --------------------------------------------------------------------------
  # 1. INSPEKSI BULLETINS TERAKHIR (BASIS SPLICING AUTOPILOT)
  # --------------------------------------------------------------------------
  st.markdown("##### 1. Bulletin Aktif di Database")

  try:
    df_all = get_historical_records()
  except Exception as e:
    st.error(f"Gagal mengakses database: {e}")
    return

  if not df_all.empty:
    latest = df_all.iloc[0]

    col_meta1, col_meta2 = st.columns(2)
    with col_meta1:
      st.markdown(
          f"**Timestamp Acuan**: `{latest.get('data_timestamp', '-')}`"
      )
      st.code(
          latest.get("encoded_metar") or "[Belum ada encoded_metar]",
          language="text",
      )
    with col_meta2:
      sync_status = (
          "✅ Synced ke BMKGSoft"
          if latest.get("synced_to_bmkg") == 1
          else "💾 Tersimpan Lokal"
      )
      st.markdown(f"**Status Transmisi**: `{sync_status}`")
      st.code(
          latest.get("encoded_synop") or "[Belum ada encoded_synop]",
          language="text",
      )
  else:
    st.warning(
        "Tabel `me48_observations` masih kosong. Silakan lakukan input data"
        " awal."
    )
    return

  st.divider()
  # --------------------------------------------------------------------------
  # 2. FILTER & KONTROL RIWAYAT OBSERVASI
  # --------------------------------------------------------------------------
  st.markdown("##### 2. Filter & Ekspor Riwayat Observasi")

  # Ubah menjadi 4 kolom agar ada ruang untuk dropdown filter
  col_f1, col_f2, col_f3, col_f4 = st.columns([1, 1, 1.5, 1])
  
  with col_f1:
    start_date = st.date_input(
        "Mulai Tanggal",
        value=pd.to_datetime(df_all["data_timestamp"].min()).date(),
    )
  with col_f2:
    end_date = st.date_input("Sampai Tanggal", value=datetime.now().date())
  with col_f3:
    export_mode = st.selectbox(
        "Format Interval CSV",
        ["Semua Data (Per 30 Menit)", "Khusus ME-48/Sinoptik (Per Jam)"]
    )

  # Ambil data mentah dari database
  df_filtered = get_historical_records(
      start_date=str(start_date), end_date=str(end_date)
  )

  # Terapkan filter berdasarkan pilihan dropdown
  if export_mode == "Khusus ME-48/Sinoptik (Per Jam)":
      # Filter hanya yang berakhiran ":00:00Z" (membuang menit :30)
      df_export = df_filtered[df_filtered["data_timestamp"].str.endswith(":00:00Z")]
      file_suffix = "ME48_PerJam"
  else:
      # Biarkan apa adanya (termasuk METAR menit :30)
      df_export = df_filtered
      file_suffix = "Semua_30Menit"

  with col_f4:
    st.write("")
    st.write("")
    # Tombol download CSV berdasarkan data yang sudah difilter
    csv_data = df_export.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Ekspor ke CSV",
        data=csv_data,
        file_name=f"export_{file_suffix}_{start_date}_to_{end_date}.csv",
        mime="text/csv",
        use_container_width=True,
    )

  # Ringkasan cepat (Gunakan panjang df_export agar sesuai dengan pilihan)
  col_s1, col_s2, col_s3 = st.columns(3)
  col_s1.metric("Total Baris CSV Terfilter", len(df_export))
  col_s2.metric("Total Seluruh Record (DB)", len(df_all))
  latest_rain = latest.get("rainfall_last_mm")
  col_s3.metric(
      "Curah Hujan Terakhir",
      f"{latest_rain} mm" if latest_rain is not None else "0.0 mm / null",
  )

  # --------------------------------------------------------------------------
  # 3. TABEL DATA OBSERVASI
  # --------------------------------------------------------------------------
  display_columns = [
      "data_timestamp",
      "temp_drybulb_c_tttttt",
      "temp_wetbulb_c",
      "temp_dewpoint_c_tdtdtd",
      "relative_humidity_pc",
      "pressure_qfe_mb_derived",
      "pressure_qff_mb_derived",
      "wind_speed_ff",
      "rainfall_last_mm",
      "visibility_vv",
      "cloud_cover_oktas_m",
      "encoded_metar",
  ]
  valid_display = [col for col in display_columns if col in df_filtered.columns]

  st.dataframe(
      df_filtered[valid_display],
      use_container_width=True,
      hide_index=True,
  )

  from acs_reporter import ACSGenerator

  # ACS Report
  st.divider()
  st.subheader("📑 Aerodrome Climatological Summary (ACS) Bulanan")
  st.caption(
      "Menghasilkan ringkasan klimatologi penerbangan ICAO murni dari histori"
      " `encoded_metar`."
  )

  col_a1, col_a2, col_a3 = st.columns([1, 1, 1])
  with col_a1:
    sel_year = st.number_input("Tahun", min_value=2020, max_value=2030, value=2026)
  with col_a2:
    sel_month = st.selectbox(
        "Bulan",
        range(1, 13),
        index=datetime.now().month - 1,
        format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
    )
  with col_a3:
    st.write("")
    st.write("")
    btn_generate_acs = st.button("📊 Hitung ACS Bulanan", use_container_width=True)

  if btn_generate_acs:
    gen = ACSGenerator()
    df_parsed = gen.fetch_monthly_metars(sel_year, sel_month)

    if df_parsed.empty:
      st.warning(
          f"Tidak ada data METAR pada periode {sel_year}-{sel_month:02d} di"
          " database."
      )
    else:
      st.success(f"Berhasil menganalisis {len(df_parsed)} sandi METAR!")

      tab_w, tab_vc, tab_diurn, tab_phenom = st.tabs([
          "💨 Distribusi Angin",
          "👁️ Visibility & Ceiling",
          "🌡️ Suhu & QNH",
          "⛈️ Fenomena Cuaca",
      ])

      with tab_w:
        st.markdown("**Distribusi Frekuensi Arah vs Kecepatan Angin (%)**")
        st.dataframe(gen.table_wind_distribution(df_parsed))

      with tab_vc:
        st.markdown(
            "**Matriks Kategori Operasional (Visibility vs Cloud Ceiling)**"
        )
        st.dataframe(gen.table_vis_ceiling(df_parsed))

      with tab_diurn:
        st.markdown("**Variasi Diurnal Suhu (°C), Titik Embun, dan QNH per Jam UTC**")
        st.dataframe(gen.table_diurnal_stats(df_parsed))

      with tab_phenom:
        st.markdown("**Frekuensi Kemunculan Fenomena Signifikan**")
        st.dataframe(gen.table_weather_phenomena(df_parsed))

  #Monthly Synoptic Report
  st.divider()
  st.subheader("📑 Laporan Sinoptik Bulanan (ME-48 / F-Met)")
  st.caption(
      "Rekapitulasi resmi iklim dan sinoptik stasiun WAGB (Suhu Tx/Tn, Hujan,"
      " Tekanan QFF/QFE, dan Angin)."
  )

  col_s1, col_s2, col_s3 = st.columns([1, 1, 1])
  with col_s1:
    rep_year = st.number_input(
        "Tahun Laporan", min_value=2020, max_value=2030, value=2026
    )
  with col_s2:
    rep_month = st.selectbox(
        "Bulan Laporan",
        range(1, 13),
        index=datetime.now().month - 1,
        format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
    )
  with col_s3:
    st.write("")
    st.write("")
    btn_synop_rep = st.button(
        "📊 Susun Laporan Sinoptik", use_container_width=True
    )

  if btn_synop_rep:
    reporter = SynopMonthlyReport()
    raw_df = reporter.fetch_monthly_data(rep_year, rep_month)

    if raw_df.empty:
      st.warning(f"Belum ada data ME-48 pada periode {rep_year}-{rep_month:02d}.")
    else:
      daily_df = reporter.build_daily_summary(raw_df)
      extremes_df = reporter.build_monthly_extremes(daily_df, raw_df)

      st.success(f"Berhasil merangkum {len(raw_df)} observasi sinoptik!")

      # Opsi Ekspor Lengkap
      if st.button("💾 Ekspor Paket Laporan (Excel & 4 Grafik PNG 300 DPI)"):
        generate_synoptic_monthly_package(rep_year, rep_month)
        st.success("File Excel & Gambar tersimpan di folder `reports/synoptic/`.")

      tab_tab, tab_g1, tab_g2, tab_g3 = st.tabs([
          "📋 Tabel Rekapitulasi",
          "📈 Suhu & Curah Hujan",
          "🧭 Barometer QFF/QFE & RH",
          "💨 Mawar Angin Sinoptik",
      ])

      with tab_tab:
        col_t1, col_t2 = st.columns([1, 2])
        with col_t1:
          st.markdown("**Ringkasan Iklim & Ekstrem Bulanan**")
          st.dataframe(extremes_df, use_container_width=True, hide_index=True)
        with col_t2:
          st.markdown("**Tabel Observasi Harian Sinoptik (ME-48)**")
          st.dataframe(daily_df, use_container_width=True, hide_index=True)

      with tab_g1:
        st.pyplot(plot_temperature_and_rain(daily_df, rep_year, rep_month))

      with tab_g2:
        st.pyplot(plot_pressure_trend(daily_df, rep_year, rep_month))
        st.pyplot(plot_rh_and_clouds(daily_df, raw_df, rep_year, rep_month))

      with tab_g3:
        st.pyplot(plot_synoptic_wind_rose(raw_df, rep_year, rep_month))

  st.divider()
  st.header("📑 Laporan Fklim 71 & Sandi CLIMAT")

  col_y, col_m, col_b = st.columns([1, 1, 1])
  with col_y:
    sel_year = st.number_input(
        "Year", min_value=2020, max_value=2030, value=2026
    )
  with col_m:
    sel_month = st.selectbox("Month", range(1, 13), index=8)  # Default: September
  with col_b:
    st.write("")
    st.write("")
    btn_generate = st.button("Proses Data", use_container_width=True)

  if btn_generate:
    df_fklim = generate_fklim71(sel_year, sel_month)

    if not df_fklim.empty:
      # Tampilan dan unduhan CSV Raw
      st.subheader("Data Rekapitulasi (CSV Raw)")
      st.dataframe(df_fklim, use_container_width=True)

      csv_raw = df_fklim.to_csv(index=True).encode("utf-8")
      st.download_button(
          label="📥 Unduh CSV Raw Fklim 71",
          data=csv_raw,
          file_name=f"fklim71_{sel_year}_{sel_month:02d}.csv",
          mime="text/csv",
      )

      # Teks Sandi CLIMAT
      climat_bulletin = generate_climat_from_fklim(
          df_fklim, sel_year, sel_month, station_wmo="96655"
      )

      st.subheader("📡 Buletin Sandi CLIMAT (FM 71)")
      st.code(climat_bulletin, language="text")

      st.download_button(
          label="📥 Unduh Buletin Sandi (.txt)",
          data=climat_bulletin,
          file_name=f"CLIMAT_{sel_year}_{sel_month:02d}_96655.txt",
          mime="text/plain",
      )
    else:
      st.warning("Data pengamatan untuk periode tersebut tidak ditemukan.") 

  st.header("🪣 Helper Pengukuran Panci Evaporasi")

  # Pilihan periode pengamatan
  col_th, col_bl, col_prev = st.columns([1, 1, 1])
  with col_th:
    thn = st.number_input(
        "Tahun", min_value=2025, max_value=2030, value=2026, key="ev_thn"
    )
  with col_bl:
    bln = st.selectbox("Bulan", range(1, 13), index=8, key="ev_bln")
  with col_prev:
    init_s2 = st.number_input(
        "Skala 2 Akhir Bulan Lalu", value=20.0, step=0.1, format="%.1f"
    )

  # Inisialisasi tabel kosong jika belum ada input
  days_count = pd.Period(f"{thn}-{bln}").days_in_month
  default_df = pd.DataFrame({
      "TGL": range(1, days_count + 1),
      "scale_1": [np.nan] * days_count,
      "scale_2": [20.0] * days_count,  # Default tinggi standar setelah isi air
      "rainfall_r": [0.0] * days_count,
  })

  st.markdown("Masukkan pembacaan **Skala 1** dan **Skala 2** harian:")

  # Editor tabel dengan perhitungan langsung
  edited_df = st.data_editor(
      default_df,
      column_config={
          "TGL": st.column_config.NumberColumn("TGL", disabled=True),
          "scale_1": st.column_config.NumberColumn(
              "Skala 1 (Isikan)", step=0.1, format="%.1f"
          ),
          "scale_2": st.column_config.NumberColumn(
              "Skala 2 (Ganti Air)", step=0.1, format="%.1f"
          ),
          "rainfall_r": st.column_config.NumberColumn(
              "Hujan R (mm)", step=0.1, format="%.1f"
          ),
      },
      hide_index=True,
      use_container_width=True,
  )

  # Tombol proses kalkulasi
  if st.button("Hitung Evaporasi", use_container_width=True):
    result_df = compute_pan_evaporation(
        edited_df, prev_month_last_scale2=init_s2
    )

    # Tampilkan hasil perhitungan
    st.subheader("Hasil Perhitungan Evaporasi")
    st.dataframe(
        result_df[[
            "TGL",
            "scale_1",
            "scale_2",
            "diff_h",
            "rainfall_r",
            "evaporation_ev",
        ]],
        column_config={
            "diff_h": st.column_config.NumberColumn(
                "H (Beda Tinggi)", format="%.1f"
            ),
            "evaporation_ev": st.column_config.NumberColumn(
                "EV (E=H+R)", format="%.1f"
            ),
        },
        use_container_width=True,
    )

    # Unduh CSV hasil kalkulasi
    csv_evap = result_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Unduh CSV Rekap Evaporasi",
        data=csv_evap,
        file_name=f"evaporasi_{thn}_{bln:02d}.csv",
        mime="text/csv",
    )