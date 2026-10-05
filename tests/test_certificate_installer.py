"""Tests for scripts/certificate-installer.sh (spec §111-112).

Keys and certificates are generated on the fly with `cryptography`; no
private key is ever committed. A fake `docker` and a small in-process TLS
server stand in for Docker and nginx, so no container is needed.
"""
from __future__ import annotations

import datetime as dt
import shutil
import socket
import ssl
import stat
import subprocess
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "certificate-installer.sh"
FQDN = "sign.example.test"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("openssl") is None,
    reason="needs bash and openssl",
)


def make_cert(
    tmp: Path,
    name: str,
    *,
    sans: list[str] | None = None,
    cn: str = FQDN,
    days_from: int = -1,
    days_to: int = 90,
    key=None,
    self_signed: bool = True,
) -> tuple[Path, Path]:
    key = key or ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    issuer = subject if self_signed else x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Some CA")]
    )
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + dt.timedelta(days=days_from))
        .not_valid_after(now + dt.timedelta(days=days_to))
    )
    if sans is not None:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False
        )
    signer = key if self_signed else ec.generate_private_key(ec.SECP256R1())
    cert = builder.sign(signer, hashes.SHA256())
    crt_path, key_path = tmp / f"{name}.crt", tmp / f"{name}.key"
    crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return crt_path, key_path


class Env:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.install = tmp / "install"
        self.certs = self.install / "certs"
        self.install.mkdir()
        (self.install / "docker-compose.yml").write_text("services: {}\n")
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.flags = tmp / "flags"
        self.flags.mkdir()
        shim = self.bin / "docker"
        shim.write_text(
            "#!/bin/sh\n"
            f'FLAGS="{self.flags}"\n'
            'case "$*" in\n'
            '  *"config -q"*) [ -e "$FLAGS/fail_config" ] && exit 1; exit 0 ;;\n'
            '  *"up -d"*) echo "up" >> "$FLAGS/up_calls"; '
            '[ -e "$FLAGS/fail_up" ] && exit 1; exit 0 ;;\n'
            "esac\nexit 0\n"
        )
        shim.chmod(0o755)
        self.port = 0

    def env(self) -> dict[str, str]:
        import os

        return {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "LCIT_SIGN_DIR": str(self.install),
            "LCIT_SIGN_CERT_DIR": str(self.certs),
            "LCIT_SIGN_FQDN": FQDN,
            "LCIT_SIGN_HTTPS_PORT": str(self.port),
            "LCIT_SIGN_VERIFY_TIMEOUT": "3",
        }

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            ["bash", str(SCRIPT), "--test-command", *args],  # noqa: S607
            env=self.env(), capture_output=True, text=True, timeout=60, check=False,
        )

    def flag(self, name: str) -> None:
        (self.flags / name).write_text("1")

    def log(self) -> str:
        path = self.install / "certificate-installer.log"
        return path.read_text() if path.exists() else ""


class TlsServer:
    """Presents whatever certificate is currently in `source_dir`, re-read on
    every connection — what nginx does after a recreate."""

    def __init__(self, source_dir: Path) -> None:
        self.source_dir = source_dir
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(
                    self.source_dir / "tls.crt", self.source_dir / "tls.key"
                )
                with context.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(1)
            except (ssl.SSLError, OSError, FileNotFoundError):
                conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()


@pytest.fixture
def env(tmp_path: Path):
    e = Env(tmp_path)
    yield e


def good_cert(env: Env, name: str = "good", **kw) -> tuple[Path, Path]:
    return make_cert(env.tmp, name, sans=kw.pop("sans", [FQDN]), **kw)


# --- validate-certificate ----------------------------------------------------------


def test_valid_certificate_passes(env):
    crt, key = good_cert(env)
    result = env.run("validate-certificate", str(crt), str(key), FQDN)
    assert result.returncode == 0, result.stderr
    assert "SAN present" in result.stdout


def test_missing_files_are_rejected(env):
    crt, key = good_cert(env)
    assert env.run("validate-certificate", "/nonexistent.crt", str(key), FQDN).returncode == 1
    assert env.run("validate-certificate", str(crt), "/nonexistent.key", FQDN).returncode == 1


def test_bad_pem_is_rejected(env):
    crt, key = good_cert(env)
    bad = env.tmp / "bad.crt"
    bad.write_text("this is not a certificate\n")
    result = env.run("validate-certificate", str(bad), str(key), FQDN)
    assert result.returncode == 1
    assert "not a valid PEM certificate" in result.stderr
    bad_key = env.tmp / "bad.key"
    bad_key.write_text("-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----\n")
    assert env.run("validate-certificate", str(crt), str(bad_key), FQDN).returncode == 1


