# Geovisor Calarcá — Backend API

Backend del geovisor web del Municipio de Calarcá, Quindío, Colombia.
Construido con FastAPI + PostgreSQL + PostGIS.

---

## Requisitos

- Docker + Docker Compose
- Python 3.11+ (si corre sin Docker)

---

## Inicio rápido con Docker

```bash
# 1. Clonar y entrar al directorio
cd geovisor-backend

# 2. Copiar variables de entorno
cp .env.example .env
# Editar .env con tu SECRET_KEY segura

# 3. Levantar todos los servicios
docker compose up -d

# 4. Verificar que todo esté corriendo
docker compose ps

# 5. La API estará disponible en:
#    http://localhost:8000
#    Documentación: http://localhost:8000/docs
#    Martin tile server: http://localhost:3000
```

---

## Endpoints principales

### Autenticación
```
POST /api/v1/auth/register    — Registrar usuario
POST /api/v1/auth/login       — Login (retorna JWT)
GET  /api/v1/auth/me          — Perfil del usuario actual
```

### Capas
```
GET    /api/v1/layers/                        — Listar capas
GET    /api/v1/layers/{id}                    — Ver capa
PATCH  /api/v1/layers/{id}                    — Editar (ADMIN)
DELETE /api/v1/layers/{id}                    — Eliminar (ADMIN)
GET    /api/v1/layers/{id}/export/geojson     — Exportar GeoJSON
GET    /api/v1/layers/{id}/tile-url           — URL de tiles para MapLibre
```

### Subida de archivos (ADMIN)
```
POST /api/v1/upload/shapefile   — Subir ZIP con shapefile
POST /api/v1/upload/geojson     — Subir GeoJSON
POST /api/v1/upload/kml         — Subir KML o KMZ
```

### Análisis espacial (ADMIN)
```
POST /api/v1/analysis/buffer           — Buffer por distancia
POST /api/v1/analysis/intersection     — Intersección entre capas
POST /api/v1/analysis/dissolve         — Disolver por atributo
GET  /api/v1/analysis/spatial-query/{id}?lat=&lon=&radius_m=  — Query por punto
```

---

## Ejemplos de uso con curl

### Login
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@calarca.gov.co", "password": "mipassword"}'
```

### Subir shapefile
```bash
curl -X POST http://localhost:8000/api/v1/upload/shapefile \
  -H "Authorization: Bearer TU_TOKEN" \
  -F "file=@predios_calarca.zip" \
  -F "name=Predios Calarcá 2024" \
  -F "description=Predios catastrales del municipio"
```

### Buffer de 500 metros
```bash
curl -X POST http://localhost:8000/api/v1/analysis/buffer \
  -H "Authorization: Bearer TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"layer_id": 1, "distance_meters": 500}'
```

### URL de tiles para MapLibre (frontend)
```javascript
// En el frontend React:
const tileInfo = await fetch('/api/v1/layers/1/tile-url');
const { tile_url, style } = await tileInfo.json();

map.addSource('predios', {
  type: 'vector',
  tiles: [tile_url],
  minzoom: 10,
  maxzoom: 18
});
```

---

## Roles de usuario

| Rol | Permisos |
|-----|----------|
| `visitante` | Ver capas públicas, exportar GeoJSON, consulta por punto |
| `admin` | Todo + subir, editar, eliminar capas, ejecutar análisis |

---

## Estructura de archivos

```
geovisor-backend/
├── app/
│   ├── core/
│   │   ├── config.py       # Configuración desde .env
│   │   ├── database.py     # Conexión async a PostgreSQL+PostGIS
│   │   └── security.py     # JWT, hash, dependencias de auth
│   ├── models/
│   │   ├── user.py         # Modelo SQLAlchemy Usuario
│   │   └── layer.py        # Modelo SQLAlchemy Capa geoespacial
│   ├── schemas/
│   │   └── schemas.py      # Modelos Pydantic (validación)
│   ├── services/
│   │   └── geo_service.py  # GeoPandas, PostGIS, análisis espacial
│   ├── routers/
│   │   ├── auth.py         # Login, registro, /me
│   │   ├── layers.py       # CRUD de capas
│   │   ├── upload.py       # Subida de archivos
│   │   └── analysis.py     # Buffer, intersección, dissolve
│   └── main.py             # FastAPI app, middlewares, routers
├── uploads/                # Archivos subidos (shapefile originals)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```
