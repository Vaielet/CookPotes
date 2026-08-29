#!/usr/bin/env python3
"""
test_db_connection.py — Vérifie que la connexion à Supabase fonctionne
AVANT de lancer l'application complète.

Usage :
    python3 test_db_connection.py

Lit DATABASE_URL depuis .streamlit/secrets.toml (même format que l'app).
"""

import sys
from pathlib import Path

try:
    from sqlalchemy import create_engine, text
except ImportError:
    print("❌ sqlalchemy n'est pas installé. Lancez : pip install sqlalchemy psycopg2-binary")
    sys.exit(1)

SECRETS_PATH = Path(__file__).parent / ".streamlit" / "secrets.toml"


def load_url() -> str:
    if not SECRETS_PATH.exists():
        print(f"❌ Fichier introuvable : {SECRETS_PATH}")
        print('   Créez .streamlit/secrets.toml avec : DATABASE_URL = "postgresql://..."')
        sys.exit(1)

    try:
        import tomllib  # Python 3.11+
        with open(SECRETS_PATH, "rb") as f:
            data = tomllib.load(f)
    except ImportError:
        import toml  # Python < 3.11 : nécessite `pip install toml`
        data = toml.load(SECRETS_PATH)

    try:
        return data["DATABASE_URL"]
    except KeyError:
        print("❌ La clé DATABASE_URL est absente de secrets.toml.")
        sys.exit(1)


def main() -> None:
    url = load_url()
    masked = url.split("@")[-1] if "@" in url else url
    print(f"🔌 Connexion à ...@{masked} ...")

    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version();")).scalar()
        print("✅ Connexion réussie !")
        print(f"   {version}")
    except Exception as exc:
        print(f"❌ Échec de connexion : {exc}")
        sys.exit(1)

    print("\nVous pouvez maintenant lancer : streamlit run Accueil.py")


if __name__ == "__main__":
    main()
