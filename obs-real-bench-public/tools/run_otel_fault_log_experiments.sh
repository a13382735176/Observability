#!/usr/bin/env bash
set -uo pipefail

BENCH_ROOT="${BENCH_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DEMO_ROOT="${DEMO_ROOT:-../source_repos/open-telemetry__opentelemetry-demo}"
RUN_ROOT="${RUN_ROOT:-$BENCH_ROOT/results/agent-gpt5.5-6.3}"
PROMPT_LEVEL="${PROMPT_LEVEL:-p_fewshot}"
MODEL_ID="${MODEL_ID:-gpt-5.5}"
BASE_URL="${BASE_URL:-http://localhost:8080}"
CURL_MAX_TIME="${CURL_MAX_TIME:-20}"
OUT_ROOT="${OUT_ROOT:-$BENCH_ROOT/runs/otel_fault_logs/$(basename "$RUN_ROOT")-$PROMPT_LEVEL-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ORIGINAL="${RUN_ORIGINAL:-1}"
RUN_LLM="${RUN_LLM:-1}"

mkdir -p "$OUT_ROOT" "$OUT_ROOT/backups" "$OUT_ROOT/logs" "$OUT_ROOT/responses"

cd "$DEMO_ROOT" || exit 2

export TELEMETRY_DOCS_HOST="${TELEMETRY_DOCS_HOST:-telemetry-docs}"
export TELEMETRY_DOCS_PORT="${TELEMETRY_DOCS_PORT:-8000}"
export PROFILES_HOST="${PROFILES_HOST:-telemetry-docs}"
export PROFILES_PORT="${PROFILES_PORT:-8000}"
export FIREPIT_HOST="${FIREPIT_HOST:-frontend}"
export FIREPIT_PORT="${FIREPIT_PORT:-8080}"

COMPOSE_OVERRIDE="$OUT_ROOT/compose.experiment.override.yml"
cat > "$COMPOSE_OVERRIDE" <<YAML
services:
  frontend-proxy:
    environment:
      TELEMETRY_DOCS_HOST: "${TELEMETRY_DOCS_HOST}"
      TELEMETRY_DOCS_PORT: "${TELEMETRY_DOCS_PORT}"
      PROFILES_HOST: "${PROFILES_HOST}"
      PROFILES_PORT: "${PROFILES_PORT}"
      FIREPIT_HOST: "${FIREPIT_HOST}"
      FIREPIT_PORT: "${FIREPIT_PORT}"
YAML

dc() {
  docker compose -f docker-compose.yml -f "$COMPOSE_OVERRIDE" "$@"
}

summary="$OUT_ROOT/summary.tsv"
printf 'case\tvariant\tstatus\tevidence\tnotes\n' > "$summary"

targets=(
  "src/payment/charge.js"
  "src/recommendation/recommendation_server.py"
  "src/ad/src/main/java/oteldemo/AdService.java"
  "src/checkout/main.go"
  "src/cart/src/services/CartService.cs"
  "src/cart/src/services/HealthCheckService.cs"
  "src/llm/app.py"
  "src/product-reviews/product_reviews_server.py"
  "src/product-catalog/main.go"
  "src/load-generator/locustfile.py"
  "src/flagd/demo.flagd.json"
)

for target in "${targets[@]}"; do
  mkdir -p "$OUT_ROOT/backups/$(dirname "$target")"
  cp "$DEMO_ROOT/$target" "$OUT_ROOT/backups/$target"
done

restore_file() {
  local target="$1"
  cp "$OUT_ROOT/backups/$target" "$DEMO_ROOT/$target"
}

restore_all_sources() {
  for target in "${targets[@]}"; do
    restore_file "$target"
  done
}

record() {
  local case_name="$1"
  local variant="$2"
  local status="$3"
  local evidence="$4"
  local notes="$5"
  printf '%s\t%s\t%s\t%s\t%s\n' "$case_name" "$variant" "$status" "$evidence" "$notes" >> "$summary"
}

artifact_path() {
  local inst="$1"
  printf '%s/%s/%s/%s/llm_source.py' "$RUN_ROOT" "$inst" "$PROMPT_LEVEL" "$MODEL_ID"
}

