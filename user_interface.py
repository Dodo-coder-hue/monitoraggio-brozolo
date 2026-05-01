import streamlit as st
import pandas as pd
import sqlalchemy
from sqlalchemy import create_engine, text
import ftplib
import io
from datetime import datetime
import os
import plotly.express as px

# --- 1. CONFIGURAZIONI ---
FTP_CONFIG = {
    "host": "ftp.geotronica.it",
    "user": "4256589@aruba.it",
    "pass": "@Birocco556",
    "file": "/www.geotronica.it/ftp/BROZOLO/Brozolo esempio.csv"
}

TARGET_TABLE = "tabella_dati_ftp"

# --- 2. FUNZIONI TECNICHE (IL "MOTORE" DELL'APPLICAZIONE) ---

def get_engine():
    """Connessione blindata con conversione manuale della porta"""
    import sqlalchemy
    
    # Prendiamo i dati dai Secrets
    u = st.secrets["db_user"]
    p = st.secrets["db_pass"]
    h = st.secrets["db_host"]
    db = st.secrets["db_name"]
    
    # FORZIAMO la porta a essere un numero intero, pulendola da ogni spazio
    porta = int(str(st.secrets["db_port"]).strip())
    
    # Costruiamo l'URL
    url = f"postgresql://{u}:{p}@{h}:{porta}/{db}?pgbouncer=true"
    return sqlalchemy.create_engine(url)



def carica_da_ftp():
    """
    Gestisce l'intero flusso di importazione dati:
    1. Si connette all'FTP e scarica il CSV in memoria RAM (buffer).
    2. Pulisce i dati e assegna i nomi alle colonne.
    3. Converte le date e ordina cronologicamente.
    4. Sovrascrive la tabella su PostgreSQL.
    """
    # Connessione al server FTP definito nelle configurazioni globali
    with ftplib.FTP(FTP_CONFIG["host"]) as ftp:
        ftp.login(FTP_CONFIG["user"], FTP_CONFIG["pass"])
        ftp.set_pasv(True) # Necessario per evitare blocchi dai firewall moderni
        buffer = io.BytesIO()
        # Scarica il file e lo scrive nel buffer di memoria
        ftp.retrbinary(f"RETR {FTP_CONFIG['file']}", buffer.write)
        buffer.seek(0) # Riporta l'indice all'inizio per la lettura
    
    # Nomi delle colonne basati sulla struttura del tuo file (senza intestazione)
    nomi_colonne = ['Codice_misura', 'Data_misura', 'Nome_punto', 'Misura', 'Inclinazione']
    
    # Lettura CSV: sep=',' perché hai notato che il separatore è la virgola
    df = pd.read_csv(buffer, sep=',', header=None, names=nomi_colonne, engine='python')
    
    # Conversione Data: format='%d/%m/%y' gestisce l'anno a 2 cifre (es. 25 invece di 2025)
    df['Data_misura'] = pd.to_datetime(df['Data_misura'], format='%d/%m/%y', errors='coerce')
    
    # Pulizia: eliminiamo righe con date corrotte e ordiniamo per data (fondamentale per i grafici)
    df = df.dropna(subset=['Data_misura']).sort_values('Data_misura')
    
    # Caricamento su DB: 'replace' cancella i vecchi dati e inserisce i nuovi (Sync totale)
    engine = get_engine()
    df.to_sql(TARGET_TABLE, engine, if_exists='replace', index=False)
    
    return df

def ottieni_iniziali(nome):
    """Estrae le prime due lettere dello username per creare il badge grafico in alto."""
    if nome and len(nome) >= 2:
        return nome[:2].upper()
    return nome.upper() if nome else "??"

# --- 3. GESTIONE DELLO STATO (SESSION STATE) ---
# Streamlit ricarica l'intero script ad ogni click. 
# Usiamo st.session_state per 'salvare' le variabili che non devono resettarsi.

if 'autenticato' not in st.session_state:
    st.session_state['autenticato'] = False # Stato del login

if 'utente_nome' not in st.session_state:
    st.session_state['utente_nome'] = "" # Nome dell'utente loggato

if 'dati_caricati' not in st.session_state:
    st.session_state['dati_caricati'] = False # Sblocca la dashboard dopo il sync FTP

if 'vista_attiva' not in st.session_state:
    st.session_state['vista_attiva'] = 'nessuna' # Decide se mostrare grafico o tabella punto

# --- 4. INTERFACCIA GRAFICA (LAYOUT) ---
st.set_page_config(page_title="Monitoraggio SP590", layout="wide")

