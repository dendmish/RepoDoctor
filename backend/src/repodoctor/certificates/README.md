# GigaChat application trust anchor

`russian_trusted_root_ca.pem` is the public Russian Trusted Root CA, downloaded over
verified HTTPS from https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
on 2026-10-25, following https://developers.sber.ru/docs/ru/gigachat/certificates.

SHA-256 of the DER certificate:
`d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31`

Only GigaChatProvider adds this root to its own SSLContext, with hostname verification
and CERT_REQUIRED. It does not modify OS/certifi stores, GitHub/OpenAI transports,
or allow insecure TLS. No certificate is downloaded automatically at app startup.
`GIGACHAT_CA_BUNDLE` can supply additional trusted PEM certificates when needed.
