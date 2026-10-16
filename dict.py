"""BMKG & WMO Synoptic Observation Code Tables and UI Dropdown Mappings."""

# Bagian Langit Tertutup Awan (Total Cloud Cover - N)
CLOUD_COVER_OKTAS = {
    None: "",
    0: "0 - Langit cerah (0 oktas)",
    1: "1 - 1 okta",
    2: "2 - 2 oktas",
    3: "3 - 3 oktas",
    4: "4 - 4 oktas",
    5: "5 - 5 oktas",
    6: "6 - 6 oktas",
    7: "7 - 7 oktas",
    8: "8 - 8 oktas",
    9: "9 - Langit tertutup kabut atau fenomena cuaca lainnya",
    "/": "/ - Tidak dapat ditentukan selain kabut",
}

# Awan Rendah (CL)
CLOUD_LOW_TYPE_CL = {
    None: "",
    0: "0 - Tidak ada awan Cl",
    1: "1 - Cumulus humilis / fractocumulus cuaca baik",
    2: "2 - Cumulus mediocris / congestus",
    3: "3 - Cumulonimbus calvus (tanpa landasan)",
    4: "4 - Stratocumulus cumulogenitus",
    5: "5 - Stratocumulus bukan cumulogenitus",
    6: "6 - Stratus nebulosus / fractus cuaca baik",
    7: "7 - Pannus (fraktostratus/fraktocumulus cuaca buruk)",
    8: "8 - Cumulus dan stratocumulus bersamaan",
    9: "9 - Cumulonimbus capillatus (berlandasan / anvil)",
    "/": "/ - Cl tidak terlihat karena kabut/debu",
}

# Genus Awan Rendah (Jenis Lapisan 1, 2, 3)
LOW_CLOUD_GENUS = {
    None: "",
    6: "6 - Stratocumulus (Sc)",
    7: "7 - Stratus (St)",
    8: "8 - Cumulus (Cu)",
    9: "9 - Cumulonimbus (Cb)",
    "/": "/ - Cloud not visible",
}

# Awan Menengah (CM)
CLOUD_MED_TYPE_CM = {
    None: "",
    0: "0 - Tidak ada awan Cm",
    1: "1 - Altostratus translucidus",
    2: "2 - Altostratus opacus / Nimbostratus",
    3: "3 - Altocumulus translucidus satu lapis",
    4: "4 - Altocumulus lenticularis bertambah tebal",
    5: "5 - Altocumulus translucidus bergelombang",
    6: "6 - Altocumulus cumulogenitus / cumulonimbogenitus",
    7: "7 - Altocumulus duplikus / opacus",
    8: "8 - Altocumulus castellanus / floccus",
    9: "9 - Altocumulus langit semrawut (chaotic)",
    "/": "/ - Cm tidak terlihat karena kabut/debu",
}

# Genus Awan Menengah
MED_CLOUD_GENUS = {
    None: "",
    3: "3 - Altocumulus (Ac)",
    4: "4 - Altostratus (As)",
    5: "5 - Nimbostratus (Ns)",
    "/": "/ - Cloud not visible",
}

# Awan Tinggi (CH)
CLOUD_HIGH_TYPE_CH = {
    None: "",
    0: "0 - Tidak ada awan Ch",
    1: "1 - Cirrus fibratus / uncinus",
    2: "2 - Cirrus spissatus / castellanus",
    3: "3 - Cirrus spissatus cumulonimbogenitus",
    4: "4 - Cirrus uncinus / fibratus bertambah tebal",
    5: "5 - Cirrus / Cirrostratus mendekati horizon < 45°",
    6: "6 - Cirrus / Cirrostratus mendekati horizon > 45°",
    7: "7 - Cirrostratus menutupi seluruh langit",
    8: "8 - Cirrostratus tidak menutupi seluruh langit",
    9: "9 - Cirrocumulus sendiri atau dominan",
    "/": "/ - Ch tidak terlihat karena kabut/debu",
}

# Genus Awan Tinggi
HIGH_CLOUD_GENUS = {
    None: "",
    0: "0 - Cirrus (Ci)",
    1: "1 - Cirrocumulus (Cc)",
    2: "2 - Cirrostratus (Cs)",
    "/": "/ - Cloud not visible",
}

