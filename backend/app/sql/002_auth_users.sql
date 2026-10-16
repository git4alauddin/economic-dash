-- Private identity state; passwords are never stored in plaintext.
CREATE TABLE auth_users (
    user_id TEXT PRIMARY KEY CHECK(length(user_id) = 32 AND user_id NOT GLOB '*[^0-9a-f]*'),
    username TEXT NOT NULL UNIQUE CHECK(length(username) BETWEEN 3 AND 64
        AND username = lower(username) AND substr(username, 1, 1) GLOB '[a-z]'
        AND username NOT GLOB '*[^a-z0-9_.-]*'),
    password_hash TEXT NOT NULL CHECK(length(password_hash) BETWEEN 80 AND 512
        AND password_hash LIKE '$argon2id$v=19$%'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    credential_version INTEGER NOT NULL DEFAULT 1 CHECK(credential_version > 0),
    created_at TEXT NOT NULL CHECK(length(created_at) = 27 AND created_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(created_at) IS NOT NULL),
    updated_at TEXT NOT NULL CHECK(length(updated_at) = 27 AND updated_at GLOB '????-??-??T??:??:??.??????Z' AND julianday(updated_at) IS NOT NULL AND updated_at >= created_at)
) STRICT;