wait_url() {
  local url="$1"
  local label="$2"
  local max_tries="${3:-90}"
  local i
  for ((i=1; i<=max_tries; i++)); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    printf '[wait] %s not ready yet (%d/%d)\n' "$label" "$i" "$max_tries"
    sleep 2
  done
  return 1
}

set_flags() {
  local spec="$1"
  python3 - "$DEMO_ROOT/src/flagd/demo.flagd.json" "$spec" <<'PY'
import json
import sys

path, spec = sys.argv[1], sys.argv[2]
with open(path, encoding='utf-8') as f:
    data = json.load(f)
for item in filter(None, spec.split(',')):
    name, variant = item.split('=', 1)
    data['flags'][name]['defaultVariant'] = variant
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PY
  python3 - "$DEMO_ROOT/src/flagd/demo.flagd.json" <<'PY' > "$OUT_ROOT/.flag_payload.json"
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
print(json.dumps({'data': data}))
PY
  curl -fsS -X POST "$BASE_URL/feature/api/write-to-file" \
    -H 'Content-Type: application/json' \
    --data-binary "@$OUT_ROOT/.flag_payload.json" >/dev/null 2>&1 || true
  dc restart flagd >/dev/null 2>&1 || true
  sleep 4
}

reset_flags() {
  restore_file "src/flagd/demo.flagd.json"
  python3 - "$DEMO_ROOT/src/flagd/demo.flagd.json" <<'PY' > "$OUT_ROOT/.flag_payload.json"
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
print(json.dumps({'data': data}))
PY
  curl -fsS -X POST "$BASE_URL/feature/api/write-to-file" \
    -H 'Content-Type: application/json' \
    --data-binary "@$OUT_ROOT/.flag_payload.json" >/dev/null 2>&1 || true
  dc restart flagd >/dev/null 2>&1 || true
  sleep 3
}

checkout_payload() {
  local user_id="$1"
  python3 - "$DEMO_ROOT/src/load-generator/people.json" "$user_id" <<'PY'
import json, sys
people_path, user_id = sys.argv[1], sys.argv[2]
with open(people_path, encoding='utf-8') as f:
    person = json.load(f)[0]
person['userId'] = user_id
print(json.dumps(person))
PY
}

add_to_cart() {
  local user_id="$1"
  curl -sS -o "$OUT_ROOT/responses/${CURRENT_CASE}_${CURRENT_VARIANT}_add_cart.json" \
    --max-time "$CURL_MAX_TIME" \
    -w '%{http_code}\n' \
    -H 'Content-Type: application/json' \
    -X POST "$BASE_URL/api/cart" \
    --data-binary "{\"item\":{\"productId\":\"OLJCESPC7Z\",\"quantity\":1},\"userId\":\"$user_id\"}" \
    > "$OUT_ROOT/responses/${CURRENT_CASE}_${CURRENT_VARIANT}_add_cart.status" || true
}

