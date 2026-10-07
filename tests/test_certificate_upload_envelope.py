from uuid import uuid4

import pytest

from apps.certificates.services.upload_envelope import (
    CertificateUploadEnvelope,
    CertificateUploadEnvelopeError,
    generate_upload_keypair,
)


def test_web_envelope_can_only_be_decrypted_with_worker_private_key(tmp_path):
    private_key = tmp_path / "private.key"
    public_key = tmp_path / "public.key"
    request_id = uuid4()
    generate_upload_keypair(
        private_key_file=private_key,
        public_key_file=public_key,
    )
    web_envelope = CertificateUploadEnvelope(public_key_file=public_key)
    worker_envelope = CertificateUploadEnvelope(
        public_key_file=public_key,
        private_key_file=private_key,
    )

    encrypted = web_envelope.encrypt(
        b"pfx-content",
        request_id=request_id,
        purpose="pfx",
    )

    assert worker_envelope.decrypt(
        encrypted,
        request_id=request_id,
        purpose="pfx",
    ) == b"pfx-content"
    with pytest.raises(CertificateUploadEnvelopeError):
        worker_envelope.decrypt(
            encrypted,
            request_id=request_id,
            purpose="password",
        )
