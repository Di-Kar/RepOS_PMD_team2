import asyncio
import argparse
import time
import random
import string
import json
import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import asyncpg

# ================= CONFIG =================
TOTAL_RECORDS = 10_000_000
BATCH_SIZE = 10_000
USERS_COUNT = 1_000_000
MOVIES_COUNT = 100_000
UNSTRUCTURED_COUNT = 500_000  # NEW: объем неструктурированных данных

def random_string(length=10):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

def generate_unstructured_doc(doc_id):
    """Создает документ с рандомизированной структурой и глубиной вложенности."""
    doc = {
        "_id": doc_id,
        "user_id": random.randint(0, USERS_COUNT),
        "timestamp": datetime.datetime.utcnow(),  # ИСПРАВЛЕНО: теперь datetime объект, не строка
    }
    
    # Случайное количество полей верхнего уровня (2-6)
    num_fields = random.randint(2, 6)
    field_names = ["meta", "payload", "context", "tags", "attributes", "details"]
    
    for i in range(num_fields):
        field_name = field_names[i]
        field_type = random.choice(["string", "number", "array", "nested", "mixed"])
        
        if field_type == "string":
            doc[field_name] = random_string(random.randint(5, 30))
        elif field_type == "number":
            doc[field_name] = random.randint(1, 10000)
        elif field_type == "array":
            doc[field_name] = [random_string(8) for _ in range(random.randint(1, 10))]
        elif field_type == "nested":
            # Глубокая вложенность (2-4 уровня)
            depth = random.randint(2, 4)
            current = {}
            for d in range(depth):
                key = f"level_{d}"
                current[key] = {}
                current = current[key]
            current["value"] = random.choice([random_string(10), random.randint(1, 1000), True])
            doc[field_name] = current
        elif field_type == "mixed":
            doc[field_name] = {
                "event_type": random.choice(["click", "view", "purchase", "scroll"]),
                "data": {"value": random.randint(1, 100), "label": random_string(5)},
                "flags": [random.choice([True, False]) for _ in range(3)]
            }
    
    return doc