trigger_case() {
  local case_name="$1"
  local variant="$2"
  CURRENT_CASE="$case_name"
  CURRENT_VARIANT="$variant"
  local response_prefix="$OUT_ROOT/responses/${case_name}_${variant}"
  local user_id="exp-${case_name}-${variant}-$(date +%s)-$RANDOM"

  case "$case_name" in
    payment_failure|payment_unreachable|kafka_queue)
      add_to_cart "$user_id"
      checkout_payload "$user_id" > "$response_prefix.checkout.payload.json"
      curl -sS -o "$response_prefix.checkout.json" -w '%{http_code}\n' \
        --max-time "$CURL_MAX_TIME" \
        -H 'Content-Type: application/json' \
        -X POST "$BASE_URL/api/checkout" \
        --data-binary "@$response_prefix.checkout.payload.json" \
        > "$response_prefix.checkout.status" || true
      ;;
    cart_failure)
      docker run --rm --network opentelemetry-demo \
        -v "$DEMO_ROOT/pb:/protos" \
        fullstorydev/grpcurl:latest \
        -plaintext -max-time "$CURL_MAX_TIME" -import-path /protos -proto demo.proto \
        -d "{\"user_id\":\"$user_id\"}" \
        cart:7070 oteldemo.CartService/EmptyCart \
        > "$response_prefix.empty_cart.json" 2> "$response_prefix.empty_cart.stderr"
      printf '%s\n' "$?" > "$response_prefix.empty_cart.status"
      ;;
    failed_readiness_probe)
      docker run --rm --network opentelemetry-demo \
        ghcr.io/grpc-ecosystem/grpc-health-probe:v0.4.37 \
        -addr=cart:7070 \
        > "$response_prefix.health.txt" 2>&1
      printf '%s\n' "$?" > "$response_prefix.health.status"
      ;;
    recommendation_cache)
      curl -sS -o "$response_prefix.recommendations.json" -w '%{http_code}\n' \
        --max-time "$CURL_MAX_TIME" \
        "$BASE_URL/api/recommendations?productIds=OLJCESPC7Z&currencyCode=USD&sessionId=$user_id" \
        > "$response_prefix.recommendations.status" || true
      ;;
    ad_failure)
      : > "$response_prefix.ads.status"
      for _ in $(seq 1 25); do
        curl -sS -o "$response_prefix.ads.json" -w '%{http_code}\n' \
          --max-time "$CURL_MAX_TIME" \
          "$BASE_URL/api/data?contextKeys=binoculars" >> "$response_prefix.ads.status" || true
      done
      ;;
    llm_inaccurate)
      curl -sS -o "$response_prefix.llm.json" -w '%{http_code}\n' \
        --max-time "$CURL_MAX_TIME" \
        -H 'Content-Type: application/json' \
        -X POST "$BASE_URL/api/product-ask-ai-assistant/L9ECAV7KIM" \
        --data-binary '{"question":"Can you summarize the product reviews?"}' \
        > "$response_prefix.llm.status" || true
      ;;
    llm_rate_limit)
      : > "$response_prefix.llm.status"
      for _ in $(seq 1 8); do
        curl -sS -o "$response_prefix.llm.json" -w '%{http_code}\n' \
          --max-time "$CURL_MAX_TIME" \
          -H 'Content-Type: application/json' \
          -X POST "$BASE_URL/api/product-ask-ai-assistant/OLJCESPC7Z" \
          --data-binary '{"question":"Can you summarize the product reviews?"}' \
          >> "$response_prefix.llm.status" || true
      done
      ;;
    product_catalog_failure)
      curl -sS -o "$response_prefix.product.json" -w '%{http_code}\n' \
        --max-time "$CURL_MAX_TIME" \
        "$BASE_URL/api/products/OLJCESPC7Z?currencyCode=USD" \
        > "$response_prefix.product.status" || true
      ;;
    loadgen_flood)
      sleep 45
      ;;
  esac
}

