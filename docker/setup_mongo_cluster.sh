#!/bin/bash
# Скрипт инициализации MongoDB кластера
# Запуск: ./docker/setup_mongo_cluster.sh

set -e

echo "=========================================="
echo "MongoDB Cluster Setup"
echo "=========================================="

echo ""
echo "1. Ожидание запуска всех контейнеров..."
for i in $(seq 1 30); do
  if docker exec mongo_config-0 mongosh --quiet --eval "db.adminCommand('ping')" >/dev/null 2>&1; then
    echo "   Все контейнеры готовы!"
    break
  fi
  echo "   Ожидание... ($i/30)"
  sleep 2
done

echo ""
echo "2. Инициализация серверов конфигурации..."
docker exec mongo_config-0 mongosh --eval '
  rs.initiate({
    _id: "config",
    configsvr: true,
    members: [
      { _id: 0, host: "mongo_config-0" },
      { _id: 1, host: "mongo_config-1" },
      { _id: 2, host: "mongo_config-2" }
    ]
  })
'

echo "   Статус config replica set:"
docker exec mongo_config-0 mongosh --quiet --eval "rs.status().set"

echo ""
echo "3. Инициализация Shard 1..."
docker exec mongo_shard1-0 mongosh --eval '
  rs.initiate({
    _id: "shard1",
    members: [
      { _id: 0, host: "mongo_shard1-0" },
      { _id: 1, host: "mongo_shard1-1" },
      { _id: 2, host: "mongo_shard1-2" }
    ]
  })
'

echo "   Статус shard1 replica set:"
docker exec mongo_shard1-0 mongosh --quiet --eval "rs.status().set"

echo ""
echo "4. Инициализация Shard 2..."
docker exec mongo_shard2-0 mongosh --eval '
  rs.initiate({
    _id: "shard2",
    members: [
      { _id: 0, host: "mongo_shard2-0" },
      { _id: 1, host: "mongo_shard2-1" },
      { _id: 2, host: "mongo_shard2-2" }
    ]
  })
'

echo "   Статус shard2 replica set:"
docker exec mongo_shard2-0 mongosh --quiet --eval "rs.status().set"

echo ""
echo "5. Ожидание election primary (до 60 сек)..."
for i in $(seq 1 30); do
  CONFIG_PRIMARY=$(docker exec mongo_config-0 mongosh --quiet --eval "print(rs.isMaster().ismaster)" 2>/dev/null || echo "false")
  SHARD1_PRIMARY=$(docker exec mongo_shard1-0 mongosh --quiet --eval "print(rs.isMaster().ismaster)" 2>/dev/null || echo "false")
  SHARD2_PRIMARY=$(docker exec mongo_shard2-0 mongosh --quiet --eval "print(rs.isMaster().ismaster)" 2>/dev/null || echo "false")
  if [ "$CONFIG_PRIMARY" = "true" ] && [ "$SHARD1_PRIMARY" = "true" ] && [ "$SHARD2_PRIMARY" = "true" ]; then
    echo "   Все primaries elected!"
    break
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "   Ожидание... ($i/30)"
  fi
  sleep 2
done

echo ""
echo "6. Добавление шардов в кластер..."
docker exec mongo_mongos-0 mongosh --host mongo_mongos-0 --port 27017 --eval '
  sh.addShard("shard1/mongo_shard1-0:27017,mongo_shard1-1:27017,mongo_shard1-2:27017");
  sh.addShard("shard2/mongo_shard2-0:27017,mongo_shard2-1:27017,mongo_shard2-2:27017");
'

echo ""
echo "7. Включение шардирования для базы ugc_service..."
docker exec mongo_mongos-0 mongosh --host mongo_mongos-0 --port 27017 --eval '
  sh.enableSharding("ugc_service");
'

echo ""
echo "8. Настройка shard keys..."
docker exec mongo_mongos-0 mongosh --host mongo_mongos-0 --port 27017 --eval '
  sh.shardCollection("ugc_service.bookmarks", { user_id: "hashed" });
  sh.shardCollection("ugc_service.likes", { user_id: "hashed" });
  sh.shardCollection("ugc_service.reviews", { film_id: 1 });
  sh.shardCollection("ugc_service.review_votes", { review_id: 1 });
'

echo ""
echo "9. Статус кластера:"
docker exec mongo_mongos-0 mongosh --host mongo_mongos-0 --port 27017 --quiet --eval "sh.status()"

echo ""
echo "=========================================="
echo "MongoDB Cluster Setup Complete!"
echo "=========================================="
echo ""
echo "Монго доступ через:"
echo "  mongo_mongos-0:27017 (хост: localhost:27017)"
echo "  mongo_mongos-1:27017 (хост: localhost:27018)"
echo ""
echo "MONGO_URI=mongodb://mongo_mongos-0:27017,mongo_mongos-1:27017"
