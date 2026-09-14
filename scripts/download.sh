#!/bin/bash
# Atomic downloads with bounded connection/stall waits and readable retry logs.
set -euo pipefail
[[ $# -eq 3 ]] || { echo 'Usage: download.sh LABEL URL DESTINATION' >&2; exit 2; }
label="$1"; url="$2"; destination="$3"
connect="${K3S_DOWNLOAD_CONNECT_TIMEOUT:-10}"
stall="${K3S_DOWNLOAD_STALL_TIMEOUT:-20}"
attempts="${K3S_DOWNLOAD_ATTEMPTS:-4}"
delay="${K3S_DOWNLOAD_RETRY_DELAY:-2}"
for value in "$connect" "$stall" "$attempts" "$delay"; do
  [[ "$value" =~ ^[0-9]+$ ]] && (( value <= 3600 )) || { echo 'Invalid download timing setting' >&2; exit 2; }
done
(( connect > 0 && stall > 0 && attempts > 0 && attempts <= 10 )) || exit 2
mkdir -p "$(dirname "$destination")"
temporary="$(mktemp "${destination}.part.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
printf '\n[Загрузка] %s\nИсточник: %s\n' "$label" "$url"
for (( attempt=1; attempt<=attempts; attempt++ )); do
  printf '[%s] Попытка %s/%s · подключение до %s с · остановка передачи до %s с\n' "$label" "$attempt" "$attempts" "$connect" "$stall"
  if curl --fail --location --silent --show-error --connect-timeout "$connect" --speed-time "$stall" --speed-limit 1024 "$url" -o "$temporary"; then
    mv "$temporary" "$destination"
    printf '[Готово] %s · %s байт\n' "$label" "$(wc -c < "$destination" | tr -d ' ')"
    exit 0
  else
    result=$?
  fi
  printf '[Ошибка загрузки] %s · curl %s\n' "$label" "$result" >&2
  if (( attempt < attempts )); then
    printf '[Повтор] %s через %s с\n' "$label" "$delay"
    sleep "$delay"
  fi
done
printf 'Не удалось скачать %s после %s попыток. Источник: %s\n' "$label" "$attempts" "$url" >&2
exit "$result"
