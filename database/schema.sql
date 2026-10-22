-- =====================================================================
-- flAIre · flaire.gpkg · Tolosaldea pilot · schema v1.3 (2 Oct 2026; v1.0 + linker fixes, see CHANGES v1.1 / v1.2 / v1.3)
-- Single GeoPackage (SQLite) that the agent tools query.
--
-- Create:   sqlite3 flaire.gpkg < schema.sql
-- Load:     geopandas .to_file("flaire.gpkg", layer=..., mode="a", engine="pyogrio")
--           or INSERT ... SELECT from a staging layer. CHECKs/triggers reject bad rows.
-- Spatial index (after load, GDAL):
--           ogrinfo flaire.gpkg -sql "SELECT CreateSpatialIndex('buildings','geom')"
-- Metric layers are EPSG:25830 (ETRS89/UTM30N). lon/lat columns (EPSG:4326) are
-- duplicated on point tables so agent tools need no GIS library.
--
-- TEAM RULES ENFORCED HERE (search "RULE"):
--  R1 missing != 0          nullable value columns + CHECKs that forbid 0 as a stand-in
--  R2 building counted once  building_id UNIQUE; one municipality, one zone per method,
--                            PK (scenario,k,building) on results
--  R3 unroutable kept        routable flag; minutes NULL when unroutable; QA views
--  R4 never mix sources/dates every data row has source_id; scenarios pin data_version
--  R5 k_max <= valid candidates  trigger on scenarios
--  R6 plan_year never changes results  plan_year lives only in `plans`, not in scenario key
--  R7 frequency != probability; weighted coverage != population  (column names + docs)
--  R8 FWI not computed ad hoc   profile_methods.index_type
--  R9 times are estimates       *_min_est naming, parameters.threshold is_official = 0
-- QA views named qa_* MUST return 0 rows before a data_version is frozen.
--
-- CHANGES v1.3 (linker, 2 Oct 2026) - data v0.3.1-official:
--  * road_edges.speed_source accepts 'reclass_service_with_GI_ref' (highway=service ways carrying a GI-* foral road
--    number are routed as unclassified, 40 km/h).
--
-- CHANGES v1.2 (linker, 2 Oct 2026) - data v0.3-official:
--  * scenarios.weighting accepts 'uniform' (weight 1 per building as an explicit comparison with the weather-weighted
--    run; 'uniform_pending_weather' kept for old versions); qa_uniform_weight checks both.
--
-- CHANGES v1.1 (linker, 1 Oct 2026) - requested by the network agent / needed to load v0.2:
--  * road_edges.region accepts 'OTHER' (Rioja/Burgos/Cantabria/France fragments kept for connectivity);
--    extra nullable columns speed_truck_kmh, t_light_s, t_truck_s, is_track, in_main_component, name, ref
--  * fire_stations.include_in_baseline (Hondarribia airport point loaded with 0, not an origin)
--  * buildings: in_analysis_set, routable, unroutable_reason, snap_edge_class, snap_road, residential_flag, footprint_m2
--  * candidates: pool_id, site_type, tier, osm_id, area_m2, current_truck_time_min_est, selection_step
--  * travel_times.profile ('light'|'truck', DEFAULT 'light') in the PK; reason 'snap>150m' allowed
--  * scenarios.profile; weighting 'uniform_pending_weather' (no weather weights yet: weight = 1 for every building);
--    method_version nullable unless weighting = 'historical_frequency'; uniqueness by expression index
--  * parameters: snap_max_m = 150 (was 200), access_speed_kmh = 15, candidate rule parameters
--  * new QA views: qa_analysis_flag, qa_uniform_weight, qa_unroutable_without_reason, qa_candidate_spacing
--  * sources: the PBF has ONE id (SRC-OSM-GEOFABRIK-PV-20260930; SRC-OSM-PV-260930 merged into it by the loader)
-- =====================================================================

PRAGMA application_id = 1196444487;   -- 'GPKG'
PRAGMA user_version   = 10300;        -- GeoPackage 1.3
PRAGMA foreign_keys   = ON;           -- set on every connection too

-- ---------------------------------------------------------------- GPKG core
CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
  srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
  organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
CREATE TABLE IF NOT EXISTS gpkg_contents (
  table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
  description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
  srs_id INTEGER, CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
  table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
  srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
  CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
  CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
  CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));

INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES
 ('Undefined cartesian SRS',-1,'NONE',-1,'undefined',NULL),
 ('Undefined geographic SRS',0,'NONE',0,'undefined',NULL),
 ('WGS 84 geodetic',4326,'EPSG',4326,'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]',NULL),
 ('ETRS89 / UTM zone 30N',25830,'EPSG',25830,'PROJCS["ETRS89 / UTM zone 30N",GEOGCS["ETRS89",DATUM["European_Terrestrial_Reference_System_1989",SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","6258"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4258"]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-3],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH],AUTHORITY["EPSG","25830"]]',NULL);

