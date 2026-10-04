import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()


class Database:
    def __init__(self):
        self.pool: asyncpg.Pool | None = None

        self.DB_URL = os.getenv("DB_URL")
    
    async def connect(self):
        self.pool = await asyncpg.create_pool(
            dsn=self.DB_URL,
            min_size=1,
            max_size=10
        )


    async def close(self):
        if self.pool:
            await self.pool.close()

    def acquire(self):
        if not self.pool:
            raise RuntimeError("Database pool is not initialized. Call connect() first.")
        return self.pool.acquire()

    async def execute(self, query: str, *args):
        if not self.pool:
            raise RuntimeError("Database pool is not initialized.")
        return await self.pool.execute(query, *args)

    async def fetch(self, query: str, *args):
        if not self.pool:
            raise RuntimeError("Database pool is not initialized.")
        return await self.pool.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        if not self.pool:
            raise RuntimeError("Database pool is not initialized.")
        return await self.pool.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        if not self.pool:
            raise RuntimeError("Database pool is not initialized.")
        return await self.pool.fetchval(query, *args)


