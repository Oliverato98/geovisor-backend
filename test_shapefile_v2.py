"""Diagnóstico v2 - probar con if_exists=replace y geoalchemy2 importado"""
import zipfile
import tempfile
import traceback
from pathlib import Path
import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text
from geoalchemy2 import Geometry  # IMPORTANTE: importar antes de usar to_postgis
import warnings
warnings.filterwarnings("ignore")

DB_URL = "postgresql://geovisor_user:geovisor_pass@db:5432/geovisor"

with tempfile.TemporaryDirectory() as tmpdir:
    with zipfile.ZipFile("/tmp/proyecto.zip", "r") as z:
        z.extractall(tmpdir)

    shp = list(Path(tmpdir).rglob("Bocatomas_Acueducto_CRQ.shp"))[0]
    print(f"Procesando: {shp.name}")

    gdf = gpd.read_file(str(shp))
    print(f"  Filas: {len(gdf)}, CRS: {gdf.crs}")

    if gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    # Convertir datetime
    for col in gdf.columns:
        if col != gdf.geometry.name and pd.api.types.is_datetime64_any_dtype(gdf[col]):
            gdf[col] = gdf[col].astype(str)

    geom_type = gdf.geometry.geom_type.iloc[0].upper()
    print(f"  Tipo geometría: {geom_type}")

    engine = create_engine(DB_URL)
    table_name = "test_v2_bocatomas"

    # PRUEBA 1: Con dtype y replace
    print("\n--- PRUEBA: replace con dtype Geometry ---")
    try:
        gdf.to_postgis(
            name=table_name,
            con=engine,
            if_exists="replace",
            index=False,
            schema="public",
            dtype={"geometry": Geometry(geometry_type=geom_type, srid=4326)},
        )
        print("  ✓ ÉXITO con replace+dtype")

        # Verificar
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = result.scalar()
            print(f"  ✓ Filas en tabla: {count}")
    except Exception as e:
        print(f"  ✗ ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()

    engine.dispose()
