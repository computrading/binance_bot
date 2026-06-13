#!/bin/bash

# Controllo parametro
if [ -z "$1" ]; then
  echo "Usage: $0 <log_file>"
  exit 1
fi

LOG_FILE="$1"


# Config Telegram
set -a
source .env
set +a

while read line; do
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    -d "text=${line}" > /dev/null
done < <(tail -F "$LOG_FILE")
