"""
gh_trigger.py — Dispara la GitHub Action de recolección vía API (workflow_dispatch).

El token NUNCA va en el código. Se lee de st.secrets (en Streamlit Cloud) o de
una variable de entorno (local). Si no hay token, la función lo dice claramente.
"""
import os
import requests

# Ajusta estos dos a tu repo cuando lo crees:
GH_OWNER = "TU_USUARIO_GITHUB"
GH_REPO = "optmagnet"
WORKFLOW_FILE = "collect.yml"   # nombre del archivo en .github/workflows/
BRANCH = "main"


def _get_token():
    """Lee el token de Streamlit secrets o de entorno. Devuelve None si no hay."""
    # 1) Streamlit secrets (produccion)
    try:
        import streamlit as st
        if "GH_TOKEN" in st.secrets:
            return st.secrets["GH_TOKEN"]
    except Exception:
        pass
    # 2) Variable de entorno (local)
    return os.environ.get("GH_TOKEN")


def trigger_collection():
    """
    Dispara la Action. Devuelve (ok: bool, mensaje: str).
    No lanza excepciones hacia arriba: siempre devuelve un mensaje legible.
    """
    token = _get_token()
    if not token:
        return (False, "No hay token de GitHub configurado. Agrega GH_TOKEN en los "
                       "secrets de Streamlit (o como variable de entorno local).")

    if GH_OWNER == "TU_USUARIO_GITHUB":
        return (False, "Configura GH_OWNER y GH_REPO en gh_trigger.py con tu repo real.")

    url = (f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"
           f"/actions/workflows/{WORKFLOW_FILE}/dispatches")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.post(url, headers=headers, json={"ref": BRANCH}, timeout=15)
    except requests.RequestException as e:
        return (False, f"Error de red al contactar GitHub: {e}")

    if r.status_code == 204:
        return (True, "Recolección disparada. La Action tarda ~1-2 min; refresca "
                      "el dashboard en un rato para ver los datos nuevos.")
    elif r.status_code == 401:
        return (False, "Token inválido o sin permisos (necesita scope 'actions:write').")
    elif r.status_code == 404:
        return (False, "No encontré el workflow o el repo. Revisa GH_OWNER, GH_REPO "
                       "y que collect.yml exista en la rama main.")
    else:
        return (False, f"GitHub respondió {r.status_code}: {r.text[:200]}")