# Intestazione con stile HTML centrato
st.markdown("<h1 style='text-align: center;'>CITTÀ METROPOLITANA DI TORINO</h1>", unsafe_allow_html=True)
st.markdown("<h3 style='text-align: center;'>Sistema di monitoraggio integrato</h3>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray;'>Sito monitorato: SP590 loc. Fabbrica, comune di Brozolo (TO)</p>", unsafe_allow_html=True)

# Badge Utente: viene renderizzato solo se l'utente ha superato il login
if st.session_state['autenticato']:
    iniziali = ottieni_iniziali(st.session_state['utente_nome'])
    st.markdown(
        f"""
        <div style="position: absolute; top: -85px; right: 0px; display: flex; align-items: center; background-color: #ffffff; padding: 5px 15px; border-radius: 50px; border: 1px solid #e0e0e0; box-shadow: 2px 2px 5px rgba(0,0,0,0.05);">
            <div style="background-color: #004a99; color: white; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; margin-right: 10px;">
                {iniziali}
            </div>
            <span style="font-weight: 500; color: #444; font-size: 14px;">{st.session_state['utente_nome']}</span>
        </div>
        """, 
        unsafe_allow_html=True
    )

st.write("---")

# --- 5. LOGICA DI ACCESSO / REGISTRAZIONE INTELLIGENTE ---
if not st.session_state['autenticato']:
    st.subheader("🔐 Accesso o Registrazione Utente")
    with st.form("auth_form"):
        user_in = st.text_input("Username").strip()
        pass_in = st.text_input("Password", type="password").strip()
        c_login, c_reg = st.columns(2)
        btn_login = c_login.form_submit_button("ACCEDI")
        btn_reg = c_reg.form_submit_button("REGISTRATI")

        # --- LOGICA DEL TASTO ACCEDI ---
        if btn_login:
            if user_in and pass_in:
                try:
                    engine = get_engine()
                    with engine.connect() as conn:
                        # STEP 1: Cerchiamo se lo username esiste nel database
                        check_user = conn.execute(text("SELECT * FROM utenti WHERE username = :u"), {"u": user_in}).fetchone()
                        
                        if check_user:
                            # STEP 2: Se lo username esiste, verifichiamo la password associata
                            query = text("SELECT * FROM utenti WHERE username = :u AND password = :p")
                            result = conn.execute(query, {"u": user_in, "p": pass_in}).fetchone()
                            
                            if result:
                                st.session_state['autenticato'] = True
                                st.session_state['utente_nome'] = user_in
                                st.rerun() # Login riuscito, ricarichiamo la dashboard
                            else:
                                st.error("❌ Password errata per questo utente. Riprova.")
                        else:
                            # STEP 3: Se lo username non esiste, avvisiamo l'utente che deve registrarsi
                            st.warning("❓ Utente non trovato nel sistema. Se sei nuovo, usa il tasto 'REGISTRATI'.")
                except Exception as e:
                    st.error(f"Errore connessione al Database Utenti: {e}")
            else:
                st.info("💡 Inserisci username e password per continuare.")

        # --- LOGICA DEL TASTO REGISTRATI ---
        if btn_reg:
            if user_in and pass_in:
                try:
                    engine = get_engine()
                    with engine.connect() as conn:
                        # Verifichiamo che il nome non sia già occupato da qualcun altro
                        check = conn.execute(text("SELECT * FROM utenti WHERE username = :u"), {"u": user_in}).fetchone()
                        if not check:
                            # Registrazione: inseriamo i dati nella tabella utenti di Postgres
                            conn.execute(text("INSERT INTO utenti (username, password) VALUES (:u, :p)"), {"u": user_in, "p": pass_in})
                            conn.commit()
                            st.success(f"✅ Utente '{user_in}' registrato con successo! Ora puoi effettuare l'accesso.")
                        else:
                            st.warning("⚠️ Questo username è già occupato. Prova con un altro nome.")
                except Exception as e:
                    st.error(f"Errore durante la registrazione: {e}")
            else:
                st.warning("⚠️ Inserisci dati validi in entrambi i campi per la registrazione.")