-- ---------------------------------------------------------------- provenance (R4)
CREATE TABLE sources (
  source_id      TEXT PRIMARY KEY CHECK (source_id GLOB 'SRC-[A-Z0-9]*'),  -- e.g. SRC-B5M-BU
  title          TEXT NOT NULL,
  organization   TEXT NOT NULL,
  url            TEXT NOT NULL CHECK (url GLOB 'http*'),   -- exact URL used (incl. WFS query)
  licence        TEXT NOT NULL,
  download_date  TEXT NOT NULL CHECK (download_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  edition        TEXT,            -- edition / flight year / OSM snapshot timestamp
  period_from    TEXT,            -- data period (weather) YYYY-MM-DD
  period_to      TEXT,
  raw_file       TEXT NOT NULL,   -- path under raw/
  sha256         TEXT NOT NULL CHECK (length(sha256) = 64),
  crs_native     TEXT,
  owner_persona  TEXT CHECK (owner_persona IN ('P1','P2','P3','P4')),
  notes          TEXT,
  CHECK (period_from IS NULL OR period_to IS NULL OR period_from <= period_to)
);

CREATE TABLE data_versions (
  data_version TEXT PRIMARY KEY CHECK (data_version GLOB 'v[0-9]*'),    -- v0.2, v1.0
  created_utc  TEXT NOT NULL,
  frozen       INTEGER NOT NULL DEFAULT 0 CHECK (frozen IN (0,1)),
  notes        TEXT
);
CREATE TABLE data_version_sources (            -- exactly which source editions a version uses
  data_version TEXT NOT NULL REFERENCES data_versions(data_version),
  source_id    TEXT NOT NULL REFERENCES sources(source_id),
  PRIMARY KEY (data_version, source_id)
);

CREATE TABLE parameters (                      -- every tunable number in one place
  key         TEXT PRIMARY KEY,
  value       REAL NOT NULL,
  unit        TEXT NOT NULL,
  is_official INTEGER NOT NULL CHECK (is_official IN (0,1)),
  note        TEXT
);
INSERT INTO parameters VALUES
 ('threshold_default_min', 12,  'min', 0, 'RULE R9: demo threshold, not an official standard'),
 ('veg_proximity_m',       100, 'm',   0, 'TEAM TO CONFIRM: building near vegetation if rep point within this distance of a fuel polygon'),
 ('snap_max_m',            150, 'm',   0, 'building/candidate farther than this from the network -> routable=0, reason snap>150m'),
 ('access_speed_kmh',      15,  'km/h',0, 'speed of the straight-line access between a point and its snap point on the road'),
 ('cand_snap_max_m',       60,  'm',   0, 'candidate eligibility: snap to the road network <= this'),
 ('cand_min_dist_park_m',  2000,'m',   0, 'candidate eligibility: straight-line distance to any existing park >= this'),
 ('cand_min_separation_m', 3000,'m',   0, 'minimum straight-line separation between candidates'),
 ('k_max_allowed',         6,   'count',0,'combinations of 10 candidates for k=0..6 = 848'),
 ('truck_speed_factor',    1.0, 'ratio',0,'sensitivity: 0.8 for heavy vehicle');

CREATE TABLE seasons (
  season_id TEXT PRIMARY KEY,                  -- 'JUL-AUG'
  months    TEXT NOT NULL,                     -- '7,8'
  label     TEXT NOT NULL
);
INSERT INTO seasons VALUES ('JUL-AUG','7,8','July-August'), ('JUN-SEP','6,7,8,9','June-September');

-- ---------------------------------------------------------------- territory (P2)
CREATE TABLE municipalities (
  fid        INTEGER PRIMARY KEY AUTOINCREMENT,
  geom       MULTIPOLYGON,
  ine_code   TEXT NOT NULL UNIQUE CHECK (ine_code GLOB '20[0-9][0-9][0-9]'),   -- Gipuzkoa INE code
  name       TEXT NOT NULL,                    -- official (bilingual where applicable)
  in_pilot   INTEGER NOT NULL CHECK (in_pilot IN (0,1)),   -- 28 Tolosaldea = 1; neighbours = 0
  area_km2   REAL CHECK (area_km2 > 0),
  source_id  TEXT NOT NULL REFERENCES sources(source_id)
);
CREATE TABLE boundary (
  fid        INTEGER PRIMARY KEY AUTOINCREMENT,
  geom       MULTIPOLYGON,
  name       TEXT NOT NULL DEFAULT 'Tolosaldea (28 municipios, AF Tolosa PTP)',
  n_municipalities INTEGER NOT NULL CHECK (n_municipalities = 28),
  source_id  TEXT NOT NULL REFERENCES sources(source_id)
);

-- ---------------------------------------------------------------- vegetation (P3)
CREATE TABLE vegetation_classes (
  class_code_orig TEXT NOT NULL,
  source_id       TEXT NOT NULL REFERENCES sources(source_id),
  class_name_orig TEXT NOT NULL,
  class_group     TEXT NOT NULL CHECK (class_group IN
                  ('conifer','broadleaf','mixed_forest','shrub','grassland','crop','non_vegetated','water','other')),
  is_fuel         INTEGER NOT NULL CHECK (is_fuel IN (0,1)),   -- counts for "near vegetation"
  PRIMARY KEY (class_code_orig, source_id)
);
CREATE TABLE vegetation (
  fid             INTEGER PRIMARY KEY AUTOINCREMENT,
  geom            MULTIPOLYGON,
  class_code_orig TEXT NOT NULL,
  class_group     TEXT NOT NULL,
  is_fuel         INTEGER NOT NULL CHECK (is_fuel IN (0,1)),
  source_id       TEXT NOT NULL REFERENCES sources(source_id),
  FOREIGN KEY (class_code_orig, source_id) REFERENCES vegetation_classes(class_code_orig, source_id)
);

-- ---------------------------------------------------------------- road network (P4)
CREATE TABLE road_nodes (
  fid      INTEGER PRIMARY KEY AUTOINCREMENT,
  geom     POINT,
  node_id  INTEGER NOT NULL UNIQUE,
  x        REAL NOT NULL, y REAL NOT NULL,     -- EPSG:25830
  in_main_component INTEGER NOT NULL CHECK (in_main_component IN (0,1))
);
CREATE TABLE road_edges (
  fid            INTEGER PRIMARY KEY AUTOINCREMENT,
  geom           LINESTRING,
  edge_id        INTEGER NOT NULL UNIQUE,
  osm_id         TEXT,                          -- NULL only for synthetic connectors
  u              INTEGER NOT NULL REFERENCES road_nodes(node_id),
  v              INTEGER NOT NULL REFERENCES road_nodes(node_id),
  fclass         TEXT NOT NULL,
  oneway         TEXT NOT NULL CHECK (oneway IN ('F','T','B')),
  length_m       REAL NOT NULL CHECK (length_m > 0),
  maxspeed_osm   REAL CHECK (maxspeed_osm IS NULL OR maxspeed_osm > 0),  -- R1: NULL, never 0
  speed_used_kmh REAL NOT NULL CHECK (speed_used_kmh BETWEEN 5 AND 130),
  speed_source   TEXT NOT NULL CHECK (speed_source IN ('osm_maxspeed_capped','class_assumed','synthetic_connector','reclass_service_with_GI_ref')),
  region         TEXT NOT NULL CHECK (region IN ('PV','NAV','OTHER')),
  source_id      TEXT NOT NULL REFERENCES sources(source_id),
  speed_truck_kmh REAL CHECK (speed_truck_kmh IS NULL OR speed_truck_kmh > 0),
  t_light_s      REAL CHECK (t_light_s IS NULL OR t_light_s > 0),
  t_truck_s      REAL CHECK (t_truck_s IS NULL OR t_truck_s > 0),
  is_track       INTEGER CHECK (is_track IN (0,1)),
  in_main_component INTEGER CHECK (in_main_component IN (0,1)),   -- edge in the default routing graph
  name           TEXT, ref TEXT,
  CHECK (u <> v),
  CHECK ((speed_source = 'synthetic_connector') = (osm_id IS NULL)),
  CHECK (speed_source <> 'osm_maxspeed_capped' OR maxspeed_osm IS NOT NULL)
);
CREATE INDEX ix_edges_u ON road_edges(u);
CREATE INDEX ix_edges_v ON road_edges(v);

-- ---------------------------------------------------------------- buildings (P2 + links)
CREATE TABLE buildings (
  fid               INTEGER PRIMARY KEY AUTOINCREMENT,
  geom              POINT,                     -- interior representative point, EPSG:25830
  building_id       TEXT NOT NULL UNIQUE,      -- RULE R2: stable source id (INSPIRE localId)
  source_id         TEXT NOT NULL REFERENCES sources(source_id),
  source_use        TEXT,                      -- currentUse as published; NULL = not declared
  dwellings         INTEGER CHECK (dwellings IS NULL OR dwellings >= 0),  -- R1: NULL = unknown
  is_residential    INTEGER NOT NULL CHECK (is_residential IN (0,1)),
  residential_rule  TEXT NOT NULL CHECK (residential_rule IN ('use','dwellings','use_and_dwellings','none')),
  municipality_code TEXT NOT NULL REFERENCES municipalities(ine_code),   -- by rep point: one only
  x REAL NOT NULL, y REAL NOT NULL,            -- EPSG:25830 (rep point)
  lon REAL NOT NULL CHECK (lon BETWEEN -2.4 AND -1.7), lat REAL NOT NULL CHECK (lat BETWEEN 42.9 AND 43.4),
  veg_distance_m    REAL CHECK (veg_distance_m IS NULL OR veg_distance_m >= 0),  -- NULL = not computed
  veg_rule_m        REAL CHECK (veg_rule_m > 0),
  near_vegetation   INTEGER CHECK (near_vegetation IN (0,1)),          -- NULL = not computed
  node_id           INTEGER REFERENCES road_nodes(node_id),            -- NULL = not snapped
  snap_distance_m   REAL CHECK (snap_distance_m IS NULL OR snap_distance_m >= 0),
  year_built        INTEGER CHECK (year_built IS NULL OR year_built BETWEEN 1000 AND 2027),
  residential_flag  TEXT CHECK (residential_flag IN ('residential','non_residential','unknown')),
  footprint_m2      REAL CHECK (footprint_m2 IS NULL OR footprint_m2 > 0),
  in_analysis_set   INTEGER CHECK (in_analysis_set IN (0,1)),          -- = scope rule (qa_analysis_flag)
  routable          INTEGER CHECK (routable IN (0,1)),                 -- NULL = not linked yet
  unroutable_reason TEXT CHECK (unroutable_reason IN ('no_snap','snap>150m','disconnected_component')),
  snap_edge_class   TEXT, snap_road TEXT,
  CHECK (routable IS NULL OR (routable = 1) = (unroutable_reason IS NULL)),
  CHECK (routable IS NULL OR routable = 0 OR node_id IS NOT NULL),
  CHECK (near_vegetation IS NULL OR (veg_distance_m IS NOT NULL AND veg_rule_m IS NOT NULL
         AND near_vegetation = (veg_distance_m <= veg_rule_m))),
  CHECK ((node_id IS NULL) = (snap_distance_m IS NULL)),
  CHECK (residential_rule <> 'none' OR is_residential = 0)
);
CREATE INDEX ix_bld_muni  ON buildings(municipality_code);
CREATE INDEX ix_bld_scope ON buildings(is_residential, near_vegetation);

-- ---------------------------------------------------------------- weather (P1)
CREATE TABLE weather_stations (
  fid         INTEGER PRIMARY KEY AUTOINCREMENT,
  geom        POINT,                           -- EPSG:25830
  station_id  TEXT NOT NULL UNIQUE,            -- Euskalmet code, e.g. C026
  name        TEXT NOT NULL,
  operator    TEXT NOT NULL DEFAULT 'Euskalmet',
  lon REAL NOT NULL, lat REAL NOT NULL,
  elevation_m REAL,
  temp_sensor_height_m REAL, wind_sensor_height_m REAL,
  native_timezone TEXT NOT NULL,               -- as published (e.g. 'UTC'); obs stored in UTC
  native_frequency_min INTEGER CHECK (native_frequency_min > 0),
  in_pilot    INTEGER NOT NULL CHECK (in_pilot IN (0,1)),
  source_id   TEXT NOT NULL REFERENCES sources(source_id)
);
CREATE TABLE weather_obs (
  station_id   TEXT NOT NULL REFERENCES weather_stations(station_id),
  ts_utc       TEXT NOT NULL CHECK (ts_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
  variable     TEXT NOT NULL CHECK (variable IN ('tair','rh','wind_speed','wind_gust','wind_dir','precip')),
  value        REAL,                           -- RULE R1: NULL when missing/invalid, never 0
  unit         TEXT NOT NULL,
  quality_flag TEXT NOT NULL CHECK (quality_flag IN ('valid','suspect','invalid','missing')),
  source_id    TEXT NOT NULL REFERENCES sources(source_id),
  PRIMARY KEY (station_id, ts_utc, variable),
  CHECK ((variable='tair' AND unit='degC') OR (variable='rh' AND unit='%')
      OR (variable IN ('wind_speed','wind_gust') AND unit='m/s')
      OR (variable='wind_dir' AND unit='deg') OR (variable='precip' AND unit='mm')),
  CHECK ((value IS NULL) = (quality_flag IN ('missing','invalid'))),
  CHECK (variable <> 'rh' OR value IS NULL OR value BETWEEN 0 AND 100),
  CHECK (variable <> 'wind_dir' OR value IS NULL OR value BETWEEN 0 AND 360),
  CHECK (variable NOT IN ('wind_speed','wind_gust','precip') OR value IS NULL OR value >= 0)
) WITHOUT ROWID;
CREATE TABLE weather_quality (                 -- station x year x month x variable
  station_id TEXT NOT NULL REFERENCES weather_stations(station_id),
  year INTEGER NOT NULL, month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  variable TEXT NOT NULL,
  n_expected INTEGER NOT NULL CHECK (n_expected > 0),
  n_present  INTEGER NOT NULL, n_valid INTEGER NOT NULL,
  PRIMARY KEY (station_id, year, month, variable),
  CHECK (n_valid <= n_present AND n_present <= n_expected)
);
CREATE TABLE profile_methods (                 -- RULE R8
  method_version TEXT PRIMARY KEY,             -- e.g. 'ADV-v1'
  index_type     TEXT NOT NULL CHECK (index_type IN ('threshold_rule','official_fwi')),
  definition     TEXT NOT NULL,                -- e.g. 'adverse day: Tmax>=28 AND RHmin<=35 AND gust>=X'
  valid_day_rule TEXT NOT NULL,                -- e.g. '>=20 of 24 hourly values valid for each variable'
  year_from INTEGER NOT NULL, year_to INTEGER NOT NULL,
  source_id TEXT REFERENCES sources(source_id),
  CHECK (year_from <= year_to),
  CHECK (index_type <> 'official_fwi' OR source_id IS NOT NULL)   -- FWI only from a published source
);
CREATE TABLE weather_zones (
  zone_id    TEXT PRIMARY KEY,                 -- e.g. 'Z-C026'
  station_id TEXT NOT NULL REFERENCES weather_stations(station_id),
  description TEXT
);
CREATE TABLE zone_assignment (                 -- RULE R2: one zone per building per method
  building_id    TEXT NOT NULL REFERENCES buildings(building_id),
  method_version TEXT NOT NULL REFERENCES profile_methods(method_version),
  zone_id        TEXT NOT NULL REFERENCES weather_zones(zone_id),
  station_id     TEXT NOT NULL REFERENCES weather_stations(station_id),
  assign_method  TEXT NOT NULL CHECK (assign_method IN ('nearest_station','nearest_same_valley','voronoi','manual')),
  distance_km    REAL CHECK (distance_km >= 0),
  elev_diff_m    REAL,
  PRIMARY KEY (building_id, method_version)
);
CREATE TABLE weather_profile (
  zone_id         TEXT NOT NULL REFERENCES weather_zones(zone_id),
  season_id       TEXT NOT NULL REFERENCES seasons(season_id),
  method_version  TEXT NOT NULL REFERENCES profile_methods(method_version),
  year_from INTEGER NOT NULL, year_to INTEGER NOT NULL,
  n_years_used    INTEGER NOT NULL CHECK (n_years_used >= 0),
  valid_days      INTEGER NOT NULL CHECK (valid_days >= 0),
  adverse_days    INTEGER NOT NULL CHECK (adverse_days >= 0),
  adverse_day_frequency REAL,                  -- RULE R7: historical frequency, NOT fire probability
  interannual_sd  REAL CHECK (interannual_sd IS NULL OR interannual_sd >= 0),
  data_version    TEXT NOT NULL REFERENCES data_versions(data_version),
  PRIMARY KEY (zone_id, season_id, method_version, data_version),
  CHECK (adverse_days <= valid_days),
  CHECK ((valid_days = 0 AND adverse_day_frequency IS NULL)                     -- R1
      OR (valid_days > 0 AND abs(adverse_day_frequency - 1.0*adverse_days/valid_days) < 1e-9))
);
CREATE TABLE weather_profile_year (            -- answers "which years back it"
  zone_id TEXT NOT NULL, season_id TEXT NOT NULL, method_version TEXT NOT NULL, data_version TEXT NOT NULL,
  year INTEGER NOT NULL,
  valid_days INTEGER NOT NULL CHECK (valid_days >= 0),
  adverse_days INTEGER NOT NULL CHECK (adverse_days >= 0 AND adverse_days <= valid_days),
  PRIMARY KEY (zone_id, season_id, method_version, data_version, year),
  FOREIGN KEY (zone_id, season_id, method_version, data_version)
    REFERENCES weather_profile(zone_id, season_id, method_version, data_version)
);
CREATE TABLE weather_adverse_days (            -- answers "which days back it"
  zone_id TEXT NOT NULL REFERENCES weather_zones(zone_id),
  method_version TEXT NOT NULL REFERENCES profile_methods(method_version),
  date_utc TEXT NOT NULL CHECK (date_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  tmax_c REAL, rhmin_pct REAL, wind_max_ms REAL, precip_mm REAL,
  PRIMARY KEY (zone_id, method_version, date_utc)
);

-- ---------------------------------------------------------------- fire stations & candidates (P4)
CREATE TABLE fire_stations (
  fid            INTEGER PRIMARY KEY AUTOINCREMENT,
  geom           POINT,
  station_id     TEXT NOT NULL UNIQUE,         -- 'GIP-ORIA'
  name           TEXT NOT NULL,
  operator       TEXT NOT NULL CHECK (operator IN ('DFG','municipal','Navarra','other')),
  address        TEXT,
  lon REAL NOT NULL, lat REAL NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
  loc_confidence TEXT NOT NULL CHECK (loc_confidence IN ('verified_ortho','address_street','approximate')),
  node_id        INTEGER REFERENCES road_nodes(node_id),
  snap_distance_m REAL,
  routable       INTEGER NOT NULL CHECK (routable IN (0,1)),     -- NAV stations 0 until Navarra roads loaded
  source_id      TEXT NOT NULL REFERENCES sources(source_id),
  include_in_baseline INTEGER NOT NULL DEFAULT 1 CHECK (include_in_baseline IN (0,1)),  -- 0 = not a park (e.g. airport)
  b5m_code       TEXT, municipality TEXT, snap_edge_class TEXT, note TEXT,
  CHECK (routable = 0 OR node_id IS NOT NULL)
);
CREATE TABLE candidates (
  fid            INTEGER PRIMARY KEY AUTOINCREMENT,
  geom           POINT,
  cand_id        TEXT NOT NULL UNIQUE CHECK (cand_id GLOB 'CAND-[0-9][0-9]'),
  name           TEXT NOT NULL,
  municipality_code TEXT REFERENCES municipalities(ine_code),
  lon REAL NOT NULL, lat REAL NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
  reference      TEXT,                          -- e.g. 'restaurant en OSM'
  access_road    TEXT,
  access_dist_m  REAL, node_id INTEGER REFERENCES road_nodes(node_id), snap_distance_m REAL,
  parking_dist_m REAL,                          -- NULL = not found (R1)
  current_time_min_est REAL,                    -- from nearest existing station
  current_time_from TEXT REFERENCES fire_stations(station_id),
  selection_order INTEGER UNIQUE CHECK (selection_order BETWEEN 1 AND 10),
  selection_reason TEXT,
  gain_alone_n    INTEGER, reach_within_threshold_n INTEGER,
  status          TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','validated','discarded')),
  is_valid        INTEGER NOT NULL DEFAULT 1 CHECK (is_valid IN (0,1)),   -- usable in optimizer
  disclaimer      TEXT NOT NULL DEFAULT 'Candidata para estudio de cobertura; no autorizada ni validada',
  source_id       TEXT NOT NULL REFERENCES sources(source_id),
  pool_id         TEXT,                          -- candidate_pool id (P4)
  site_type       TEXT, tier INTEGER CHECK (tier IS NULL OR tier BETWEEN 1 AND 6),
  osm_id          TEXT, area_m2 REAL CHECK (area_m2 IS NULL OR area_m2 > 0),
  current_truck_time_min_est REAL, selection_step TEXT CHECK (selection_step IN ('cluster','spread','manual')),
  CHECK (status <> 'discarded' OR is_valid = 0),
  CHECK (is_valid = 0 OR node_id IS NOT NULL)
);
CREATE TABLE candidate_checks (                -- the "pendiente de comprobar" list per ficha
  cand_id    TEXT NOT NULL REFERENCES candidates(cand_id),
  check_item TEXT NOT NULL CHECK (check_item IN ('heavy_vehicle_space','ownership_permit','truck_access',
                                   'water','traffic_restrictions','ortho_location')),
  status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ok','fail')),
  checked_by TEXT, checked_date TEXT, note TEXT,
  PRIMARY KEY (cand_id, check_item)
);
CREATE TRIGGER trg_cand_validated BEFORE UPDATE OF status ON candidates
WHEN NEW.status = 'validated' AND EXISTS (SELECT 1 FROM candidate_checks c
     WHERE c.cand_id = NEW.cand_id AND c.status <> 'ok')
BEGIN SELECT RAISE(ABORT, 'candidate cannot be validated with pending/failed checks'); END;

CREATE TABLE origins (                         -- union used by travel_times
  origin_id   TEXT PRIMARY KEY,                -- = station_id or cand_id
  origin_type TEXT NOT NULL CHECK (origin_type IN ('station','candidate')),
  CHECK ((origin_type = 'candidate') = (origin_id GLOB 'CAND-*'))
);
CREATE TRIGGER trg_origin_exists BEFORE INSERT ON origins
WHEN NOT EXISTS (SELECT 1 FROM fire_stations WHERE station_id = NEW.origin_id)
 AND NOT EXISTS (SELECT 1 FROM candidates   WHERE cand_id    = NEW.origin_id)
BEGIN SELECT RAISE(ABORT, 'origin must exist in fire_stations or candidates'); END;

-- ---------------------------------------------------------------- travel times (P4) RULE R3
CREATE TABLE travel_times (
  origin_id    TEXT NOT NULL REFERENCES origins(origin_id),
  building_id  TEXT NOT NULL REFERENCES buildings(building_id),
  minutes_est  REAL,                           -- NULL iff unroutable (never 0, never 999)
  distance_km  REAL,
  routable     INTEGER NOT NULL CHECK (routable IN (0,1)),
  unroutable_reason TEXT CHECK (unroutable_reason IN ('no_snap','snap_too_far','snap>150m','disconnected_component','origin_unroutable')),
  data_version TEXT NOT NULL REFERENCES data_versions(data_version),
  profile      TEXT NOT NULL DEFAULT 'light' CHECK (profile IN ('light','truck')),
  PRIMARY KEY (data_version, profile, origin_id, building_id),
  CHECK ((routable = 1 AND minutes_est IS NOT NULL AND minutes_est >= 0 AND unroutable_reason IS NULL)
      OR (routable = 0 AND minutes_est IS NULL AND distance_km IS NULL AND unroutable_reason IS NOT NULL))
) WITHOUT ROWID;
CREATE INDEX ix_tt_building ON travel_times(data_version, profile, building_id);

-- ---------------------------------------------------------------- scenarios & results
CREATE TABLE scenarios (                       -- RULE R6: NO plan_year here
  scenario_id    TEXT PRIMARY KEY,             -- e.g. 'S-JULAUG-12-A-v1.0'
  season_id      TEXT NOT NULL REFERENCES seasons(season_id),
  threshold_min  REAL NOT NULL CHECK (threshold_min > 0 AND threshold_min <= 60),
  k_max          INTEGER NOT NULL CHECK (k_max BETWEEN 0 AND 6),
  strategy       TEXT NOT NULL CHECK (strategy IN ('A','B')),
  weighting      TEXT NOT NULL CHECK (weighting IN ('historical_frequency','none','uniform','uniform_pending_weather')),
  method_version TEXT REFERENCES profile_methods(method_version),   -- NULL only without weather weighting
  speed_factor   REAL NOT NULL DEFAULT 1.0 CHECK (speed_factor > 0 AND speed_factor <= 1),
  data_version   TEXT NOT NULL REFERENCES data_versions(data_version),
  n_candidates   INTEGER NOT NULL,
  n_combinations INTEGER NOT NULL,
  created_utc    TEXT NOT NULL,
  code_version   TEXT NOT NULL,                -- optimizer.py version/hash
  profile        TEXT NOT NULL DEFAULT 'light' CHECK (profile IN ('light','truck')),
  CHECK (weighting <> 'historical_frequency' OR method_version IS NOT NULL)
);
CREATE UNIQUE INDEX ux_scenario_key ON scenarios (season_id, threshold_min, k_max, strategy, weighting,
  coalesce(method_version, ''), speed_factor, profile, data_version);
CREATE TRIGGER trg_kmax_le_valid BEFORE INSERT ON scenarios          -- RULE R5
WHEN NEW.k_max > (SELECT count(*) FROM candidates WHERE is_valid = 1)
BEGIN SELECT RAISE(ABORT, 'k_max exceeds number of valid candidates'); END;

CREATE TABLE results (                         -- best combination per k
  scenario_id    TEXT NOT NULL REFERENCES scenarios(scenario_id),
  k              INTEGER NOT NULL CHECK (k BETWEEN 0 AND 6),
  selection      TEXT NOT NULL,                -- sorted 'CAND-02|CAND-05', '' for k=0
  n_buildings    INTEGER NOT NULL CHECK (n_buildings > 0),
  n_covered      INTEGER NOT NULL CHECK (n_covered >= 0),
  pct_covered    REAL NOT NULL,
  weighted_covered REAL,                       -- RULE R7: sum of historical weights, not people
  weighted_total   REAL,
  weighted_share   REAL CHECK (weighted_share IS NULL OR weighted_share BETWEEN 0 AND 1),
  n_weight_missing INTEGER NOT NULL CHECK (n_weight_missing >= 0),
  worst_time_min_est REAL,                     -- over routable buildings
  n_unroutable   INTEGER NOT NULL CHECK (n_unroutable >= 0),
  gain_covered_vs_k0  INTEGER NOT NULL CHECK (gain_covered_vs_k0 >= 0),
  gain_weighted_vs_k0 REAL,
  gain_covered_vs_prev INTEGER,                -- benefit-per-reten chart (can be <0 if not nested)
  nested_with_prev INTEGER CHECK (nested_with_prev IN (0,1)),
  ties           INTEGER NOT NULL DEFAULT 1,   -- n combos with identical objective
  PRIMARY KEY (scenario_id, k),
  CHECK (n_covered + n_unroutable <= n_buildings),
  CHECK (abs(pct_covered - 100.0*n_covered/n_buildings) < 1e-6)
);
CREATE TABLE result_selection (
  scenario_id TEXT NOT NULL, k INTEGER NOT NULL,
  cand_id     TEXT NOT NULL REFERENCES candidates(cand_id),
  PRIMARY KEY (scenario_id, k, cand_id),
  FOREIGN KEY (scenario_id, k) REFERENCES results(scenario_id, k)
);
CREATE TABLE result_building (                 -- RULE R2: one row per building per k
  scenario_id TEXT NOT NULL, k INTEGER NOT NULL,
  building_id TEXT NOT NULL REFERENCES buildings(building_id),
  best_origin_id TEXT REFERENCES origins(origin_id),
  best_minutes_est REAL,
  routable INTEGER NOT NULL CHECK (routable IN (0,1)),
  covered  INTEGER NOT NULL CHECK (covered IN (0,1)),
  PRIMARY KEY (scenario_id, k, building_id),
  FOREIGN KEY (scenario_id, k) REFERENCES results(scenario_id, k),
  CHECK ((routable = 0 AND best_minutes_est IS NULL AND best_origin_id IS NULL AND covered = 0)
      OR (routable = 1 AND best_minutes_est IS NOT NULL AND best_origin_id IS NOT NULL))
) WITHOUT ROWID;
CREATE TABLE combo_metrics (                   -- all 848 combinations (transparency: "why not X?")
  scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
  selection   TEXT NOT NULL, k INTEGER NOT NULL,
  n_covered INTEGER NOT NULL, weighted_covered REAL, worst_time_min_est REAL,
  n_unroutable INTEGER NOT NULL, rank_in_k INTEGER NOT NULL,
  PRIMARY KEY (scenario_id, selection)
);
CREATE TABLE plans (                           -- RULE R6: plan_year is a label only
  plan_id     TEXT PRIMARY KEY,                -- 'PLAN-2027-JULAUG'
  plan_year   INTEGER NOT NULL CHECK (plan_year >= 2026),
  season_id   TEXT NOT NULL REFERENCES seasons(season_id),
  scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
  title       TEXT NOT NULL                    -- 'Plan preventivo · Julio–agosto 2027'
);                                             -- season consistency: view qa_plan_season

-- ---------------------------------------------------------------- quality
CREATE TABLE quality_reports (
  report_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  data_version TEXT NOT NULL REFERENCES data_versions(data_version),
  dataset      TEXT NOT NULL,                  -- table name
  check_name   TEXT NOT NULL,                  -- 'row_count','crs','duplicates','geom_valid','nulls:<col>',...
  scope        TEXT,                           -- e.g. municipality code
  value        REAL, expected TEXT,
  status       TEXT NOT NULL CHECK (status IN ('pass','warn','fail')),
  run_utc      TEXT NOT NULL, run_by TEXT NOT NULL, note TEXT
);

-- ---------------------------------------------------------------- views for tools
CREATE VIEW v_scope_buildings AS               -- the population every metric is computed on
SELECT b.* FROM buildings b JOIN municipalities m ON m.ine_code = b.municipality_code
WHERE m.in_pilot = 1 AND b.is_residential = 1 AND b.near_vegetation = 1;

CREATE VIEW v_building_weight AS               -- NULL weight = no valid weather (R1), not 0
SELECT za.building_id, wp.season_id, za.method_version, wp.data_version,
       za.zone_id, wp.adverse_day_frequency AS weight
FROM zone_assignment za
LEFT JOIN weather_profile wp ON wp.zone_id = za.zone_id AND wp.method_version = za.method_version;

-- ---------------------------------------------------------------- QA views (must be empty)
CREATE VIEW qa_scope_without_zone AS
SELECT s.building_id FROM v_scope_buildings s
WHERE NOT EXISTS (SELECT 1 FROM zone_assignment z WHERE z.building_id = s.building_id);
CREATE VIEW qa_missing_travel_pairs AS          -- R3: every (valid origin, scope building, profile) has a row
SELECT dp.data_version, dp.profile, o.origin_id, s.building_id
FROM (SELECT DISTINCT data_version, profile FROM travel_times) dp CROSS JOIN origins o CROSS JOIN v_scope_buildings s
LEFT JOIN candidates c ON c.cand_id = o.origin_id
WHERE (o.origin_type = 'station' OR c.is_valid = 1)
  AND NOT EXISTS (SELECT 1 FROM travel_times t WHERE t.data_version = dp.data_version AND t.profile = dp.profile
                  AND t.origin_id = o.origin_id AND t.building_id = s.building_id);
CREATE VIEW qa_result_building_count AS         -- R2/R3: n_buildings = rows = scope size
SELECT r.scenario_id, r.k, r.n_buildings,
       (SELECT count(*) FROM result_building rb WHERE rb.scenario_id = r.scenario_id AND rb.k = r.k) AS n_rows,
       (SELECT count(*) FROM v_scope_buildings) AS n_scope
FROM results r
WHERE r.n_buildings <> (SELECT count(*) FROM result_building rb WHERE rb.scenario_id = r.scenario_id AND rb.k = r.k)
   OR r.n_buildings <> (SELECT count(*) FROM v_scope_buildings);
CREATE VIEW qa_monotone_results AS              -- best objective non-decreasing in k
SELECT a.scenario_id, a.k FROM results a JOIN results b
  ON a.scenario_id = b.scenario_id AND b.k = a.k - 1
JOIN scenarios s ON s.scenario_id = a.scenario_id
WHERE (s.strategy = 'A' AND coalesce(a.weighted_covered, a.n_covered) < coalesce(b.weighted_covered, b.n_covered) - 1e-9)
   OR (s.strategy = 'B' AND (a.n_unroutable > b.n_unroutable
        OR (a.n_unroutable = b.n_unroutable AND a.worst_time_min_est > b.worst_time_min_est + 1e-9)));
CREATE VIEW qa_plan_season AS
SELECT p.plan_id FROM plans p JOIN scenarios s ON s.scenario_id = p.scenario_id
WHERE p.season_id <> s.season_id;
CREATE VIEW qa_source_not_in_version AS         -- R4: no row from a source outside its version
SELECT 'buildings' AS tbl, dv.data_version, b.source_id FROM buildings b CROSS JOIN data_versions dv
WHERE dv.frozen = 1 AND NOT EXISTS (SELECT 1 FROM data_version_sources x
      WHERE x.data_version = dv.data_version AND x.source_id = b.source_id)
UNION ALL
SELECT 'weather_obs', dv.data_version, w.source_id FROM (SELECT DISTINCT source_id FROM weather_obs) w
CROSS JOIN data_versions dv WHERE dv.frozen = 1 AND NOT EXISTS (SELECT 1 FROM data_version_sources x
      WHERE x.data_version = dv.data_version AND x.source_id = w.source_id);
CREATE VIEW qa_duplicate_building_geom AS       -- same rep point twice = probable duplicate
SELECT x, y, count(*) AS n FROM buildings GROUP BY round(x,1), round(y,1) HAVING n > 1;
CREATE VIEW qa_analysis_flag AS                 -- stored analysis flag must equal the scope rule
SELECT b.building_id FROM buildings b JOIN municipalities m ON m.ine_code = b.municipality_code
WHERE b.in_analysis_set IS NOT NULL
  AND b.in_analysis_set <> (m.in_pilot = 1 AND b.is_residential = 1 AND coalesce(b.near_vegetation, 0) = 1);
CREATE VIEW qa_uniform_weight AS                -- uniform weights: weighted coverage must equal the count
SELECT r.scenario_id, r.k FROM results r JOIN scenarios s ON s.scenario_id = r.scenario_id
WHERE s.weighting IN ('uniform','uniform_pending_weather')
  AND (r.weighted_covered IS NULL OR abs(r.weighted_covered - r.n_covered) > 1e-9
       OR abs(r.weighted_total - r.n_buildings) > 1e-9 OR r.n_weight_missing <> 0);
CREATE VIEW qa_unroutable_without_reason AS     -- R3
SELECT 'buildings' AS tbl, building_id AS id FROM buildings WHERE routable = 0 AND unroutable_reason IS NULL
UNION ALL
SELECT 'travel_times', origin_id || '>' || building_id FROM travel_times WHERE routable = 0 AND unroutable_reason IS NULL;
CREATE VIEW qa_candidate_spacing AS             -- valid candidates >= 3 km apart and >= 2 km from parks
SELECT a.cand_id AS a, b.cand_id AS b, round(sqrt((a.x-b.x)*(a.x-b.x)+(a.y-b.y)*(a.y-b.y))) AS dist_m
FROM candidates a JOIN candidates b ON a.cand_id < b.cand_id
WHERE a.is_valid = 1 AND b.is_valid = 1
  AND (a.x-b.x)*(a.x-b.x)+(a.y-b.y)*(a.y-b.y) < (SELECT value*value FROM parameters WHERE key='cand_min_separation_m')
UNION ALL
SELECT c.cand_id, f.station_id, round(sqrt((c.x-f.x)*(c.x-f.x)+(c.y-f.y)*(c.y-f.y)))
FROM candidates c JOIN fire_stations f
WHERE c.is_valid = 1
  AND (c.x-f.x)*(c.x-f.x)+(c.y-f.y)*(c.y-f.y) < (SELECT value*value FROM parameters WHERE key='cand_min_dist_park_m');

-- ---------------------------------------------------------------- register feature tables
INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES
 ('municipalities','features','municipalities','INE code, name, pilot flag',25830),
 ('boundary','features','boundary','Tolosaldea union of 28 municipalities',25830),
 ('vegetation','features','vegetation','Mapa Forestal polygons, original + grouped class',25830),
 ('road_nodes','features','road_nodes','Routing graph nodes',25830),
 ('road_edges','features','road_edges','Routing graph edges with speed_used and speed_source',25830),
 ('buildings','features','buildings','Building representative points with links',25830),
 ('weather_stations','features','weather_stations','Euskalmet stations',25830),
 ('fire_stations','features','fire_stations','Existing fire stations',25830),
 ('candidates','features','candidates','10 candidate reten sites (study only)',25830);
INSERT INTO gpkg_geometry_columns VALUES
 ('municipalities','geom','MULTIPOLYGON',25830,0,0), ('boundary','geom','MULTIPOLYGON',25830,0,0),
 ('vegetation','geom','MULTIPOLYGON',25830,0,0),     ('road_nodes','geom','POINT',25830,0,0),
 ('road_edges','geom','LINESTRING',25830,0,0),       ('buildings','geom','POINT',25830,0,0),
 ('weather_stations','geom','POINT',25830,0,0),      ('fire_stations','geom','POINT',25830,0,0),
 ('candidates','geom','POINT',25830,0,0);
INSERT INTO gpkg_contents (table_name, data_type, identifier, description) VALUES
 ('sources','attributes','sources','Source register'), ('data_versions','attributes','data_versions',''),
 ('data_version_sources','attributes','data_version_sources',''), ('parameters','attributes','parameters',''),
 ('seasons','attributes','seasons',''), ('vegetation_classes','attributes','vegetation_classes',''),
 ('weather_obs','attributes','weather_obs','UTC observations'), ('weather_quality','attributes','weather_quality',''),
 ('profile_methods','attributes','profile_methods',''), ('weather_zones','attributes','weather_zones',''),
 ('zone_assignment','attributes','zone_assignment',''), ('weather_profile','attributes','weather_profile',''),
 ('weather_profile_year','attributes','weather_profile_year',''), ('weather_adverse_days','attributes','weather_adverse_days',''),
 ('candidate_checks','attributes','candidate_checks',''), ('origins','attributes','origins',''),
 ('travel_times','attributes','travel_times',''), ('scenarios','attributes','scenarios',''),
 ('results','attributes','results',''), ('result_selection','attributes','result_selection',''),
 ('result_building','attributes','result_building',''), ('combo_metrics','attributes','combo_metrics',''),
 ('plans','attributes','plans',''), ('quality_reports','attributes','quality_reports','');
