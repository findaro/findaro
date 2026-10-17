"""List or update access requests from the website.

    python leads.py                 # newest first
    python leads.py --status new
    python leads.py --set 12 contacted
"""

from __future__ import annotations

import argparse
import asyncio
import os

import asyncpg


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status")
    ap.add_argument("--set", nargs=2, metavar=("ID", "STATUS"))
    args = ap.parse_args()
    conn = await asyncpg.connect(os.environ["SITE_DATABASE_URL"])
    try:
        if args.set:
            await conn.execute("UPDATE site_leads SET status = $2 WHERE id = $1", int(args.set[0]), args.set[1])
        q = "SELECT * FROM site_leads" + (" WHERE status = $1" if args.status else "") + " ORDER BY id DESC"
        for r in await conn.fetch(q, *([args.status] if args.status else [])):
            print(f"#{r['id']} {r['created_at']:%Y-%m-%d %H:%M} [{r['status']}] {r['name']} <{r['email']}> "
                  f"{r['company']} {r['website'] or ''} plan={r['plan'] or '-'} catalog={r['catalog_size'] or '-'}")
            if r["message"]:
                print("    " + r["message"].replace("\n", "\n    "))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