# ================= MONGODB =================
class MongoHandler:
    def __init__(self):
        self.client = AsyncIOMotorClient("mongodb://mongo:27017/")
        self.db = self.client.research

    async def setup(self):
        for attempt in range(20):
            try:
                await self.client.admin.command('ping')
                print("[Mongo] Connected successfully.")
                break
            except Exception as e:
                print(f"[Mongo] Waiting for DB... (Attempt {attempt + 1}/20) Error: {e}")
                await asyncio.sleep(2)
        else:
            raise Exception("MongoDB did not become ready in time")

        await self.db.users.drop()
        await self.db.movies.drop()
        await self.db.user_likes.drop()
        await self.db.action_logs.drop()
        await self.db.unstructured_events.drop()  # NEW
        
        await self.db.user_likes.create_index("user_id")
        await self.db.user_likes.create_index("movie_id")
        await self.db.action_logs.create_index("user_id")
        # NEW: индексы для неструктурированных данных
        await self.db.unstructured_events.create_index("user_id")
        await self.db.unstructured_events.create_index("meta.event_type")  # sparse index на вложенное поле
        await self.db.unstructured_events.create_index("payload.data.value")

    async def generate(self):
        print("[Mongo] Generating data...")
        users_batch = []
        for i in range(USERS_COUNT):
            users_batch.append({
                "_id": i,
                "profile": {"theme": random.choice(["dark", "light"]), "settings": {"nested": {"val": random.randint(1, 100)}}},
                "bookmarks": [{"movie_id": random.randint(0, MOVIES_COUNT), "meta": {"note": random_string(20)}} for _ in range(3)]
            })
            if len(users_batch) >= BATCH_SIZE:
                await self.db.users.insert_many(users_batch)
                users_batch = []
        
        movies_batch = []
        for i in range(MOVIES_COUNT):
            movies_batch.append({
                "_id": i, "title": f"Movie {i}", 
                "avg_rating": round(random.uniform(1, 5), 1), 
                "total_likes": random.randint(0, 10000)
            })
        await self.db.movies.insert_many(movies_batch)

        remaining = TOTAL_RECORDS - USERS_COUNT - MOVIES_COUNT - UNSTRUCTURED_COUNT
        likes_batch = []
        logs_batch = []
        
        for i in range(remaining):
            if i % 2 == 0:
                likes_batch.append({"user_id": random.randint(0, USERS_COUNT), "movie_id": random.randint(0, MOVIES_COUNT), "type": "like"})
            else:
                logs_batch.append({"user_id": random.randint(0, USERS_COUNT), "action": "click", "payload": {"page": random_string(5)}})
            
            if len(likes_batch) >= BATCH_SIZE:
                await self.db.user_likes.insert_many(likes_batch)
                likes_batch = []
            if len(logs_batch) >= BATCH_SIZE:
                await self.db.action_logs.insert_many(logs_batch)
                logs_batch = []
        
        if likes_batch: await self.db.user_likes.insert_many(likes_batch)
        if logs_batch: await self.db.action_logs.insert_many(logs_batch)

        # NEW: Генерация неструктурированных данных
        print("[Mongo] Generating unstructured data...")
        unstructured_batch = []
        for i in range(UNSTRUCTURED_COUNT):
            unstructured_batch.append(generate_unstructured_doc(i))
            if len(unstructured_batch) >= BATCH_SIZE:
                await self.db.unstructured_events.insert_many(unstructured_batch)
                unstructured_batch = []
        if unstructured_batch:
            await self.db.unstructured_events.insert_many(unstructured_batch)

        print("[Mongo] Generation complete.")

    async def benchmark(self):
        print("\n[Mongo] Benchmarking...")
        results = []
        user_id = random.randint(0, USERS_COUNT)
        movie_id = random.randint(0, MOVIES_COUNT)

        # 1. Read user likes
        start = time.time()
        await self.db.user_likes.find({"user_id": user_id}).to_list(length=100)
        t1 = (time.time() - start) * 1000
        results.append({"scenario": "Read User Likes", "time_ms": round(t1, 2)})
        print(f"Read User Likes: {t1:.2f} ms")

        # 2. Read movie likes count (Pre-aggregated)
        start = time.time()
        await self.db.movies.find_one({"_id": movie_id}, {"total_likes": 1})
        t2 = (time.time() - start) * 1000
        results.append({"scenario": "Read Movie Likes Count", "time_ms": round(t2, 2)})
        print(f"Read Movie Likes Count: {t2:.2f} ms")

        # 3. Read bookmarks (Nested JSON)
        start = time.time()
        await self.db.users.find_one({"_id": user_id}, {"bookmarks": 1})
        t3 = (time.time() - start) * 1000
        results.append({"scenario": "Read Bookmarks", "time_ms": round(t3, 2)})
        print(f"Read Bookmarks: {t3:.2f} ms")

        # 4. Write + Read (Real-time like)
        start = time.time()
        await self.db.user_likes.insert_one({"user_id": user_id, "movie_id": movie_id, "type": "like"})
        await self.db.movies.update_one({"_id": movie_id}, {"$inc": {"total_likes": 1}})
        await self.db.movies.find_one({"_id": movie_id}, {"total_likes": 1})
        t4 = (time.time() - start) * 1000
        results.append({"scenario": "Write Like + Read Count", "time_ms": round(t4, 2)})
        print(f"Write Like + Read Count: {t4:.2f} ms")

        # NEW: Тесты неструктурированных данных
        # 5. Insert unstructured document
        start = time.time()
        new_doc = generate_unstructured_doc(UNSTRUCTURED_COUNT + 1)
        await self.db.unstructured_events.insert_one(new_doc)
        t5 = (time.time() - start) * 1000
        results.append({"scenario": "Insert Unstructured Doc", "time_ms": round(t5, 2)})
        print(f"Insert Unstructured Doc: {t5:.2f} ms")

        # 6. Read unstructured document by ID
        start = time.time()
        await self.db.unstructured_events.find_one({"_id": 100})
        t6 = (time.time() - start) * 1000
        results.append({"scenario": "Read Unstructured Doc by ID", "time_ms": round(t6, 2)})
        print(f"Read Unstructured Doc by ID: {t6:.2f} ms")

        # 7. Query by nested field (dot notation)
        start = time.time()
        await self.db.unstructured_events.find({"meta.event_type": "click"}).to_list(length=50)
        t7 = (time.time() - start) * 1000
        results.append({"scenario": "Query by Nested Field", "time_ms": round(t7, 2)})
        print(f"Query by Nested Field: {t7:.2f} ms")

        # 8. Query with deep nesting
        start = time.time()
        await self.db.unstructured_events.find({"payload.data.value": {"$gt": 50}}).to_list(length=50)
        t8 = (time.time() - start) * 1000
        results.append({"scenario": "Query Deep Nested Field", "time_ms": round(t8, 2)})
        print(f"Query Deep Nested Field: {t8:.2f} ms")

        return results


