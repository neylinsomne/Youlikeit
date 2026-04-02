# Cuentas y API Keys necesarias

Todo es gratis. Ninguna pide tarjeta de crédito.

---

## OBLIGATORIAS (sin estas no corre el pipeline)

### 1. OpenSubtitles — descargar subtítulos .srt

- **Crear cuenta:** https://www.opensubtitles.com/users/sign_up
- **Pedir API key:** https://www.opensubtitles.com/consumers
  - Nombre de app: lo que quieras (ej: "shorts-automation")
  - Descripción: "Personal subtitle download tool"
- **Límite gratis:** 20 descargas de .srt por día
- **Variables .env:**
  ```
  OPENSUBTITLES_API_KEY=tu_api_key
  OPENSUBTITLES_USERNAME=tu_usuario
  OPENSUBTITLES_PASSWORD=tu_password
  ```
- **Nota:** la API key tarda entre 1 minuto y unas horas en activarse

---

## RECOMENDADAS (mejoran el pipeline pero hay fallback sin ellas)

### 2. TMDB — descubrir películas trending y populares

- **Crear cuenta:** https://www.themoviedb.org/signup
- **Pedir API key:** https://www.themoviedb.org/settings/api
  - Tipo: "Developer"
  - Uso: "Personal / educational"
- **Límite gratis:** sin límite real (solo piden rate limiting razonable)
- **Variable .env:**
  ```
  TMDB_API_KEY=tu_api_key
  ```
- **Sin esta key:** ex04 usa una lista hardcoded de 15 películas icónicas (Godfather, Pulp Fiction, etc.), así que funciona igual pero no descubre películas nuevas/trending

### 3. SubDL — alternativa de subtítulos si OpenSubtitles falla

- **Crear cuenta + API key:** https://subdl.com/panel/api
- **Límite gratis:** 20 descargas por día
- **Variable .env:**
  ```
  SUBDL_API_KEY=tu_api_key
  ```
- **Sin esta key:** solo usa OpenSubtitles. Con ambas tienes 40 descargas/día

---

## OPCIONALES (para fases futuras)

### 4. YouTube Data API v3 — subir Shorts automáticamente

- **Ir a:** https://console.cloud.google.com/
- **Crear proyecto** nuevo
- **Habilitar:** YouTube Data API v3 (buscar en la biblioteca de APIs)
- **Crear credenciales:** OAuth 2.0 Client ID (tipo "Desktop app")
- **Descargar** el archivo `client_secrets.json`
- **Límite gratis:** 10,000 unidades/día = ~6 uploads/día
- **Cuándo lo necesitas:** cuando quieras publicar Shorts automáticamente (aún no implementado)

### 5. Google Cloud — para OAuth de YouTube

- Solo necesario si vas a usar la YouTube Data API (punto 4)
- No requiere facturación para la cuota gratuita
- **Pantalla de consentimiento OAuth:** configurar como "External" → modo "Testing" (no requiere verificación, soporta hasta 100 usuarios de prueba)

---

## Resumen rápido

| # | Servicio | URL de registro | Tiempo | Prioridad |
|---|----------|----------------|--------|-----------|
| 1 | OpenSubtitles | opensubtitles.com/users/sign_up | 5 min | **Obligatoria** |
| 2 | TMDB | themoviedb.org/signup | 3 min | Recomendada |
| 3 | SubDL | subdl.com/panel/api | 2 min | Opcional |
| 4 | Google Cloud | console.cloud.google.com | 15 min | Futuro |

---

## Después de crear las cuentas

1. Copiar `.env.example` a `.env`
2. Llenar las keys:
   ```
   TMDB_API_KEY=abc123...
   OPENSUBTITLES_API_KEY=def456...
   OPENSUBTITLES_USERNAME=mi_usuario
   OPENSUBTITLES_PASSWORD=mi_password
   SUBDL_API_KEY=ghi789...
   ```
3. Verificar con:
   ```
   python main.py ex00
   ```
4. Ejecutar el pipeline:
   ```
   python main.py ex04              # descubrir películas + frases
   python main.py ex05              # descargar subtítulos
   python main.py ex06              # matching frases ↔ timestamps
   python main.py ex07 --query "epic villain moment"   # buscar escenas
  python main.py ex09 --query "epic villain moment"   # ranking + grupos antes de editar
  python main.py ex08 --query "epic villain moment"   # hashtags + songs + checklist
   ```

## Ejecucion automatizada cada 3 dias

Tambien puedes usar los scripts de flujo:

```powershell
.\run-content-flow.ps1 -Query "epic villain moment" -CountryCode CO -UseDocker
.\schedule-flow-every-3-days.ps1 -StartTime "09:00" -Query "epic villain moment" -CountryCode CO
```

Para remover la tarea:

```powershell
.\unschedule-flow.ps1
```
