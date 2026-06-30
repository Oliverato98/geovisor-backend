# FASES 5 Y 6 — Integración QGIS + Despliegue Completo
## Geovisor Calarcá, Quindío

---

## FASE 5 — Integración con QGIS

### ¿Qué hace QGIS Server?

QGIS Server convierte cualquier proyecto `.qgz` en un servicio web estándar OGC:
- **WMS** (Web Map Service): imágenes raster del mapa
- **WFS** (Web Feature Service): datos vectoriales descargables
- **WMTS** (Web Map Tile Service): tiles en caché

El flujo completo es:

```
QGIS Desktop (diseñas el mapa) 
    → guarda proyecto .qgz en el servidor
    → QGIS Server lo publica automáticamente
    → tu geovisor React consume el WMS/WFS
    → el mapa refleja exactamente la simbología de QGIS
```

---

### Paso 1 — Instalar QGIS Server

```bash
# Ubuntu 22.04
sudo apt-get install -y qgis-server python3-qgis

# Verificar instalación
/usr/lib/qgis/qgis_mapserv.fcgi --version

# Directorio de proyectos
sudo mkdir -p /srv/qgis/projects
sudo chmod 777 /srv/qgis/projects
```

### Paso 2 — Configurar Nginx como proxy

```nginx
# /etc/nginx/sites-available/qgis-server
server {
    listen 80;
    server_name gis.calarca.gov.co;

    location /qgis/ {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME /usr/lib/qgis/qgis_mapserv.fcgi;
        fastcgi_param QGIS_SERVER_LOG_LEVEL 0;
        fastcgi_param QGIS_PROJECT_FILE /srv/qgis/projects/$arg_MAP;
        fastcgi_pass unix:/var/run/qgis-server.sock;
    }
}
```

### Paso 3 — Publicar proyecto desde QGIS Desktop

1. Abre QGIS Desktop en tu computador
2. Carga y estiliza tus capas (predios, vías, ríos, etc.)
3. Ve a **Proyecto → Propiedades → Servidor QGIS**
4. Activa *"Propiedades del servicio WMS"*
5. Guarda el proyecto como `calarca.qgz`
6. Copia el archivo al servidor: `scp calarca.qgz usuario@servidor:/srv/qgis/projects/`
7. ¡Listo! El servicio está disponible en `http://servidor/qgis/?MAP=calarca.qgz`

### Paso 4 — Consumir WMS en el geovisor (React + MapLibre)

```typescript
// services/wmsService.ts

export const QGIS_SERVER_URL = 'http://tu-servidor/qgis/?MAP=calarca.qgz';

// Agregar capa WMS al mapa MapLibre
export function addWMSLayer(map: maplibregl.Map, layerName: string) {
  const sourceId = `wms-${layerName}`;
  const layerId = `wms-lyr-${layerName}`;

  map.addSource(sourceId, {
    type: 'raster',
    tiles: [
      `${QGIS_SERVER_URL}&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap` +
      `&LAYERS=${layerName}&STYLES=&FORMAT=image/png&TRANSPARENT=true` +
      `&WIDTH=256&HEIGHT=256&CRS=EPSG:3857` +
      `&BBOX={bbox-epsg-3857}`
    ],
    tileSize: 256,
    attribution: 'Municipio de Calarcá',
  });

  map.addLayer({
    id: layerId,
    type: 'raster',
    source: sourceId,
    paint: { 'raster-opacity': 0.8 },
  });
}

// Obtener lista de capas disponibles
export async function getWMSCapabilities(): Promise<string[]> {
  const url = `${QGIS_SERVER_URL}&SERVICE=WMS&REQUEST=GetCapabilities`;
  const response = await fetch(url);
  const text = await response.text();
  const parser = new DOMParser();
  const xml = parser.parseFromString(text, 'text/xml');
  const layers = xml.querySelectorAll('Layer[queryable="1"] > Name');
  return Array.from(layers).map((l) => l.textContent ?? '');
}

// Consulta WFS para obtener features como GeoJSON
export async function getWFSFeatures(layerName: string, bbox?: string): Promise<any> {
  let url = `${QGIS_SERVER_URL}&SERVICE=WFS&VERSION=1.1.0&REQUEST=GetFeature` +
    `&TYPENAME=${layerName}&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326`;
  if (bbox) url += `&BBOX=${bbox}`;
  const response = await fetch(url);
  return response.json();
}

// GetFeatureInfo — información al hacer click en el mapa
export async function getFeatureInfo(
  layerName: string,
  lngLat: { lng: number; lat: number },
  map: maplibregl.Map
): Promise<any> {
  const point = map.project(lngLat);
  const bounds = map.getBounds();
  const size = map.getCanvas();

  const url = `${QGIS_SERVER_URL}&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo` +
    `&LAYERS=${layerName}&QUERY_LAYERS=${layerName}` +
    `&INFO_FORMAT=application/json` +
    `&I=${Math.round(point.x)}&J=${Math.round(point.y)}` +
    `&WIDTH=${size.width}&HEIGHT=${size.height}` +
    `&CRS=EPSG:4326` +
    `&BBOX=${bounds.getSouth()},${bounds.getWest()},${bounds.getNorth()},${bounds.getEast()}`;

  const response = await fetch(url);
  return response.json();
}
```