# --- 6. AGGIORNAMENTO DATI OBBLIGATORIO (STEP POST-LOGIN) ---
elif not st.session_state['dati_caricati']:
    st.title(f"👋 Benvenuto, {st.session_state['utente_nome']}")
    st.info("⚠️ Sincronizza i dati dal server FTP per consultare i monitoraggi più recenti.")
    if st.button("🚀 SCARICA DATI DA FTP E INIZIA", use_container_width=True):
        try:
            # Scarica il file e calcola subito gli estremi temporali
            df_csv = carica_da_ftp()
            st.session_state['data_inizio_monitoraggio'] = df_csv['Data_misura'].min().strftime('%d/%m/%Y')
            st.session_state['data_ultima_misura'] = df_csv['Data_misura'].max().strftime('%d/%m/%Y')
            st.session_state['tot_righe'] = len(df_csv)
            st.session_state['dati_caricati'] = True
            st.rerun() # Sblocca la dashboard finale
        except Exception as e:
            st.error(f"Errore durante il recupero dei dati FTP: {e}")

# --- 7. DASHBOARD ATTIVA (VISUALIZZAZIONE DATI) ---
else:
    # Barra laterale per Logout
    st.sidebar.header("📂 Menu")
    if st.sidebar.button("🚪 Logout"):
        st.session_state.update({"autenticato": False, "dati_caricati": False})
        st.rerun()
    
    # Metriche principali: arco temporale e quantità dati
    c1, c2, c3 = st.columns(3)
    c1.metric("Data Prima Misura", st.session_state.get('data_inizio_monitoraggio'))
    c2.metric("Data Ultima Misura", st.session_state.get('data_ultima_misura'))
    c3.metric("Righe Totali Lette", st.session_state.get('tot_righe'))
    
    st.divider()
    
    # Leggiamo la tabella principale da Postgres
    engine = get_engine()
    df_db = pd.read_sql(f"SELECT * FROM {TARGET_TABLE} ORDER BY \"Data_misura\" ASC", engine)
    
    st.subheader("📊 Visualizzazione Database Completo")
    st.dataframe(df_db, use_container_width=True)
    
    st.divider()
    
    # SEZIONE ANALISI SINGOLO PUNTO
    if not df_db.empty:
        st.subheader("🔍 Analisi Dettagliata Punto")
        punti = df_db['Nome_punto'].unique()
        punto_scelto = st.selectbox("🎯 Seleziona il punto da monitorare:", punti)
        df_f = df_db[df_db['Nome_punto'] == punto_scelto]

        # Calcolo dinamico massimi e minimi per le label
        idx_max = df_f['Misura'].idxmax()
        val_max = df_f.loc[idx_max, 'Misura']
        dt_max = df_f.loc[idx_max, 'Data_misura'].strftime('%d/%m/%Y')

        idx_min = df_f['Misura'].idxmin()
        val_min = df_f.loc[idx_min, 'Misura']
        dt_min = df_f.loc[idx_min, 'Data_misura'].strftime('%d/%m/%Y')

        # Visualizzazione label con font grande (HTML Inline)
        st.markdown(f"📈 **Spostamento Massimo:** <span style='font-size:24px; color:#004a99;'>**{val_max} mm**</span> (rilevato il {dt_max})", unsafe_allow_html=True)
        st.markdown(f"📉 **Spostamento Minimo:** <span style='font-size:24px; color:#d32f2f;'>**{val_min} mm**</span> (rilevato il {dt_min})", unsafe_allow_html=True)
        
        st.write("") 

        cb1, cb2 = st.columns(2)
        if cb1.button("📈 Visualizza Grafico", use_container_width=True): st.session_state['vista_attiva'] = 'grafico'
        if cb2.button("📋 Tabella Storico Misure", use_container_width=True): st.session_state['vista_attiva'] = 'tabella'
        
        # LOGICA GRAFICO PROFESSIONALE (PLOTLY)
        if st.session_state['vista_attiva'] == 'grafico':
            st.subheader(f"Andamento Temporale: {punto_scelto}")
            fig = px.line(df_f, x='Data_misura', y='Misura', markers=True, 
                          labels={'Data_misura': 'Data Rilievo', 'Misura': 'Valore Misurato (mm)'},
                          template="plotly_white")
            
            # Impostazioni Layout: font grandi e scala asse Y legata ad asse X per zoom coerente
            fig.update_layout(
                font=dict(size=18),
                xaxis=dict(tickfont=dict(size=14), title=dict(font=dict(size=20)), rangeslider=dict(visible=False), constrain="domain"),
                yaxis=dict(tickfont=dict(size=14), title=dict(font=dict(size=20)), fixedrange=False, scaleanchor="x"),
                hovermode="x unified", height=600
            )
            # Abilitiamo lo zoom diretto con la rotella del mouse
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

        elif st.session_state['vista_attiva'] == 'tabella':
            st.subheader(f"Cronologia Letture: {punto_scelto}")
            st.table(df_f[['Data_misura', 'Misura']].reset_index(drop=True))