case_config() {
  local case_name="$1"
  case "$case_name" in
    payment_failure)
      CASE_SERVICE="payment"; CASE_TARGET="src/payment/charge.js"; CASE_INSTANCE="otel-demo__js__payment__charge__startSpan__L24"; CASE_FLAGS="paymentFailure=100%"; CASE_LOG_SERVICES="payment checkout frontend"; CASE_EVIDENCE='paymentFailure|Payment request failed|Invalid token|app.loyalty.level|Payment charge failed|failed to charge card|error' ;;
    recommendation_cache)
      CASE_SERVICE="recommendation"; CASE_TARGET="src/recommendation/recommendation_server.py"; CASE_INSTANCE="otel-demo__py__recommendation__get_product_list"; CASE_FLAGS="recommendationCacheFailure=on"; CASE_LOG_SERVICES="recommendation frontend"; CASE_EVIDENCE='recommendationCacheFailure|cache|cache hit|cache miss|get_product_list|feature.flag|feature_flag' ;;
    ad_failure)
      CASE_SERVICE="ad"; CASE_TARGET="src/ad/src/main/java/oteldemo/AdService.java"; CASE_INSTANCE="otel-demo__java__ad__AdService__AdServiceImpl_getAds__L149"; CASE_FLAGS="adFailure=on,adHighCpu=on,adManualGc=on"; CASE_LOG_SERVICES="ad frontend"; CASE_EVIDENCE='adFailure|adHighCpu|adManualGc|High CPU|manual garbage|GetAds Failed|UNAVAILABLE|Feature Flag' ;;
    kafka_queue)
      CASE_SERVICE="checkout"; CASE_TARGET="src/checkout/main.go"; CASE_INSTANCE="otel-demo__go__checkout__main__sendToPostProcessor__L630"; CASE_FLAGS="kafkaQueueProblems=on"; CASE_LOG_SERVICES="checkout accounting kafka"; CASE_EVIDENCE='kafkaQueueProblems|overload|Successful to write message|Failed to write message|postProcessor|Kafka' ;;
    payment_unreachable)
      CASE_SERVICE="checkout"; CASE_TARGET="src/checkout/main.go"; CASE_INSTANCE="otel-demo__go__checkout__main__PlaceOrder__L293"; CASE_FLAGS="paymentUnreachable=on"; CASE_LOG_SERVICES="checkout payment frontend"; CASE_EVIDENCE='paymentUnreachable|badAddress|failed to charge|could not charge|payment' ;;
    cart_failure)
      CASE_SERVICE="cart"; CASE_TARGET="src/cart/src/services/CartService.cs"; CASE_INSTANCE="otel-demo__cs__cart__CartService__CartService_EmptyCart__L75"; CASE_FLAGS="cartFailure=on"; CASE_LOG_SERVICES="cart"; CASE_EVIDENCE='cartFailure|EmptyCart|badhost|FailedPrecondition|Can.t access cart storage|empty cart|cart storage' ;;
    failed_readiness_probe)
      CASE_SERVICE="cart"; CASE_TARGET="src/cart/src/services/HealthCheckService.cs"; CASE_INSTANCE="otel-demo__cs__cart__HealthCheckService__HealthServiceImpl_Check__L62"; CASE_FLAGS="failedReadinessProbe=on"; CASE_LOG_SERVICES="cart"; CASE_EVIDENCE='failedReadinessProbe|health check|Health check|NOT_SERVING|NotServing|connection failed|Unhealthy|Received health check request' ;;
    llm_inaccurate)
      CASE_SERVICE="llm"; CASE_TARGET="src/llm/app.py"; CASE_INSTANCE="otel-demo__py__llm__generate_response"; CASE_FLAGS="llmInaccurateResponse=on"; CASE_LOG_SERVICES="llm product-reviews frontend"; CASE_EVIDENCE='llmInaccurateResponse|inaccurate|Returning an inaccurate response|generate_response|L9ECAV7KIM' ;;
    llm_rate_limit)
      CASE_SERVICE="product-reviews"; CASE_TARGET="src/product-reviews/product_reviews_server.py"; CASE_INSTANCE="otel-demo__py__product_reviews__get_ai_assistant_response"; CASE_FLAGS="llmRateLimitError=on"; CASE_LOG_SERVICES="product-reviews llm frontend"; CASE_EVIDENCE='llmRateLimitError|rate-limit|rate limit|Rate limit|Caught Exception|astronomy-llm-rate-limit|unable to process|AI assistant rate-limit probe' ;;
    product_catalog_failure)
      CASE_SERVICE="product-catalog"; CASE_TARGET="src/product-catalog/main.go"; CASE_INSTANCE="otel-demo__go__product_catalog__main__GetProduct__L357"; CASE_FLAGS="productCatalogFailure=on"; CASE_LOG_SERVICES="product-catalog frontend"; CASE_EVIDENCE='productCatalogFailure|OLJCESPC7Z|failed to get product|error|GetProduct' ;;
    loadgen_flood)
      CASE_SERVICE="load-generator"; CASE_TARGET="src/load-generator/locustfile.py"; CASE_INSTANCE="otel-demo__py__load_generator__WebsiteUser_flood_home"; CASE_FLAGS="loadGeneratorFloodHomepage=on"; CASE_LOG_SERVICES="load-generator frontend frontend-proxy"; CASE_EVIDENCE='loadGeneratorFloodHomepage|flood|Flood|homepage|User flooding' ;;
    *) return 1 ;;
  esac
}