### Paso 5 — Sincronización automática con PostGIS desde QGIS

```python
# Script Python para ejecutar en QGIS o como cron job
# Mantiene PostGIS sincronizado con capas editadas en QGIS

import psycopg2
from qgis.core import QgsVectorLayer, QgsProject

POSTGIS_CONN = "postgresql://geovisor_user:geovisor_pass@localhost:5432/geovisor"

def sync_layer_to_postgis(qgis_layer_name: str, pg_table: str):
    layer = QgsProject.instance().mapLayersByName(qgis_layer_name)[0]

    # Exportar a GeoJSON temporal
    import geopandas as gpd
    tmp_path = f'/tmp/{pg_table}.geojson'
    QgsVectorFileWriter.writeAsVectorFormat(
        layer, tmp_path, 'utf-8',
        layer.crs(), 'GeoJSON'
    )

    # Cargar y subir a PostGIS
    gdf = gpd.read_file(tmp_path)
    if gdf.crs != 'EPSG:4326':
        gdf = gdf.to_crs('EPSG:4326')
    gdf.to_postgis(pg_table, POSTGIS_CONN, if_exists='replace', index=False)
    print(f"Capa '{qgis_layer_name}' sincronizada → tabla '{pg_table}'")
```

---

## FASE 6 — Despliegue completo

### Arquitectura de producción

```
Internet
    │
    ▼
Cloudflare (CDN + SSL)
    │
    ├─ geovisor.calarca.gov.co ──── Vercel (Frontend React)
    │
    └─ api.calarca.gov.co ────────── VPS / Servidor propio
                                        │
                                        ├── Nginx (proxy reverso)
                                        ├── FastAPI (puerto 8000)
                                        ├── PostgreSQL + PostGIS (puerto 5432)
                                        ├── Redis (puerto 6379)
                                        ├── Martin tiles (puerto 3000)
                                        └── QGIS Server (puerto 8080)
```

---

### Despliegue del backend en servidor VPS

#### Opción A — Docker Compose (recomendado)

```bash
# 1. En el servidor, instalar Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# 2. Clonar el repositorio
git clone https://github.com/municipio-calarca/geovisor-backend.git
cd geovisor-backend

# 3. Configurar variables de entorno de producción
cp .env.example .env
nano .env
# → Cambiar DATABASE_URL con datos reales
# → Cambiar SECRET_KEY por una clave de 64 chars aleatoria:
#   python3 -c "import secrets; print(secrets.token_hex(32))"

# 4. Levantar todo
docker compose -f docker-compose.prod.yml up -d

# 5. Verificar
docker compose ps
curl http://localhost:8000/health
```

#### docker-compose.prod.yml (producción)

```yaml
version: "3.9"
services:
  db:
    image: postgis/postgis:15-3.3
    restart: always
    environment:
      POSTGRES_DB: geovisor
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASS}
    volumes:
      - pgdata:/var/lib/postgresql/data
    # No exponer puerto 5432 al exterior en producción

  redis:
    image: redis:7-alpine
    restart: always
    command: redis-server --requirepass ${REDIS_PASS}

  api:
    build: .
    restart: always
    command: uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
    volumes:
      - ./uploads:/app/uploads
    env_file: .env
    depends_on: [db, redis]

  martin:
    image: maplibre/martin:latest
    restart: always
    environment:
      DATABASE_URL: postgresql://${DB_USER}:${DB_PASS}@db:5432/geovisor
    depends_on: [db]

volumes:
  pgdata:
```

---

### Configuración Nginx para producción

```nginx
# /etc/nginx/sites-available/geovisor
server {
    listen 80;
    server_name api.calarca.gov.co;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.calarca.gov.co;

    ssl_certificate     /etc/letsencrypt/live/api.calarca.gov.co/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.calarca.gov.co/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    # Tamaño máximo para upload de shapefiles
    client_max_body_size 250M;

    # API FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }

    # Martin tile server
    location /tiles/ {
        proxy_pass http://127.0.0.1:3000/;
        proxy_cache_valid 200 10m;
        add_header Cache-Control "public, max-age=600";
        add_header Access-Control-Allow-Origin "*";
    }
}
```

```bash
# SSL con Let's Encrypt (gratuito)
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d api.calarca.gov.co
```

---

### Despliegue del Frontend en Vercel

