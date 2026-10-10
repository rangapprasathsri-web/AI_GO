# Firebase Realtime Database Integration & Setup Guide

This document describes the Firebase Realtime Database integration for the **AI GO** platform (`project: ai-go-a6a7a`, database instance: `ai-go-a6a7a-default-rtdb`).

---

## 1. Architecture Overview

- **Primary Cloud Store**: Firebase Realtime Database (RTDB)
  - URL: `https://ai-go-a6a7a-default-rtdb.firebaseio.com/`
  - Project ID: `ai-go-a6a7a`
- **Backend Writer**: Python Admin SDK (`FirebaseRepository`)
  - Server-authoritative computation of units, energy Joules, purpose-fit verdicts, and avoided savings.
  - Clients are denied direct write permissions to computed metrics.
- **Local Fallback Store**: SQLite Storage (`SQLiteStorage`)
  - Enabled when `STORAGE_MODE=local` or when Firebase credentials / network are unavailable.
  - Zero crashes; writes are buffered in `OutboxQueue` (`data/outbox.json`) for seamless replay.
- **Engine Zero-Dependency Invariant**:
  - `backend/engine/` contains 0 imports of Firebase or storage layers. Verified via AST unit test (`test_firebase_isolation.py`).

---

## 2. Security Rules (`database.rules.json`)

The deployed database rules enforce:
1. **User Scoping**: Users can only read their own generations and running summary:
   - `/generations/$uid`: `.read: "auth != null && auth.uid === $uid"`, `.write: false`
   - `/summaries/$uid`: `.read: "auth != null && auth.uid === $uid"`, `.write: false`
2. **Public / Authenticated Reads**:
   - `/config/active` and `/config/versions`: Readable by all clients; write-restricted to admin.
3. **Admin Authoritative Writes**:
   - Client writes to computed metrics are denied (`.write: false`). All writes are signed by backend Firebase Admin SDK credentials.

---

## 3. Running with Live Firebase Credentials

1. Go to the [Firebase Console Service Accounts Page](https://console.firebase.google.com/u/1/project/ai-go-a6a7a/settings/serviceaccounts/adminsdk).
2. Click **Generate new private key** and download the JSON file.
3. Save it securely on your host (e.g. `serviceAccountKey.json`) — **never commit this file to git**.
4. Set the environment variable:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/serviceAccountKey.json"
   export FIREBASE_DATABASE_URL="https://ai-go-a6a7a-default-rtdb.firebaseio.com/"
   export STORAGE_MODE="firebase"
   ```
5. Start the backend:
   ```bash
   python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
   ```
6. Check `http://localhost:8000/health`:
   ```json
   {
     "status": "healthy",
     "storage": {
       "active_backend": "firebase",
       "primary_reachable": true,
       "outbox_pending_count": 0
     }
   }
   ```

---

## 4. Running with the Firebase Emulator Suite

To develop or test completely offline without live Google credentials:
```bash
# Install Firebase CLI if not already installed
npm install -g firebase-tools

# Start the Realtime Database emulator
firebase emulators:start --only database

# In your application terminal:
export FIREBASE_DATABASE_EMULATOR_HOST="127.0.0.1:9000"
export STORAGE_MODE="firebase"
pytest backend/tests/
```

---

## 5. Offline Fallback Mode (Default when uncredentialed)

When `GOOGLE_APPLICATION_CREDENTIALS` is not set:
- The system automatically engages `active_backend: "sqlite (fallback)"`.
- Full platform functionality remains available: generation, purpose routing, quality gates, history, and benchmarks.
- No network timeouts, no crashes, 100% test pass rate.
