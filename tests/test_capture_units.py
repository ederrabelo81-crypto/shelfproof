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


def _resp(url, ctype="image/webp", body=BIG, rtype="image"):
    return FakeResp(url=url, headers={"content-type": ctype}, _body=body,
                    request=SimpleNamespace(resource_type=rtype))


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


def test_imagem_servida_como_octet_stream_e_reconhecida_pelos_bytes(tmp_path: Path):
    # no Windows o servidor de teste mandava .webp como application/octet-stream (12/11/2026)
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"x" * 5000
    sink = _ImageSink(tmp_path, min_bytes=4000)
    sink.on_response(_resp("https://a/banner.webp", "application/octet-stream", webp))
    sink.on_response(_resp("https://a/app.js", "application/octet-stream", BIG, rtype="script"))
    sink.on_response(_resp("https://a/blob", "application/octet-stream", BIG))  # nao e imagem
    sink.flush()
    assert list(sink.index) == ["https://a/banner.webp"] and sink.index["https://a/banner.webp"].endswith(".webp")


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


def test_anon_warm_so_em_desktop_e_falha_com_manifest(tmp_path: Path):
    import json

    from shelfproof.collect.capture import CaptureConfig, capture

    res = capture(CaptureConfig(url="https://www.magazineluiza.com.br/", device="mobile",
                                session="anon_warm", out_root=tmp_path))
    assert not res.ok and any("so existe" in e for e in res.errors)
    man = json.loads((res.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert man["session"] == "anon_warm" and man["errors"] == res.errors


def test_targets_marcam_anon_warm_nos_sites_com_akamai():
    import json

    targets = json.loads((Path(__file__).resolve().parents[1] / "config" / "targets.json").read_text(encoding="utf-8"))
    warm = {t["name"] for t in targets["targets"] if t.get("session") == "anon_warm"}
    assert warm == {"Magalu", "Casas Bahia"}


def test_redirect_nao_e_falha_de_imagem(tmp_path: Path):
    # Magalu 12/11/2026: /api/reverse-proxy/event responde 302 com tipo de imagem
    sink = _ImageSink(tmp_path, min_bytes=4000)
    r = _resp("https://www.magazineluiza.com.br/api/reverse-proxy/event?x", "image/gif", RuntimeError("redirect"))
    r.status = 302
    sink.on_response(r)
    sink.flush()
    assert sink.index == {} and sink.failures == []


def test_marcas_novas_da_magalu_sem_falso_positivo():
    from shelfproof.detect.brands import find_brand

    assert find_brand("Smartphone OPPO A6s 256GB 8GB RAM") == "OPPO"
    assert find_brand("/smartphone-oppo-a6x-128gb/p/241078200/te/oppo/") == "OPPO"
    assert find_brand("Fone JBL Tune 520BT") == "JBL"
    assert find_brand("Motor 1 HP monofasico") is None
    assert find_brand("Feedback positivo dos clientes") is None


def test_produto_patrocinado_e_da_marca_que_vem_primeiro():
    from shelfproof.detect.brands import find_brand_first

    # Magalu 12/11/2026: 4 notebooks Lenovo tinham saido como "Intel" (processador no titulo)
    assert find_brand_first("Notebook Gamer Lenovo LOQ 15IRX9 Intel Core i5-14500HX") == "Lenovo"
    assert find_brand_first("Notebook Samsung Galaxy Book4 Intel Core 5") == "Samsung"
    assert find_brand_first("Ar-condicionado Springer Midea 12000") == "Springer Midea"


def test_card_patrocinado_casa_com_a_posicao_pelo_caminho_do_link(tmp_path: Path):
    import json

    from shelfproof.pipeline import analyze

    html = """<html><body><h2>Patrocinados</h2><div>
      <a href="/notebook-lenovo-loq/p/hd5/in/note/?seller_id=x" title="Notebook Lenovo LOQ Intel Core i5">x</a>
      <a href="/smartphone-oppo-a6s/p/aa6bg/te/oppo/?seller_id=oppo" title="Smartphone OPPO A6s">y</a>
    </div></body></html>"""
    (tmp_path / "page.html").write_text(html, encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"url": "https://www.magazineluiza.com.br/", "final_url": "https://www.magazineluiza.com.br/",
         "viewport": {"width": 1440, "height": 900}}), encoding="utf-8")
    els = [{"src": "https://a-static.mlcdn.com.br/350x350/notebook-lenovo-loq.jpg", "alt": "Imagem do produto",
            "href": "https://www.magazineluiza.com.br/notebook-lenovo-loq/p/hd5/in/note/?seller_id=x&ads=1",
            "x": 369, "y": 859, "w": 206, "h": 137},
           {"src": "https://a-static.mlcdn.com.br/350x350/smartphone-oppo-a6s.jpg", "alt": "Imagem do produto",
            "href": "https://www.magazineluiza.com.br/smartphone-oppo-a6s/p/aa6bg/te/oppo/?seller_id=oppo&ads=2",
            "x": 1569, "y": 859, "w": 206, "h": 137}]
    (tmp_path / "elements.json").write_text(json.dumps(els), encoding="utf-8")
    pieces = {p.advertiser: p for p in analyze(tmp_path)}
    assert set(pieces) == {"Lenovo", "OPPO"}
    assert pieces["Lenovo"].bbox.x == 369 and pieces["OPPO"].bbox.x == 1569
    assert pieces["OPPO"].bbox.area == 206 * 137


def test_casas_bahia_anunciante_nomeado_no_vtr_name():
    from shelfproof.detect.rules import _cb_vtr_advertiser, detect

    assert _cb_vtr_advertiser(["Ads", "CB", "v2", "Belmicro", "Desk", "Nov-2026"]) == "Belmicro"
    assert _cb_vtr_advertiser(["Ads", "CB", "11.11", "WAP", "Desk", "port", "Nov-2026"]) == "WAP"
    assert _cb_vtr_advertiser(["Ads", "CB", "v2", "Desk"]) == ""
    html = ('<a href="https://www.casasbahia.com.br/x?vtr_name=Ads_CB%20_v2_Belmicro_Desk__Nov-2026">'
            '<img alt="Banner Casas Bahia de Aquecimento Black Friday" src="https://img/a.avif"></a>')
    (p,) = [p for p in detect(html, "https://www.casasbahia.com.br/") if p.is_paid]
    assert p.advertiser == "Belmicro" and any("nomeado no vtr_name" in e for e in p.evidence)


def test_api_octet_stream_nao_vira_falha_de_imagem(tmp_path: Path):
    sink = _ImageSink(tmp_path, min_bytes=4000)
    sink.on_response(_resp("https://retail.googleapis.com/v2/x", "application/octet-stream",
                           RuntimeError("CSP violation"), rtype="fetch"))
    sink.flush()
    assert sink.pending == [] and sink.failures == []


def test_pixel_sem_corpo_nao_e_falha(tmp_path: Path):
    # ML 12/11/2026: placements.mercadolibre.com/metrics/canary/increment (pixel) sem corpo guardado
    sink = _ImageSink(tmp_path, min_bytes=4000)
    err = RuntimeError("Protocol error (Network.getResponseBody): No data found for resource with given identifier")
    sink.on_response(_resp("https://placements.mercadolibre.com/metrics/canary/increment?name=x", "image/gif", err))
    sink.flush()
    assert sink.failures == []
