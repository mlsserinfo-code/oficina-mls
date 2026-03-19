# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import sqlite3
import datetime as dt
import os
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

DB = os.path.join(os.path.dirname(__file__), "mls_oficina.db")

app = Flask(__name__)
app.secret_key = "mls-oficina"


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def garantir_coluna(con, tabela, coluna, definicao):
    cols = [r["name"] for r in con.execute(f"PRAGMA table_info({tabela})").fetchall()]
    if coluna not in cols:
        con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def init_db():
    con = db()

    # CLIENTES
    con.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            telefone TEXT,
            endereco TEXT,
            bairro TEXT,
            cpf TEXT
        )
    """)

    # VEICULOS
    con.execute("""
        CREATE TABLE IF NOT EXISTS veiculos (
            placa TEXT PRIMARY KEY,
            marca TEXT,
            modelo TEXT,
            ano INTEGER,
            cor TEXT,
            uf TEXT,
            updated_at TEXT
        )
    """)

    # ORDENS (OS)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ordens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            placa TEXT NOT NULL,
            cliente_id INTEGER NOT NULL,
            data_entrada TEXT,
            km INTEGER,
            status TEXT DEFAULT 'ABERTA',
            obs TEXT,
            FOREIGN KEY (placa) REFERENCES veiculos(placa),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )
    """)

    # ITENS DA OS
    con.execute("""
        CREATE TABLE IF NOT EXISTS ordem_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ordem_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,          -- SERVICO ou PECA
            descricao TEXT NOT NULL,
            qtd REAL DEFAULT 1,
            valor_unit REAL DEFAULT 0,
            valor_total REAL DEFAULT 0,
            FOREIGN KEY (ordem_id) REFERENCES ordens(id)
        )
    """)

    # Atualizações de estrutura
    garantir_coluna(con, "ordens", "forma_pagamento", "TEXT")

    con.commit()
    con.close()


# ===================== HELPERS =====================

def norm_placa(s: str) -> str:
    s = (s or "").upper().strip()
    return s.replace("-", "").replace(" ", "")


def parse_float_br(txt, default=0.0):
    # aceita "180,50" ou "180.50" ou "1.234,56"
    s = str(txt or "").strip()
    if not s:
        return default
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return default


def moeda_br(v):
    try:
        v = float(v or 0)
    except Exception:
        v = 0.0
    s = f"{v:,.2f}"
    # 1,234.56 -> 1.234,56
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ===================== HOME =====================

@app.get("/")
def home():
    return render_template("home.html")


# ===================== CLIENTES =====================

