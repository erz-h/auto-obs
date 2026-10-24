"""
data_manager.py
Pusat terpadu inspeksi database lokal, log audit buletin METAR/ME-48,
rekapitulasi Fklim 71, sandi CLIMAT, serta pelaporan klimatologi (ACS & F-Met).
"""

from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st

from acs_reporter import ACSGenerator
from db import DB_PATH, get_db_connection, get_historical_records
from fklim import generate_climat_from_fklim, generate_fklim71
from synop_monthly_report import (
    SynopMonthlyReport,
    generate_synoptic_monthly_package,
    plot_pressure_trend,
    plot_rh_and_clouds,
    plot_synoptic_wind_rose,
    plot_temperature_and_rain,
)

PRIMARY_SYNOP_HOURS = {"00", "03", "06", "09", "12", "15", "18", "21"}


# ==============================================================================
# HELPER PENGUKURAN PANCI EVAPORASI
# ==============================================================================
def compute_pan_evaporation(
    df_input: pd.DataFrame, prev_month_last_scale2: float = 20.0
) -> pd.DataFrame:
  """Menghitung beda tinggi (H) dan evaporasi (EV) sesuai kaidah panci terbuka."""
  df = df_input.copy()
  for col in ["scale_1", "scale_2", "rainfall_r"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

  diff_h, ev_list = [], []
  prev_scale_2 = prev_month_last_scale2

  for _, row in df.iterrows():
    s1 = row["scale_1"]
    s2 = row["scale_2"]
    rain = row["rainfall_r"] if pd.notna(row["rainfall_r"]) else 0.0

    if pd.isna(s1) or pd.isna(prev_scale_2):
      h, ev = np.nan, np.nan
    else:
      h = round(prev_scale_2 - s1, 1)
      raw_ev = round(h + rain, 1)
      ev = 7.0 if raw_ev > 7.0 else raw_ev

    diff_h.append(h)
    ev_list.append(ev)
    prev_scale_2 = s2 if pd.notna(s2) else prev_scale_2

  df["diff_h"] = diff_h
  df["evaporation_ev"] = ev_list
  return df


# ==============================================================================
# MAIN RENDER FUNCTION (SUB-TABS MANAGEMENT)
# ==============================================================================
def render_data_manager():
  """Merender seluruh kontrol manajemen data, log audit, dan pelaporan iklim."""
  st.subheader("🗄️ Data Manager, Logs & Climate Reports")
  st.caption(
      f"Pusat pengelolaan database lokal (`{DB_PATH}`), audit buletin GTS, dan"
      " otomasi laporan iklim."
  )

  tab_me48, tab_metar, tab_evap, tab_fklim, tab_reports = st.tabs([
      "🗄️ Observasi ME-48",
      "📡 Log METAR (:00 & :30)",
      "🪣 Arsip Evaporasi Panci",
      "📑 Fklim 71 & CLIMAT",
      "📊 Analisis Lanjutan (ACS / F-Met)",
  ])

  # --------------------------------------------------------------------------
  # SUB-TAB 1: OBSERVASI ME-48
  # --------------------------------------------------------------------------
  with tab_me48:
    st.markdown("##### 1. Rekaman ME-48 & Bulletin Terakhir")
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
      st.warning("Tabel `me48_observations` masih kosong.")
      return

    st.divider()
    st.markdown("##### 2. Filter & Ekspor Riwayat Observasi")

    today = datetime.now().date()
    col_f1, col_f2, col_f3, col_f4 = st.columns([1, 1, 1.2, 1])
    with col_f1:
      start_date = st.date_input(
          "Mulai Tanggal", value=today.replace(day=1), key="m48_sdate"
      )
    with col_f2:
      end_date = st.date_input("Sampai Tanggal", value=today, key="m48_edate")
    with col_f3:
      export_mode = st.selectbox(
          "Kategori Jam",
          ["Semua Jam (00 - 23 UTC)", "Khusus Jam Sinoptik (3-Jaman)"],
          key="m48_mode",
      )
    with col_f4:
      sort_order = st.selectbox(
          "Urutan Waktu",
          ["Terbaru ke Terlama (DESC)", "Terlama ke Terbaru (ASC)"],
          key="m48_sort",
      )

    df_filtered = get_historical_records(
        start_date=str(start_date), end_date=str(end_date)
    )

    if (
        export_mode == "Khusus Jam Sinoptik (3-Jaman)"
        and not df_filtered.empty
    ):
      df_filtered = df_filtered[
          df_filtered["data_timestamp"]
          .str.slice(11, 13)
          .isin(PRIMARY_SYNOP_HOURS)
      ]

    if not df_filtered.empty:
      df_filtered = df_filtered.sort_values(
          by="data_timestamp",
          ascending=(sort_order == "Terlama ke Terbaru (ASC)"),
      )

    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric("Baris Terpilih", len(df_filtered))
    col_s2.metric("Total Arsip DB", len(df_all))
    latest_rain = latest.get("rainfall_last_mm")
    col_s3.metric(
        "Curah Hujan Terakhir",
        f"{latest_rain} mm" if pd.notnull(latest_rain) else "0.0 mm / null",
    )
    with col_s4:
      st.write("")
      st.download_button(
          label="📥 Ekspor CSV ME-48",
          data=df_filtered.to_csv(index=False).encode("utf-8"),
          file_name=f"ME48_{start_date}_to_{end_date}.csv",
          mime="text/csv",
          use_container_width=True,
      )

    column_labels = {
        "data_timestamp": "Timestamp UTC",
        "temp_drybulb_c_tttttt": "TT (°C)",
        "temp_wetbulb_c": "Tw (°C)",
        "temp_dewpoint_c_tdtdtd": "Td (°C)",
        "relative_humidity_pc": "RH (%)",
        "pressure_qfe_mb_derived": "QFE (mb)",
        "pressure_qff_mb_derived": "QFF (mb)",
        "wind_speed_ff": "Angin (kt)",
        "wind_dir_deg_dd": "Arah (°)",
        "rainfall_last_mm": "Hujan (mm)",
        "visibility_vv": "Vis (km)",
        "cloud_cover_oktas_m": "N (oktas)",
        "encoded_metar": "Sandi METAR",
    }
    valid_cols = [c for c in column_labels if c in df_filtered.columns]
    st.dataframe(
        df_filtered[valid_cols].rename(columns=column_labels),
        use_container_width=True,
        hide_index=True,
    )

  # --------------------------------------------------------------------------
  # SUB-TAB 2: LOG TRANSMISI METAR (:00 & :30)
  # --------------------------------------------------------------------------
  with tab_metar:
    st.subheader("📡 Arsip Transmisi Buletin METAR WAGB")
    st.caption(
        "Riwayat seluruh buletin METAR (:00, :30, dan SPECI) yang disiarkan ke"
        " GTS BMKG."
    )
    try:
      with get_db_connection() as conn:
        df_metar_logs = pd.read_sql_query(
            """SELECT 
                    bulletin_timestamp,
                    station_icao,
                    metar_code,
                    CASE WHEN sent_to_gts = 1 THEN '✅ Terkirim (200 OK)' ELSE '❌ Gagal Siar' END AS status_gts,
                    wmo_bulletin,
                    created_at
                FROM metar_logs 
                ORDER BY bulletin_timestamp DESC LIMIT 150""",
            conn,
        )
      if not df_metar_logs.empty:
        col_m1, col_m2 = st.columns([3, 1])
        col_m1.metric("Total Buletin Tercatat", len(df_metar_logs))
        with col_m2:
          st.write("")
          st.download_button(
              "📥 Ekspor Log METAR (.csv)",
              df_metar_logs.to_csv(index=False).encode("utf-8"),
              f"metar_logs_{today}.csv",
              "text/csv",
              use_container_width=True,
          )

        st.dataframe(
            df_metar_logs[[
                "bulletin_timestamp",
                "station_icao",
                "metar_code",
                "status_gts",
                "created_at",
            ]],
            column_config={
                "bulletin_timestamp": "Waktu Buletin (UTC)",
                "station_icao": "ICAO",
                "metar_code": "Sandi METAR",
                "status_gts": "Status GTS",
                "created_at": "Waktu Sistem Lokal",
            },
            use_container_width=True,
            hide_index=True,
        )
      else:
        st.info("Belum ada riwayat transmisi buletin METAR tersimpan.")
    except Exception as err:
      st.error(f"Gagal memuat log METAR: {err}")

  # --------------------------------------------------------------------------
  # SUB-TAB 3: ARSIP EVAPORASI PANCI
  # --------------------------------------------------------------------------
  with tab_evap:
    st.subheader("🪣 Arsip Pengukuran Evaporasi Panci Terbuka")
    st.caption(
        "Data histori perhitungan beda tinggi skala (H) dan evaporasi (EV)"
        " tersimpan."
    )
    try:
      with get_db_connection() as conn:
        df_evap_logs = pd.read_sql_query(
            "SELECT * FROM pan_evaporation ORDER BY obs_date DESC", conn
        )
      if not df_evap_logs.empty:
        col_e1, col_e2 = st.columns([3, 1])
        col_e1.metric("Total Hari Tercatat", len(df_evap_logs))
        with col_e2:
          st.write("")
          st.download_button(
              "📥 Unduh CSV Evaporasi",
              df_evap_logs.to_csv(index=False).encode("utf-8"),
              f"arsip_evaporasi_{today}.csv",
              "text/csv",
              use_container_width=True,
          )
        st.dataframe(
            df_evap_logs[[
                "obs_date",
                "scale_1",
                "scale_2",
                "diff_h",
                "rainfall_r",
                "evaporation_ev",
                "created_at",
            ]],
            column_config={
                "obs_date": "Tanggal",
                "scale_1": "Skala 1 (mm)",
                "scale_2": "Skala 2 (mm)",
                "diff_h": "Beda Tinggi H (mm)",
                "rainfall_r": "Curah Hujan R (mm)",
                "evaporation_ev": "Evaporasi EV (mm)",
                "created_at": "Tercatat Pada",
            },
            use_container_width=True,
            hide_index=True,
        )
      else:
        st.info("Belum ada data rekaman evaporasi panci di database.")
    except Exception as err:
      st.error(f"Gagal memuat arsip evaporasi: {err}")

  # --------------------------------------------------------------------------
  # SUB-TAB 4: FKLIM 71 & SANDI CLIMAT (FM 71)
  # --------------------------------------------------------------------------
  with tab_fklim:
    st.subheader("📑 Rekapitulasi Fklim 71 & Buletin Sandi CLIMAT (FM 71)")
    st.caption(
        "Rekapitulasi bulanan resmi standar BMKG Fklim 71 dan generator sandi"
        " CLIMAT (FM 71)."
    )

    col_fk1, col_fk2, col_fk3 = st.columns([1, 1, 1])
    with col_fk1:
      fk_year = st.number_input(
          "Tahun Laporan",
          min_value=2020,
          max_value=2030,
          value=today.year,
          key="fk_yr",
      )
    with col_fk2:
      fk_month = st.selectbox(
          "Bulan Laporan",
          range(1, 13),
          index=today.month - 1,
          format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
          key="fk_mo",
      )
    with col_fk3:
      st.write("")
      st.write("")
      btn_fk = st.button(
          "📊 Generate Fklim 71 & CLIMAT",
          type="primary",
          use_container_width=True,
      )

    if btn_fk:
      df_fklim_res = generate_fklim71(fk_year, fk_month)
      if not df_fklim_res.empty:
        st.markdown("#### Tabel Raw CSV Fklim 71")
        st.dataframe(df_fklim_res, use_container_width=True)
        st.download_button(
            "📥 Unduh Raw CSV Fklim 71",
            df_fklim_res.to_csv(index=True).encode("utf-8"),
            f"fklim71_{fk_year}_{fk_month:02d}.csv",
            "text/csv",
        )

        climat_txt = generate_climat_from_fklim(
            df_fklim_res, fk_year, fk_month, station_wmo="96655"
        )
        st.markdown("#### 📡 Buletin Resmi CLIMAT (FM 71)")
        st.code(climat_txt, language="text")
        st.download_button(
            "📥 Unduh Teks Sandi CLIMAT (.txt)",
            climat_txt,
            f"CLIMAT_{fk_year}_{fk_month:02d}_96655.txt",
            "text/plain",
        )
      else:
        st.warning(
            f"Tidak ada data observasi pada periode {fk_year}-{fk_month:02d}."
        )

  # --------------------------------------------------------------------------
  # SUB-TAB 5: ANALISIS LANJUTAN (ACS & LAPORAN SINOPTIK)
  # --------------------------------------------------------------------------
  with tab_reports:
    st.subheader("📊 Analisis Klimatologi & Pelaporan Sinoptik Bulanan")

    opt_rep = st.radio(
        "Pilih Modul Laporan",
        [
            "Aerodrome Climatological Summary (ACS - ICAO)",
            "Laporan Sinoptik Bulanan (ME-48 / F-Met)",
        ],
        horizontal=True,
    )

    if opt_rep == "Aerodrome Climatological Summary (ACS - ICAO)":
      st.caption(
          "Menghasilkan ringkasan klimatologi penerbangan ICAO murni dari"
          " riwayat sandi METAR."
      )
      c_a1, c_a2, c_a3 = st.columns([1, 1, 1])
      with c_a1:
        sel_year = st.number_input(
            "Tahun",
            min_value=2020,
            max_value=2030,
            value=today.year,
            key="acs_yr",
        )
      with c_a2:
        sel_month = st.selectbox(
            "Bulan",
            range(1, 13),
            index=today.month - 1,
            format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
            key="acs_mo",
        )
      with c_a3:
        st.write("")
        st.write("")
        btn_acs = st.button("📊 Hitung ACS Bulanan", use_container_width=True)

      if btn_acs:
        gen = ACSGenerator()
        df_parsed = gen.fetch_monthly_metars(sel_year, sel_month)
        if df_parsed.empty:
          st.warning(
              f"Tidak ada data METAR pada periode {sel_year}-{sel_month:02d}."
          )
        else:
          st.success(f"Berhasil menganalisis {len(df_parsed)} buletin METAR!")
          tab_w, tab_vc, tab_diurn, tab_phenom = st.tabs([
              "💨 Distribusi Angin",
              "👁️ Visibility & Ceiling",
              "🌡️ Suhu & QNH",
              "⛈️ Fenomena Cuaca",
          ])
          with tab_w:
            st.dataframe(
                gen.table_wind_distribution(df_parsed), use_container_width=True
            )
          with tab_vc:
            st.dataframe(
                gen.table_vis_ceiling(df_parsed), use_container_width=True
            )
          with tab_diurn:
            st.dataframe(
                gen.table_diurnal_stats(df_parsed), use_container_width=True
            )
          with tab_phenom:
            st.dataframe(
                gen.table_weather_phenomena(df_parsed), use_container_width=True
            )

    else:
      st.caption(
          "Rekapitulasi resmi iklim dan sinoptik stasiun WAGB (Suhu Tx/Tn,"
          " Hujan, Barometer, dan Angin)."
      )
      c_r1, c_r2, c_r3 = st.columns([1, 1, 1])
      with c_r1:
        rep_year = st.number_input(
            "Tahun",
            min_value=2020,
            max_value=2030,
            value=today.year,
            key="syn_yr",
        )
      with c_r2:
        rep_month = st.selectbox(
            "Bulan",
            range(1, 13),
            index=today.month - 1,
            format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
            key="syn_mo",
        )
      with c_r3:
        st.write("")
        st.write("")
        if st.button("📊 Susun Laporan Sinoptik", use_container_width=True):
          st.session_state["show_synop_report"] = True

      if st.session_state.get("show_synop_report", False):
        reporter = SynopMonthlyReport()
        raw_df = reporter.fetch_monthly_data(rep_year, rep_month)
        if raw_df.empty:
          st.warning(
              f"Belum ada data ME-48 pada periode {rep_year}-{rep_month:02d}."
          )
        else:
          daily_df = reporter.build_daily_summary(raw_df)
          extremes_df = reporter.build_monthly_extremes(daily_df, raw_df)
          st.success(f"Berhasil merangkum {len(raw_df)} observasi sinoptik!")

          if st.button("💾 Ekspor Paket Laporan (Excel & 4 Grafik PNG 300 DPI)"):
            with st.spinner("Merender berkas Excel & Grafik..."):
              generate_synoptic_monthly_package(rep_year, rep_month)
            st.success(
                "✅ File Excel & Gambar tersimpan di folder `reports/synoptic/`."
            )

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
              st.dataframe(
                  extremes_df, use_container_width=True, hide_index=True
              )
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