collect_logs() {
  local case_name="$1"
  local variant="$2"
  local since="$3"
  local log_file="$OUT_ROOT/logs/${case_name}_${variant}.log"
  dc logs --no-color --since "$since" $CASE_LOG_SERVICES > "$log_file" 2>&1 || true
  local evidence_count=0
  evidence_count=$(grep -Eic "$CASE_EVIDENCE" "$log_file" || true)
  if [[ "$evidence_count" -gt 0 ]]; then
    record "$case_name" "$variant" "evidence_found" "$evidence_count" "$log_file"
  else
    record "$case_name" "$variant" "no_log_evidence" "0" "$log_file"
  fi
}

build_service() {
  local service="$1"
  local variant="$2"
  local case_name="$3"
  local build_log="$OUT_ROOT/logs/${case_name}_${variant}_build.log"
  dc up -d --no-deps --build --force-recreate "$service" > "$build_log" 2>&1
}

run_variant() {
  local case_name="$1"
  local variant="$2"
  case_config "$case_name" || return 1
  local since
  since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  reset_flags
  set_flags "$CASE_FLAGS"
  trigger_case "$case_name" "$variant"
  sleep 8
  collect_logs "$case_name" "$variant" "$since"
  reset_flags
}

run_llm_case() {
  local case_name="$1"
  case_config "$case_name" || return 1
  local artifact
  artifact="$(artifact_path "$CASE_INSTANCE")"
  if [[ ! -f "$artifact" ]]; then
    record "$case_name" "llm" "missing_artifact" "0" "$artifact"
    return 0
  fi

  restore_file "$CASE_TARGET"
  cp "$artifact" "$DEMO_ROOT/$CASE_TARGET"

  if ! build_service "$CASE_SERVICE" "llm" "$case_name"; then
    record "$case_name" "llm" "build_failed" "0" "$OUT_ROOT/logs/${case_name}_llm_build.log"
    restore_file "$CASE_TARGET"
    build_service "$CASE_SERVICE" "restore" "$case_name" >/dev/null 2>&1 || true
    return 0
  fi

  run_variant "$case_name" "llm"

  restore_file "$CASE_TARGET"
  build_service "$CASE_SERVICE" "restore" "$case_name" >/dev/null 2>&1 || true
}

cases=(
  payment_failure
  recommendation_cache
  ad_failure
  kafka_queue
  payment_unreachable
  cart_failure
  failed_readiness_probe
  llm_inaccurate
  llm_rate_limit
  product_catalog_failure
  loadgen_flood
)

if [[ -n "${CASES:-}" ]]; then
  read -r -a cases <<< "$CASES"
fi

printf '[setup] output: %s\n' "$OUT_ROOT"
restore_all_sources
if curl -fsS --max-time 5 "$BASE_URL" >/dev/null 2>&1; then
  printf '[setup] OpenTelemetry Demo already reachable at %s; reusing running services.\n' "$BASE_URL"
  printf 'frontend already reachable at %s; skipped compose up\n' "$BASE_URL" > "$OUT_ROOT/logs/demo_start.log"
else
  printf '[setup] starting OpenTelemetry Demo original services...\n'
  dc up --remove-orphans --detach > "$OUT_ROOT/logs/demo_start.log" 2>&1
fi
if ! wait_url "$BASE_URL" "frontend" 120; then
  record "setup" "original" "frontend_not_ready" "0" "$OUT_ROOT/logs/demo_start.log"
  restore_all_sources
  exit 1
fi

if [[ "$RUN_ORIGINAL" != "0" ]]; then
  printf '[phase] original log evidence\n'
  for case_name in "${cases[@]}"; do
    printf '[original] %s\n' "$case_name"
    run_variant "$case_name" "original"
  done
fi

if [[ "$RUN_LLM" != "0" ]]; then
  printf '[phase] llm log evidence from %s/%s/%s\n' "$RUN_ROOT" "$PROMPT_LEVEL" "$MODEL_ID"
  for case_name in "${cases[@]}"; do
    printf '[llm] %s\n' "$case_name"
    run_llm_case "$case_name"
  done
fi

restore_all_sources
reset_flags

printf '[done] summary: %s\n' "$summary"
cat "$summary"