def test_key_not_matching_certificate_is_rejected(env):
    crt, _ = good_cert(env, "a")
    _, other_key = good_cert(env, "b")
    result = env.run("validate-certificate", str(crt), str(other_key), FQDN)
    assert result.returncode == 1
    assert "does not match" in result.stderr


def test_rsa_key_works_too(env):
    crt, key = make_cert(env.tmp, "rsa", sans=[FQDN], key=rsa.generate_private_key(65537, 2048))
    assert env.run("validate-certificate", str(crt), str(key), FQDN).returncode == 0


def test_expired_certificate_is_rejected(env):
    crt, key = good_cert(env, days_from=-60, days_to=-1)
    result = env.run("validate-certificate", str(crt), str(key), FQDN)
    assert result.returncode == 1 and "expired" in result.stderr


def test_not_yet_valid_certificate_is_rejected(env):
    crt, key = good_cert(env, days_from=5, days_to=90)
    result = env.run("validate-certificate", str(crt), str(key), FQDN)
    assert result.returncode == 1 and "not valid yet" in result.stderr


def test_certificate_without_san_is_rejected(env):
    crt, key = make_cert(env.tmp, "nosan", sans=None)
    result = env.run("validate-certificate", str(crt), str(key), FQDN)
    assert result.returncode == 1 and "no Subject Alternative Name" in result.stderr


def test_fqdn_not_covered_is_rejected(env):
    crt, key = good_cert(env, sans=["other.example.test"])
    result = env.run("validate-certificate", str(crt), str(key), FQDN)
    assert result.returncode == 1 and "not covered" in result.stderr


@pytest.mark.parametrize(
    ("san", "host", "valid"),
    [
        ("*.example.test", "sign.example.test", True),
        ("*.example.test", "SIGN.Example.Test", True),
        ("*.example.test", "a.b.example.test", False),   # wildcard covers one label
        ("*.example.test", "example.test", False),        # ... and not the apex
        ("*.test", "sign.example.test", False),           # no wildcard over a TLD
        ("sign.*.test", "sign.example.test", False),      # only the leftmost label
        ("sign.example.test", "SIGN.EXAMPLE.TEST", True),
    ],
)
def test_wildcard_rules(env, san, host, valid):
    crt, key = good_cert(env, sans=[san])
    result = env.run("validate-certificate", str(crt), str(key), host)
    assert (result.returncode == 0) is valid, result.stderr


def test_missing_intermediate_is_only_a_warning(env):
    crt, key = make_cert(env.tmp, "leaf", sans=[FQDN], self_signed=False)
    result = env.run("validate-certificate", str(crt), str(key), FQDN)
    assert result.returncode == 0
    assert "possible intermediate certificate missing" in result.stderr


# --- copy / permissions --------------------------------------------------------------


def mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))[2:]


def test_copy_certificate_sets_strict_permissions_atomically(env):
    crt, key = good_cert(env)
    result = env.run("copy-certificate", str(crt), str(key), str(env.certs))
    assert result.returncode == 0, result.stderr
    assert mode(env.certs) == "700"
    assert mode(env.certs / "tls.key") == "600"
    assert mode(env.certs / "tls.crt") == "644"
    assert (env.certs / "tls.key").read_bytes() == key.read_bytes()
    assert not [p for p in env.certs.iterdir() if p.name.startswith(".")]  # no temp leftovers


def test_validate_installation_detects_loose_key_permissions(env):
    crt, key = good_cert(env)
    env.run("copy-certificate", str(crt), str(key), str(env.certs))
    server = TlsServer(env.certs)
    env.port = server.port
    try:
        assert env.run("validate-installation").returncode == 0
        (env.certs / "tls.key").chmod(0o644)
        result = env.run("validate-installation")
        assert result.returncode == 1 and "mode 644 (expected 600)" in result.stderr
    finally:
        server.close()


# --- install, runtime fingerprint, rollback ------------------------------------------


def test_install_succeeds_and_verifies_the_presented_certificate(env):
    old_crt, old_key = good_cert(env, "old")
    env.run("copy-certificate", str(old_crt), str(old_key), str(env.certs))
    new_crt, new_key = good_cert(env, "new")
    server = TlsServer(env.certs)
    env.port = server.port
    try:
        result = env.run("install-certificate", str(new_crt), str(new_key))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "presents the new certificate" in result.stdout
        assert (env.certs / "tls.crt").read_bytes() == new_crt.read_bytes()
        assert "result=success" in env.log()
        assert "BEGIN" not in env.log()  # no key material in the trace
        assert (env.tmp / "install" / "certs.backup" / "tls.crt").read_bytes() == (
            old_crt.read_bytes()
        )
    finally:
        server.close()


