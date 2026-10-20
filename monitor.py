"""Monitor externo da loja Felix (20/10/2026).

Roda no GitHub Actions a cada 5 minutos, FORA da loja: quando o servidor da loja perde energia ou internet,
ele nao consegue avisar ninguem -- este monitor consegue. Avisa por e-mail e WhatsApp quando o site cai e
quando volta.

Regras:
  - "fora" = o /health do agente nao responde em 4 tentativas ao longo de 3 minutos. Um reinicio normal do
    agente (deploy) leva ~1 minuto e nao pode virar alarme;
  - so' avisa na MUDANCA (caiu / voltou), nunca a cada checagem; o estado fica em estado.json, gravado por
    commit so' quando muda;
  - uma vez a cada 20 dias grava um "batimento" no estado.json: o GitHub desliga agendamentos de repositorio
    publico sem atividade ha' 60 dias;
  - so' biblioteca padrao do Python; segredos so' pelas variaveis de ambiente (Settings > Secrets).
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

PRINCIPAL = "https://api.varejai.com.br/health"
OUTRAS = ["https://loja.felixsupermercado.com.br/"]
TENTATIVAS, INTERVALO_S = 4, 60
ESTADO = "estado.json"
FUSO = timezone(timedelta(hours=-3))          # Arapiraca/AL, sem horario de verao
BATIMENTO_DIAS = 20


def agora():
    return datetime.now(FUSO)


def responde(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "felix-monitor/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 500, r.status
    except urllib.error.HTTPError as e:
        return e.code < 500, e.code
    except Exception as e:
        return False, type(e).__name__


def site_no_ar():
    ultimo = None
    for i in range(TENTATIVAS):
        ok, cod = responde(PRINCIPAL)
        print(f"tentativa {i + 1}: {PRINCIPAL} -> {cod}")
        if ok:
            return True, cod
        ultimo = cod
        if i < TENTATIVAS - 1:
            time.sleep(INTERVALO_S)
    return False, ultimo


def ler_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"estado": "up", "desde": agora().isoformat(timespec="seconds"), "batimento": ""}


def gravar_estado(e):
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _post(url, corpo, headers):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "felix-monitor/1", **headers})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return True, r.status
    except urllib.error.HTTPError as e:
        return False, f"{e.code} {e.read().decode(errors='replace')[:200]}"
    except Exception as e:
        return False, type(e).__name__


def avisar_whatsapp(motivo, quando):
    token, phone_id = os.environ.get("WA_TOKEN", ""), os.environ.get("WA_PHONE_ID", "")
    destinos = [d.strip() for d in os.environ.get("ALERTA_WHATSAPP", "").split(",") if d.strip()]
    if not (token and phone_id and destinos):
        print("WhatsApp: segredos faltando, pulei")
        return
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    auth = {"Authorization": f"Bearer {token}"}
    for d in destinos:
        ok, info = _post(url, {"messaging_product": "whatsapp", "to": d, "type": "template",
                               "template": {"name": "felix_alerta_servidor", "language": {"code": "pt_BR"},
                                            "components": [{"type": "body", "parameters": [
                                                {"type": "text", "text": motivo},
                                                {"type": "text", "text": quando}]}]}}, auth)
        if not ok:   # modelo ainda em analise: texto comum (so' chega com a conversa aberta)
            print(f"WhatsApp modelo falhou ({info}); tentando texto")
            ok, info = _post(url, {"messaging_product": "whatsapp", "to": d, "type": "text",
                                   "text": {"body": f"Alerta do sistema da loja Félix: {motivo}. Horário: {quando}."}},
                             auth)
        print(f"WhatsApp ...{d[-4:]}: {'ok' if ok else info}")


def avisar_email(assunto, texto):
    chave = os.environ.get("RESEND_API_KEY", "")
    remetente = os.environ.get("RESEND_REMETENTE", "")
    destinos = [d.strip() for d in os.environ.get("ALERTA_EMAIL", "").split(",") if d.strip()]
    if not (chave and remetente and destinos):
        print("E-mail: segredos faltando, pulei")
        return
    ok, info = _post("https://api.resend.com/emails",
                     {"from": remetente, "to": destinos, "subject": assunto, "text": texto},
                     {"Authorization": f"Bearer {chave}"})
    print(f"E-mail: {'ok' if ok else info}")


def main():
    if os.environ.get("TESTE", "").lower() == "true":
        quando = agora().strftime("%d/%m %H:%M")
        avisar_whatsapp("teste do monitor externo, está tudo funcionando", quando)
        avisar_email("Loja Félix: teste do monitor", f"Teste do monitor externo às {quando}. Se chegou, os avisos funcionam.")
        return
    e = ler_estado()
    no_ar, cod = site_no_ar()
    t = agora()
    quando = t.strftime("%d/%m %H:%M")
    if no_ar and e.get("estado") == "down":
        desde = datetime.fromisoformat(e["desde"])
        minutos = max(1, round((t - desde).total_seconds() / 60))
        motivo = f"o site e o atendimento do WhatsApp voltaram ao ar depois de cerca de {minutos} min fora"
        avisar_whatsapp(motivo, quando)
        avisar_email(f"Loja Félix: voltou ao ar ({minutos} min fora)",
                     f"O servidor da loja voltou a responder às {quando}, depois de cerca de {minutos} minutos fora "
                     f"(desde {desde.strftime('%d/%m %H:%M')}).")
        e = {"estado": "up", "desde": t.isoformat(timespec="seconds"), "batimento": e.get("batimento", "")}
    elif not no_ar and e.get("estado") != "down":
        outras = ", ".join(f"{u} -> {responde(u)[1]}" for u in OUTRAS)
        motivo = "o site e o atendimento do WhatsApp estão fora do ar (o servidor da loja não responde)"
        avisar_whatsapp(motivo, quando)
        avisar_email("Loja Félix: FORA DO AR",
                     f"Desde {quando} o servidor da loja não responde ({PRINCIPAL} -> {cod}; {outras}). "
                     "Confira se o computador do servidor está ligado e se a internet da loja está funcionando. "
                     "Se o computador estiver ligado e sem internet, o vigia reinicia a placa de rede e, "
                     "depois de 12 minutos, o computador. Aviso de novo quando voltar.")
        e = {"estado": "down", "desde": t.isoformat(timespec="seconds"), "batimento": e.get("batimento", "")}
    bat = e.get("batimento") or ""
    if not bat or (t - datetime.fromisoformat(bat)).days >= BATIMENTO_DIAS:
        e["batimento"] = t.isoformat(timespec="seconds")
    gravar_estado(e)
    print("estado:", e["estado"], "desde", e["desde"])


if __name__ == "__main__":
    main()
