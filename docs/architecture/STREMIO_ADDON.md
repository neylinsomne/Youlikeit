# Contrato: addon de Stremio como fuente del estudio

El estudio usa un addon de Stremio como **un proveedor más** (`stremio`), al lado de
Internet Archive (`archive_org`) y la biblioteca local (`local`). Código del lado del
estudio: [`src/apps/media/stremio_addon.py`](../../src/apps/media/stremio_addon.py).
Addon de referencia que ya cumple este contrato:
[`scripts/testing/mock_stremio_addon.py`](../../scripts/testing/mock_stremio_addon.py).

## Cómo se conecta

No se conecta con un ID: se conecta con la **URL del manifest**.

```env
STREMIO_ADDON_URL=https://mi-addon.example/manifest.json   # también acepta stremio://
STREMIO_OWN_HOSTS=192.168.1.20,127.0.0.1                    # hosts de TU biblioteca, sin puerto
```

Los IDs aparecen después, en cada búsqueda:

```
Biblioteca → "Buscar películas" (título, año)
  1. GET {base}/manifest.json                                  ¿qué catálogos y tipos sirve?
  2. GET {base}/catalog/movie/{catalogId}/search={título}.json  → metas [{id, name, releaseInfo}]
     (si el addon no tiene catálogo con búsqueda pero acepta IDs tt…, se busca el ID en Cinemeta)
  3. filtro por año (±1)
  4. GET {base}/stream/movie/{id}.json                          → streams [{url, …}]
  5. cada stream se clasifica (reglas abajo) → candidatos → "Registrar" → indexar como siempre
```

Lo que se registra de un stream propio es `provider=stremio`, `external_id=movie/{id}`.
Al registrar, el estudio vuelve a pedir los streams de ese `id`.

## Lo que el addon debe exponer

| Ruta | Obligatoria | Respuesta |
|---|---|---|
| `GET /manifest.json` | Sí | `id`, `version`, `name`, `resources` con `"stream"`, `types` con `"movie"`, `idPrefixes`, `catalogs`. |
| `GET /catalog/movie/{catalogId}/search={q}.json` | Sí, salvo que el addon solo use IDs `tt…` | `{"metas": [{"id", "type": "movie", "name", "releaseInfo": "1972"}]}`. El catálogo declara `"extra": [{"name": "search"}]`. |
| `GET /stream/movie/{id}.json` | Sí | `{"streams": [{"url": "https://…", "name", "title", "behaviorHints": {"filename", "videoSize"}}]}`. |
| `GET /meta/movie/{id}.json` | Solo para la app de Stremio | El estudio no la usa. |

La búsqueda (`{q}`) llega con URL-encoding (`search=Night%20of%20the%20Living%20Dead`).
Con IDs propios (`"idPrefixes": ["ylk:"]`), el catálogo con búsqueda es obligatorio.

## Qué streams usa el estudio

Las reglas son las mismas para cualquier addon, propio o ajeno, y no se pueden configurar:

| Stream | Qué hace el estudio |
|---|---|
| `url` a `archive.org` (`/download/{id}/…` o `…/items/{id}/…`) | Re-verifica los derechos con la metadata de Internet Archive. El candidato sale como `archive_org`, no como `stremio`, y se elige ahí el mejor archivo maestro y el proxy. |
| `url` a un host de `STREMIO_OWN_HOSTS` | Lo marca `owned`, igual que un archivo de `E:`. |
| `url` a cualquier otro host | Lo marca `unknown`. Se ve con "Ver todos los derechos", pero no se puede registrar. |
| `infoHash`, `magnet:`, `ytId`, `externalUrl` | Lo descarta. |
| `url` a un servicio de debrid (Real-Debrid, AllDebrid, Premiumize, TorBox…) | Lo descarta siempre, aunque esté en `STREMIO_OWN_HOSTS`. |

Por eso el addon solo sirve para **dos cosas**:

1. Encontrar películas de dominio público en archive.org.
2. Servir tus propios archivos desde tu Jellyfin, NAS o servidor.

Si el addon entrega torrents o debrid, el estudio no ve nada.

## Requisitos de los enlaces propios

- **HTTP con `Range`**: responde `206` y `Accept-Ranges: bytes`. Así ffmpeg corta 10 s sin bajar la película.
- **Contenedor con índice**: mp4 o mkv. Un MPEG-PS de DVD no deja saltar por rangos.
- **URL estable**: sin tokens que venzan. El asset se identifica por `(provider, external_id, master_uri)`, así que una URL que cambia crea un asset nuevo cada vez.
- **Sin secretos en la URL del stream**: queda guardada en la base local.
- **Host fijo** (IP de la LAN o nombre), listado en `STREMIO_OWN_HOSTS`.

La URL del manifest **sí** puede llevar configuración en el path. El estudio solo muestra
y registra en los logs el host, nunca la URL completa.

## Verificar

```powershell
python scripts/testing/mock_stremio_addon.py --media-dir E:/movies   # addon de prueba en :7010
# .env: STREMIO_ADDON_URL=http://127.0.0.1:7010/manifest.json  y  STREMIO_OWN_HOSTS=127.0.0.1
ylk doctor                                          # "Addon Stremio OK <nombre> <versión> en <host>"
ylk media search "Night of the Living Dead" --year 1968 --provider stremio
python -m pytest tests/media/test_stremio_addon.py
```

En el estudio, **Biblioteca** muestra la casilla "Addon Stremio" cuando `STREMIO_ADDON_URL`
está configurada. Si el addon no responde, la búsqueda sigue con las demás fuentes y
avisa cuál se saltó.

## Pendiente

- **Series**: los streams van por episodio (`tt…:temporada:episodio`). Hoy el proveedor solo pide `movie`.
