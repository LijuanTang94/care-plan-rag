#!/usr/bin/env bash
# Replay the whole knowledge-ingestion topic from offset 0 and check the rebuild is idempotent:
# chunk counts in pgvector and Elasticsearch must be identical before and after.
# Run from the repo root with the compose stack up and the corpus already loaded.
set -euo pipefail

GROUP=knowledge-indexer
TOPIC=knowledge-ingestion
KAFKA_GROUPS="docker compose exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092"

pg_counts() {
  docker compose exec -T db psql -U careplan -d careplan -Atc \
    "select count(*) || ' chunks / ' || count(distinct source) || ' documents' from knowledge_chunks"
}
es_count() {
  curl -s "localhost:9200/knowledge_chunks/_count" | python3 -c "import json,sys; print(json.load(sys.stdin)['count'], 'chunks')"
}
lag() {
  $KAFKA_GROUPS --describe --group "$GROUP" 2>/dev/null \
    | awk -v t="$TOPIC" '$2 == t && $6 ~ /^[0-9]+$/ {s += $6} END {print s + 0}'
}

group_state() {
  $KAFKA_GROUPS --describe --group "$GROUP" --state 2>/dev/null | awk 'NR > 1 && NF {print $(NF - 1)}' | tail -1
}

echo "before: pgvector $(pg_counts); elasticsearch $(es_count)"
docker compose stop ingestion-consumer >/dev/null
# Kafka refuses to reset offsets while the group still has members, and says so with exit code 0.
until [ "$(group_state)" = "Empty" ]; do sleep 2; done
$KAFKA_GROUPS --group "$GROUP" --topic "$TOPIC" --reset-offsets --to-earliest --execute >/dev/null
backlog=$(lag)
if [ "$backlog" -eq 0 ]; then echo "offset reset did not take effect" >&2; exit 1; fi
echo "offsets reset to earliest; lag $backlog messages"

start=$(date +%s)
docker compose start ingestion-consumer >/dev/null
sleep 10
until [ "$(lag)" -eq 0 ]; do sleep 5; done
elapsed=$(( $(date +%s) - start ))

echo "after:  pgvector $(pg_counts); elasticsearch $(es_count)"
echo "replayed the full topic in ${elapsed}s"
