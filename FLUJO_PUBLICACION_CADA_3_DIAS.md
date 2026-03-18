# Flujo de publicacion cada 3 dias

Este flujo automatiza la parte de preparacion de contenido y metadata para Shorts.

## Que ejecuta

En cada ciclo corre:

1. ex00: chequeo de llaves y conexion
2. ex04: descubre peliculas/frases
3. ex05: descarga subtitulos
4. ex06: asigna timestamps
5. ex07: busca escenas por tema
6. ex09: rankea matches y propone grupos antes de edicion
7. ex08: genera hashtags, songs y checklist

## Ejecutar una vez (manual)

```powershell
cd D:\Youlikeit\youtube-automatizacion-ejercicios
.\run-content-flow.ps1 -Query "epic villain moment" -CountryCode CO -UseDocker
```

## Programar cada 3 dias

```powershell
cd D:\Youlikeit\youtube-automatizacion-ejercicios
.\schedule-flow-every-3-days.ps1 -StartTime "09:00" -Query "epic villain moment" -CountryCode CO
```

## Ver estado de la tarea

```powershell
Get-ScheduledTask -TaskName "YouTubeShortsFlowEvery3Days"
Get-ScheduledTaskInfo -TaskName "YouTubeShortsFlowEvery3Days"
```

## Quitar programacion

```powershell
.\unschedule-flow.ps1
```

## Donde quedan los resultados

- Logs de flujo: outputs/logs/flow_*.log
- Logs por ejercicio: outputs/logs/ex0*.log
- Manifest de clips: outputs/manifests/
- Pack de metadata/hashtags/songs: outputs/metadata/
- Curacion y grupos recomendados: outputs/curation/

## Nota sobre subida automatica

Este flujo deja listo el contenido y metadata. La subida automatica a YouTube/TikTok requiere implementar ex10/ex11 con OAuth/API de publicacion.