# Arah Gerak Awan (Da / Dm / Dh)
CLOUD_DIRECTION = {
    None: "",
    0: "0 - Stationary / Tidak bergerak",
    1: "1 - Timur Laut (NE)",
    2: "2 - Timur (E)",
    3: "3 - Tenggara (SE)",
    4: "4 - Selatan (S)",
    5: "5 - Barat Daya (SW)",
    6: "6 - Barat (W)",
    7: "7 - Barat Laut (NW)",
    8: "8 - Utara (N)",
    9: "9 - All Directions / Segala penjuru",
    "/": "/ - Arah tidak dapat ditentukan",
}

# Okta per Lapisan
LAYER_OKTAS = {
    None: "",
    0: "0 oktas",
    1: "1 oktas",
    2: "2 oktas",
    3: "3 oktas",
    4: "4 oktas",
    5: "5 oktas",
    6: "6 oktas",
    7: "7 oktas",
    8: "8 oktas",
    9: "9 - Langit terhalang",
    "/": "/ - Tidak dapat ditentukan",
}

# -----------------------------------------------------------------------------
# WMO Code Table 4561: Past Weather reported from a manned weather station (W1, W2)
# Cuaca yang Lalu (Periode antara jam pengamatan sebelumnya hingga sekarang)
# -----------------------------------------------------------------------------
PAST_WEATHER_W = {
    None: "",
    0: (
        "0 - Awan menutupi ≤ 4 oktas (separuh atau kurang) selama periode"
        " observasi"
    ),
    1: (
        "1 - Awan menutupi > 4 oktas pada sebagian periode, dan ≤ 4 oktas pada"
        " sebagian lainnya"
    ),
    2: (
        "2 - Awan menutupi > 4 oktas (lebih dari separuh) selama seluruh"
        " periode observasi"
    ),
    3: "3 - Badai debu, badai pasir, atau tiupan salju (drifting/blowing snow)",
    4: "4 - Kabut (fog / ice fog) atau udara kabur tebal (jarak pandang < 1 km)",
    5: "5 - Gerimis (drizzle)",
    6: "6 - Hujan kontinu atau selang-seling (rain)",
    7: "7 - Salju atau hujan bercampur salju (snow / sleet)",
    8: "8 - Hujan lebat sesaat (showers / hujan tipe curahan)",
    9: "9 - Badai guntur (thunderstorm) dengan atau tanpa presipitasi",
    "/": "/ - Cuaca yang lalu tidak dapat diamati atau tidak dilaporkan",
}