```bash
# 1. Instalar Vercel CLI
npm i -g vercel

# 2. En la carpeta del frontend
cd geovisor-frontend

# 3. Configurar variables de entorno en Vercel (dashboard o CLI)
vercel env add VITE_API_URL production
# → https://api.calarca.gov.co/api/v1

vercel env add VITE_MARTIN_URL production
# → https://api.calarca.gov.co/tiles

vercel env add VITE_GOOGLE_MAPS_KEY production
# → Tu API Key de Google Maps

# 4. Desplegar
vercel --prod

# La URL será: https://geovisor-calarca.vercel.app
# Puedes conectar un dominio propio: geovisor.calarca.gov.co
```

---

### Variables de entorno de producción (.env)

```bash
# Base de datos
DATABASE_URL=postgresql+asyncpg://geovisor_user:PASS_SEGURO@localhost:5432/geovisor
SYNC_DATABASE_URL=postgresql://geovisor_user:PASS_SEGURO@localhost:5432/geovisor
DB_USER=geovisor_user
DB_PASS=PASS_SEGURO

# JWT — CAMBIAR OBLIGATORIAMENTE
SECRET_KEY=genera-esto-con-python3-secrets-token-hex-32
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Redis
REDIS_URL=redis://:REDIS_PASS@localhost:6379
REDIS_PASS=REDIS_PASS_SEGURO

# Uploads
UPLOAD_DIR=/app/uploads
MAX_FILE_SIZE_MB=200

# CORS — solo el dominio del frontend
ALLOWED_ORIGINS=https://geovisor.calarca.gov.co
```

---

### Backups automáticos de PostGIS

```bash
#!/bin/bash
# /etc/cron.daily/backup-geovisor

DATE=$(date +%Y%m%d_%H%M)
BACKUP_DIR=/backups/geovisor
mkdir -p $BACKUP_DIR

# Backup completo de la base de datos
docker exec geovisor_db pg_dump \
  -U geovisor_user \
  -F c \
  geovisor > $BACKUP_DIR/geovisor_$DATE.dump

# Solo las últimas 30 copias
ls -t $BACKUP_DIR/*.dump | tail -n +31 | xargs rm -f

echo "Backup completado: geovisor_$DATE.dump"
```

```bash
# Hacer ejecutable y activar
chmod +x /etc/cron.daily/backup-geovisor
```

---

### Lista de verificación de seguridad

```
Seguridad de base de datos:
✓ PostgreSQL no expuesto a Internet (solo localhost)
✓ Usuario de BD con solo los permisos necesarios
✓ Contraseña fuerte (mínimo 24 chars, generada aleatoriamente)
✓ Backups diarios automatizados

Seguridad de la API:
✓ HTTPS obligatorio (redirigir HTTP → HTTPS)
✓ SECRET_KEY de 64+ caracteres generada aleatoriamente
✓ CORS configurado SOLO para el dominio del frontend
✓ Rate limiting en Nginx (limit_req_zone)
✓ Validación de tipos de archivo en uploads
✓ Límite de tamaño de archivo (200MB)
✓ Tokens JWT con expiración (8 horas)

Seguridad del servidor:
✓ UFW firewall: solo puertos 80, 443, 22 abiertos
✓ SSH con clave pública (deshabilitar password login)
✓ Actualizaciones automáticas de seguridad (unattended-upgrades)
✓ fail2ban para proteger SSH
✓ Logs centralizados

Monitoreo:
✓ Health check endpoint: /health
✓ Logs de FastAPI en /var/log/geovisor/
✓ Alertas de espacio en disco (uploads y PostgreSQL crecen)
```

---

### Comandos de mantenimiento útiles

```bash
# Ver logs en tiempo real
docker compose logs -f api

# Reiniciar solo la API
docker compose restart api

# Restaurar backup de PostGIS
docker exec -i geovisor_db pg_restore \
  -U geovisor_user -d geovisor \
  < /backups/geovisor/geovisor_20240101.dump

# Ejecutar migraciones manualmente
docker exec geovisor_api alembic upgrade head

# Ver tamaño de tablas en PostGIS
docker exec geovisor_db psql -U geovisor_user -d geovisor -c "
  SELECT table_name, pg_size_pretty(pg_total_relation_size(quote_ident(table_name)))
  FROM information_schema.tables
  WHERE table_schema = 'public'
  ORDER BY pg_total_relation_size(quote_ident(table_name)) DESC;
"

# Crear índices GIST en todas las tablas de capas
docker exec geovisor_db psql -U geovisor_user -d geovisor -c "
  SELECT 'CREATE INDEX IF NOT EXISTS idx_'||table_name||'_geom ON '||table_name||' USING GIST(geometry);'
  FROM information_schema.tables
  WHERE table_name LIKE 'layer_%' AND table_schema = 'public';
"
```
