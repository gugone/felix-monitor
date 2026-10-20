# felix-monitor

Monitor externo do servidor da loja Félix. A cada 5 minutos o GitHub Actions confere se o servidor responde
e, quando ele cai ou volta, avisa por e-mail e WhatsApp.

- O código está em `monitor.py`, e as regras estão no docstring.
- O estado fica em `estado.json` e só ganha commit quando muda.
- Os segredos (Settings › Secrets and variables › Actions) são: `WA_TOKEN`, `WA_PHONE_ID`, `ALERTA_WHATSAPP`,
  `RESEND_API_KEY`, `RESEND_REMETENTE` e `ALERTA_EMAIL`.
- Para testar na hora: Actions › Monitor da loja › Run workflow.
