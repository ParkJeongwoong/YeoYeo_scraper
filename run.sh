#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/logs/flaskServer.pid"
LOG_FILE="$SCRIPT_DIR/logs/flaskServer.out.log"

find_python() {
  local candidates=(
    "$SCRIPT_DIR/.venv_flask/bin/python"
    "$SCRIPT_DIR/.venv/bin/python"
    "python3"
    "python"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ "$candidate" == */* ]]; then
      if [[ -x "$candidate" ]]; then
        echo "$candidate"
        return 0
      fi
    elif command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  return 1
}

is_running() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi

  local pid
  pid="$(cat "$PID_FILE")"

  if [[ -z "$pid" ]]; then
    return 1
  fi

  if kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  rm -f "$PID_FILE"
  return 1
}

start_server() {
  if is_running; then
    echo "flaskServer.py is already running. pid=$(cat "$PID_FILE")"
    return 0
  fi

  mkdir -p "$SCRIPT_DIR/logs"

  local python_bin
  python_bin="$(find_python)" || {
    echo "Python executable not found. Expected .venv_flask/bin/python, .venv/bin/python, python3, or python."
    return 1
  }

  cd "$SCRIPT_DIR" || return 1

  nohup env PYTHONUNBUFFERED=1 "$python_bin" flaskServer.py >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" >"$PID_FILE"

  sleep 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "flaskServer.py started. pid=$pid log=$LOG_FILE"
    return 0
  fi

  rm -f "$PID_FILE"
  echo "Failed to start flaskServer.py. Check $LOG_FILE"
  return 1
}

stop_server() {
  if ! is_running; then
    echo "flaskServer.py is not running."
    return 0
  fi

  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" >/dev/null 2>&1 || true

  local i
  for i in {1..10}; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$PID_FILE"
      echo "flaskServer.py stopped."
      return 0
    fi
    sleep 1
  done

  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
  echo "flaskServer.py force-stopped."
}

status_server() {
  if is_running; then
    echo "flaskServer.py is running. pid=$(cat "$PID_FILE")"
  else
    echo "flaskServer.py is not running."
  fi
}

case "${1:-start}" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    status_server
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