def test_invalid_certificate_changes_nothing(env):
    old_crt, old_key = good_cert(env, "old")
    env.run("copy-certificate", str(old_crt), str(old_key), str(env.certs))
    expired_crt, expired_key = good_cert(env, "exp", days_from=-60, days_to=-1)
    result = env.run("install-certificate", str(expired_crt), str(expired_key))
    assert result.returncode == 1
    assert "nothing was changed" in result.stderr
    assert (env.certs / "tls.crt").read_bytes() == old_crt.read_bytes()
    assert not (env.flags / "up_calls").exists()


def test_proxy_that_does_not_start_triggers_rollback(env):
    old_crt, old_key = good_cert(env, "old")
    env.run("copy-certificate", str(old_crt), str(old_key), str(env.certs))
    new_crt, new_key = good_cert(env, "new")
    env.flag("fail_up")
    result = env.run("install-certificate", str(new_crt), str(new_key))
    assert result.returncode == 1
    assert "did not start" in result.stderr
    assert (env.certs / "tls.crt").read_bytes() == old_crt.read_bytes()
    assert (env.certs / "tls.key").read_bytes() == old_key.read_bytes()
    assert "rollback=yes" in env.log()


def test_invalid_compose_triggers_rollback(env):
    old_crt, old_key = good_cert(env, "old")
    env.run("copy-certificate", str(old_crt), str(old_key), str(env.certs))
    new_crt, new_key = good_cert(env, "new")
    env.flag("fail_config")
    result = env.run("install-certificate", str(new_crt), str(new_key))
    assert result.returncode == 1 and "configuration is invalid" in result.stderr
    assert (env.certs / "tls.crt").read_bytes() == old_crt.read_bytes()


def test_wrong_certificate_presented_triggers_rollback(env, tmp_path):
    old_crt, old_key = good_cert(env, "old")
    env.run("copy-certificate", str(old_crt), str(old_key), str(env.certs))
    new_crt, new_key = good_cert(env, "new")
    # A proxy that keeps serving the OLD certificate whatever is on disk.
    frozen = tmp_path / "frozen"
    env.run("copy-certificate", str(old_crt), str(old_key), str(frozen))
    server = TlsServer(frozen)
    env.port = server.port
    try:
        result = env.run("install-certificate", str(new_crt), str(new_key))
        assert result.returncode == 1
        assert "presents a different certificate" in result.stderr
        assert (env.certs / "tls.crt").read_bytes() == old_crt.read_bytes()
        assert "rollback=yes" in env.log()
    finally:
        server.close()


def test_first_install_rollback_removes_the_files(env):
    new_crt, new_key = good_cert(env, "new")
    env.flag("fail_up")
    result = env.run("install-certificate", str(new_crt), str(new_key))
    assert result.returncode == 1
    assert not (env.certs / "tls.crt").exists()
    assert not (env.certs / "tls.key").exists()


def test_revert_to_selfsigned_removes_custom_files_and_verifies_tls(env):
    crt, key = good_cert(env)
    env.run("copy-certificate", str(crt), str(key), str(env.certs))
    selfsigned_dir = env.tmp / "selfsigned"
    ss_crt, ss_key = good_cert(env, "ss")
    env.run("copy-certificate", str(ss_crt), str(ss_key), str(selfsigned_dir))
    server = TlsServer(selfsigned_dir)  # what nginx falls back to
    env.port = server.port
    try:
        result = env.run("revert-selfsigned")
        assert result.returncode == 0, result.stdout + result.stderr
        assert not (env.certs / "tls.crt").exists()
        assert "self-signed" in result.stdout
    finally:
        server.close()


def test_show_current_prints_the_presented_certificate(env):
    crt, key = good_cert(env, sans=[FQDN, "alt.example.test"])
    env.run("copy-certificate", str(crt), str(key), str(env.certs))
    server = TlsServer(env.certs)
    env.port = server.port
    try:
        result = env.run("show-current")
        assert result.returncode == 0, result.stderr
        for label in ("Subject", "Issuer", "Valid from", "Valid until",
                      "Days remaining", "SAN", "SHA-256"):
            assert label in result.stdout
        assert "alt.example.test" in result.stdout
        assert "BEGIN" not in result.stdout
    finally:
        server.close()


def test_show_current_warns_when_expiry_is_near(env):
    crt, key = good_cert(env, days_to=10)
    env.run("copy-certificate", str(crt), str(key), str(env.certs))
    server = TlsServer(env.certs)
    env.port = server.port
    try:
        result = env.run("show-current")
        assert "expires in less than 30 days" in result.stderr
    finally:
        server.close()
