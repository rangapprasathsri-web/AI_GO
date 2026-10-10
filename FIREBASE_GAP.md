# Firebase Realtime Database Integration Gap Audit (FIREBASE_GAP.md)

**Audit Date**: 2026-10-10  
**Baseline Test Count**: 167 passed, 1059 warnings in 11.12s  
**Architecture Rule**: Engine never imports infrastructure/Firebase code. All storage operations abstracted behind `StorageInterface`.

---

## Gap Matrix

| Section | Feature / Requirement | Status | Existing / Target File Paths | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **1. Goal & Decisions** | Storage-agnostic repository interface | Partly done | `backend/storage/base.py` | Add `save_generation`, `get_generation`, `list_generations`, `get_generation_summary`, `save_feedback`, `get_feedback` to interface. |
| | Firebase Realtime Database implementation | Missing | `backend/storage/firebase_repository.py` | Admin SDK writer, handles live tree `/generations`, `/summaries`, `/config`, `/benchmarks`. |
| | Existing SQLite as fallback/dev implementation | Done | `backend/storage/sqlite_storage.py` | Fully functional; needs fallback wiring in factory. |
| | Auth with Anonymous UID & claims | Missing | `frontend/firebase.js`, `backend/api/main.py` | Anonymous sign-in for client UID, server token verification. |
| **2. SDK & Project Config** | Web config environment variables | Missing | `.env.example`, `frontend/firebase.js` | Ingest user configuration (`ai-go-a6a7a`) without committing secrets. |
| | Config files (`firebase.json`, `database.rules.json`, `.firebaserc.example`) | Missing | Workspace root | Configure RTDB rules, emulator ports, project aliases. |
| | Service account handling | Missing | `backend/storage/firebase_repository.py` | Support `GOOGLE_APPLICATION_CREDENTIALS` and emulator env vars. |
| **3. Architecture** | `FirebaseRepository` module | Missing | `backend/storage/firebase_repository.py` | Implements `StorageInterface` using `firebase_admin.db`. |
| | Frontend Firebase client module | Missing | `frontend/firebase.js` | Uses modular Web SDK v10/v11 with live sync. |
| | Engine import isolation | Done | `backend/engine/` | Pure domain logic; add automated test ensuring 0 Firebase imports. |
| | Repository factory & fallback mechanism | Missing | `backend/storage/factory.py` | Supports `STORAGE_MODE=firebase|local`, auto-fallback to SQLite. |
| | Idempotency & server timestamps | Missing | `backend/storage/firebase_repository.py` | Pre-generated generation IDs and `.sv: "timestamp"`. |
| **4. Data Model** | Schema (`/generations`, `/summaries`, `/config`, `/benchmarks`, `/audit`) | Missing | `database.rules.json`, `backend/storage/firebase_repository.py` | Denormalized RTDB structure, indexing `.indexOn`. |
| | Image reference handling | Done | `backend/adapters/mock_image.py` | Image references and base64 URLs stored; raw bytes omitted from DB. |
| **5. Security Rules** | Rules file with per-user reads and client-write deny | Missing | `database.rules.json` | `$uid === auth.uid`, `.write: false` for client computed paths. |
| **6. Realtime Features** | Frontend live listeners (`onValue` / `onChildAdded`) | Missing | `frontend/index.html`, `frontend/firebase.js` | Live sync for history, summary, and benchmark progress. |
| | Connection state indicator | Missing | `frontend/index.html` | Text pill ("Live", "Reconnecting", "Offline / Local"). |
| | Origin badges preserved in DB | Missing | `backend/storage/firebase_repository.py` | `data_origin` persisted in units object. |
| **7. Failure Handling & Fallback** | Unreachable Firebase fallback to SQLite | Missing | `backend/storage/factory.py`, `backend/api/main.py` | Try Firebase -> catch error -> fallback to SQLite -> log status. |
| | Local storage switch (`STORAGE_MODE=local`) | Missing | `backend/storage/factory.py` | Allows offline demo and unit tests without emulator. |
| | Outbox offline replay | Missing | `backend/storage/outbox.py` | Queues failed writes and replays when connected. |
| **8. Config Versioning** | `/config/active` and `/config/versions` in Firebase | Missing | `backend/storage/firebase_repository.py` | Versioning and atomic rollback in RTDB. |
| **9. Required Tests** | Contract tests for SQLite and Firebase | Missing | `backend/tests/test_storage_contract.py` | Runs identical test battery on SQLite and Firebase. |
| | Engine import isolation test | Missing | `backend/tests/test_firebase_isolation.py` | AST/import check ensuring engine has no Firebase imports. |
| | Fallback and outbox tests | Missing | `backend/tests/test_storage_fallback.py` | Simulates disconnected Firebase and verifies local persistence. |
| | Security rules test / structure | Missing | `backend/tests/test_firebase_rules.py` | Validates `database.rules.json` syntax and rule coverage. |
| **10. Documentation** | `FIREBASE_SETUP.md` & `BUILD_REPORT.md` | Missing | `FIREBASE_SETUP.md`, `BUILD_REPORT.md` | Step-by-step setup, emulator instructions, and test evidence. |

---

## Tier Implementation Order (Section 11)

1. **P0 Foundation**:
   - Update `StorageInterface` in `backend/storage/base.py` to cover generations, summaries, config versions, and feedback.
   - Implement `backend/storage/firebase_repository.py` with Admin SDK (supporting both live credentials and Realtime Database Emulator `FIREBASE_DATABASE_EMULATOR_HOST`).
   - Create `backend/storage/factory.py` with `get_storage()` supporting `STORAGE_MODE=firebase|local` and automatic SQLite fallback.
   - Create `database.rules.json`, `firebase.json`, `.firebaserc.example`, and `.env.example`.
   - Implement frontend Firebase module `frontend/firebase.js` with Web SDK modular imports, anonymous sign-in, and live listeners.
   - Add contract tests, isolation test, and fallback tests.
2. **P1 Enhancements**:
   - Outbox pattern in `backend/storage/outbox.py` for queueing and replaying pending Firebase writes.
   - Realtime connection state indicator in UI ("Live", "Reconnecting", "Offline / Local").
   - Live benchmark progress streaming to `/benchmarks/{runId}`.
   - Outbox replay test suite.
3. **P2 & Verification**:
   - Documentation in `FIREBASE_SETUP.md`.
   - Update `BUILD_REPORT.md` and `ASSUMPTIONS.md`.
