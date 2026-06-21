#!/usr/bin/env python3
"""
scripts/create_user.py
-----------------------
Admin utility to create a user in the database.

Usage:
    # From the backend/ directory with the venv active:
    python scripts/create_user.py --email you@imperial.ac.uk --password secret --role admin

    # Or via uv:
    uv run python scripts/create_user.py --email you@imperial.ac.uk --password secret
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from backend/ or from project root
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main(email: str, password: str, full_name: str | None, role: str) -> None:
    from app.db.session import AsyncSessionLocal
    from app.db.crud import get_user_by_email, create_user
    from app.schemas.auth import UserCreate

    async with AsyncSessionLocal() as db:
        existing = await get_user_by_email(db, email)
        if existing:
            print(f"User {email} already exists (id={existing.id}, role={existing.role})")
            return

        user = await create_user(
            db,
            UserCreate(email=email, password=password, full_name=full_name, role=role),
        )
        await db.commit()
        print(f"Created user: {user.email}  id={user.id}  role={user.role}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new RLALab user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", default=None)
    parser.add_argument("--role", default="researcher", choices=["researcher", "admin"])
    args = parser.parse_args()

    asyncio.run(main(args.email, args.password, args.full_name, args.role))
