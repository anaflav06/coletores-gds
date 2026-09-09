# -*- coding: utf-8 -*-
"""
CONTROLE DE COLETORES E LEITORES - GDS
Versão oficial para GitHub + Streamlit, com persistência permanente dos dados.

Execução local:
    py -m pip install -r requirements.txt
    py -m streamlit run app.py

Persistência:
- No PC, salva em "database_coletores.json" na mesma pasta do app.
- No Streamlit Cloud, se os Secrets do GitHub estiverem configurados,
  lê e grava o mesmo banco diretamente no repositório.
"""

import base64
import json
import re
import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st


# ============================================================
# CONFIGURAÇÕES GERAIS
# ============================================================

st.set_page_config(
    page_title="Controle de Coletores e Leitores",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_TITLE = "CONTROLE DE COLETORES E LEITORES"
LOCAL_DB_PATH = Path(__file__).with_name("database_coletores.json")

LOCALIZACOES = ["CPQ08", "SAO12", "CDSP2", "ZARA1", "ASSISTÊNCIA"]
TIPOS_EQUIPAMENTO = ["COLETOR", "LEITOR"]
STATUS_EQUIPAMENTO = [
    "DISPONÍVEL",
    "EM USO",
    "EM ASSISTÊNCIA",
    "EMPRESTADO",
    "INATIVO",
    "BAIXADO",
]
SIM_NAO = ["Não", "Sim"]

DEFAULT_USERS = {
    "jessica": "230525",
    "julia": "gds9129",
}

EMPTY_DB = {
    "version": 1,
    "equipamentos": [],
    "movimentacoes": [],
    "assistencias": [],
    "auditoria": [],
}


# ============================================================
# VISUAL
# ============================================================

st.markdown(
    """
    <style>
        .stApp {
            background: #f5f7fb;
        }
        [data-testid="stSidebar"] {
            background: #111827;
        }
        [data-testid="stSidebar"] * {
            color: #f9fafb;
        }
        .app-header {
            padding: 1.15rem 1.4rem;
            border-radius: 16px;
            background: linear-gradient(135deg, #111827 0%, #1f2937 100%);
            color: white;
            margin-bottom: 1rem;
            box-shadow: 0 8px 24px rgba(17,24,39,.10);
        }
        .app-header h1 {
            margin: 0;
            font-size: 1.75rem;
        }
        .app-header p {
            margin: .35rem 0 0 0;
            color: #d1d5db;
        }
        .kpi-card {
            background: white;
            padding: 1rem 1.15rem;
            border-radius: 14px;
            border: 1px solid #e5e7eb;
            box-shadow: 0 4px 14px rgba(17,24,39,.04);
            min-height: 110px;
        }
        .kpi-title {
            color: #6b7280;
            font-size: .85rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .kpi-value {
            color: #111827;
            font-size: 2rem;
            font-weight: 800;
            margin-top: .35rem;
        }
        div[data-testid="stDataFrame"] {
            background: white;
            border-radius: 12px;
        }
        .small-muted {
            color: #6b7280;
            font-size: .9rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def page_header(subtitle="Cadastro, localização, movimentações e assistência técnica"):
    st.markdown(
        f"""
        <div class="app-header">
            <h1>📱 {APP_TITLE}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# UTILITÁRIOS
# ============================================================

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def today_str():
    return date.today().strftime("%d/%m/%Y")


def normalize_text(value):
    return str(value or "").strip()


def normalize_upper(value):
    return normalize_text(value).upper()


def digits_only(value):
    return re.sub(r"\D", "", str(value or ""))


def normalize_imei(value):
    return digits_only(value)


def normalize_mac(value):
    raw = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))
    raw = raw.upper()
    if len(raw) == 12:
        return ":".join(raw[i:i+2] for i in range(0, 12, 2))
    return normalize_upper(value)



def safe_date_br(value):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except Exception:
            return value
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            pass
    return None


def get_user_credentials():
    users = dict(DEFAULT_USERS)

    # Opcional: no Streamlit, permite substituir credenciais por Secrets.
    try:
        secret_users = st.secrets.get("APP_USERS", {})
        if secret_users:
            users = {str(k).lower(): str(v) for k, v in dict(secret_users).items()}
    except Exception:
        pass

    return users


# ============================================================
# BANCO DE DADOS - LOCAL + GITHUB
# ============================================================

def github_config():
    try:
        token = st.secrets.get("GITHUB_TOKEN", "")
        repo = st.secrets.get("GITHUB_REPO", "")
        branch = st.secrets.get("GITHUB_DATA_BRANCH", "main")
        path = st.secrets.get("GITHUB_COLETORES_DB_PATH", "database_coletores.json")
        if token and repo:
            return {
                "token": token,
                "repo": repo,
                "branch": branch,
                "path": path,
            }
    except Exception:
        pass
    return None


