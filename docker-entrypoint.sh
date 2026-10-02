#!/bin/sh
set -e

echo "🚀 --- InvoiceMate Docker Container Starting --- 🚀"

# Step 1: Initialize Database & Seed
echo "1. Initializing database and running migrations/seeder..."
python main.py

# Step 2: Start FastAPI Web & PDF Hosting Server in background
echo "2. Starting FastAPI Web & PDF Hosting Server on port 8000..."
python -m invoicemate.api.server &
SERVER_PID=$!

# Step 3: Start Telegram Bot in background
echo "3. Starting Telegram Bot..."
python -m invoicemate.bot.bot &
BOT_PID=$!

# Handle shutdown signals gracefully
cleanup() {
    echo "Shutting down InvoiceMate services..."
    kill -TERM "$SERVER_PID" "$BOT_PID" 2>/dev/null || true
    wait "$SERVER_PID" "$BOT_PID" 2>/dev/null || true
    exit 0
}

trap cleanup INT TERM

# Wait for processes
wait "$SERVER_PID" "$BOT_PID"