@app.get("/clientes")
def clientes():
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page") or "1"
    per_page = 20

    try:
        page_i = max(int(page), 1)
    except Exception:
        page_i = 1

    offset = (page_i - 1) * per_page

    con = db()

    where = ""
    params = []

    if q:
        q_like = f"%{q.upper()}%"
        where = """
          WHERE
            UPPER(nome) LIKE ?
            OR UPPER(telefone) LIKE ?
            OR UPPER(cpf) LIKE ?
            OR UPPER(endereco) LIKE ?
            OR UPPER(bairro) LIKE ?
        """
        params = [q_like, q_like, q_like, q_like, q_like]

    total = con.execute(f"SELECT COUNT(*) AS n FROM clientes {where}", params).fetchone()["n"]

    rows = con.execute(f"""
        SELECT *
        FROM clientes
        {where}
        ORDER BY nome
        LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()

    con.close()

    pages = max((total + per_page - 1) // per_page, 1)
    prev_page = page_i - 1 if page_i > 1 else None
    next_page = page_i + 1 if page_i < pages else None

    return render_template(
        "clientes.html",
        clientes=rows,
        q=q,
        page=page_i,
        pages=pages,
        total=total,
        prev_page=prev_page,
        next_page=next_page,
    )


@app.post("/clientes/novo")
def novo_cliente():
    nome = (request.form.get("nome") or "").strip()
    telefone = (request.form.get("telefone") or "").strip()
    endereco = (request.form.get("endereco") or "").strip()
    bairro = (request.form.get("bairro") or "").strip()
    cpf = (request.form.get("cpf") or "").strip()

    if not nome:
        flash("Informe o nome do cliente.")
        return redirect("/clientes")

    con = db()
    con.execute("""
        INSERT INTO clientes (nome, telefone, endereco, bairro, cpf)
        VALUES (?, ?, ?, ?, ?)
    """, (nome, telefone, endereco, bairro, cpf))
    con.commit()
    con.close()

    return redirect("/clientes")


@app.get("/clientes/editar/<int:cliente_id>")
def cliente_editar(cliente_id):
    con = db()
    c = con.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    con.close()

    if not c:
        flash("Cliente não encontrado.")
        return redirect("/clientes")

    return render_template("cliente_editar.html", c=c)


@app.post("/clientes/atualizar")
def cliente_atualizar():
    cliente_id = int(request.form.get("id"))
    nome = (request.form.get("nome") or "").strip()
    telefone = (request.form.get("telefone") or "").strip()
    endereco = (request.form.get("endereco") or "").strip()
    bairro = (request.form.get("bairro") or "").strip()
    cpf = (request.form.get("cpf") or "").strip()

    if not nome:
        flash("Informe o nome do cliente.")
        return redirect(url_for("cliente_editar", cliente_id=cliente_id))

    con = db()
    con.execute("""
        UPDATE clientes
           SET nome=?, telefone=?, endereco=?, bairro=?, cpf=?
         WHERE id=?
    """, (nome, telefone, endereco, bairro, cpf, cliente_id))
    con.commit()
    con.close()

    flash("Cliente atualizado.")
    return redirect("/clientes")


@app.post("/clientes/excluir")
def cliente_excluir():
    cliente_id = int(request.form.get("id"))

    con = db()

    # segurança: não deixa excluir se já tem OS
    tem_os = con.execute("SELECT 1 FROM ordens WHERE cliente_id=? LIMIT 1", (cliente_id,)).fetchone()
    if tem_os:
        con.close()
        flash("Não é possível excluir: cliente já possui OS cadastrada.")
        return redirect("/clientes")

    con.execute("DELETE FROM clientes WHERE id=?", (cliente_id,))
    con.commit()
    con.close()

    flash("Cliente excluído.")
    return redirect("/clientes")


# ===================== OS (PLACA DIRETO) =====================

@app.get("/os")
def os_inicio():
    return render_template("os_inicio.html")


@app.post("/os/placa")
def os_por_placa():
    placa = norm_placa(request.form.get("placa"))
    if not placa:
        flash("Informe a placa.")
        return redirect("/os")

    con = db()
    v = con.execute("SELECT * FROM veiculos WHERE placa=?", (placa,)).fetchone()
    con.close()

    if v:
        return redirect(url_for("os_cliente", placa=placa))
    return redirect(url_for("veiculo_novo", placa=placa))


@app.get("/veiculo/novo/<placa>")
def veiculo_novo(placa):
    return render_template("veiculo_novo.html", placa=norm_placa(placa))


@app.post("/veiculo/salvar")
def veiculo_salvar():
    placa = norm_placa(request.form.get("placa"))
    marca = (request.form.get("marca") or "").strip().upper()
    modelo = (request.form.get("modelo") or "").strip().upper()
    ano = request.form.get("ano") or ""
    cor = (request.form.get("cor") or "").strip().upper()
    uf = (request.form.get("uf") or "").strip().upper()

    try:
        ano_i = int(ano) if ano else None
    except Exception:
        ano_i = None

    con = db()
    con.execute("""
        INSERT OR REPLACE INTO veiculos (placa, marca, modelo, ano, cor, uf, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (placa, marca, modelo, ano_i, cor, uf,
          dt.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    con.close()

    return redirect(url_for("os_cliente", placa=placa))


@app.get("/os/cliente/<placa>")
def os_cliente(placa):
    placa = norm_placa(placa)
    con = db()

    v = con.execute("SELECT * FROM veiculos WHERE placa=?", (placa,)).fetchone()
    clientes = con.execute("SELECT id, nome, telefone FROM clientes ORDER BY nome").fetchall()

    con.close()

    if not v:
        return redirect(url_for("veiculo_novo", placa=placa))

    return render_template("os_cliente.html", v=v, clientes=clientes)


@app.post("/os/abrir")
def os_abrir():
    placa = norm_placa(request.form.get("placa"))
    cliente_id = request.form.get("cliente_id")
    km = request.form.get("km") or "0"
    obs = (request.form.get("obs") or "").strip()

    try:
        km_i = int(km)
    except Exception:
        km_i = 0

    if not cliente_id:
        flash("Selecione um cliente.")
        return redirect(url_for("os_cliente", placa=placa))

    con = db()
    con.execute("""
        INSERT INTO ordens (placa, cliente_id, data_entrada, km, status, obs)
        VALUES (?, ?, ?, ?, 'ABERTA', ?)
    """, (placa, int(cliente_id),
          dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
          km_i, obs))
    con.commit()

    ordem_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.close()

    return redirect(url_for("os_editar", ordem_id=ordem_id))


@app.get("/os/editar/<int:ordem_id>")
def os_editar(ordem_id):
    con = db()

    # garante coluna também ao abrir tela antiga
    garantir_coluna(con, "ordens", "forma_pagamento", "TEXT")
    con.commit()

    os_ = con.execute("""
        SELECT o.*, c.nome AS cliente_nome, c.telefone AS cliente_tel,
               v.marca, v.modelo, v.ano, v.cor, v.uf
        FROM ordens o
        JOIN clientes c ON c.id = o.cliente_id
        JOIN veiculos v ON v.placa = o.placa
        WHERE o.id=?
    """, (ordem_id,)).fetchone()

    if not os_:
        con.close()
        flash("OS nao encontrada.")
        return redirect("/os")

    itens = con.execute("""
        SELECT * FROM ordem_itens WHERE ordem_id=? ORDER BY id DESC
    """, (ordem_id,)).fetchall()

    total = con.execute("""
        SELECT COALESCE(SUM(valor_total),0) AS t FROM ordem_itens WHERE ordem_id=?
    """, (ordem_id,)).fetchone()["t"]

    con.close()

    return render_template("os_editar.html", os=os_, itens=itens, total=total)


@app.post("/os/item/add")
def os_item_add():
    ordem_id = int(request.form.get("ordem_id"))
    tipo = (request.form.get("tipo") or "SERVICO").strip().upper()
    descricao = (request.form.get("descricao") or "").strip()
    qtd = parse_float_br(request.form.get("qtd"), default=1.0)
    valor_unit = parse_float_br(request.form.get("valor_unit"), default=0.0)

    if not descricao:
        return redirect(url_for("os_editar", ordem_id=ordem_id))

    vt = round(qtd * valor_unit, 2)

    con = db()
    con.execute("""
        INSERT INTO ordem_itens (ordem_id, tipo, descricao, qtd, valor_unit, valor_total)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ordem_id, tipo, descricao, qtd, valor_unit, vt))
    con.commit()
    con.close()

    return redirect(url_for("os_editar", ordem_id=ordem_id))


@app.post("/os/item/del")
def os_item_del():
    item_id = int(request.form.get("item_id"))
    ordem_id = int(request.form.get("ordem_id"))

    con = db()
    con.execute("DELETE FROM ordem_itens WHERE id=?", (item_id,))
    con.commit()
    con.close()

    return redirect(url_for("os_editar", ordem_id=ordem_id))


@app.get("/os/pdf/<int:ordem_id>")
def os_pdf(ordem_id):
    con = db()

    garantir_coluna(con, "ordens", "forma_pagamento", "TEXT")
    con.commit()

    os_ = con.execute("""
        SELECT o.*, c.nome AS cliente_nome, c.telefone AS cliente_tel,
               c.endereco AS cliente_end, c.bairro AS cliente_bairro, c.cpf AS cliente_cpf,
               v.marca, v.modelo, v.ano, v.cor, v.uf, v.placa
        FROM ordens o
        JOIN clientes c ON c.id = o.cliente_id
        JOIN veiculos v ON v.placa = o.placa
        WHERE o.id=?
    """, (ordem_id,)).fetchone()

    if not os_:
        con.close()
        flash("OS não encontrada.")
        return redirect("/os")

    itens = con.execute("""
        SELECT * FROM ordem_itens
        WHERE ordem_id=?
        ORDER BY id
    """, (ordem_id,)).fetchall()

    total = con.execute("""
        SELECT COALESCE(SUM(valor_total),0) AS t
        FROM ordem_itens WHERE ordem_id=?
    """, (ordem_id,)).fetchone()["t"]

    con.close()

    # ====== GERA PDF (A4) ======
    buff = io.BytesIO()
    c = canvas.Canvas(buff, pagesize=A4)
    w, h = A4

    x = 40
    y = h - 50

    logo_path = os.path.join(os.path.dirname(__file__), "static", "img", "logo_rodamil.png")
    if os.path.exists(logo_path):
        img = ImageReader(logo_path)
        logo_w = 250
        logo_h = 155
        logo_x = w - 40 - logo_w
        logo_y = h - 140
        c.drawImage(img, logo_x, logo_y, width=logo_w, height=logo_h,
                    preserveAspectRatio=True, mask='auto')

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, "RODAMIL — ORDEM DE SERVIÇO")
    y -= 22

    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"OS: {os_['id']}    Data: {os_['data_entrada']}    Status: {os_['status']}")
    y -= 16
    c.drawString(x, y, f"Placa: {os_['placa']}    Veículo: {os_['marca']} {os_['modelo']} {os_['ano'] or ''}    Cor: {os_['cor'] or ''}    UF: {os_['uf'] or ''}")
    y -= 16
    c.drawString(x, y, f"Cliente: {os_['cliente_nome']}    Tel: {os_['cliente_tel'] or ''}    CPF: {os_['cliente_cpf'] or ''}")
    y -= 16

    end = (os_["cliente_end"] or "").strip()
    bai = (os_["cliente_bairro"] or "").strip()
    if end or bai:
        c.drawString(x, y, f"Endereço: {end}  {('— ' + bai) if bai else ''}")
        y -= 16

    if os_["km"]:
        c.drawString(x, y, f"KM: {os_['km']}")
        y -= 16

    if (os_["obs"] or "").strip():
        c.drawString(x, y, f"Obs: {os_['obs']}")
        y -= 16

    if (os_["forma_pagamento"] or "").strip():
        c.drawString(x, y, f"Pagamento: {os_['forma_pagamento']}")
        y -= 18

    y -= 8
    c.line(x, y, w - 40, y)
    y -= 18

    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, "Tipo")
    c.drawString(x + 70, y, "Descrição")
    c.drawString(w - 220, y, "Qtd")
    c.drawString(w - 170, y, "V.Unit")
    c.drawString(w - 90, y, "Total")
    y -= 12
    c.line(x, y, w - 40, y)
    y -= 16

    c.setFont("Helvetica", 10)

    for it in itens:
        if y < 80:
            c.showPage()
            y = h - 60
            c.setFont("Helvetica-Bold", 10)
            c.drawString(x, y, f"OS: {os_['id']}  (continuação)")
            y -= 18
            c.setFont("Helvetica", 10)

        c.drawString(x, y, (it["tipo"] or "")[:10])
        c.drawString(x + 70, y, (it["descricao"] or "")[:55])
        c.drawRightString(w - 210, y, moeda_br(it["qtd"]))
        c.drawRightString(w - 140, y, moeda_br(it["valor_unit"]))
        c.drawRightString(w - 40, y, moeda_br(it["valor_total"]))
        y -= 14

    y -= 10
    c.line(x, y, w - 40, y)
    y -= 18
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(w - 40, y, f"TOTAL GERAL: R$ {moeda_br(total)}")

    y = 40
    c.setFont("Helvetica", 8)
    c.drawString(x, y, "MLS SOFTHOUSE — Oficina Web")

    c.save()
    buff.seek(0)

    nome = f"OS_{ordem_id}.pdf"
    return send_file(buff, as_attachment=False, download_name=nome, mimetype="application/pdf")


# ===================== OS - LISTA GERAL (CONSULTA) =====================

@app.get("/os/lista")
def os_lista():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().upper()
    page = request.args.get("page") or "1"
    per_page = 20

    try:
        page_i = max(int(page), 1)
    except Exception:
        page_i = 1

    offset = (page_i - 1) * per_page

    con = db()

    garantir_coluna(con, "ordens", "forma_pagamento", "TEXT")
    con.commit()

    base_sql = """
        FROM ordens o
        JOIN veiculos v ON v.placa = o.placa
        JOIN clientes c ON c.id = o.cliente_id
        WHERE 1=1
    """
    params = []

    if status and status != "TODOS":
        base_sql += " AND o.status = ? "
        params.append(status)

    if q:
        q_up = q.upper()
        q_placa = q_up.replace("-", "").replace(" ", "")
        base_sql += """
            AND (
                REPLACE(REPLACE(UPPER(v.placa), '-', ''), ' ', '') LIKE ?
                OR UPPER(c.nome) LIKE ?
                OR UPPER(v.modelo) LIKE ?
                OR UPPER(v.marca) LIKE ?
                OR CAST(o.id AS TEXT) = ?
            )
        """
        params += [f"%{q_placa}%", f"%{q_up}%", f"%{q_up}%", f"%{q_up}%", q]

    total = con.execute("SELECT COUNT(*) AS n " + base_sql, params).fetchone()["n"]
    pages = max((total + per_page - 1) // per_page, 1)
    prev_page = page_i - 1 if page_i > 1 else None
    next_page = page_i + 1 if page_i < pages else None

    sql = """
        SELECT o.id,
               o.data_entrada,
               o.status,
               o.km,
               o.forma_pagamento,
               v.placa, v.marca, v.modelo,
               c.nome AS cliente_nome,
               c.telefone AS cliente_tel,
               (SELECT COALESCE(SUM(valor_total),0) FROM ordem_itens i WHERE i.ordem_id=o.id) AS total
    """ + base_sql + """
        ORDER BY o.id DESC
        LIMIT ? OFFSET ?
    """

    rows = con.execute(sql, params + [per_page, offset]).fetchall()
    con.close()

    return render_template(
        "os_lista_geral.html",
        oss=rows,
        q=q,
        status=status or "TODOS",
        page=page_i,
        pages=pages,
        total=total,
        prev_page=prev_page,
        next_page=next_page,
        per_page=per_page
    )


# ===================== HISTÓRICO POR PLACA =====================

@app.get("/os/historico/<placa>")
def os_historico(placa):
    placa = norm_placa(placa)
    con = db()

    garantir_coluna(con, "ordens", "forma_pagamento", "TEXT")
    con.commit()

    v = con.execute("SELECT * FROM veiculos WHERE placa=?", (placa,)).fetchone()
    if not v:
        con.close()
        flash("Veículo não encontrado.")
        return redirect("/os")

    rows = con.execute("""
        SELECT o.id,
               o.data_entrada AS data,
               o.status,
               o.km,
               o.forma_pagamento,
               c.nome AS cliente_nome,
               c.telefone AS cliente_tel,
               c.cpf AS cliente_doc,
               (SELECT GROUP_CONCAT(tipo || ': ' || descricao, CHAR(10))
                FROM ordem_itens i WHERE i.ordem_id=o.id) AS servico,
               (SELECT COALESCE(SUM(valor_total),0)
                FROM ordem_itens i WHERE i.ordem_id=o.id) AS valor
        FROM ordens o
        JOIN clientes c ON c.id = o.cliente_id
        WHERE o.placa=?
        ORDER BY o.id DESC
    """, (placa,)).fetchall()

    con.close()
    return render_template("os_historico.html", v=v, rows=rows)


@app.post("/os/finalizar")
def os_finalizar():
    ordem_id = int(request.form.get("ordem_id"))
    forma_pagamento = (request.form.get("forma_pagamento") or "").strip().upper()

    if forma_pagamento not in ["DINHEIRO", "DEBITO", "CREDITO", "PIX", "CHEQUE"]:
        flash("Selecione a forma de pagamento.")
        return redirect(url_for("os_editar", ordem_id=ordem_id))

    con = db()
    garantir_coluna(con, "ordens", "forma_pagamento", "TEXT")

    con.execute("""
        UPDATE ordens
           SET status='FINALIZADA',
               forma_pagamento=?
         WHERE id=?
    """, (forma_pagamento, ordem_id))
    con.commit()
    con.close()

    flash(f"OS finalizada com pagamento em {forma_pagamento}.")
    return redirect(url_for("os_editar", ordem_id=ordem_id))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
