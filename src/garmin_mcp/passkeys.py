"""Server-side WebAuthn (passkeys) verification, ES256 + RS256, no extra dependencies.

The ``webauthn`` PyPI package couldn't be installed for this build, so this is a small,
strict implementation on top of ``cryptography``:

* a minimal CBOR decoder (definite lengths only; the subset authenticators emit),
* COSE key -> public key (EC2 P-256 / alg -7, RSA / alg -257),
* registration: clientDataJSON (type, challenge, origin, no crossOrigin), authenticator
  data (rpIdHash, UP flag, attested credential data). Attestation statements are not
  verified: we ask for ``attestation: "none"`` and don't trust attestation either way,
  which is what "none" conveyance means.
* authentication: clientDataJSON, rpIdHash, UP flag, signature over
  ``authData || SHA-256(clientDataJSON)``, and the sign counter (must grow when either
  side is non-zero; synced passkeys report 0).

User verification is "preferred", so the UV flag is recorded but not required.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

ES256, RS256 = -7, -257
ALGS = (ES256, RS256)
MAX_CRED_ID = 1023

FLAG_UP, FLAG_UV, FLAG_AT, FLAG_ED = 0x01, 0x04, 0x40, 0x80


class WebAuthnError(ValueError):
    """Verification failed. The message is for logs; users get a generic error."""


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    if not isinstance(s, str) or len(s) > 16384:
        raise WebAuthnError("bad base64url")
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except Exception as e:
        raise WebAuthnError("bad base64url") from e


# ------------------------------------------------------------------- CBOR --
class _Cbor:
    def __init__(self, data: bytes) -> None:
        self.d, self.i, self.depth = data, 0, 0

    def _take(self, n: int) -> bytes:
        if n < 0 or self.i + n > len(self.d):
            raise WebAuthnError("truncated CBOR")
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def _arg(self, info: int) -> int:
        if info < 24:
            return info
        size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
        if size is None:
            raise WebAuthnError("unsupported CBOR length")  # indefinite lengths aren't used here
        return int.from_bytes(self._take(size), "big")

    def item(self) -> Any:
        self.depth += 1
        if self.depth > 16:
            raise WebAuthnError("CBOR too deep")
        try:
            ib = self._take(1)[0]
            major, info = ib >> 5, ib & 0x1F
            if major == 7:
                if info == 20:
                    return False
                if info == 21:
                    return True
                if info in (22, 23):
                    return None
                if info == 25:
                    return _half(self._take(2))
                if info == 26:
                    return struct.unpack(">f", self._take(4))[0]
                if info == 27:
                    return struct.unpack(">d", self._take(8))[0]
                raise WebAuthnError("unsupported CBOR simple value")
            n = self._arg(info)
            if major == 0:
                return n
            if major == 1:
                return -1 - n
            if major == 2:
                return self._take(n)
            if major == 3:
                return self._take(n).decode("utf-8")
            if major == 4:
                if n > 1024:
                    raise WebAuthnError("CBOR array too long")
                return [self.item() for _ in range(n)]
            if major == 5:
                if n > 1024:
                    raise WebAuthnError("CBOR map too long")
                out: dict[Any, Any] = {}
                for _ in range(n):
                    k = self.item()
                    if isinstance(k, (list, dict)):
                        raise WebAuthnError("unsupported CBOR map key")
                    out[k] = self.item()
                return out
            if major == 6:
                return self.item()  # tag: keep the content
            raise WebAuthnError("bad CBOR")
        finally:
            self.depth -= 1


def _half(b: bytes) -> float:
    h = int.from_bytes(b, "big")
    exp, frac = (h >> 10) & 0x1F, h & 0x3FF
    val = (frac / 1024 * 2 ** -14) if exp == 0 else (float("inf") if exp == 31 else (1 + frac / 1024) * 2 ** (exp - 15))
    return -val if h & 0x8000 else val


def cbor_decode(data: bytes) -> Any:
    """Decode one CBOR item; trailing bytes are an error."""
    item, end = cbor_decode_prefix(data)
    if end != len(data):
        raise WebAuthnError("trailing CBOR bytes")
    return item


def cbor_decode_prefix(data: bytes) -> tuple[Any, int]:
    """Decode one CBOR item from the start of ``data``; returns (item, bytes used)."""
    p = _Cbor(data)
    try:
        item = p.item()
    except WebAuthnError:
        raise
    except Exception as e:  # bad UTF-8 and friends
        raise WebAuthnError("bad CBOR") from e
    return item, p.i


# -------------------------------------------------------------- COSE keys --
def cose_public_key(cose: bytes) -> tuple[int, Any]:
    """COSE_Key bytes -> (alg, cryptography public key). Only ES256 and RS256."""
    key = cbor_decode(cose)
    if not isinstance(key, dict):
        raise WebAuthnError("bad COSE key")
    kty, alg = key.get(1), key.get(3)
    try:
        if kty == 2 and alg == ES256:
            if key.get(-1) != 1:
                raise WebAuthnError("EC key must be P-256")
            x, y = key.get(-2), key.get(-3)
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
                raise WebAuthnError("bad EC point")
            return alg, ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x04" + x + y)
        if kty == 3 and alg == RS256:
            n, e = key.get(-1), key.get(-2)
            if not (isinstance(n, bytes) and isinstance(e, bytes)) or len(n) < 256:
                raise WebAuthnError("bad RSA key")  # at least 2048-bit
            return alg, rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
    except WebAuthnError:
        raise
    except Exception as e:
        raise WebAuthnError("bad COSE key") from e
    raise WebAuthnError("unsupported key type")


def _verify_sig(cose: bytes, signature: bytes, data: bytes) -> None:
    alg, pub = cose_public_key(cose)
    try:
        if alg == ES256:
            pub.verify(signature, data, ec.ECDSA(hashes.SHA256()))
        else:
            pub.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as e:
        raise WebAuthnError("bad signature") from e


# ------------------------------------------------------- auth data parse --
@dataclass
class AuthData:
    rp_id_hash: bytes
    flags: int
    sign_count: int
    cred_id: bytes = b""
    cose_key: bytes = b""

    @property
    def user_verified(self) -> bool:
        return bool(self.flags & FLAG_UV)


def parse_auth_data(data: bytes) -> AuthData:
    if len(data) < 37:
        raise WebAuthnError("authenticator data too short")
    ad = AuthData(data[:32], data[32], int.from_bytes(data[33:37], "big"))
    rest = data[37:]
    if ad.flags & FLAG_AT:
        if len(rest) < 18:
            raise WebAuthnError("attested data too short")
        n = int.from_bytes(rest[16:18], "big")
        if n == 0 or n > MAX_CRED_ID or len(rest) < 18 + n:
            raise WebAuthnError("bad credential id")
        ad.cred_id = rest[18:18 + n]
        _, used = cbor_decode_prefix(rest[18 + n:])
        ad.cose_key = rest[18 + n:18 + n + used]
        rest = rest[18 + n + used:]
    if ad.flags & FLAG_ED:
        _, used = cbor_decode_prefix(rest)
        rest = rest[used:]
    if rest:
        raise WebAuthnError("trailing authenticator data")
    return ad


def _client_data(raw: bytes, kind: str, origin: str) -> dict[str, Any]:
    try:
        cd = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise WebAuthnError("bad clientDataJSON") from e
    if not isinstance(cd, dict) or cd.get("type") != kind:
        raise WebAuthnError("wrong ceremony type")
    if cd.get("origin") != origin:
        raise WebAuthnError("wrong origin")
    if cd.get("crossOrigin") is True:
        raise WebAuthnError("cross-origin")
    if not isinstance(cd.get("challenge"), str):
        raise WebAuthnError("no challenge")
    return cd


def client_challenge(credential: dict[str, Any]) -> str:
    """The challenge the browser signed (look it up, then verify against it)."""
    try:
        raw = b64u_dec(credential["response"]["clientDataJSON"])
        ch = json.loads(raw.decode("utf-8"))["challenge"]
    except WebAuthnError:
        raise
    except Exception as e:
        raise WebAuthnError("bad clientDataJSON") from e
    if not isinstance(ch, str) or len(ch) > 128:
        raise WebAuthnError("bad challenge")
    return ch


def _resp(credential: Any) -> dict[str, Any]:
    if not isinstance(credential, dict) or credential.get("type") != "public-key":
        raise WebAuthnError("not a public-key credential")
    r = credential.get("response")
    if not isinstance(r, dict):
        raise WebAuthnError("no response")
    return r


@dataclass
class Registered:
    cred_id: str        # base64url
    public_key: str     # base64url COSE key
    sign_count: int
    alg: int
    user_verified: bool
    transports: list[str]


def verify_registration(credential: Any, *, challenge: str, rp_id: str, origin: str) -> Registered:
    r = _resp(credential)
    cd_raw = b64u_dec(str(r.get("clientDataJSON", "")))
    cd = _client_data(cd_raw, "webauthn.create", origin)
    if cd["challenge"] != challenge:
        raise WebAuthnError("challenge mismatch")
    att = cbor_decode(b64u_dec(str(r.get("attestationObject", ""))))
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes) or not isinstance(att.get("fmt"), str):
        raise WebAuthnError("bad attestation object")
    ad = parse_auth_data(att["authData"])
    if ad.rp_id_hash != hashlib.sha256(rp_id.encode()).digest():
        raise WebAuthnError("wrong RP ID")
    if not ad.flags & FLAG_UP:
        raise WebAuthnError("user not present")
    if not ad.flags & FLAG_AT or not ad.cred_id:
        raise WebAuthnError("no attested credential")
    alg, _ = cose_public_key(ad.cose_key)
    cred_id = b64u(ad.cred_id)
    if credential.get("id") not in (None, cred_id):
        raise WebAuthnError("credential id mismatch")
    transports = [t for t in (r.get("transports") or []) if isinstance(t, str) and len(t) <= 16][:6]
    return Registered(cred_id, b64u(ad.cose_key), ad.sign_count, alg, ad.user_verified, transports)


def verify_authentication(credential: Any, *, challenge: str, rp_id: str, origin: str,
                          public_key: str, sign_count: int) -> tuple[int, bool]:
    """Returns (new sign count, user verified). Raises WebAuthnError on any failure."""
    r = _resp(credential)
    cd_raw = b64u_dec(str(r.get("clientDataJSON", "")))
    cd = _client_data(cd_raw, "webauthn.get", origin)
    if cd["challenge"] != challenge:
        raise WebAuthnError("challenge mismatch")
    ad_raw = b64u_dec(str(r.get("authenticatorData", "")))
    ad = parse_auth_data(ad_raw)
    if ad.rp_id_hash != hashlib.sha256(rp_id.encode()).digest():
        raise WebAuthnError("wrong RP ID")
    if not ad.flags & FLAG_UP:
        raise WebAuthnError("user not present")
    sig = b64u_dec(str(r.get("signature", "")))
    _verify_sig(b64u_dec(public_key), sig, ad_raw + hashlib.sha256(cd_raw).digest())
    if (ad.sign_count or sign_count) and ad.sign_count <= sign_count:
        raise WebAuthnError("sign count did not increase (possible cloned authenticator)")
    return ad.sign_count, ad.user_verified


__all__ = ["ALGS", "AuthData", "Registered", "WebAuthnError", "b64u", "b64u_dec", "cbor_decode",
           "client_challenge", "cose_public_key", "parse_auth_data", "verify_authentication",
           "verify_registration"]
