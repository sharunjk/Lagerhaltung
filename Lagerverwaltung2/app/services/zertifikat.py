"""HTTPS im Firmennetz mit eigener kleiner Zertifizierungsstelle (CA).

Warum: Smartphone-Browser erlauben App-Installation, Offline-Modus und Kamera nur über HTTPS.
Die CA wird einmal erzeugt. Wird ihr Zertifikat (``/zertifikat.crt``) auf dem Handheld als
„CA-Zertifikat“ installiert, vertraut Chrome der Lagerverwaltung ohne Warnung.
Das Serverzertifikat wird beim Start neu ausgestellt, wenn sich IP-Adresse oder PC-Name geändert haben.

Sicherheit: Die CA ist per *Name Constraints* auf private IP-Bereiche und die Namen dieses PCs beschränkt.
Selbst wenn ihr privater Schlüssel (``daten/lager_ca_schluessel.pem``) gestohlen würde, ließen sich damit keine
gültigen Zertifikate für fremde Webseiten (z. B. Firmen-Mail) ausstellen.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("lagerverwaltung")

# Nur für diese Adressbereiche darf die Lager-CA Zertifikate ausstellen (RFC 1918, Loopback, Link-Local)
ERLAUBTE_NETZE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16")]


def _intern(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in ERLAUBTE_NETZE)


def lokale_adressen() -> list[str]:
    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def _namen() -> tuple[list[str], list[str]]:
    host = socket.gethostname()
    namen = {"localhost", host, host.lower(), host.split(".")[0], host.split(".")[0].lower()}
    try:
        fqdn = socket.getfqdn()
        if "." in fqdn and not fqdn.endswith((".arpa", ".")):
            namen.add(fqdn.lower())
    except OSError:
        pass
    return sorted(n for n in namen if n), [ip for ip in lokale_adressen() if _intern(ip)]


def _hat_beschraenkung(ca_cert) -> bool:
    from cryptography import x509
    try:
        ca_cert.extensions.get_extension_for_class(x509.NameConstraints)
        return True
    except x509.ExtensionNotFound:
        return False


def _schluessel():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def _pem_key(k) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def ca_pfade(ordner: Path) -> tuple[Path, Path]:
    return ordner / "lager_ca.crt", ordner / "lager_ca_schluessel.pem"


def ca_sicherstellen(ordner: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    cert_p, key_p = ca_pfade(ordner)
    if cert_p.exists() and key_p.exists():
        c = x509.load_pem_x509_certificate(cert_p.read_bytes())
        if _hat_beschraenkung(c):
            return c, serialization.load_pem_private_key(key_p.read_bytes(), password=None)
        # CA aus Version 2.2.1 oder älter: unbeschränkt – ersetzen (Geräte müssen das Zertifikat einmal neu installieren)
        log.warning("Alte Lager-CA ohne Namensbeschränkung wird ersetzt. Zertifikat auf Handhelds/PCs bitte neu installieren.")
        for p in (cert_p, key_p):
            p.replace(p.with_name(p.name + ".alt"))
    ordner.mkdir(parents=True, exist_ok=True)
    dns, _ = _namen()
    k = _schluessel()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Lagerverwaltung CA {socket.gethostname()}"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Lagerverwaltung")])
    jetzt = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(jetzt - timedelta(days=1)).not_valid_after(jetzt + timedelta(days=3650))
         .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
         .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                                      data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()), critical=False)
         .add_extension(x509.NameConstraints(
             permitted_subtrees=[x509.IPAddress(n) for n in ERLAUBTE_NETZE] + [x509.DNSName(d) for d in dns],
             excluded_subtrees=None), critical=True)
         .sign(k, hashes.SHA256()))
    key_p.write_bytes(_pem_key(k))
    cert_p.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return c, k


def _ca_dns(ca_cert) -> list[str]:
    from cryptography import x509
    try:
        nc = ca_cert.extensions.get_extension_for_class(x509.NameConstraints).value
    except x509.ExtensionNotFound:
        return []
    return [n.value for n in (nc.permitted_subtrees or []) if isinstance(n, x509.DNSName)]


def sicherstellen(ordner: Path) -> tuple[Path, Path]:
    """Gibt (Zertifikat, Schlüssel) für den HTTPS-Server zurück; erneuert bei geänderten Adressen."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    cert_p, key_p = ordner / "https_zertifikat.pem", ordner / "https_schluessel.pem"
    dns, ips = _namen()
    if cert_p.exists() and key_p.exists():
        try:
            alt = x509.load_pem_x509_certificate(cert_p.read_bytes())
            san = alt.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            vorhanden = {str(x) for x in san.get_values_for_type(x509.IPAddress)} | set(san.get_values_for_type(x509.DNSName))
            gueltig = alt.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=30)
            ca_cert, _ = ca_sicherstellen(ordner)
            aki = alt.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value.key_identifier
            von_dieser_ca = aki == x509.SubjectKeyIdentifier.from_public_key(ca_cert.public_key()).digest
            erlaubt = {d.lower() for d in _ca_dns(ca_cert)}
            if gueltig and von_dieser_ca and set(ips) <= vorhanden and (set(dns) & erlaubt) <= vorhanden:
                return cert_p, key_p
        except Exception:
            pass
    ca_cert, ca_key = ca_sicherstellen(ordner)
    # nur Namen, die die CA ausstellen darf (nach Umbenennung des PCs: Zugriff über IP; neuer Name erst mit neuer CA)
    erlaubt = {d.lower() for d in _ca_dns(ca_cert)}
    dns = [d for d in dns if d.lower() in erlaubt]
    k = _schluessel()
    jetzt = datetime.now(timezone.utc)
    namen = [x509.DNSName(d) for d in dns] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    c = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Lagerverwaltung {socket.gethostname()}")]))
         .issuer_name(ca_cert.subject).public_key(k.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(jetzt - timedelta(days=1)).not_valid_after(jetzt + timedelta(days=820))
         .add_extension(x509.SubjectAlternativeName(namen), critical=False)
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
         .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
         .sign(ca_key, hashes.SHA256()))
    key_p.write_bytes(_pem_key(k))
    cert_p.write_bytes(c.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p
