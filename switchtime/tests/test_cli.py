from __future__ import annotations

from switchtime.cli import oauth_state

# The real pair from a failed sign-in: the states differ, which is exactly the
# case Nintendo answers with an opaque "session_token_code is invalid".
AUTHORIZE = (
    "https://accounts.nintendo.com/connect/1.0.0/authorize?client_id=54789befb391a838"
    "&redirect_uri=npf54789befb391a838%3A%2F%2Fauth&response_type=session_token_code"
    "&session_token_code_challenge=7hZC5kYl6mComxkv8DB87dPw5BvnP_QWh9kXFW_oKno"
    "&session_token_code_challenge_method=S256"
    "&state=yqGEnvgeWKwpHZsXaUgGVkSZKMSbiQcCYwqDDbNstmeJbTPnYx&theme=login_form"
)
MISMATCHED_REDIRECT = (
    "npf54789befb391a838://auth#session_token_code=eyJhbGciOiJIUzI1NiJ9.PAYLOAD.SIG"
    "&state=NXSoRejSEkPIqJVUMLnaZixCleoNZTnImTnKPaoYqocdUvUsRL"
    "&session_state=e181abea37221cabfdb4366b63819c215be9bec0"
)


class TestOAuthState:
    def test_reads_state_from_the_authorize_query_string(self):
        assert oauth_state(AUTHORIZE) == "yqGEnvgeWKwpHZsXaUgGVkSZKMSbiQcCYwqDDbNstmeJbTPnYx"

    def test_reads_state_from_the_redirect_fragment(self):
        assert oauth_state(MISMATCHED_REDIRECT) == "NXSoRejSEkPIqJVUMLnaZixCleoNZTnImTnKPaoYqocdUvUsRL"

    def test_a_redirect_from_another_attempt_is_detectable(self):
        assert oauth_state(AUTHORIZE) != oauth_state(MISMATCHED_REDIRECT)

    def test_a_matching_pair_agrees(self):
        good = "npf54789befb391a838://auth#session_token_code=abc&state=" + oauth_state(AUTHORIZE)
        assert oauth_state(good) == oauth_state(AUTHORIZE)

    def test_missing_state_is_none_rather_than_an_error(self):
        assert oauth_state("npf54789befb391a838://auth#session_token_code=abc") is None

    def test_surrounding_whitespace_is_tolerated(self):
        assert oauth_state(f"  {MISMATCHED_REDIRECT}  ") is not None

    def test_junk_input_does_not_raise(self):
        assert oauth_state("not a url at all") is None


class TestTokenStorage:
    def test_creates_env_local_with_the_token(self, tmp_path):
        from switchtime.cli import _store_token

        env = tmp_path / ".env.local"
        _store_token(env, "TOKEN123")
        assert "NINTENDO_SESSION_TOKEN=TOKEN123" in env.read_text()

    def test_file_is_not_readable_by_others(self, tmp_path):
        from switchtime.cli import _store_token

        env = tmp_path / ".env.local"
        _store_token(env, "TOKEN123")
        assert oct(env.stat().st_mode)[-3:] == "600"

    def test_replaces_an_existing_token_rather_than_appending(self, tmp_path):
        from switchtime.cli import _store_token

        env = tmp_path / ".env.local"
        env.write_text("NINTENDO_SESSION_TOKEN=OLD\nIXL_PASSWORD_OLIVER=hunter2\n")
        _store_token(env, "NEW")
        body = env.read_text()
        assert "OLD" not in body
        assert body.count("NINTENDO_SESSION_TOKEN=") == 1

    def test_keeps_the_other_secrets(self, tmp_path):
        from switchtime.cli import _store_token

        env = tmp_path / ".env.local"
        env.write_text("NINTENDO_SESSION_TOKEN=OLD\nIXL_PASSWORD_OLIVER=hunter2\n")
        _store_token(env, "NEW")
        assert "IXL_PASSWORD_OLIVER=hunter2" in env.read_text()

    def test_replacing_a_blank_placeholder(self, tmp_path):
        from switchtime.cli import _store_token

        env = tmp_path / ".env.local"
        env.write_text("NINTENDO_SESSION_TOKEN=\nIXL_PASSWORD_ALICE=x\n")
        _store_token(env, "NEW")
        assert "NINTENDO_SESSION_TOKEN=NEW" in env.read_text()


class TestEnvLocalPath:
    def test_sits_beside_the_config_file(self, tmp_path):
        from switchtime.cli import _env_local_path

        config = tmp_path / "config.toml"
        config.touch()
        assert _env_local_path(str(config)) == tmp_path / ".env.local"

    def test_defaults_to_the_working_directory(self):
        from pathlib import Path

        from switchtime.cli import _env_local_path

        assert _env_local_path(None) == Path.cwd() / ".env.local"