# -----------------------------------------------------------------------------
# WMO Code Table 4677: Present Weather reported from a manned weather station (ww)
# Cuaca Saat Pengamatan
# -----------------------------------------------------------------------------
PRESENT_WEATHER_WW = {
    None: "",
    # 00 - 09: Fenomena tanpa presipitasi, kabut, atau debu tebal di stasiun
    0: (
        "00 - Perkembangan awan tidak teramati atau tidak dapat diamati selama"
        " 1 jam terakhir"
    ),
    1: "01 - Awan umumnya berkurang atau menghilang selama 1 jam terakhir",
    2: "02 - Keadaan langit secara umum tidak berubah selama 1 jam terakhir",
    3: "03 - Awan umumnya bertambah atau berkembang selama 1 jam terakhir",
    4: "04 - Jarak pandang berkurang oleh asap (smoke)",
    5: "05 - Haze (udara kabur / partikel kering melayang)",
    6: "06 - Debu kering melayang luas di udara (bukan tertiup angin setempat)",
    7: (
        "07 - Debu atau pasir terangkat oleh angin di atau dekat stasiun saat"
        " pengamatan"
    ),
    8: "08 - Pusaran debu atau pasir (dust whirls / devil) di atau dekat stasiun",
    9: (
        "09 - Badai debu atau badai pasir terlihat saat pengamatan atau 1 jam"
        " terakhir"
    ),
    # 10 - 19: Fenomena hidrometeor non-presipitasi atau presipitasi di kejauhan
    10: "10 - Mist / Halimun (jarak pandang mendatar 1000 m - 5000 m, RH ≥ 80%)",
    11: "11 - Patches kabut tipis atau kabut es di darat (tinggi < 2 m)",
    12: (
        "12 - Lapisan kabut tipis kontinu di darat (tinggi < 2 m di atas tanah)"
    ),
    13: "13 - Kilat terlihat, tetapi guntur tidak terdengar",
    14: "14 - Presipitasi terlihat tidak mencapai permukaan tanah (Virga)",
    15: (
        "15 - Presipitasi terlihat di kejauhan mencapai tanah (> 5 km dari"
        " stasiun)"
    ),
    16: (
        "16 - Presipitasi terlihat dekat stasiun mencapai tanah (< 5 km dari"
        " stasiun)"
    ),
    17: (
        "17 - Badai guntur (thunderstorm) terdengar, tetapi tidak ada"
        " presipitasi di stasiun"
    ),
    18: "18 - Squall (angin ribut mendadak) saat pengamatan atau 1 jam terakhir",
    19: "19 - Corong awan (funnel cloud / puting beliung / waterspout)",
    # 20 - 29: Presipitasi atau badai pada jam terakhir tetapi BERHENTI saat pengamatan
    20: (
        "20 - Gerimis (drizzle) atau salju butir berhenti dalam 1 jam terakhir"
    ),
    21: "21 - Hujan (rain) berhenti dalam 1 jam terakhir",
    22: "22 - Salju (snow) berhenti dalam 1 jam terakhir",
    23: "23 - Hujan bercampur salju berhenti dalam 1 jam terakhir",
    24: "24 - Freezing drizzle atau freezing rain berhenti dalam 1 jam terakhir",
    25: "25 - Hujan lebat sesaat (rain shower) berhenti dalam 1 jam terakhir",
    26: "26 - Shower salju berhenti dalam 1 jam terakhir",
    27: "27 - Shower hujan es (hail) berhenti dalam 1 jam terakhir",
    28: "28 - Kabut (fog) atau ice fog menghilang dalam 1 jam terakhir",
    29: "29 - Badai guntur (thunderstorm) berhenti dalam 1 jam terakhir",
    # 30 - 39: Badai debu, badai pasir, atau tiupan salju
    30: "30 - Badai debu/pasir ringan atau sedang, berkurang kekuatannya",
    31: "31 - Badai debu/pasir ringan atau sedang, tidak berubah kekuatannya",
    32: "32 - Badai debu/pasir ringan atau sedang, bertambah kuat",
    33: "33 - Badai debu/pasir hebat, berkurang kekuatannya",
    34: "34 - Badai debu/pasir hebat, tidak berubah kekuatannya",
    35: "35 - Badai debu/pasir hebat, bertambah kuat",
    36: "36 - Tiupan salju rendah (drifting snow)",
    37: "37 - Tiupan salju rendah yang lebat",
    38: "38 - Badai salju tiup tinggi (blowing snow)",
    39: "39 - Badai salju tiup tinggi yang lebat",
    # 40 - 49: Kabut (Fog) saat pengamatan (Visibility < 1000 m)
    40: (
        "40 - Kabut di kejauhan saat pengamatan (meluas di atas stasiun dalam 1"
        " jam terakhir)"
    ),
    41: "41 - Kabut terputus-putus (in patches)",
    42: "42 - Kabut menipis, langit terlihat",
    43: "43 - Kabut menipis, langit tidak terlihat (terhalang)",
    44: "44 - Kabut tidak berubah kepekatannya, langit terlihat",
    45: "45 - Kabut tidak berubah kepekatannya, langit tidak terlihat",
    46: "46 - Kabut mulai menebal, langit terlihat",
    47: "47 - Kabut mulai menebal, langit tidak terlihat",
    48: "48 - Kabut rime (kabut membeku), langit terlihat",
    49: "49 - Kabut rime (kabut membeku), langit tidak terlihat",
    # 50 - 59: Gerimis (Drizzle) saat pengamatan
    50: "50 - Gerimis ringan terputus-putus (intermittent slight drizzle)",
    51: "51 - Gerimis ringan terus-menerus (continuous slight drizzle)",
    52: "52 - Gerimis sedang terputus-putus (intermittent moderate drizzle)",
    53: "53 - Gerimis sedang terus-menerus (continuous moderate drizzle)",
    54: "54 - Gerimis lebat terputus-putus (intermittent heavy drizzle)",
    55: "55 - Gerimis lebat terus-menerus (continuous heavy drizzle)",
    56: "56 - Gerimis membeku ringan (slight freezing drizzle)",
    57: "57 - Gerimis membeku sedang atau lebat (moderate/heavy freezing drizzle)",
    58: "58 - Gerimis dan hujan ringan",
    59: "59 - Gerimis dan hujan sedang atau lebat",
    # 60 - 69: Hujan kontinu / selang-seling (Rain) saat pengamatan
    60: "60 - Hujan ringan terputus-putus (intermittent slight rain)",
    61: "61 - Hujan ringan terus-menerus (continuous slight rain)",
    62: "62 - Hujan sedang terputus-putus (intermittent moderate rain)",
    63: "63 - Hujan sedang terus-menerus (continuous moderate rain)",
    64: "64 - Hujan lebat terputus-putus (intermittent heavy rain)",
    65: "65 - Hujan lebat terus-menerus (continuous heavy rain)",
    66: "66 - Hujan membeku ringan",
    67: "67 - Hujan membeku sedang atau lebat",
    68: "68 - Hujan atau gerimis bercampur salju ringan",
    69: "69 - Hujan atau gerimis bercampur salju sedang atau lebat",
    # 70 - 79: Presipitasi padat selain shower (Solid precipitation / Snow)
    70: "70 - Hujan salju ringan terputus-putus",
    71: "71 - Hujan salju ringan terus-menerus",
    72: "72 - Hujan salju sedang terputus-putus",
    73: "73 - Hujan salju sedang terus-menerus",
    74: "74 - Hujan salju lebat terputus-putus",
    75: "75 - Hujan salju lebat terus-menerus",
    76: "76 - Butir-butir es (diamond dust)",
    77: "77 - Salju butir (snow grains)",
    78: "78 - Hablur es terisolasi (isolated star-like snow crystals)",
    79: "79 - Es jarum / pelet es (ice pellets)",
    # 80 - 90: Presipitasi tipe shower (Shower precipitation)
    80: "80 - Hujan rintik/shower ringan (slight rain shower)",
    81: "81 - Hujan shower sedang atau lebat (moderate/heavy rain shower)",
    82: "82 - Hujan shower sangat lebat / deras ekstrem (violent rain shower)",
    83: "83 - Shower campuran hujan dan salju ringan",
    84: "84 - Shower campuran hujan dan salju sedang atau lebat",
    85: "85 - Shower salju ringan",
    86: "86 - Shower salju sedang atau lebat",
    87: "87 - Shower butiran es lunak (soft hail) ringan",
    88: "88 - Shower butiran es lunak (soft hail) sedang atau lebat",
    89: "89 - Shower hujan es (hail) ringan tanpa guntur",
    90: "90 - Shower hujan es (hail) sedang atau lebat tanpa guntur",
    # 91 - 99: Badai Guntur (Thunderstorm) saat pengamatan atau 1 jam terakhir
    91: (
        "91 - Hujan ringan saat pengamatan, didahului badai guntur dalam 1 jam"
        " terakhir"
    ),
    92: (
        "92 - Hujan sedang/lebat saat pengamatan, didahului badai guntur dalam 1"
        " jam terakhir"
    ),
    93: (
        "93 - Salju atau hujan es ringan saat pengamatan, didahului badai guntur"
        " dalam 1 jam terakhir"
    ),
    94: (
        "94 - Salju atau hujan es sedang/lebat saat pengamatan, didahului badai"
        " guntur dalam 1 jam terakhir"
    ),
    95: "95 - Badai guntur (TS) ringan atau sedang dengan hujan atau salju",
    96: (
        "96 - Badai guntur (TS) ringan atau sedang dengan hujan es (hail /"
        " graupel)"
    ),
    97: "97 - Badai guntur (TS) hebat / kuat dengan hujan atau salju",
    98: "98 - Badai guntur (TS) disertai badai debu atau pasir",
    99: "99 - Badai guntur (TS) hebat disertai hujan es (hail)",
}