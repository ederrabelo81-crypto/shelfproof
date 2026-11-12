"""Pecas do robo que falharam na primeira coleta real (Magalu, 12/11/2026), sem navegador.

* 0 imagens no Windows: o corpo era lido dentro do handler de eventos e falhava em silencio.
* 403 do Akamai tratado como "OK, 0 pecas": a pagina de bloqueio nao tinha frase conhecida.
* User-Agent "Chrome/131" fixo num Chrome mais novo: contradiz os client hints.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from shelfproof.collect.capture import _ImageSink, _looks_blocked, context_options

BIG = b"x" * 5000


class FakeResp(SimpleNamespace):
    def body(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _resp(url, ctype="image/webp", body=BIG):
    return FakeResp(url=url, headers={"content-type": ctype}, _body=body)


def test_sink_anota_no_evento_e_le_o_corpo_depois(tmp_path: Path):
    sink = _ImageSink(tmp_path, min_bytes=4000)
    for r in (_resp("https://a/1.webp"), _resp("https://a/2.svg", "image/svg+xml"),
              _resp("https://a/3.js", "text/javascript"), _resp("https://a/4.jpg", "image/jpeg", b"tiny"),
              _resp("https://a/5.png", "image/png", RuntimeError("no body"))):
        sink.on_response(r)
    assert sink.index == {}  # nada lido dentro do handler
    sink.flush()
    assert list(sink.index) == ["https://a/1.webp"]
    assert (tmp_path / sink.index["https://a/1.webp"]).read_bytes() == BIG
    assert sink.failures and "no body" in sink.failures[0]  # falha registrada, nao engolida


def test_sink_busca_de_novo_o_que_faltou(tmp_path: Path):
    sink = _ImageSink(tmp_path, min_bytes=4000)
    calls = []

    class Req:
        def get(self, url, timeout):
            calls.append(url)
            ok = not url.endswith("404.webp")
            return SimpleNamespace(ok=ok, headers={"content-type": "image/webp"}, body=lambda: BIG)

    sink.on_response(_resp("https://a/ja.webp"))
    sink.flush()
    got = sink.fetch_missing(Req(), ["https://a/ja.webp", "https://a/novo.webp", "https://a/novo.webp",
                                     "data:image/png;base64,xx", "https://a/404.webp"])
    assert got == 1 and "https://a/novo.webp" in sink.index
    assert calls == ["https://a/novo.webp", "https://a/404.webp"]


class FakePage:
    def __init__(self, text="", url="https://www.magazineluiza.com.br/"):
        self.text, self.url = text, url

    def inner_text(self, sel):
        return self.text


def test_bloqueio_da_magalu_e_detectado():
    akamai = "Não é possível acessar a página (Erro 403) Por favor, tente novamente em 1 minuto."
    assert _looks_blocked(FakePage(akamai), n_imgs=1)
    assert _looks_blocked(FakePage(""), n_imgs=0, http_status=403) == "HTTP 403 na pagina principal"
    assert _looks_blocked(FakePage(""), n_imgs=0, http_status=429)
    # evidencia antes de string: pagina cheia de conteudo nao e bloqueio, nem com a frase
    assert _looks_blocked(FakePage(akamai), n_imgs=40, http_status=403) is None
    assert _looks_blocked(FakePage("Ofertas do dia"), n_imgs=2, http_status=200) is None


def test_user_agent_segue_o_chrome_real():
    desk = context_options("desktop", "142.0.7444.60")
    assert "user_agent" not in desk and desk["viewport"]["width"] == 1440
    mob = context_options("mobile", "142.0.7444.60")
    assert "Chrome/142" in mob["user_agent"] and "Android" in mob["user_agent"] and mob["is_mobile"]
    # sem versao conhecida (engine launch/testes): mantem o padrao
    assert "Chrome/131" in context_options("desktop", "")["user_agent"]
