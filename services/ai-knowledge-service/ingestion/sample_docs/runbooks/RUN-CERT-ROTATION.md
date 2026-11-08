---
doc_id: RUN-CERT-ROTATION
title: TLS Certificate Rotation Runbook
department: platform
document_type: runbook
access_level: internal
created_date: 2025-10-18
version: 1.0
source_url: https://wiki.abcbank.internal/runbook/cert-rotation
---

# TLS Certificate Rotation Runbook

## When
Rotate before expiry, or during an incident caused by an expired certificate on the gateway
connector (symptom: TLS handshake failure, `certificate has expired`).

## Steps
1. Issue a new certificate for CN `gateway.cardnet.abcbank` from the internal CA.
2. Deploy the cert to the gateway-connector secret.
3. Rolling-restart the connector; verify the handshake.

## Prevention
Enable the cert-expiry alert at 30 days remaining. Several payment outages were caused by missed
renewals; this alert is mandatory.
