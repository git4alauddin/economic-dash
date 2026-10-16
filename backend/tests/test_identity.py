"""Private account lifecycle and provisioning; all credentials are test fixtures."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from getpass import GetPassWarning
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
import warnings

from argon2 import PasswordHasher

from app.auth import passwords, provision
from app.auth.passwords import PasswordWorkBusy, hash_password, normalize_username, verify_password
from app.auth.users import AccountConflict, UserStore
from app.config import DatabaseSettings
from app.database import Database
from app.migrations import migration_plan
from app.repository import SQLiteCollectionRepository
from test_normalization import wb
from test_repository import prepare

PASSWORD = "synthetic fixture passphrase 42"
REPLACEMENT = "another synthetic passphrase 73"


class IdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = DatabaseSettings(_env_file=None, app_env="test", directory=Path(temporary.name) / "db")
        self.database = Database(self.settings)
        self.database.bootstrap()
        self.store = UserStore(self.database)

    def row(self):
        with self.database.connection(read_only=True) as connection:
            return dict(connection.execute("SELECT * FROM auth_users").fetchone())

    def test_create_normalize_verify_and_keep_password_out_of_identity_and_sql_files(self):
        result = self.store.provision("  Evaluator  ", PASSWORD)
        self.assertEqual((result.action, result.identity.username), ("created", "evaluator"))
        row = self.row()
        self.assertTrue(row["password_hash"].startswith("$argon2id$v=19$m=65536,t=3,p=4$"))
        self.assertNotIn(PASSWORD, json.dumps(row))
        self.assertNotIn(PASSWORD.encode(), self.settings.path.read_bytes())
        self.assertNotIn("password", repr(result).lower())
        self.assertEqual(self.store.authenticate("EVALUATOR", PASSWORD), result.identity)
        self.assertIsNone(self.store.authenticate("evaluator", REPLACEMENT))
        self.assertIsNone(self.store.authenticate("missing-user", PASSWORD))
        self.assertEqual(self.store.get(result.identity.user_id), result.identity)

    def test_salts_differ_and_repeat_provisioning_keeps_account_hash_and_timestamps(self):
        first = self.store.provision("evaluator", PASSWORD)
        old = self.row()
        self.assertEqual(self.store.provision(" EVALUATOR ", PASSWORD).action, "unchanged")
        self.assertEqual(self.row(), old)
        second = self.store.provision("developer", PASSWORD)
        with self.database.connection(read_only=True) as connection:
            hashes = [r[0] for r in connection.execute("SELECT password_hash FROM auth_users")]
        self.assertEqual(len(set(hashes)), 2)
        self.assertNotEqual(first.identity.user_id, second.identity.user_id)

    def test_password_reset_requires_explicit_action_and_preserves_identity_and_disabled_status(self):
        original = self.store.provision("evaluator", PASSWORD).identity
        with self.assertRaises(AccountConflict):
            self.store.provision("evaluator", REPLACEMENT)
        disabled = self.store.set_active("evaluator", False)
        changed = self.store.provision("evaluator", REPLACEMENT, reset_password=True)
        self.assertEqual(changed.action, "password_reset")
        self.assertEqual(changed.identity.user_id, original.user_id)
        self.assertFalse(changed.identity.is_active)
        self.assertEqual(changed.identity.credential_version, disabled.credential_version + 1)
        self.assertIsNone(self.store.authenticate("evaluator", PASSWORD))
        self.assertIsNone(self.store.authenticate("evaluator", REPLACEMENT))
        self.store.set_active("evaluator", True)
        self.assertIsNotNone(self.store.authenticate("evaluator", REPLACEMENT))
        with self.assertRaises(AccountConflict):
            self.store.provision("missing-user", PASSWORD, reset_password=True)

    def test_disable_and_enable_are_idempotent_and_advance_credential_version_on_changes(self):
        original = self.store.provision("evaluator", PASSWORD).identity
        disabled = self.store.set_active("Evaluator", False)
        self.assertEqual(disabled.credential_version, original.credential_version + 1)
        self.assertEqual(self.store.set_active("evaluator", False), disabled)
        self.assertEqual(self.store.provision("evaluator", PASSWORD).identity, disabled)
        self.assertIsNone(self.store.authenticate("evaluator", PASSWORD))
        active = self.store.set_active("evaluator", True)
        self.assertEqual(active.credential_version, disabled.credential_version + 1)
        self.assertEqual(self.store.set_active("evaluator", True), active)
        self.assertEqual(self.store.authenticate("evaluator", PASSWORD), active)
        with self.assertRaises(AccountConflict):
            self.store.set_active("missing-user", False)

    def test_password_and_identifier_limits_preserve_exact_unicode_and_spaces(self):
        self.assertEqual(normalize_username(" Alice.Name-1 "), "alice.name-1")
        for name in ("ab", "9user", "a" * 65, "a b", "\u212Aelvin", "'; DROP TABLE auth_users;--"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.provision(name, PASSWORD)
        for password in ("short", " " * 20, "x" * 129, "passphrase with\x00nul", "passphrase with\nnewline", "passphrase with\x85control", "x" * 16 + "\ud800"):
            with self.subTest(password_length=len(password)), self.assertRaises(ValueError):
                self.store.provision("evaluator", password)
        exact = "  a long \u0928\u092e\u0938\u094d\u0924\u0947 passphrase  "
        self.store.provision("evaluator", exact)
        self.assertIsNotNone(self.store.authenticate("evaluator", exact))
        self.assertIsNone(self.store.authenticate("evaluator", exact.strip()))
        self.assertIsNone(self.store.get("' OR 1=1;--"))

    def test_unknown_inactive_and_corrupt_hashes_use_bounded_dummy_verification(self):
        self.store.provision("evaluator", PASSWORD)
        self.store.set_active("evaluator", False)
        with patch("app.auth.passwords.HASHER", wraps=passwords.HASHER) as hasher:
            self.assertIsNone(self.store.authenticate("missing-user", PASSWORD))
            self.assertIsNone(self.store.authenticate("evaluator", PASSWORD))
            self.assertIsNone(self.store.authenticate("invalid username", PASSWORD))
            self.assertFalse(verify_password("not-a-valid-hash", PASSWORD))
            self.assertTrue(all(c.args[0] == passwords._DUMMY_HASH for c in hasher.verify.call_args_list))
        self.store.set_active("evaluator", True)
        with self.database.transaction() as connection:
            connection.execute("UPDATE auth_users SET password_hash=?", ("$argon2id$v=19$" + "x" * 90,))
        self.assertIsNone(self.store.authenticate("evaluator", PASSWORD))

    def test_legacy_hash_is_upgraded_without_changing_identity_or_credential_version(self):
        original = self.store.provision("evaluator", PASSWORD).identity
        legacy = PasswordHasher(memory_cost=8192, time_cost=1, parallelism=1).hash(PASSWORD)
        with self.database.transaction() as connection:
            connection.execute("UPDATE auth_users SET password_hash=?", (legacy,))
        self.assertEqual(self.store.authenticate("evaluator", PASSWORD), original)
        self.assertNotEqual(self.row()["password_hash"], legacy)
        self.assertFalse(passwords.needs_rehash(self.row()["password_hash"]))

    def test_corrupt_high_cost_hash_does_not_allocate_its_claimed_memory(self):
        encoded = hash_password(PASSWORD).replace("m=65536", "m=1073741824")
        with patch("app.auth.passwords.HASHER", wraps=passwords.HASHER) as hasher:
            self.assertFalse(verify_password(encoded, PASSWORD))
            self.assertEqual(hasher.verify.call_args.args[0], passwords._DUMMY_HASH)

    def test_password_work_capacity_fails_safely_and_recovers(self):
        with passwords._work(), passwords._work():
            with self.assertRaises(PasswordWorkBusy):
                verify_password(None, PASSWORD)
        self.assertTrue(verify_password(hash_password(PASSWORD), PASSWORD))

    def test_concurrent_disable_wins_over_an_already_verified_password(self):
        self.store.provision("evaluator", PASSWORD)
        original = verify_password
        def disable_after_verify(encoded, supplied):
            matched = original(encoded, supplied)
            self.store.set_active("evaluator", False)
            return matched
        with patch("app.auth.users.verify_password", side_effect=disable_after_verify):
            self.assertIsNone(self.store.authenticate("evaluator", PASSWORD))

    def test_concurrent_provisioning_does_not_overwrite_the_winning_password(self):
        barrier = Barrier(2)
        def concurrent_hash(value):
            barrier.wait(timeout=5)
            return hash_password(value)
        def create(value):
            try:
                return self.store.provision("evaluator", value)
            except AccountConflict:
                return None
        with patch("app.auth.users.hash_password", side_effect=concurrent_hash), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, value) for value in (PASSWORD, REPLACEMENT)]
            outcomes = [f.result(timeout=10) for f in futures]
        self.assertEqual(sum(r is not None for r in outcomes), 1)
        self.assertEqual(sum(self.store.authenticate("evaluator", value) is not None for value in (PASSWORD, REPLACEMENT)), 1)

    def test_database_constraints_reject_plaintext_and_invalid_identity_state(self):
        self.store.provision("evaluator", PASSWORD)
        for sql, values in (("UPDATE auth_users SET password_hash=?", (PASSWORD,)),
                            ("UPDATE auth_users SET is_active=?", (2,)),
                            ("UPDATE auth_users SET credential_version=?", (0,)),
                            ("UPDATE auth_users SET username=?", ("UNNORMALIZED",))):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
                connection.execute(sql, values)

    def test_version_one_upgrade_retains_collector_data_and_migration_checksum(self):
        settings = DatabaseSettings(_env_file=None, directory=self.settings.directory / "v1")
        old = Database(settings)
        plan = migration_plan()
        with patch("app.migrations.SCHEMA_VERSION", 1), patch("app.migrations.migration_plan", return_value=plan[:1]):
            old.bootstrap()
        repository = SQLiteCollectionRepository(old)
        repository.commit(prepare(wb))
        checkpoint = repository.load()
        with old.connection(read_only=True) as connection:
            before = [tuple(r) for r in connection.execute("SELECT * FROM observations")]
            checksum = connection.execute("SELECT checksum FROM schema_migrations WHERE version=1").fetchone()[0]
        old.bootstrap()
        old.bootstrap()
        with old.connection(read_only=True) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT checksum FROM schema_migrations WHERE version=1").fetchone()[0], checksum)
            self.assertEqual([tuple(r) for r in connection.execute("SELECT * FROM observations")], before)
            self.assertEqual(connection.execute("SELECT count(*) FROM auth_users").fetchone()[0], 0)
        self.assertEqual(repository.load(), checkpoint)

    def cli(self, arguments, *, tty=True, prompts=(PASSWORD, PASSWORD)):
        output, errors = StringIO(), StringIO()
        with patch("app.auth.provision.get_database_settings", return_value=self.settings), \
                patch("app.auth.provision.sys.stdin.isatty", return_value=tty), \
                patch("app.auth.provision.getpass", side_effect=prompts) as prompt, \
                redirect_stdout(output), redirect_stderr(errors):
            status = provision.main(arguments)
        return status, output.getvalue(), errors.getvalue(), prompt.call_count

    def test_cli_prompts_privately_repeats_and_admin_status_actions_need_no_password(self):
        for expected in ("created", "unchanged"):
            code, output, error, prompts = self.cli(["--username", "evaluator"])
            self.assertEqual((code, error, prompts), (0, "", 2))
            self.assertEqual(json.loads(output)["action"], expected)
            self.assertNotIn(PASSWORD, output + error)
            self.assertNotIn("argon2", output + error)
        code, output, error, prompts = self.cli(["--username", "evaluator", "--disable"], tty=False)
        self.assertEqual((code, prompts), (0, 0))
        self.assertFalse(json.loads(output)["is_active"])

    def test_cli_rejects_noninteractive_mismatch_and_echo_fallback_without_writing_account(self):
        cases = ((False, (PASSWORD, PASSWORD)), (True, (PASSWORD, REPLACEMENT)))
        for tty, prompts in cases:
            code, output, errors, _ = self.cli(["--username", "evaluator"], tty=tty, prompts=prompts)
            self.assertEqual(code, 1)
            self.assertNotIn(PASSWORD, output + errors)
            self.assertIsNone(self.store._record("evaluator"))
        def insecure_prompt(*args):
            warnings.warn("Cannot control echo on the terminal.", GetPassWarning)
            return PASSWORD
        code, output, errors, _ = self.cli(["--username", "evaluator"], prompts=insecure_prompt)
        self.assertEqual(code, 1)
        self.assertIsNone(self.store._record("evaluator"))
        self.assertNotIn(PASSWORD, output + errors)

    def test_cli_storage_errors_do_not_leak_paths_or_credentials(self):
        with patch("app.auth.provision.Database.bootstrap", side_effect=sqlite3.OperationalError("private path " + PASSWORD)):
            code, output, errors, _ = self.cli(["--username", "evaluator"])
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertEqual(errors, "Account operation could not be completed.\n")

    def test_cli_explicit_reset_enable_and_accidental_password_arguments(self):
        self.store.provision("evaluator", PASSWORD)
        code, output, errors, _ = self.cli(["--username", "evaluator", "--reset-password"], prompts=(REPLACEMENT, REPLACEMENT))
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["action"], "password_reset")
        self.store.set_active("evaluator", False)
        code, output, errors, prompts = self.cli(["--username", "evaluator", "--enable"], tty=False)
        self.assertEqual((code, prompts), (0, 0))
        self.assertIsNotNone(self.store.authenticate("evaluator", REPLACEMENT))
        errors = StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as exit_error:
            provision.main(["--username", "evaluator", "--password", PASSWORD])
        self.assertEqual(exit_error.exception.code, 2)
        self.assertNotIn(PASSWORD, errors.getvalue())


if __name__ == "__main__":
    unittest.main()