def github_headers(cfg):
    return {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_db_shape(db):
    result = deepcopy(EMPTY_DB)
    if isinstance(db, dict):
        for key in result:
            if key in db:
                result[key] = db[key]
    for key in ("equipamentos", "movimentacoes", "assistencias", "auditoria"):
        if not isinstance(result.get(key), list):
            result[key] = []
    return result


def load_local_db():
    if not LOCAL_DB_PATH.exists():
        save_local_db(deepcopy(EMPTY_DB))
        return deepcopy(EMPTY_DB)
    try:
        with open(LOCAL_DB_PATH, "r", encoding="utf-8") as f:
            return ensure_db_shape(json.load(f))
    except Exception:
        return deepcopy(EMPTY_DB)


def save_local_db(db):
    with open(LOCAL_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def load_github_db(cfg):
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{cfg['path']}"
    params = {"ref": cfg["branch"]}
    r = requests.get(url, headers=github_headers(cfg), params=params, timeout=20)

    if r.status_code == 404:
        return deepcopy(EMPTY_DB)

    r.raise_for_status()
    payload = r.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    db = json.loads(content)
    return ensure_db_shape(db)


def save_github_db(db, cfg):
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{cfg['path']}"
    params = {"ref": cfg["branch"]}
    current = requests.get(url, headers=github_headers(cfg), params=params, timeout=20)

    sha = None
    if current.status_code == 200:
        sha = current.json().get("sha")
    elif current.status_code != 404:
        current.raise_for_status()

    content = json.dumps(db, ensure_ascii=False, indent=2).encode("utf-8")
    payload = {
        "message": f"Atualiza banco de coletores - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "content": base64.b64encode(content).decode("ascii"),
        "branch": cfg["branch"],
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=github_headers(cfg), json=payload, timeout=30)
    r.raise_for_status()


def load_db():
    cfg = github_config()
    if cfg:
        try:
            db = load_github_db(cfg)
            # Mantém uma cópia local útil para contingência.
            try:
                save_local_db(db)
            except Exception:
                pass
            return db, "GitHub"
        except Exception as exc:
            st.warning(
                f"Não foi possível ler o banco permanente do GitHub. "
                f"Usando a cópia local neste acesso. Detalhe: {exc}"
            )
    return load_local_db(), "Arquivo local"


def save_db(db):
    db = ensure_db_shape(db)
    save_local_db(db)

    cfg = github_config()
    if cfg:
        try:
            save_github_db(db, cfg)
            return True, "Dados salvos localmente e no GitHub."
        except Exception as exc:
            return False, (
                "Os dados foram salvos no PC, mas não foi possível atualizar "
                f"o banco permanente no GitHub. Detalhe: {exc}"
            )
    return True, "Dados salvos no banco local do PC."


def audit(db, action, item_id="", detail=""):
    db["auditoria"].append(
        {
            "id": str(uuid.uuid4()),
            "data_hora": now_iso(),
            "usuario": st.session_state.get("usuario", ""),
            "acao": action,
            "item_id": item_id,
            "detalhe": detail,
        }
    )


# ============================================================
# LOGIN
# ============================================================

def login_screen():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.15, 1])

    with c2:
        st.markdown(
            """
            <div class="app-header" style="text-align:center;">
                <h1>📱 Coletores e Leitores</h1>
                <p>Acesso restrito</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            users = get_user_credentials()
            user_key = usuario.strip().lower()
            if user_key in users and senha == users[user_key]:
                st.session_state["logged_in"] = True
                st.session_state["usuario"] = user_key
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

        st.caption("GDS • Controle interno de equipamentos")


if not st.session_state.get("logged_in"):
    login_screen()
    st.stop()


# ============================================================
# CARREGA BANCO
# ============================================================

db, db_source = load_db()


# ============================================================
# FUNÇÕES DE NEGÓCIO
# ============================================================

def equipment_by_id(equipment_id):
    return next((e for e in db["equipamentos"] if e.get("id") == equipment_id), None)


def equipment_label(e):
    return f"{e.get('nome_equipamento','SEM NOME')} | {e.get('tipo','')} | {e.get('localizacao','')}"


def validate_equipment(data, editing_id=None):
    errors = []

    if not data["nome_equipamento"]:
        errors.append("Informe o nome/identificação do equipamento.")
    if not data["tipo"]:
        errors.append("Informe o tipo do equipamento.")
    if not data["localizacao"]:
        errors.append("Informe a localização.")
    if not data["status"]:
        errors.append("Informe o status.")

    imei = normalize_imei(data.get("imei"))
    if imei and len(imei) != 15:
        errors.append("Quando informado, o IMEI deve possuir exatamente 15 dígitos.")

    for e in db["equipamentos"]:
        if editing_id and e.get("id") == editing_id:
            continue

        if normalize_upper(e.get("nome_equipamento")) == normalize_upper(data["nome_equipamento"]):
            errors.append("Já existe um equipamento com esse nome/identificação.")
            break

    if imei:
        for e in db["equipamentos"]:
            if editing_id and e.get("id") == editing_id:
                continue
            if normalize_imei(e.get("imei")) == imei:
                errors.append("Já existe um equipamento cadastrado com esse IMEI.")
                break

    serial = normalize_upper(data.get("serial"))
    if serial and serial not in ("*", "**", "N/A", "NA"):
        for e in db["equipamentos"]:
            if editing_id and e.get("id") == editing_id:
                continue
            existing = normalize_upper(e.get("serial"))
            if existing == serial:
                errors.append("Já existe um equipamento cadastrado com esse número de série.")
                break

    return errors


def save_and_notify(success_text="Alterações salvas."):
    ok, msg = save_db(db)
    if ok:
        st.success(success_text)
    else:
        st.warning(msg)
    return ok


def equipment_df(items=None):
    rows = []
    for e in (items if items is not None else db["equipamentos"]):
        rows.append(
            {
                "Equipamento": e.get("nome_equipamento", ""),
                "Tipo": e.get("tipo", ""),
                "Status": e.get("status", ""),
                "Localização": e.get("localizacao", ""),
                "Responsável": e.get("responsavel_atual", ""),
                "IMEI": e.get("imei", ""),
                "Wi-Fi MAC": e.get("wifi_mac", ""),
                "Modelo": e.get("modelo", ""),
                "P/N": e.get("pn_modelo", ""),
                "S/N": e.get("serial", ""),
                "Case": e.get("tem_case", ""),
                "Android": e.get("android", ""),
                "Última atualização": safe_date_br(e.get("data_atualizacao")),
                "Observação": e.get("observacao", ""),
            }
        )
    return pd.DataFrame(rows)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("### 📱 GDS")
    st.caption(f"Usuário: {st.session_state.get('usuario','').upper()}")
    st.caption(f"Banco: {db_source}")
    st.divider()

    menu = st.radio(
        "Menu",
        [
            "🏠 Dashboard",
            "📋 Equipamentos",
            "🔄 Movimentações",
            "🛠️ Assistência",
            "📊 Relatórios",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# ============================================================
# DASHBOARD
# ============================================================

if menu == "🏠 Dashboard":
    page_header()

    total = len(db["equipamentos"])
    em_uso = sum(1 for e in db["equipamentos"] if e.get("status") == "EM USO")
    disponiveis = sum(1 for e in db["equipamentos"] if e.get("status") == "DISPONÍVEL")
    assistencia = sum(1 for e in db["equipamentos"] if e.get("status") == "EM ASSISTÊNCIA")

    cols = st.columns(4)
    cards = [
        ("Total de equipamentos", total),
        ("Em uso", em_uso),
        ("Disponíveis", disponiveis),
        ("Em assistência", assistencia),
    ]
    for col, (title, value) in zip(cols, cards):
        with col:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-title">{title}</div>
                    <div class="kpi-value">{value}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("### Equipamentos por unidade")
    if db["equipamentos"]:
        loc_rows = []
        for loc in LOCALIZACOES:
            loc_rows.append(
                {
                    "Localização": loc,
                    "Quantidade": sum(
                        1 for e in db["equipamentos"] if e.get("localizacao") == loc
                    ),
                }
            )
        loc_df = pd.DataFrame(loc_rows)
        st.dataframe(loc_df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum equipamento cadastrado ainda. O app está zerado para o novo cadastro.")

    st.markdown("### Últimos equipamentos atualizados")
    latest = sorted(
        db["equipamentos"],
        key=lambda x: x.get("atualizado_em", ""),
        reverse=True,
    )[:10]
    if latest:
        st.dataframe(equipment_df(latest), use_container_width=True, hide_index=True)
    else:
        st.caption("Sem registros.")


# ============================================================
# EQUIPAMENTOS
# ============================================================

elif menu == "📋 Equipamentos":
    page_header("Cadastro completo e edição dos coletores e leitores")

    tab1, tab2 = st.tabs(["➕ Novo equipamento", "✏️ Consultar / editar"])

    with tab1:
        st.markdown("### Cadastrar equipamento")

        with st.form("novo_equipamento", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)

            with c1:
                nome = st.text_input("Nome / identificação *", placeholder="Ex.: GDS2026-01")
                tipo = st.selectbox("Tipo *", TIPOS_EQUIPAMENTO)
                localizacao = st.selectbox("Localização *", LOCALIZACOES)
                status = st.selectbox("Status *", STATUS_EQUIPAMENTO)
                responsavel = st.text_input("Responsável atual")

            with c2:
                imei = st.text_input("IMEI", placeholder="15 dígitos")
                wifi_mac = st.text_input("Wi-Fi MAC ID")
                pn_modelo = st.text_input("P/N modelo")
                serial = st.text_input("S/N - número de série")
                mfd = st.text_input("MFD")

            with c3:
                modelo = st.text_input("Modelo")
                android = st.text_input("Versão Android")
                tem_case = st.selectbox("Tem case?", SIM_NAO)
                lacre = st.text_input("Número do lacre")
                senha_pin = st.text_input("Senha PIN")

            st.markdown("#### Dados de acesso do equipamento")
            a1, a2 = st.columns(2)
            with a1:
                email = st.text_input("E-mail")
            with a2:
                senha_equipamento = st.text_input("Senha do equipamento")

            observacao = st.text_area("Observação")
            data_atualizacao = st.date_input("Data da atualização", value=date.today())

            submitted = st.form_submit_button("💾 Salvar equipamento", use_container_width=True)

        if submitted:
            data = {
                "id": str(uuid.uuid4()),
                "nome_equipamento": normalize_upper(nome),
                "tipo": tipo,
                "localizacao": localizacao,
                "status": status,
                "responsavel_atual": normalize_text(responsavel),
                "imei": normalize_imei(imei),
                "wifi_mac": normalize_mac(wifi_mac),
                "pn_modelo": normalize_text(pn_modelo),
                "serial": normalize_text(serial),
                "mfd": normalize_text(mfd),
                "modelo": normalize_text(modelo),
                "android": normalize_text(android),
                "tem_case": tem_case,
                "numero_lacre": normalize_text(lacre),
                "senha_pin": normalize_text(senha_pin),
                "email": normalize_text(email),
                "senha_equipamento": normalize_text(senha_equipamento),
                "observacao": normalize_text(observacao),
                "data_atualizacao": data_atualizacao.isoformat(),
                "criado_em": now_iso(),
                "atualizado_em": now_iso(),
                "criado_por": st.session_state.get("usuario", ""),
            }

            errors = validate_equipment(data)
            if errors:
                for err in errors:
                    st.error(err)
            else:
                db["equipamentos"].append(data)
                audit(db, "CADASTRO EQUIPAMENTO", data["id"], data["nome_equipamento"])
                save_and_notify("Equipamento cadastrado com sucesso.")

    with tab2:
        if not db["equipamentos"]:
            st.info("Ainda não existem equipamentos cadastrados.")
        else:
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                busca = st.text_input("Pesquisar", placeholder="Nome, IMEI, série ou responsável")
            with f2:
                filtro_tipo = st.selectbox("Tipo", ["TODOS"] + TIPOS_EQUIPAMENTO)
            with f3:
                filtro_local = st.selectbox("Localização", ["TODAS"] + LOCALIZACOES)
            with f4:
                filtro_status = st.selectbox("Status", ["TODOS"] + STATUS_EQUIPAMENTO)

            filtered = []
            term = normalize_upper(busca)
            for e in db["equipamentos"]:
                haystack = " ".join(
                    [
                        str(e.get("nome_equipamento", "")),
                        str(e.get("imei", "")),
                        str(e.get("serial", "")),
                        str(e.get("responsavel_atual", "")),
                        str(e.get("modelo", "")),
                    ]
                ).upper()

                if term and term not in haystack:
                    continue
                if filtro_tipo != "TODOS" and e.get("tipo") != filtro_tipo:
                    continue
                if filtro_local != "TODAS" and e.get("localizacao") != filtro_local:
                    continue
                if filtro_status != "TODOS" and e.get("status") != filtro_status:
                    continue
                filtered.append(e)

            st.dataframe(equipment_df(filtered), use_container_width=True, hide_index=True)

            if filtered:
                options = {equipment_label(e): e["id"] for e in filtered}
                selected_label = st.selectbox("Selecione um equipamento para editar", list(options.keys()))
                selected_id = options[selected_label]
                e = equipment_by_id(selected_id)

                st.markdown("### Editar equipamento")
                with st.form(f"edit_{selected_id}"):
                    c1, c2, c3 = st.columns(3)

                    with c1:
                        ed_nome = st.text_input("Nome / identificação *", value=e.get("nome_equipamento", ""))
                        ed_tipo = st.selectbox(
                            "Tipo *",
                            TIPOS_EQUIPAMENTO,
                            index=TIPOS_EQUIPAMENTO.index(e.get("tipo")) if e.get("tipo") in TIPOS_EQUIPAMENTO else 0,
                        )
                        ed_local = st.selectbox(
                            "Localização *",
                            LOCALIZACOES,
                            index=LOCALIZACOES.index(e.get("localizacao")) if e.get("localizacao") in LOCALIZACOES else 0,
                        )
                        ed_status = st.selectbox(
                            "Status *",
                            STATUS_EQUIPAMENTO,
                            index=STATUS_EQUIPAMENTO.index(e.get("status")) if e.get("status") in STATUS_EQUIPAMENTO else 0,
                        )
                        ed_resp = st.text_input("Responsável atual", value=e.get("responsavel_atual", ""))

                    with c2:
                        ed_imei = st.text_input("IMEI", value=e.get("imei", ""))
                        ed_mac = st.text_input("Wi-Fi MAC ID", value=e.get("wifi_mac", ""))
                        ed_pn = st.text_input("P/N modelo", value=e.get("pn_modelo", ""))
                        ed_serial = st.text_input("S/N - número de série", value=e.get("serial", ""))
                        ed_mfd = st.text_input("MFD", value=e.get("mfd", ""))

                    with c3:
                        ed_modelo = st.text_input("Modelo", value=e.get("modelo", ""))
                        ed_android = st.text_input("Versão Android", value=e.get("android", ""))
                        current_case = e.get("tem_case", "Não")
                        ed_case = st.selectbox(
                            "Tem case?",
                            SIM_NAO,
                            index=SIM_NAO.index(current_case) if current_case in SIM_NAO else 0,
                        )
                        ed_lacre = st.text_input("Número do lacre", value=e.get("numero_lacre", ""))
                        ed_pin = st.text_input("Senha PIN", value=e.get("senha_pin", ""))

                    a1, a2 = st.columns(2)
                    with a1:
                        ed_email = st.text_input("E-mail", value=e.get("email", ""))
                    with a2:
                        ed_senha = st.text_input("Senha do equipamento", value=e.get("senha_equipamento", ""))

                    ed_obs = st.text_area("Observação", value=e.get("observacao", ""))
                    current_date = parse_date(e.get("data_atualizacao")) or date.today()
                    ed_data = st.date_input("Data da atualização", value=current_date)

                    save_edit = st.form_submit_button("💾 Salvar alterações", use_container_width=True)

                if save_edit:
                    old_local = e.get("localizacao", "")
                    old_resp = e.get("responsavel_atual", "")
                    old_status = e.get("status", "")

                    updated = dict(e)
                    updated.update(
                        {
                            "nome_equipamento": normalize_upper(ed_nome),
                            "tipo": ed_tipo,
                            "localizacao": ed_local,
                            "status": ed_status,
                            "responsavel_atual": normalize_text(ed_resp),
                            "imei": normalize_imei(ed_imei),
                            "wifi_mac": normalize_mac(ed_mac),
                            "pn_modelo": normalize_text(ed_pn),
                            "serial": normalize_text(ed_serial),
                            "mfd": normalize_text(ed_mfd),
                            "modelo": normalize_text(ed_modelo),
                            "android": normalize_text(ed_android),
                            "tem_case": ed_case,
                            "numero_lacre": normalize_text(ed_lacre),
                            "senha_pin": normalize_text(ed_pin),
                            "email": normalize_text(ed_email),
                            "senha_equipamento": normalize_text(ed_senha),
                            "observacao": normalize_text(ed_obs),
                            "data_atualizacao": ed_data.isoformat(),
                            "atualizado_em": now_iso(),
                        }
                    )

                    errors = validate_equipment(updated, editing_id=selected_id)
                    if errors:
                        for err in errors:
                            st.error(err)
                    else:
                        e.update(updated)

                        if (
                            old_local != ed_local
                            or old_resp != normalize_text(ed_resp)
                            or old_status != ed_status
                        ):
                            db["movimentacoes"].append(
                                {
                                    "id": str(uuid.uuid4()),
                                    "equipamento_id": selected_id,
                                    "equipamento": e.get("nome_equipamento", ""),
                                    "data": date.today().isoformat(),
                                    "origem": old_local,
                                    "destino": ed_local,
                                    "responsavel_anterior": old_resp,
                                    "responsavel_novo": normalize_text(ed_resp),
                                    "status_anterior": old_status,
                                    "status_novo": ed_status,
                                    "observacao": "Movimentação gerada automaticamente pela edição do cadastro.",
                                    "registrado_em": now_iso(),
                                    "registrado_por": st.session_state.get("usuario", ""),
                                }
                            )

                        audit(db, "EDIÇÃO EQUIPAMENTO", selected_id, e.get("nome_equipamento", ""))
                        save_and_notify("Equipamento atualizado com sucesso.")
                        st.rerun()


# ============================================================
# MOVIMENTAÇÕES
# ============================================================

elif menu == "🔄 Movimentações":
    page_header("Transferência entre unidades e troca de responsável")

    if not db["equipamentos"]:
        st.info("Cadastre ao menos um equipamento antes de registrar movimentações.")
    else:
        options = {equipment_label(e): e["id"] for e in db["equipamentos"]}

        with st.form("form_movimentacao"):
            equipamento_label_sel = st.selectbox("Equipamento *", list(options.keys()))
            selected_id = options[equipamento_label_sel]
            selected = equipment_by_id(selected_id)

            st.caption(
                f"Atual: {selected.get('localizacao','')} • "
                f"{selected.get('status','')} • "
                f"Responsável: {selected.get('responsavel_atual','—') or '—'}"
            )

            c1, c2, c3 = st.columns(3)
            with c1:
                data_mov = st.date_input("Data da movimentação", value=date.today())
                destino = st.selectbox(
                    "Nova localização *",
                    LOCALIZACOES,
                    index=LOCALIZACOES.index(selected.get("localizacao"))
                    if selected.get("localizacao") in LOCALIZACOES else 0,
                )
            with c2:
                novo_resp = st.text_input("Novo responsável", value=selected.get("responsavel_atual", ""))
                novo_status = st.selectbox(
                    "Novo status",
                    STATUS_EQUIPAMENTO,
                    index=STATUS_EQUIPAMENTO.index(selected.get("status"))
                    if selected.get("status") in STATUS_EQUIPAMENTO else 0,
                )
            with c3:
                obs_mov = st.text_area("Observação")

            mov_submit = st.form_submit_button("🔄 Registrar movimentação", use_container_width=True)

        if mov_submit:
            mov = {
                "id": str(uuid.uuid4()),
                "equipamento_id": selected_id,
                "equipamento": selected.get("nome_equipamento", ""),
                "data": data_mov.isoformat(),
                "origem": selected.get("localizacao", ""),
                "destino": destino,
                "responsavel_anterior": selected.get("responsavel_atual", ""),
                "responsavel_novo": normalize_text(novo_resp),
                "status_anterior": selected.get("status", ""),
                "status_novo": novo_status,
                "observacao": normalize_text(obs_mov),
                "registrado_em": now_iso(),
                "registrado_por": st.session_state.get("usuario", ""),
            }
            db["movimentacoes"].append(mov)

            selected["localizacao"] = destino
            selected["responsavel_atual"] = normalize_text(novo_resp)
            selected["status"] = novo_status
            selected["data_atualizacao"] = data_mov.isoformat()
            selected["atualizado_em"] = now_iso()

            audit(db, "MOVIMENTAÇÃO", selected_id, f"{mov['origem']} -> {destino}")
            save_and_notify("Movimentação registrada e cadastro atualizado.")
            st.rerun()

    st.markdown("### Histórico de movimentações")
    if db["movimentacoes"]:
        rows = []
        for m in sorted(db["movimentacoes"], key=lambda x: x.get("registrado_em", ""), reverse=True):
            rows.append(
                {
                    "Data": safe_date_br(m.get("data")),
                    "Equipamento": m.get("equipamento", ""),
                    "Origem": m.get("origem", ""),
                    "Destino": m.get("destino", ""),
                    "Responsável anterior": m.get("responsavel_anterior", ""),
                    "Novo responsável": m.get("responsavel_novo", ""),
                    "Status anterior": m.get("status_anterior", ""),
                    "Novo status": m.get("status_novo", ""),
                    "Observação": m.get("observacao", ""),
                    "Registrado por": m.get("registrado_por", ""),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("Nenhuma movimentação registrada.")


# ============================================================
# ASSISTÊNCIA
# ============================================================

elif menu == "🛠️ Assistência":
    page_header("Histórico de defeitos, envio e retorno da assistência")

    if not db["equipamentos"]:
        st.info("Cadastre ao menos um equipamento antes de registrar assistência.")
    else:
        options = {equipment_label(e): e["id"] for e in db["equipamentos"]}

        with st.form("form_assistencia"):
            equipamento_label_sel = st.selectbox("Equipamento *", list(options.keys()))
            selected_id = options[equipamento_label_sel]
            selected = equipment_by_id(selected_id)

            c1, c2, c3 = st.columns(3)
            with c1:
                data_envio = st.date_input("Data de envio", value=date.today())
                defeito = st.text_area("Defeito / motivo *")
            with c2:
                fornecedor = st.text_input("Assistência / fornecedor")
                custo = st.number_input("Custo (R$)", min_value=0.0, step=10.0, format="%.2f")
            with c3:
                obs_ass = st.text_area("Observação")
                marcar_assistencia = st.checkbox(
                    "Mover equipamento para ASSISTÊNCIA e status EM ASSISTÊNCIA",
                    value=True,
                )

            ass_submit = st.form_submit_button("🛠️ Registrar envio", use_container_width=True)

        if ass_submit:
            if not normalize_text(defeito):
                st.error("Informe o defeito/motivo.")
            else:
                origem_anterior = selected.get("localizacao", "")
                status_anterior = selected.get("status", "")

                ass = {
                    "id": str(uuid.uuid4()),
                    "equipamento_id": selected_id,
                    "equipamento": selected.get("nome_equipamento", ""),
                    "data_envio": data_envio.isoformat(),
                    "defeito": normalize_text(defeito),
                    "fornecedor": normalize_text(fornecedor),
                    "custo": float(custo),
                    "observacao_envio": normalize_text(obs_ass),
                    "status_assistencia": "EM ABERTO",
                    "data_retorno": "",
                    "servico_realizado": "",
                    "local_retorno": "",
                    "observacao_retorno": "",
                    "registrado_em": now_iso(),
                    "registrado_por": st.session_state.get("usuario", ""),
                }
                db["assistencias"].append(ass)

                if marcar_assistencia:
                    selected["localizacao"] = "ASSISTÊNCIA"
                    selected["status"] = "EM ASSISTÊNCIA"
                    selected["atualizado_em"] = now_iso()

                    db["movimentacoes"].append(
                        {
                            "id": str(uuid.uuid4()),
                            "equipamento_id": selected_id,
                            "equipamento": selected.get("nome_equipamento", ""),
                            "data": data_envio.isoformat(),
                            "origem": origem_anterior,
                            "destino": "ASSISTÊNCIA",
                            "responsavel_anterior": selected.get("responsavel_atual", ""),
                            "responsavel_novo": selected.get("responsavel_atual", ""),
                            "status_anterior": status_anterior,
                            "status_novo": "EM ASSISTÊNCIA",
                            "observacao": f"Envio para assistência: {normalize_text(defeito)}",
                            "registrado_em": now_iso(),
                            "registrado_por": st.session_state.get("usuario", ""),
                        }
                    )

                audit(db, "ENVIO ASSISTÊNCIA", selected_id, normalize_text(defeito))
                save_and_notify("Envio para assistência registrado.")
                st.rerun()

    st.markdown("### Assistências em aberto")
    open_items = [a for a in db["assistencias"] if a.get("status_assistencia") == "EM ABERTO"]

    if open_items:
        open_options = {
            f"{a.get('equipamento','')} | Envio {safe_date_br(a.get('data_envio'))} | {a.get('defeito','')}": a["id"]
            for a in open_items
        }
        chosen = st.selectbox("Selecione para registrar o retorno", list(open_options.keys()))
        ass_id = open_options[chosen]
        ass = next(a for a in db["assistencias"] if a["id"] == ass_id)
        eq = equipment_by_id(ass["equipamento_id"])

        with st.form(f"retorno_{ass_id}"):
            r1, r2 = st.columns(2)
            with r1:
                data_retorno = st.date_input("Data do retorno", value=date.today())
                servico = st.text_area("Serviço realizado *")
                local_retorno = st.selectbox(
                    "Localização após retorno *",
                    [x for x in LOCALIZACOES if x != "ASSISTÊNCIA"],
                )
            with r2:
                status_retorno = st.selectbox(
                    "Status após retorno",
                    ["DISPONÍVEL", "EM USO", "EMPRESTADO", "INATIVO"],
                )
                obs_retorno = st.text_area("Observação do retorno")

            retorno_submit = st.form_submit_button("✅ Finalizar assistência", use_container_width=True)

        if retorno_submit:
            if not normalize_text(servico):
                st.error("Informe o serviço realizado.")
            else:
                origem_anterior = eq.get("localizacao", "") if eq else ""
                status_anterior = eq.get("status", "") if eq else ""

                ass["status_assistencia"] = "FINALIZADA"
                ass["data_retorno"] = data_retorno.isoformat()
                ass["servico_realizado"] = normalize_text(servico)
                ass["local_retorno"] = local_retorno
                ass["observacao_retorno"] = normalize_text(obs_retorno)
                ass["finalizado_em"] = now_iso()
                ass["finalizado_por"] = st.session_state.get("usuario", "")

                if eq:
                    eq["localizacao"] = local_retorno
                    eq["status"] = status_retorno
                    eq["data_atualizacao"] = data_retorno.isoformat()
                    eq["atualizado_em"] = now_iso()

                    db["movimentacoes"].append(
                        {
                            "id": str(uuid.uuid4()),
                            "equipamento_id": eq["id"],
                            "equipamento": eq.get("nome_equipamento", ""),
                            "data": data_retorno.isoformat(),
                            "origem": origem_anterior,
                            "destino": local_retorno,
                            "responsavel_anterior": eq.get("responsavel_atual", ""),
                            "responsavel_novo": eq.get("responsavel_atual", ""),
                            "status_anterior": status_anterior,
                            "status_novo": status_retorno,
                            "observacao": f"Retorno da assistência: {normalize_text(servico)}",
                            "registrado_em": now_iso(),
                            "registrado_por": st.session_state.get("usuario", ""),
                        }
                    )

                audit(db, "RETORNO ASSISTÊNCIA", ass.get("equipamento_id", ""), normalize_text(servico))
                save_and_notify("Assistência finalizada e equipamento atualizado.")
                st.rerun()
    else:
        st.caption("Nenhuma assistência em aberto.")

    st.markdown("### Histórico de assistência")
    if db["assistencias"]:
        rows = []
        for a in sorted(db["assistencias"], key=lambda x: x.get("registrado_em", ""), reverse=True):
            rows.append(
                {
                    "Equipamento": a.get("equipamento", ""),
                    "Envio": safe_date_br(a.get("data_envio")),
                    "Defeito": a.get("defeito", ""),
                    "Assistência / fornecedor": a.get("fornecedor", ""),
                    "Custo (R$)": a.get("custo", 0),
                    "Situação": a.get("status_assistencia", ""),
                    "Retorno": safe_date_br(a.get("data_retorno")),
                    "Serviço realizado": a.get("servico_realizado", ""),
                    "Local após retorno": a.get("local_retorno", ""),
                    "Observação": a.get("observacao_retorno", "") or a.get("observacao_envio", ""),
                }
            )
        df_ass = pd.DataFrame(rows)
        st.dataframe(
            df_ass,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Custo (R$)": st.column_config.NumberColumn(format="R$ %.2f")
            },
        )
    else:
        st.caption("Nenhum histórico de assistência registrado.")


# ============================================================
# RELATÓRIOS
# ============================================================

elif menu == "📊 Relatórios":
    page_header("Filtros, conferência e exportação dos dados")

    if not db["equipamentos"]:
        st.info("Ainda não existem equipamentos para gerar relatório.")
    else:
        r1, r2, r3 = st.columns(3)
        with r1:
            rel_local = st.multiselect("Localização", LOCALIZACOES, default=LOCALIZACOES)
        with r2:
            rel_tipo = st.multiselect("Tipo", TIPOS_EQUIPAMENTO, default=TIPOS_EQUIPAMENTO)
        with r3:
            rel_status = st.multiselect("Status", STATUS_EQUIPAMENTO, default=STATUS_EQUIPAMENTO)

        rel_items = [
            e for e in db["equipamentos"]
            if e.get("localizacao") in rel_local
            and e.get("tipo") in rel_tipo
            and e.get("status") in rel_status
        ]

        df_rel = equipment_df(rel_items)
        st.dataframe(df_rel, use_container_width=True, hide_index=True)

        st.markdown("### Exportações")
        c1, c2, c3 = st.columns(3)

        with c1:
            csv_equip = df_rel.to_csv(index=False, sep=";", encoding="utf-8-sig")
            st.download_button(
                "⬇️ Equipamentos CSV",
                data=csv_equip.encode("utf-8-sig"),
                file_name=f"coletores_leitores_{date.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with c2:
            mov_rows = []
            for m in db["movimentacoes"]:
                mov_rows.append(
                    {
                        "Data": safe_date_br(m.get("data")),
                        "Equipamento": m.get("equipamento", ""),
                        "Origem": m.get("origem", ""),
                        "Destino": m.get("destino", ""),
                        "Responsável anterior": m.get("responsavel_anterior", ""),
                        "Novo responsável": m.get("responsavel_novo", ""),
                        "Status anterior": m.get("status_anterior", ""),
                        "Novo status": m.get("status_novo", ""),
                        "Observação": m.get("observacao", ""),
                    }
                )
            df_mov = pd.DataFrame(mov_rows)
            csv_mov = df_mov.to_csv(index=False, sep=";", encoding="utf-8-sig")
            st.download_button(
                "⬇️ Movimentações CSV",
                data=csv_mov.encode("utf-8-sig"),
                file_name=f"movimentacoes_coletores_{date.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with c3:
            ass_rows = []
            for a in db["assistencias"]:
                ass_rows.append(
                    {
                        "Equipamento": a.get("equipamento", ""),
                        "Envio": safe_date_br(a.get("data_envio")),
                        "Defeito": a.get("defeito", ""),
                        "Fornecedor": a.get("fornecedor", ""),
                        "Custo": a.get("custo", 0),
                        "Situação": a.get("status_assistencia", ""),
                        "Retorno": safe_date_br(a.get("data_retorno")),
                        "Serviço": a.get("servico_realizado", ""),
                    }
                )
            df_ass_export = pd.DataFrame(ass_rows)
            csv_ass = df_ass_export.to_csv(index=False, sep=";", encoding="utf-8-sig")
            st.download_button(
                "⬇️ Assistências CSV",
                data=csv_ass.encode("utf-8-sig"),
                file_name=f"assistencias_coletores_{date.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.markdown("### Banco / segurança dos dados")
        if db_source == "GitHub":
            st.success("Banco permanente do GitHub conectado.")
        else:
            st.info(
                "No PC, os dados ficam gravados em "
                "`database_coletores.json` na mesma pasta do app e permanecem "
                "salvos ao fechar e abrir novamente."
            )

        st.caption(
            "Para publicação no Streamlit, configure os Secrets do GitHub "
            "para que os dados não dependam do armazenamento temporário do servidor."
        )
