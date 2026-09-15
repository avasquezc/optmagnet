# 🚀 Guía de despliegue — Option Magnets online (gratis)

Arquitectura: **GitHub Actions** recolecta los datos (cron + botón) y **Streamlit
Community Cloud** muestra el dashboard. Todo gratis. Sigue estos pasos en orden.

---

## Paso 1 — Subir el proyecto a GitHub (repo público)

1. Crea una cuenta en github.com si no tienes.
2. Crea un repo nuevo **público** llamado `optmagnet` (o el nombre que quieras).
3. Sube todos estos archivos al repo. Puedes hacerlo por la web (botón "Add file
   > Upload files") o por git:
   ```bash
   git init
   git add .
   git commit -m "primer commit"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/optmagnet.git
   git push -u origin main
   ```
   > El `.gitignore` ya evita que se suban secretos. Verifica que **NO** subiste
   > ningún archivo con un token dentro.

---

## Paso 2 — Editar tu usuario/repo en el código

Abre `gh_trigger.py` y cambia estas dos líneas con tus datos reales:
```python
GH_OWNER = "TU_USUARIO_GITHUB"   # tu usuario de GitHub
GH_REPO  = "optmagnet"           # el nombre del repo
```
Haz commit del cambio.

---

## Paso 3 — Crear el token de GitHub (para el botón "Actualizar")

El botón del dashboard dispara la Action vía API, y eso necesita un token.

1. Ve a **github.com > Settings > Developer settings > Personal access tokens >
   Fine-grained tokens > Generate new token**.
2. Configúralo así:
   - **Repository access**: Only select repositories → elige tu repo `optmagnet`.
   - **Permissions > Actions**: Read and write.
   - (Con eso basta. No le des más permisos de los necesarios.)
3. Genera el token y **cópialo** (empieza con `github_pat_...`). Solo se muestra
   una vez.

> ⚠️ Este token NUNCA va en el código ni en el repo. Solo en los secrets (paso 5).
> Si alguna vez se te filtra, bórralo desde la misma página y crea otro.

---

## Paso 4 — Activar la GitHub Action

1. En tu repo, ve a la pestaña **Actions**.
2. Si te pide habilitar workflows, acepta.
3. Verás el workflow "collect-options". Púlsalo y dale **Run workflow** una vez a
   mano para probar que recolecta y hace commit de `options.db`.
   - Si falla, mira el log. Lo más común: yfinance sin conexión momentánea
     (reintenta) o falta algún permiso.
4. A partir de ahí corre solo cada 30 min en horario de mercado (L-V).

> Nota: GitHub deshabilita los cron de repos públicos sin actividad por 60 días.
> Si dejas de usarlo un tiempo, entra y reactívalo.

---

## Paso 5 — Desplegar el dashboard en Streamlit Cloud

1. Ve a **share.streamlit.io** e inicia sesión con GitHub.
2. **New app** → elige tu repo `optmagnet`, rama `main`, archivo `dashboard.py`.
3. Antes de deploy, abre **Advanced settings > Secrets** y pega:
   ```toml
   GH_TOKEN = "github_pat_tu_token_del_paso_3"
   ```
4. Deploy. En 1-2 min tendrás una URL pública tipo
   `https://tu-app.streamlit.app`.

Listo: el dashboard está online, se actualiza solo cada 30 min, y el botón
"🔄 Actualizar datos" fuerza una recolección cuando quieras.

---

## Cómo cambiar los tickers

Edita `watchlist.txt` en el repo (por la web de GitHub o git), un ticker por
línea. La próxima recolección lo toma. No hace falta tocar nada más.

---

## Consumo de minutos (repo público = ilimitado)

En repos **públicos**, GitHub Actions es gratis e ilimitado — no vigilas cuota.
El cron está limitado a horario de mercado igual, por prolijidad (fuera de
mercado el OI no cambia).

---

## Seguridad — resumen

- El token vive solo en: los secrets de Streamlit (paso 5) y, si lo usas local,
  en `.streamlit/secrets.toml` (que el `.gitignore` bloquea).
- Nunca en el código ni en el repo.
- Permisos mínimos: solo Actions read/write sobre un repo.
- Si se filtra: revócalo en GitHub y crea otro. No da acceso a nada más que
  disparar tu Action.

---

## Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Botón dice "No hay token" | Falta GH_TOKEN en secrets | Paso 5.3 |
| Botón dice "404" | GH_OWNER/GH_REPO mal | Paso 2 |
| Botón dice "401" | Token sin permiso Actions | Regenera con Actions:write |
| Dashboard vacío | Aún no corrió la Action | Paso 4.3, corre una vez a mano |
| App "dormida" al abrir | Streamlit duerme tras 12h | Espera unos segundos, despierta sola |
| Cron no corre | Repo público inactivo 60d | Entra a Actions y reactívalo |