# ================= POSTGRESQL =================
class PostgresHandler:
    def __init__(self):
        self.pool = None

    async def setup(self):
        for attempt in range(20):
            try:
                self.pool = await asyncpg.create_pool("postgres://user:password@postgres:5432/research")
                print("[Postgres] Connected successfully.")
                break
            except Exception as e:
                print(f"[Postgres] Waiting for DB... (Attempt {attempt + 1}/20) Error: {e}")
                await asyncio.sleep(2)
        else:
            raise Exception("PostgreSQL did not become ready in time")

        async with self.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS users, movies, user_likes, action_logs, unstructured_events;")
            await conn.execute("""
                CREATE TABLE users (id INT PRIMARY KEY, profile JSONB, bookmarks JSONB);
                CREATE TABLE movies (id INT PRIMARY KEY, title VARCHAR, avg_rating FLOAT, total_likes INT);
                CREATE TABLE user_likes (id SERIAL PRIMARY KEY, user_id INT, movie_id INT, type VARCHAR);
                CREATE TABLE action_logs (id SERIAL PRIMARY KEY, user_id INT, action VARCHAR, payload JSONB);
                CREATE TABLE unstructured_events (id INT PRIMARY KEY, user_id INT, timestamp TIMESTAMPTZ, data JSONB);  -- NEW
                
                CREATE INDEX idx_likes_user ON user_likes(user_id);
                CREATE INDEX idx_likes_movie ON user_likes(movie_id);
                CREATE INDEX idx_logs_user ON action_logs(user_id);
                CREATE INDEX idx_users_bookmarks ON users USING GIN (bookmarks);
                -- NEW: индексы для неструктурированных данных
                CREATE INDEX idx_unstructured_user ON unstructured_events(user_id);
                CREATE INDEX idx_unstructured_data ON unstructured_events USING GIN (data);
                CREATE INDEX idx_unstructured_event_type ON unstructured_events USING GIN ((data->'meta'));
            """)

    async def generate(self):
        print("[Postgres] Generating data...")
        async with self.pool.acquire() as conn:
            users_data = [(i, '{"theme": "dark"}', '[{"movie_id": 1}]') for i in range(USERS_COUNT)]
            await conn.executemany("INSERT INTO users VALUES ($1, $2::jsonb, $3::jsonb)", users_data)
            
            movies_data = [(i, f"Movie {i}", 4.5, 100) for i in range(MOVIES_COUNT)]
            await conn.executemany("INSERT INTO movies VALUES ($1, $2, $3, $4)", movies_data)

            remaining = TOTAL_RECORDS - USERS_COUNT - MOVIES_COUNT - UNSTRUCTURED_COUNT
            likes_data = [(random.randint(0, USERS_COUNT), random.randint(0, MOVIES_COUNT), 'like') for _ in range(remaining // 2)]
            await conn.executemany("INSERT INTO user_likes (user_id, movie_id, type) VALUES ($1, $2, $3)", likes_data)
            
            logs_data = [(random.randint(0, USERS_COUNT), 'click', '{"page": "home"}') for _ in range(remaining // 2)]
            await conn.executemany("INSERT INTO action_logs (user_id, action, payload) VALUES ($1, $2, $3::jsonb)", logs_data)

            # NEW: Генерация неструктурированных данных
            print("[Postgres] Generating unstructured data...")
            unstructured_data = []
            for i in range(UNSTRUCTURED_COUNT):
                doc = generate_unstructured_doc(i)
                # Преобразуем _id в id и собираем data в JSONB
                data_json = {k: v for k, v in doc.items() if k not in ("_id", "user_id", "timestamp")}
                unstructured_data.append((
                    doc["_id"],
                    doc["user_id"],
                    doc["timestamp"],
                    json.dumps(data_json)
                ))
                if len(unstructured_data) >= BATCH_SIZE:
                    await conn.executemany(
                        "INSERT INTO unstructured_events (id, user_id, timestamp, data) VALUES ($1, $2, $3, $4::jsonb)",
                        unstructured_data
                    )
                    unstructured_data = []
            if unstructured_data:
                await conn.executemany(
                    "INSERT INTO unstructured_events (id, user_id, timestamp, data) VALUES ($1, $2, $3, $4::jsonb)",
                    unstructured_data
                )

        print("[Postgres] Generation complete.")

    async def benchmark(self):
        print("\n[Postgres] Benchmarking...")
        results = []
        user_id = random.randint(0, USERS_COUNT)
        movie_id = random.randint(0, MOVIES_COUNT)
        
        async with self.pool.acquire() as conn:
            # 1. Read user likes
            start = time.time()
            await conn.fetch("SELECT * FROM user_likes WHERE user_id = $1 LIMIT 100", user_id)
            t1 = (time.time() - start) * 1000
            results.append({"scenario": "Read User Likes", "time_ms": round(t1, 2)})
            print(f"Read User Likes: {t1:.2f} ms")

            # 2. Read movie likes count
            start = time.time()
            await conn.fetchval("SELECT total_likes FROM movies WHERE id = $1", movie_id)
            t2 = (time.time() - start) * 1000
            results.append({"scenario": "Read Movie Likes Count", "time_ms": round(t2, 2)})
            print(f"Read Movie Likes Count: {t2:.2f} ms")

            # 3. Read bookmarks (Nested JSON)
            start = time.time()
            await conn.fetchval("SELECT bookmarks FROM users WHERE id = $1", user_id)
            t3 = (time.time() - start) * 1000
            results.append({"scenario": "Read Bookmarks", "time_ms": round(t3, 2)})
            print(f"Read Bookmarks: {t3:.2f} ms")

            # 4. Write + Read (Real-time like)
            start = time.time()
            await conn.execute("INSERT INTO user_likes (user_id, movie_id, type) VALUES ($1, $2, 'like')", user_id, movie_id)
            await conn.execute("UPDATE movies SET total_likes = total_likes + 1 WHERE id = $1", movie_id)
            await conn.fetchval("SELECT total_likes FROM movies WHERE id = $1", movie_id)
            t4 = (time.time() - start) * 1000
            results.append({"scenario": "Write Like + Read Count", "time_ms": round(t4, 2)})
            print(f"Write Like + Read Count: {t4:.2f} ms")

            # NEW: Тесты неструктурированных данных
            # 5. Insert unstructured document
            start = time.time()
            new_doc = generate_unstructured_doc(UNSTRUCTURED_COUNT + 1)
            data_json = {k: v for k, v in new_doc.items() if k not in ("_id", "user_id", "timestamp")}
            await conn.execute(
                "INSERT INTO unstructured_events (id, user_id, timestamp, data) VALUES ($1, $2, $3, $4::jsonb)",
                new_doc["_id"], new_doc["user_id"], new_doc["timestamp"], json.dumps(data_json)
            )
            t5 = (time.time() - start) * 1000
            results.append({"scenario": "Insert Unstructured Doc", "time_ms": round(t5, 2)})
            print(f"Insert Unstructured Doc: {t5:.2f} ms")

            # 6. Read unstructured document by ID
            start = time.time()
            await conn.fetchrow("SELECT * FROM unstructured_events WHERE id = $1", 100)
            t6 = (time.time() - start) * 1000
            results.append({"scenario": "Read Unstructured Doc by ID", "time_ms": round(t6, 2)})
            print(f"Read Unstructured Doc by ID: {t6:.2f} ms")

            # 7. Query by nested field (using JSONB containment operator @>)
            start = time.time()
            await conn.fetch(
                "SELECT * FROM unstructured_events WHERE data @> '{\"meta\": {\"event_type\": \"click\"}}' LIMIT 50"
            )
            t7 = (time.time() - start) * 1000
            results.append({"scenario": "Query by Nested Field", "time_ms": round(t7, 2)})
            print(f"Query by Nested Field: {t7:.2f} ms")

            # 8. Query with deep nesting (using ->> operator)
            start = time.time()
            await conn.fetch(
                "SELECT * FROM unstructured_events WHERE (data->'payload'->'data'->>'value')::int > 50 LIMIT 50"
            )
            t8 = (time.time() - start) * 1000
            results.append({"scenario": "Query Deep Nested Field", "time_ms": round(t8, 2)})
            print(f"Query Deep Nested Field: {t8:.2f} ms")

        return results


# ================= MAIN =================
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", choices=["mongo", "postgres"], required=True)
    parser.add_argument("--action", choices=["generate", "benchmark"], required=True)
    args = parser.parse_args()

    if args.db == "mongo":
        handler = MongoHandler()
    else:
        handler = PostgresHandler()

    await handler.setup()
    
    if args.action == "generate":
        await handler.generate()
    elif args.action == "benchmark":
        results = await handler.benchmark()
        
        report = {
            "database": args.db.upper(),
            "test_date": datetime.datetime.utcnow().isoformat() + "Z",
            "total_records_in_db": TOTAL_RECORDS,
            "unstructured_records": UNSTRUCTURED_COUNT,  # NEW
            "sla_requirement_ms": 200,
            "results": results
        }
        
        filename = f"{args.db}_benchmark_report.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
            
        print(f"\n[Report] Successfully saved to {filename}")


if __name__ == "__main__":
    asyncio.run(main())