# TEMPORARY review server for the newbie CI walkthrough (removed before merge).
import os, sys
port, user, data = sys.argv[1], sys.argv[2], sys.argv[3]
from garmin_mcp.tokens import generate_key
os.environ.update(GARMIN_MCP_FERNET_KEY=generate_key(), MCP_ENABLED="false", APP_ENABLED="true", PORT=port,
                  HOST="127.0.0.1", DATA_DIR=data, DEV_NO_AUTH_USER=user, RABBIT_FAKE_GARMIN="1",
                  ALLOWED_GOOGLE_USERS=f"{user}@example.com:{user}", PUBLIC_BASE_URL=f"http://localhost:{port}",
                  LOG_LEVEL="WARNING", VAPID_SUBJECT="mailto:dev@localhost.invalid", ANTHROPIC_API_KEY="review-stub",
                  OWNER_USER_IDS=user)
os.makedirs(data, exist_ok=True)
from garmin_mcp import server
server.main()
