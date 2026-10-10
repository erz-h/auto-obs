import sqlite3

def init_db():
    # Opens 'station_me48.db' (if it doesn't exist, Python creates it automatically)
    conn = sqlite3.connect("station_me48.db")
    cursor = conn.cursor()
    
    # Executes the SQL command to create the table structure
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS me48_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_timestamp TEXT UNIQUE NOT NULL,
        bmkgsoft_id INTEGER,
        observer_id INTEGER,
        
        -- Temperatures & Pressures
        temp_drybulb_c REAL,
        temp_wetbulb_c REAL,
        temp_max_c REAL,
        temp_min_c REAL,
        pressure_qff_mb REAL,
        pressure_qfe_mb REAL,
        
        -- Wind & Weather
        wind_dir_deg INTEGER,
        wind_speed_ff INTEGER,
        visibility_vv REAL,
        present_weather_ww INTEGER,
        past_weather_w1 TEXT,
        past_weather_w2 TEXT,
        rainfall_last_mm REAL,
        
        -- Clouds
        cloud_cover_oktas TEXT,
        cloud_low_type TEXT,
        cloud_med_type TEXT,
        cloud_high_type TEXT,
        
        -- SYNOP Code & Sync Tracker
        encoded_synop TEXT,
        synced_to_bmkg INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Save (commit) changes and close the database connection
    conn.commit()
    conn.close()
    print("Success! 'station_me48.db' has been created.")

if __name__ == "__main__":
    init_db()