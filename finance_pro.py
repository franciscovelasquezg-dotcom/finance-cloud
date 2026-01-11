import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time
import socket
import hashlib
from supabase import create_client, Client
from twilio.rest import Client as TwilioClient

# --- NOTIFICACIONES TWILIO (WHATSAPP) ---
def enviar_alerta_whatsapp(mensaje):
    """Envía alerta WhatsApp usando Credenciales Seguras de Streamlit"""
    try:
        if "twilio" in st.secrets:
            # Obtener credenciales de secretos (Local o Nube)
            sid = st.secrets["twilio"]["ACCOUNT_SID"]
            token = st.secrets["twilio"]["AUTH_TOKEN"]
            from_wa = st.secrets["twilio"]["FROM_NUMBER"]
            to_wa = st.secrets["twilio"]["TO_NUMBER"]
            
            # Solo enviar si no son los placeholders
            if "TU_ACCOUNT" not in sid:
                client = TwilioClient(sid, token)
                msg = client.messages.create(
                    body=mensaje,
                    from_=from_wa,
                    to=to_wa
                )
                return True, msg.sid
        return False, "No configurado"
    except Exception as e:
        print(f"Error Twilio: {e}")
        return False, str(e)

# --- CONFIGURACIÓN SUPABASE ---
# ESTAS CREDENCIALES SON SEGURAS EN EL CLIENTE PORQUE SON DE TIPO "ANON" (PÚBLICAS)
SUPABASE_URL = "https://ucfdvkirludawhplqgjv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVjZmR2a2lybHVkYXdocGxxZ2p2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjcxMTY4NTMsImV4cCI6MjA4MjY5Mjg1M30.tR-Wl41jo64UvvltNMaIS2qwOrkdksD5BW1H-cWL7Oo"

# @st.cache_resource -> ELIMINADO POR SEGURIDAD (Evita compartir sesión entre usuarios)
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# --- CONFIGURACIÓN PRINCIPAL ---
st.set_page_config(
    page_title="FinancePro Cloud",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CONFIGURACIÓN ADMIN ---
ADMIN_EMAIL = "franciscovelasquezg@gmail.com"
WHATSAPP_NUMERO = "56956082703"

def db_admin_get_users():
    """Obtiene todos los usuarios para el panel admin"""
    try:
        response = supabase.table("perfiles").select("*").execute()
        return response.data
    except Exception as e:
        return []



def db_admin_update_subscription(user_id, days):
    """Actualiza la suscripción de un usuario"""
    try:
        new_date = (datetime.now() + timedelta(days=days)).isoformat()
        supabase.table("perfiles").update({"subscription_end": new_date, "plan": "premium"}).eq("id", user_id).execute()
        return True
    except:
        return False

def db_admin_block_user(user_id):
    """Bloquea un usuario (fecha pasada)"""
    try:
        # Fecha en el pasado bloquea el acceso
        past_date = (datetime.now() - timedelta(days=1)).isoformat()
        supabase.table("perfiles").update({"subscription_end": past_date, "plan": "blocked"}).eq("id", user_id).execute()
        return True
    except:
        return False

# --- UTILIDADES DE RED ---
def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# --- SEGURIDAD ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return True
    return False

# --- FUNCIONES DE BASE DE DATOS (CLOUD) ---

# --- FUNCIONES DE BASE DE DATOS (SAAS / AUTH) ---

def db_crear_usuario(email, password, nombre):
    try:
        # 1. Registrar en Supabase Auth y pasar metadatos para el Trigger
        res = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "nombre": nombre
                },
                "email_redirect_to": "https://finance-cloud-ypzz4p5ezhnja3ns8cexek.streamlit.app"
            }
        })
        
        # 2. Verificar éxito
        if res.user:
            # Si Supabase devuelve una sesión (Email confirm desactivado), retornamos la sesión
            if res.session:
                return True, res.session, None
            else:
                return True, None, "Cuenta creada. Por favor revisa tu correo para confirmar."
            
    except Exception as e:
        msg = str(e)
        if "User already registered" in msg or "already registered" in msg:
            return False, None, "Este correo ya está registrado. Intenta iniciar sesión."
        return False, None, f"Error: {msg}"
    return False, None, "Error desconocido"

# ... (db_login se mantiene igual) ...
def db_login(email, password):
    try:
        # Autenticar
        res = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
        
        if res.user:
            # CHECK GATEKEEPER 
            profile_res = supabase.table("perfiles").select("*").eq("id", res.user.id).execute()
            
            if profile_res.data:
                profile = profile_res.data[0]
                
                # REVISAR VENCIMIENTO
                if profile.get('subscription_end'):
                    fin = datetime.fromisoformat(profile['subscription_end'].replace('Z', '+00:00'))
                    ahora = datetime.now(fin.tzinfo)
                    
                    dias_restantes = (fin - ahora).days
                    profile['dias_restantes'] = dias_restantes
                    
                    if dias_restantes < 0:
                        # MODIFICACION: Permitimos entrar pero marcamos como vencido para modo "solo lectura"
                        profile['expired'] = True
                        # No retornamos error, dejamos pasar
                        # return None, "🔒 TIEMPO AGOTADO: Tu periodo de prueba terminó. Por favor renueva tu plan."
                    else:
                        profile['expired'] = False
                
                if not profile.get('activo', True):
                    return None, "🔒 BLOQUEADO: Tu cuenta ha sido desactivada."
                
                # Inyectamos el email para que el frontend sepa si es admin
                profile['email'] = res.user.email 
                return profile, None 
            else:
                # AUTO-HEAL: Si el usuario existe en Auth pero NO en la tabla 'perfiles' (Fallo del Trigger),
                # lo creamos manualmente ahora para que aparezca en el Panel Admin.
                try:
                    new_profile = {
                        "id": res.user.id,
                        "email": res.user.email,
                        "nombre": res.user.user_metadata.get('nombre', 'Usuario'),
                        "plan": "free",
                        "activo": True,
                        "subscription_end": (datetime.now() + timedelta(days=30)).isoformat()
                    }
                    supabase.table("perfiles").insert(new_profile).execute()
                    
                    # Añadir campos volátiles para la sesión actual
                    new_profile['dias_restantes'] = 30
                    new_profile['expired'] = False
                    return new_profile, None
                except Exception as e:
                    # Fallback final si falla la escritura (ej: error de red)
                    print(f"Error Auto-Heal Profile: {e}")
                    return {"id": res.user.id, "nombre": "Usuario", "email": res.user.email, "plan": "free", "dias_restantes": 30}, None
                
    except Exception as e:
        msg = str(e)
        if "Email not confirmed" in msg:
            return None, "✉️ Tu correo no ha sido confirmado. Revisa tu bandeja de entrada (y Spam) y haz clic en el enlace."
        return None, f"Error: {msg}"  # Mostrar error exacto para depurar
    
    return None, "Error de credenciales"

def db_recuperar_password(email):
    try:
        # Enviar el Link Mágico apuntando a la APP REAL (no localhost)
        # Nota: El usuario debe agregar esta URL en Supabase > Auth > URL Configuration > Redirect URLs
        url_app = "https://finance-cloud-ypzz4p5ezhnja3ns8cexek.streamlit.app"
        supabase.auth.reset_password_email(email, options={"redirect_to": url_app})
        return True, None
    except Exception as e:
        return False, str(e)

def db_insertar(usuario_id, fecha, tipo, categoria, descripcion, monto, metodo):
    try:
        data = {
            "usuario_id": usuario_id,
            "fecha": str(fecha),
            "tipo": tipo,
            "categoria": categoria,
            "descripcion": descripcion,
            "monto": float(monto),
            "metodo": metodo
        }
        supabase.table("transacciones").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Error conexión: {e}")
        return False

def db_obtener(usuario_id):
    try:
        response = supabase.table("transacciones").select("*").eq("usuario_id", usuario_id).order("fecha", desc=True).execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df['fecha'] = pd.to_datetime(df['fecha'])
            return df
    except Exception as e:
        pass
    return pd.DataFrame()

def db_borrar(id_transaccion, usuario_id):
    try:
        supabase.table("transacciones").delete().eq("id", id_transaccion).eq("usuario_id", usuario_id).execute()
    except:
        pass

def db_crear_habito(usuario_id, nombre):
    try:
        supabase.table("habitos").insert({"usuario_id": usuario_id, "nombre": nombre}).execute()
        return True
    except Exception as e:
        return False

def db_obtener_habitos(usuario_id):
    try:
        # 1. Obtener hábitos
        habitos = supabase.table("habitos").select("*").eq("usuario_id", usuario_id).order("created_at").execute().data
        if not habitos: return []
        
        # 2. Obtener registros de los últimos 7 días
        hoy = datetime.now().date()
        hace_7_dias = hoy - timedelta(days=6)
        registros = supabase.table("registros_habitos").select("*").in_("habito_id", [h['id'] for h in habitos]).gte("fecha", str(hace_7_dias)).execute().data
        
        # 3. Mapear registros
        mapa_registros = {(r['habito_id'], r['fecha']): r['completado'] for r in registros}
        
        res = []
        dias = [(hoy - timedelta(days=i)) for i in range(5, -1, -1)] # Hoy y 5 dias atras
        
        for h in habitos:
            row = {"id": h['id'], "nombre": h['nombre']}
            # Calcular racha (simplificado)
            racha = 0
            # Populate days
            for d in dias:
                fecha_str = str(d)
                estado = mapa_registros.get((h['id'], fecha_str), False)
                row[fecha_str] = estado
            res.append(row)
            
        return res, [str(d) for d in dias]
    except Exception as e:
        print(f"Error habitos: {e}")
        return [], []

def db_toggle_habito(habito_id, fecha, estado):
    try:
        if estado:
            # Insertar (Upsert para evitar duplicados si la constraint única falla)
            supabase.table("registros_habitos").upsert(
                {"habito_id": habito_id, "fecha": fecha, "completado": True}, 
                on_conflict="habito_id, fecha"
            ).execute()
        else:
            # Borrar
            supabase.table("registros_habitos").delete().eq("habito_id", habito_id).eq("fecha", fecha).execute()
        return True
    except Exception as e:
        return False

# --- ESTADO Y RUTAS ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_info' not in st.session_state:
    st.session_state['user_info'] = None

# --- ESTILOS VISUALES "PREMIUM" (CSS AVANZADO) ---
st.markdown("""
    <style>
    /* FUENTE Y FONDO */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;700&display=swap');
    
    html, body, [class*="css"] { 
        font-family: 'Outfit', sans-serif; 
        color: #E2E8F0; 
    }
    
    /* FONDO PRINCIPAL OSCURO AZULADO */
    .stApp { 
        background-color: #020617; /* Slate 950 */
        background-image: 
            radial-gradient(at 0% 0%, hsla(253,16%,7%,1) 0, transparent 50%), 
            radial-gradient(at 50% 0%, hsla(225,39%,30%,1) 0, transparent 50%), 
            radial-gradient(at 100% 0%, hsla(339,49%,30%,1) 0, transparent 50%);
    }

    /* TARJETAS DE MÉTRICAS (GLASSMORPHISM) */
    div.metric-card {
        background-color: rgba(30, 41, 59, 0.4); /* Slate 800 + Transparencia */
        border: 1px solid rgba(148, 163, 184, 0.1);
        border-radius: 16px;
        padding: 20px;
        backdrop-filter: blur(10px);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    div.metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        border-color: rgba(96, 165, 250, 0.3); /* Azul claro */
    }

    /* INPUTS Y CAMPOS DE TEXTO ELEGANTES */
    .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox > div > div {
        background-color: rgba(15, 23, 42, 0.6) !important; 
        color: #F8FAFC !important;
        border: 1px solid #334155 !important; 
        border-radius: 12px !important;
        padding: 10px !important;
        min-height: 60px !important; /* MÁS ALTOS - SOLICITUD 60PX */
        transition: border-color 0.3s ease;
    }
    .stTextInput input:focus, .stNumberInput input:focus {
        border-color: #60A5FA !important; /* Azul Focus */
        box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2);
    }

    /* BOTONES GRADIENTES Y LUMINOSOS */
    .stButton > button {
        background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%);
        color: white; 
        border: none; 
        padding: 0.75rem 1.5rem; 
        font-weight: 600; 
        letter-spacing: 0.5px;
        border-radius: 12px;
        width: 100%;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.3);
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%);
        transform: translateY(-1px);
        box-shadow: 0 8px 10px -1px rgba(37, 99, 235, 0.4);
    }

    /* PESTAÑAS Y EXPANSORES */
    .stTabs [data-baseweb="tab-list"] {
        background-color: rgba(30, 41, 59, 0.3);
        border-radius: 10px;
        padding: 5px;
        gap: 5px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        color: #94A3B8;
    }
    .stTabs [aria-selected="true"] {
        background-color: #1E293B;
        color: #FFFFFF;
        font-weight: bold;
    }

    /* BARRA LATERAL */
    section[data-testid="stSidebar"] {
        background-color: #020617;
        border-right: 1px solid rgba(148, 163, 184, 0.1);
    }
    
    /* ═══════════════════════════════════════════════════════════════
       FIX URGENTE: SELECTBOX - Visualización Premium Correcta
       ═══════════════════════════════════════════════════════════════ */
    
    /* Contenedor principal del Selectbox */
    div[data-baseweb="select"] > div {
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
        color: #F8FAFC !important;
        border-radius: 12px !important;
        /* Flexbox vital para centrar el texto verticalmente */
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        min-height: 60px !important; 
        padding-left: 12px !important;
        padding-right: 12px !important;
    }

    /* Texto seleccionado (Value) */
    div[data-baseweb="select"] span {
        color: #F8FAFC !important;
        font-size: 15px !important;
        line-height: normal !important; /* Importante para que no corte */
    }

    /* Icono de Flecha */
    div[data-baseweb="select"] svg {
        fill: #94A3B8 !important;
    }
    
    /* Opciones del Dropdown (Menú desplegable) */
    li[role="option"] {
         background-color: #1E293B !important;
         color: #E2E8F0 !important;
    }
    li[role="option"]:hover, li[role="option"][aria-selected="true"] {
        background-color: #334155 !important;
        color: #60A5FA !important;
    }

    

    
    /* Dropdown menu - Fondo oscuro GLOBAL */
    div[data-baseweb="popover"], div[data-baseweb="popover"] > div, ul[data-baseweb="menu"] {
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
    }
    
    /* Opciones del menú - Texto blanco */
    ul[role="listbox"] li {
        color: #FFFFFF !important;
        background-color: #1E293B !important;
        padding: 10px 15px !important;
        font-size: 14px !important;
    }
    
    /* Opción al pasar el mouse - Azul claro */
    ul[role="listbox"] li:hover {
        background-color: #334155 !important;
        color: #60A5FA !important;
    }
    
    /* Opción seleccionada - Azul */
    ul[role="listbox"] li[aria-selected="true"] {
        background-color: #3B82F6 !important;
        color: #FFFFFF !important;
    }
    
    /* INPUTS MEJORADOS - Tamaño y contraste */
    input[type="number"], input[type="text"], input[type="date"], textarea {
        color: #FFFFFF !important;
        background-color: #1E293B !important;
        border: 2px solid #334155 !important;
        font-size: 14px !important;
        min-height: 45px !important;
        padding: 8px 12px !important;
    }
    
    input::placeholder, textarea::placeholder {
        color: #64748B !important;
        font-size: 13px !important;
    }
    
    /* Labels más visibles */
    label {
        color: #E2E8F0 !important;
        font-size: 14px !important;
        font-weight: 500 !important;
    }
    </style>
""", unsafe_allow_html=True)

def login_register_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"""
            <div style="text-align: center; margin-bottom: 2rem;">
                <h1 style="color: #60A5FA; margin-bottom: 0;">FinancePro <span style="font-size:0.5em">💎</span></h1>
                <p style="color: #94A3B8;">Professional Cloud Suite</p>
                <div style="background: #1e293b; padding: 10px; border-radius: 8px; font-size: 0.8rem; margin-top: 10px; border: 1px solid #334155;">
                    🌍 <b>Estado:</b> <span style="color: #10B981;">Online (Nube Global)</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        # Tabs nativas de Streamlit para mejor indicación visual
        tab_login, tab_register, tab_recover = st.tabs(["🔑 Ingresar", "✨ Registrarse", "🔄 Recuperar"])
        
        with tab_login:
            st.write("")  # Espaciador
            u = st.text_input("Correo Electrónico", key="l_u")
            p = st.text_input("Contraseña", type="password", key="l_p")
            if st.button("Iniciar Sesión 🚀", use_container_width=True):
                user, error = db_login(u, p)
                if user:
                    st.success(f"Bienvenido de nuevo, {user.get('nombre', 'Usuario')}")
                    st.session_state['logged_in'] = True
                    st.session_state['user_info'] = user
                    st.rerun()
                else:
                    st.error(error)
        
        with tab_register:
            st.markdown("""
                <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid #10B981; border-radius: 8px; padding: 10px; margin-bottom: 15px;">
                    <h4 style="margin:0; color: #10B981;">💎 Comienza Gratis 30 Días</h4>
                    <p style="margin:0; font-size: 0.9rem; color: #E2E8F0;">Luego elige tu plan:</p>
                    <ul style="margin: 5px 0 0 15px; font-size: 0.85rem; color: #CBD5E1;">
                        <li><b>Básico ($2.490):</b> App Web + 🤖 Telegram Bot</li>
                        <li><b>Pro ($3.990):</b> App Web + 💬 WhatsApp Bot</li>
                    </ul>
                </div>
            """, unsafe_allow_html=True)
            nu = st.text_input("Correo Electrónico", key="s_u")
            nn = st.text_input("Nombre Completo", key="s_n")
            np = st.text_input("Contraseña", type="password", help="Mínimo 6 caracteres", key="s_p")
            
            if st.button("Comenzar Prueba Gratis ✨", use_container_width=True):
                ok, session, msg = db_crear_usuario(nu, np, nn)
                if ok:
                    if session:
                        # Auto-Login si Supabase ya nos dio sesión
                        st.success("¡Cuenta creada! Entrando...")
                        # Necesitamos obtener el perfil completo aunque tengamos la sesión
                        user_profile, _ = db_login(nu, np) 
                        st.session_state['logged_in'] = True
                        st.session_state['user_info'] = user_profile
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.success("¡Cuenta creada! ✅")
                        st.info("✉️ Hemos enviado un correo de confirmación. Revisa tu bandeja de entrada (y Spam).")
                        st.caption("Redirigiendo al inicio de sesión en 3 segundos...")
                        time.sleep(3)
                        st.rerun()
                else:
                    st.error(f"Error: {msg}")

        with tab_recover:
            st.write("")  # Espaciador
            ru = st.text_input("Correo para recuperar", key="r_u")
            
            # Prevenir múltiples envíos con session state
            if 'recovery_sent' not in st.session_state:
                st.session_state['recovery_sent'] = False
            
            if st.button("Enviar Enlace", use_container_width=True, disabled=st.session_state['recovery_sent']):
                success, error = db_recuperar_password(ru)
                if success:
                    st.success("¡Enviado! Revisa tu bandeja de entrada.")
                    st.session_state['recovery_sent'] = True
                    st.info("Si no llega en 2 minutos, recarga la página y vuelve a intentarlo.")
                else:
                    st.error(f"Error al enviar: {error}")
            
            if st.session_state['recovery_sent']:
                if st.button("Reintentar", use_container_width=True):
                    st.session_state['recovery_sent'] = False
                    st.rerun()

def render_reset_password_page():
    st.markdown("""
        <div style="text-align: center; margin-bottom: 2rem;">
             <h1>🔄 Establecer Nueva Contraseña</h1>
             <p>Ingresa tu nueva clave para asegurar tu cuenta.</p>
        </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        new_p1 = st.text_input("Nueva Contraseña", type="password", key="reset_p1")
        new_p2 = st.text_input("Confirmar Nueva Contraseña", type="password", key="reset_p2")
        
        if st.button("💾 Guardar y Entrar", use_container_width=True):
            if new_p1 == new_p2 and len(new_p1) >= 6:
                try:
                    supabase.auth.update_user({"password": new_p1})
                    st.success("¡Contraseña actualizada correctamente! 🔐")
                    st.toast("Clave guardada. Redirigiendo...", icon="✅")
                    # Quitamos el modo reset y entramos normal
                    st.session_state['reset_mode'] = False
                    st.session_state['logged_in'] = True
                    # Opcional: limpiar query params si quedaba algo
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar: {e}")
            else:
                 st.error("Las contraseñas no coinciden o son muy cortas (mín. 6 caracteres).")

def check_auth_callback():
    """Verifica si hay un código de autenticación en la URL (Link Mágico/Recuperación)"""
    try:
        # Detectar parámetros URL (Streamlit moderno usa st.query_params)
        qp = st.query_params
        code = qp.get("code")
        
        if code:
            # Intercambiar código por sesión
            st.toast("🔑 Autenticando token de recuperación...", icon="🔄")
            res = supabase.auth.exchange_code_for_session({"auth_code": code})
            if res.user:
                # Login exitoso via link -> ACTIVAR MODO RESET
                # En vez de entrar directo, mostramos la pantalla de nueva clave
                st.session_state['reset_mode'] = True
                
                # Obtener perfil (para tener nombre y datos por si acaso)
                prof_res = supabase.table("perfiles").select("*").eq("id", res.user.id).execute()
                if prof_res.data:
                    st.session_state['user_info'] = prof_res.data[0]
                    st.session_state['user_info']['email'] = res.user.email
                
                # Limpiar URL
                st.query_params.clear()
                st.rerun()
    except Exception as e:
        st.error(f"Error procesando enlace: {e}")
            if res.user:
                # Login exitoso via link
                st.session_state['logged_in'] = True
                # Obtener perfil
                profile, _ = db_login(res.user.email, "dummy") # Hack: db_login maneja perfil. Ideal refactor pero funciona.
                # Mejor: obtener perfil directo para no requerir password
                prof_res = supabase.table("perfiles").select("*").eq("id", res.user.id).execute()
                if prof_res.data:
                    st.session_state['user_info'] = prof_res.data[0]
                    st.session_state['user_info']['email'] = res.user.email
                
                # Limpiar URL
                st.query_params.clear()
                st.success("¡Acceso concedido vía enlace seguro! 🔐")
                time.sleep(1)
                st.rerun()
    except Exception as e:
        st.error(f"Error procesando enlace: {e}")

# --- INIT AUTH CHECK ---
check_auth_callback()

def render_habitos_page(user):
    st.title("🎯 Tracker de Hábitos")
    st.markdown("Crea hábitos y marca tu progreso diario. ¡La consistencia es clave!")
    
    # 1. Crear Nuevo Hábito
    with st.expander("✨ Nuevo Hábito", expanded=False):
        c1, c2 = st.columns([3, 1])
        with c1:
            nuevo_nombre = st.text_input("Nombre del Hábito (Ej: Gimnasio, Leer)", key="new_habit_name")
        with c2:
            st.write("") # Spacer
            st.write("") 
            if st.button("Crear", use_container_width=True):
                if db_crear_habito(user['id'], nuevo_nombre):
                    st.success("¡Creado!")
                    st.rerun()
                else:
                    st.error("Error al crear")

    # 2. Visualizar y Marcar
    habitos_data, dias_labels = db_obtener_habitos(user['id'])
    
    if not habitos_data:
        st.info("Aún no tienes hábitos. ¡Crea uno arriba!")
        return

    # Construir DataFrame para Data Editor
    df = pd.DataFrame(habitos_data)
    
    # Configurar columnas editables (fechas) y no editables (id, nombre)
    column_config = {
        "id": None, # Ocultar
        "nombre": st.column_config.TextColumn("Hábito", disabled=True, width="medium"),
    }
    
    # Configurar columnas de fechas como Checkbox
    for dia in dias_labels:
        # Formato bonito para el header: "Lun 11"
        fecha_obj = datetime.strptime(dia, "%Y-%m-%d")
        header_dia = fecha_obj.strftime("%d/%m")
        column_config[dia] = st.column_config.CheckboxColumn(header_dia, width="small")

    # Mostrar Data Editor
    st.markdown("### 📅 Tu Semana")
    edited_df = st.data_editor(
        df,
        column_config=column_config,
        hide_index=True,
        use_container_width=True,
        key="habits_editor"
    )

    # Detectar cambios y guardar (Callback simple)
    # Streamlit data_editor no devuelve diff fácil, pero comparamos vs sesión o vs DB?
    # Mejor: Al hacer cambios, Streamlit re-ejecuta. Pero ups, data_editor returna el estado FINAL.
    # ¿Cómo saber qué celda cambió para llamar toggle?
    # Diff vs snapshot anterior es complejo.
    # ENFOQUE SIMPLE: Botones individuales si data_editor es muy complejo de sincronizar row-by-row.
    # Ó iterar todo el DF editado y comparar con el original (costoso pero seguro).
    
    # Vamos a Iterar y comparar con lo que trajimos de DB (habitos_data es nuestra 'source of truth' al inicio del run)
    # Si hay diferencia, actualizamos DB.
    
    for index, row in edited_df.iterrows():
        # Buscar la fila original correspondiente por ID
        original_row = next((h for h in habitos_data if h['id'] == row['id']), None)
        if original_row:
            for dia in dias_labels:
                if row[dia] != original_row[dia]:
                    # CAMBIO DETECTADO
                    nuevo_estado = row[dia]
                    # Actualizar DB
                    db_toggle_habito(row['id'], dia, nuevo_estado)
                    # No hacemos rerun inmedito para permitir multiples clicks, 
                    # pero ojo que al siguiente rerun se refresca desde DB.
                    # toast para feedback
                    st.toast(f"Hábito actualizado: {row['nombre']}", icon="✅")

# --- CONFIGURACIÓN ADMIN Y SOPORTE ---
ADMIN_EMAIL = "franciscovelasquezg@gmail.com"
# IMPORTANTE: CAMBIE ESTE NÚMERO POR EL SUYO (Formato internacional sin +)
WHATSAPP_NUMERO = "56940928228" 

def admin_panel_page():
    st.title("🕵️‍♂️ Panel de Super-Admin")
    # st.warning("⚠️ Zona de Control Maestra") # Eliminado para limpieza visual
    
    # Obtener todos los perfiles
    try:
        res = supabase.table("perfiles").select("*").order("fecha_registro", desc=True).execute()
        users = res.data
        
        # --- NUEVO DASHBOARD SAAS ---
        total_users = len(users)
        active_users = sum(1 for u in users if u.get('activo', True))
        ingresos_estimados = active_users * 2490 
        
        st.markdown("### 📊 Métricas de Negocio")
        m1, m2, m3 = st.columns(3)
        
        m1.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8;">👥 Usuarios Totales</span>
                <h3 style="color:#F8FAFC; margin:0;">{total_users}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        m2.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8;">🟢 Clientes Activos</span>
                <h3 style="color:#10B981; margin:0;">{active_users}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        m3.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8;">💰 Ingresos (Est.)</span>
                <h3 style="color:#60A5FA; margin:0;">${ingresos_estimados:,.0f}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        st.divider()
        st.subheader("👥 Gestión de Usuarios")
        
        for u in users:
            # --- LÓGICA SEMÁFORO Y PAGO ---
            activo = u.get('activo', True)
            pago_pendiente = u.get('pago_pendiente', False)
            
            color_estado = "⚪"
            dias_msg = "Indefinido"
            
            # Prioridad 1: Pago Reportado (Azul)
            if pago_pendiente:
                color_estado = "🔵 PAGO REPORTADO"
            # Prioridad 2: Estado Cuenta
            elif not activo:
                color_estado = "⚫ (Bloqueado)"
            elif u.get('subscription_end'):
                try:
                    fin = datetime.fromisoformat(u['subscription_end'].replace('Z', '+00:00'))
                    ahora = datetime.now(fin.tzinfo)
                    dias = (fin - ahora).days
                    dias_msg = f"{dias} días"
                    
                    if dias < 0:
                        color_estado = "🔴 Vencido"
                    elif dias < 5:
                        color_estado = "🔴 Vence pronto"
                    elif dias < 10:
                        color_estado = "🟡 Atención"
                    else:
                        color_estado = "🟢 OK"
                except:
                    pass
            else:
                color_estado = "🟢 (Sin fecha)"
            
            # Header del Expander Visual
            header_text = f"{color_estado} | {u.get('nombre')} | {dias_msg}"
            
            with st.expander(header_text):
                c1, c2, c3 = st.columns(3)
                
                # Info
                estado_str = "🟢 Activo" if activo else "🔴 Bloqueado"
                if pago_pendiente:
                    c1.info(f"💰 **¡Usuario dice que PAGÓ!**")
                
                c1.write(f"Estado: **{estado_str}**")
                c1.write(f"Email: `{u.get('email')}`")
                
                vence = u.get('subscription_end')
                c1.write(f"Vence: `{vence}`")
                
                # Acciones
                with c2:
                    if pago_pendiente:
                         if st.button("✅ CONFIRMAR PAGO (Renovar)", key=f"payconf_{u['id']}"):
                            nuevo_venc = (datetime.now() + timedelta(days=30)).isoformat()
                            supabase.table("perfiles").update({
                                "subscription_end": nuevo_venc, 
                                "activo": True,
                                "pago_pendiente": False
                            }).eq("id", u['id']).execute()
                            st.balloons()
                            st.success("¡Pago confirmado y cuenta renovada!")
                            time.sleep(1.5)
                            st.rerun()

                    if st.button("📅 Extender 30 días", key=f"ext_{u['id']}"):
                        nuevo_venc = (datetime.now() + timedelta(days=30)).isoformat()
                        supabase.table("perfiles").update({"subscription_end": nuevo_venc, "activo": True}).eq("id", u['id']).execute()
                        st.success("¡Renovado!")
                        time.sleep(1)
                        st.rerun()

                with c3:
                    if activo:
                        # Botón para bloquear/dar de baja
                        if st.button("⛔ Dar de Baja / Bloquear", key=f"blk_{u['id']}", help="Desactiva el acceso inmediatamente (Ej: No pagó)"):
                            supabase.table("perfiles").update({"activo": False}).eq("id", u['id']).execute()
                            st.toast("Usuario bloqueado")
                            time.sleep(1)
                            st.rerun()
                    else:
                        if st.button("✅ Reactivar Acceso", key=f"unblk_{u['id']}"):
                            supabase.table("perfiles").update({"activo": True}).eq("id", u['id']).execute()
                            st.toast("Usuario reactivado")
                            time.sleep(1)
                            st.rerun()
        
        st.divider()
        st.subheader("🗑️ Zona de Limpieza")
        st.caption("Eliminar usuarios vencidos hace más de 15 días para liberar espacio.")
        
        if st.button("Buscar Usuarios para Eliminar"):
            candidatos = []
            for u in users:
                vence = u.get('subscription_end')
                if vence:
                    fin = datetime.fromisoformat(vence.replace('Z', '+00:00'))
                    dias_pasados = (datetime.now(fin.tzinfo) - fin).days
                    if dias_pasados > 15:
                        candidatos.append(u)
            
            if candidatos:
                st.error(f"⚠️ Se encontraron {len(candidatos)} usuarios vencidos hace >15 días.")
                for cand in candidatos:
                    st.write(f"- {cand['nombre']} (Venció hace {dias_pasados} días)")
                
                if st.button("🔥 ELIMINAR DATOS PERMANENTEMENTE"):
                    for cand in candidatos:
                        # Borrar transacciones primero (por seguridad de llaves foráneas)
                        supabase.table("transacciones").delete().eq("usuario_id", cand['id']).execute()
                        # Borrar perfil
                        supabase.table("perfiles").delete().eq("id", cand['id']).execute()
                        # Nota: El usuario de Auth queda, pero sin perfil no puede entrar ni ocupa espacio real.
                    st.success("Limpieza completada.")
                    time.sleep(2)
                    st.rerun()
            else:
                st.info("Todo limpio. No hay usuarios tan antiguos para borrar.")

    except Exception as e:
        st.error(f"Error al cargar usuarios: {e}")

def main_app():
    user = st.session_state['user_info']
    email_actual = user.get('email', '') # Necesitamos el email en el login
    
    # --- BARRA LATERAL ---
    with st.sidebar:
        # Avatar Automático (Generado por Iniciales)
        nombre_user = user.get('nombre', 'Usuario')
        # API de UI-Avatars (Estilo profesional y simple)
        avatar_url = f"https://ui-avatars.com/api/?name={nombre_user}&background=3B82F6&color=fff&size=128&rounded=true&bold=true"
        
        col_av1, col_av2 = st.columns([1, 3])
        with col_av1:
            st.image(avatar_url, width=60)
        with col_av2:
            st.write(f"Hola,")
            st.subheader(f"**{nombre_user.split(' ')[0]}**") # Mostrar solo primer nombre para que quepa bien
        if email_actual == ADMIN_EMAIL:
            st.info("👮 MODO ADMIN DETECTADO")
            modo = st.radio("Menú", ["Mi Panel", "ADMINISTRACIÓN"])
            if modo == "ADMINISTRACIÓN":
                nav = "ADMIN"
            else:
                nav = st.radio("", ["Panel", "Ingreso", "Gasto", "Datos"])
        else:
            # SI ES UN MORTAL (CLIENTE)
            dias = user.get('dias_restantes', 30)
            if dias <= 5:
                st.warning(f"⚠️ Quedan {dias} días")
                # Botón de WhatsApp
                msg = f"Hola, quiero renovar mi plan en FinancePro. Mi correo es: {email_actual}"
                link_wa = f"https://wa.me/{WHATSAPP_NUMERO}?text={msg.replace(' ', '%20')}"
                
                # Stacked buttons for sidebar (better for mobile/narrow width)
                st.link_button("💬 Pagar (WhatsApp)", link_wa, use_container_width=True, type="primary")
                
                # Botón para reportar pago
                if st.button("💰 Ya Pagué (Avisar)", use_container_width=True):
                    try:
                        # 1. Marcar en base de datos
                        supabase.table("perfiles").update({"pago_pendiente": True}).eq("id", user['id']).execute()
                        
                        # 2. Enviar WhatsApp (Si está configurado)
                        msg_admin = f"🔔 PAGO REPORTADO\nUsuario: {email_actual}\nNombre: {nombre_user}"
                        ok, err = enviar_alerta_whatsapp(msg_admin)
                        
                        if ok:
                            st.toast("Aviso enviado a Administración. Te confirmaremos pronto.", icon="✅")
                            time.sleep(2)
                        else:
                            st.error(f"No se pudo enviar el WhatsApp: {err}")
                    except Exception as e:
                        st.error(f"Error al avisar: {e}")
            else:
                st.success(f"✅ Quedan {dias} días")

            st.divider()
            
            # CAMBIAR CONTRASEÑA (Para usuarios que entraron por recuperación)
            with st.expander("🔐 Seguridad / Cambiar Clave"):
                new_p1 = st.text_input("Nueva Contraseña", type="password", key="np1")
                new_p2 = st.text_input("Confirmar Contraseña", type="password", key="np2")
                if st.button("Actualizar Clave"):
                    if new_p1 == new_p2 and len(new_p1) >= 6:
                        try:
                            supabase.auth.update_user({"password": new_p1})
                            st.success("¡Contraseña actualizada!")
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.error("Las contraseñas no coinciden o son muy cortas.")

            st.divider()
            nav = st.radio("", ["Panel", "Ingreso", "Gasto", "Ahorro", "Hábitos", "Datos"], key="nav_dashboard")
        
        st.divider()
        if st.button("Cerrar Sesión"):
            supabase.auth.sign_out()
            st.session_state['logged_in'] = False
            st.rerun()

    # --- ENRUTAMIENTO ---
    # Verificar si está vencido
    if user.get('expired', False) or user.get('dias_restantes', 0) < 0:
        st.error("🔒 MODO LECTURA: Tu plan ha vencido. No puedes agregar, editar ni descargar datos.")
        # Banner de pago prominente
        msg = f"Hola, deseo renovar mi plan FinancePro. Mi correo: {email_actual}"
        link_wa = f"https://wa.me/{WHATSAPP_NUMERO}?text={msg.replace(' ', '%20')}"
        colp1, colp2 = st.columns([1, 1])
        with colp1:
            st.link_button("💳 RENOVAR AHORA (WhatsApp)", link_wa, type="primary", use_container_width=True)
            
        with colp2:
             if st.button("💰 Ya Pagué (Desbloquear)", key="pay_unlock", use_container_width=True):
                try:
                    # SELECT para ver si el update funcionó (Fix RLS silencioso)
                    data = supabase.table("perfiles").update({"pago_pendiente": True}).eq("id", user['id']).execute()
                    
                    if not data.data:
                         st.error("⚠️ Error de Permisos (RLS): No se pudo actualizar tu estado. Contacta al soporte.")
                    else:
                        msg_admin = f"🔔 PAGO (DESBLOQUEO)\nUsuario: {email_actual}\nNombre: {nombre_user}"
                        ok, err = enviar_alerta_whatsapp(msg_admin)
                        if ok:
                            st.success(f"✅ ¡Solicitud Enviada! (ID: {err})")
                        else:
                            st.error(f"Error Twilio: {err}")
                except Exception as e:
                    st.error(f"Error al enviar: {e}")
        st.divider()

    if 'nav' in locals() and nav == "ADMIN":
        admin_panel_page()
    elif nav == "Hábitos":
        render_habitos_page(user)
    elif nav == "Panel":
        if not user.get('expired', False) and user.get('dias_restantes', 0) <= 5:
             st.info(f"💡 Recordatorio: Tu membresía vence en {user.get('dias_restantes')} días.")

        st.title("Tu Balance")
        st.caption("Resumen financiero en tiempo real.")
        
        df = db_obtener(user['id'])
        
        ing = df[df['tipo']=='Ingreso']['monto'].sum() if not df.empty else 0
        gas = df[df['tipo']=='Gasto']['monto'].sum() if not df.empty else 0
        aho = df[df['tipo']=='Ahorro']['monto'].sum() if not df.empty else 0
        
        # Balance Neto = Caja Disponible (Lo que me queda para gastar)
        neto = ing - gas - aho
        
        # Tarjetas Métricas Personalizadas (HTML + CSS Premium)
        c1, c2, c3, c4 = st.columns(4)
        
        # Pre-formatear valores
        neto_fmt = "{:,.0f}".format(neto)
        ing_fmt = "{:,.0f}".format(ing)
        gas_fmt = "{:,.0f}".format(gas)
        aho_fmt = "{:,.0f}".format(aho)
        color_neto = '#10B981' if neto >= 0 else '#EF4444'

        c1.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8; font-size:0.9rem;">Balance (Caja)</span>
                <h2 style="color:{color_neto}; margin:0;">${neto_fmt}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        c2.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8; font-size:0.9rem;">Ingresos</span>
                <h3 style="color:#F8FAFC; margin:0;">${ing_fmt}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        c3.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8; font-size:0.9rem;">Gastos</span>
                <h3 style="color:#F8FAFC; margin:0;">${gas_fmt}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        c4.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8; font-size:0.9rem;">💰 Ahorro/Inv.</span>
                <h3 style="color:#FBBF24; margin:0;">${aho_fmt}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        st.write("") # Espaciador
        
        if not df.empty:
            # Gráfico con fondo transparente
            fig = px.area(df, x='fecha', y='monto', color='tipo', 
                          color_discrete_map={'Ingreso':'#10B981','Gasto':'#EF4444', 'Ahorro':'#FBBF24'},
                          title="Evolución Financiera")
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#94A3B8')
            st.plotly_chart(fig, use_container_width=True)
            
            st.divider()
            
            # SECCIÓN DE ANÁLISIS DE GASTOS
            st.subheader("🍰 Distribución de Gastos")
            
            # Filtrar solo gastos para el análisis
            df_gastos = df[df['tipo'] == 'Gasto']
            
            if not df_gastos.empty:
                # Agrupar por categoría
                gastos_por_cat = df_gastos.groupby('categoria')['monto'].sum().reset_index()
                
                c_pie, c_bar = st.columns(2)
                
                with c_pie:
                    st.caption("Por Porcentaje (%)")
                    fig_pie = px.pie(gastos_por_cat, values='monto', names='categoria', 
                                     color_discrete_sequence=px.colors.sequential.RdBu,
                                     hole=0.4)
                    fig_pie.update_traces(textinfo='percent+label', textposition='inside')
                    fig_pie.update_layout(showlegend=False, 
                                          paper_bgcolor='rgba(0,0,0,0)', 
                                          plot_bgcolor='rgba(0,0,0,0)', 
                                          font_color='#94A3B8',
                                          margin=dict(t=0, b=0, l=0, r=0))
                    st.plotly_chart(fig_pie, use_container_width=True)
                
                with c_bar:
                    st.caption("Por Valor ($)")
                    fig_bar = px.bar(gastos_por_cat, x='categoria', y='monto', text='monto',
                                     color='monto', color_continuous_scale='Reds')
                    
                    # Formato de texto en las barras (ej: $50k)
                    fig_bar.update_traces(texttemplate='$%{text:.0f}', textposition='outside')
                    fig_bar.update_layout(paper_bgcolor='rgba(0,0,0,0)', 
                                          plot_bgcolor='rgba(0,0,0,0)', 
                                          font_color='#94A3B8',
                                          yaxis=dict(showgrid=False),
                                          xaxis=dict(title=None),
                                          showlegend=False,
                                          margin=dict(t=20, b=0, l=0, r=0))
                    st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("No hay gastos registrados para analizar.")
        else:
            st.info("¡Bienvenido! Empieza registrando tus ingresos en el menú lateral.")

    elif nav in ["Ingreso", "Gasto", "Ahorro"]:
        st.header(f"Registrar {nav}")

        # BLOQUEO SI ESTÁ VENCIDO
        if user.get('expired', False):
             st.warning(f"🔒 Para registrar nuevos {nav}s debes renovar tu suscripción.")
             st.info("👆 Usa el botón de arriba 'RENOVAR AHORA' para desbloquear esta función.")
        else:
            # Monto
            # Layout de 2 columnas para TODO (Más homogéneo)
            c1, c2 = st.columns(2)
            
            # Columna 1
            m = c1.number_input("Monto", step=100.0, min_value=0.0)
            f = c2.date_input("Fecha", datetime.now())
            
            # CATEGORÍAS MEJORADAS SEGÚN TIPO
            if nav == "Ingreso":
                categorias_predefinidas = [
                    "💰 Salario", "💼 Freelance", "📈 Rendimientos", "🎁 Regalo",
                    "🤝 Préstamo Recibido", "🏠 Arriendo", "🆕 Crear nueva..."
                ]
            elif nav == "Gasto":
                categorias_predefinidas = [
                    "🏠 Vivienda", "🍔 Alimentación", "🚗 Transporte", "💊 Salud",
                    "🎓 Educación", "🎮 Entretenimiento", "👕 Ropa", "💳 Deudas / Préstamos",
                    "📱 Servicios", "✈️ Viajes", "🆕 Crear nueva..."
                ]
            elif nav == "Ahorro":
                 categorias_predefinidas = [
                    "🏦 Fondo Emergencia", "📈 Inversión Bolsa", "₿ Criptomonedas", 
                    "🏡 Ahorro Casa", "🚗 Ahorro Auto", "🏖️ Vacaciones", "🆕 Crear nueva..."
                ]
            else:
                 categorias_predefinidas = ["General", "🆕 Crear nueva..."]
            
            cat_seleccionada = c1.selectbox("Categoría", categorias_predefinidas, index=0)
            
            # Si selecciona "Crear nueva...", mostrar campo de texto
            if cat_seleccionada == "🆕 Crear nueva...":
                cat = c1.text_input("Nombre de la categoría", placeholder="Ej: Mascotas 🐶")
                if not cat:
                    cat = "General"
            else:
                cat = cat_seleccionada
            
            # MÉTODO DE PAGO MEJORADO con emojis y key única
            # MÉTODO DE PAGO MEJORADO con emojis y key única
            metodos_pago = ["💵 Efectivo", "💳 Tarjeta Débito", "💎 Tarjeta Crédito", "🏦 Transferencia", "📱 Billetera Digital", "🆕 Otro..."]
            met_seleccionado = c2.selectbox("Método de Pago", metodos_pago, index=0, key=f"metodo_{nav}")
            
            if met_seleccionado == "🆕 Otro...":
                met = c2.text_input("Nombre del método", placeholder="Ej: Cheque 🎫")
                if not met:
                    met = "Otro"
            else:
                met = met_seleccionado
            
            # Nota opcional (Full Width para balancear)
            desc = st.text_input("Nota opcional", placeholder="Ej: Compra en supermercado")
            
            # Botón guardar con validación
            if st.button("Guardar Movimiento 💾", use_container_width=True):
                if m > 0:
                    ok = db_insertar(user['id'], f, nav, cat, desc, m, met)
                    if ok:
                        st.success("✅ Registro guardado correctamente. Volviendo al inicio...")
                        time.sleep(1.5)
                        st.session_state["nav_dashboard"] = "Panel" # Redirigir
                        st.rerun()
                    else:
                        st.error("Error al guardar en la nube")
                else:
                    st.error("El monto debe ser mayor a 0")

    elif nav == "Datos":
        st.title("📊 Historial de Transacciones")
        st.caption("Todas tus transacciones ordenadas por fecha")
        
        df = db_obtener(user['id'])
        
        if not df.empty:
            # FORMATEAR FECHAS A ZONA HORARIA DE CHILE
            df_display = df.copy()
            
            # Convertir a horario de Chile (UTC-3)
            from datetime import timezone, timedelta
            chile_tz = timezone(timedelta(hours=-3))
            
            # Formatear la fecha de forma legible
            df_display['fecha'] = pd.to_datetime(df_display['fecha']).dt.tz_localize('UTC').dt.tz_convert(chile_tz)
            df_display['fecha'] = df_display['fecha'].dt.strftime('%d-%m-%Y')  # Formato: 07-01-2026
            
            # Formatear el monto con símbolo de peso y comas
            df_display['monto'] = df_display['monto'].apply(lambda x: f"${x:,.0f}")
            
            # Renombrar columnas para que sean más claras
            df_display = df_display.rename(columns={
                'fecha': '📅 Fecha',
                'tipo': '📌 Tipo',
                'categoria': '🏷️ Categoría',
                'descripcion': '📝 Descripción',
                'monto': '💰 Monto',
                'metodo': '💳 Método'
            })
            
            # Seleccionar solo las columnas relevantes
            columnas_mostrar = ['📅 Fecha', '📌 Tipo', '🏷️ Categoría', '📝 Descripción', '💰 Monto', '💳 Método']
            df_display = df_display[columnas_mostrar]
            
            # Mostrar tabla con configuración mejorada
            st.dataframe(df_display, use_container_width=True, hide_index=True, height=400)
            
            # Mostrar total de transacciones
            st.caption(f"📊 Total de transacciones: {len(df_display)}")
            
            st.divider()
            st.subheader("📥 Exportar Datos")
            
            # LÓGICA DE EXPORTACIÓN (SaaS Feature)
            csv = df_display.to_csv(index=False).encode('utf-8')
            
            if user.get('expired', False):
                 st.warning("🔒 La exportación de datos es una función Premium.")
                 st.download_button(
                     label="🔒 Descargar CSV (Premium)",
                     data=csv,
                     file_name="mis_finanzas_locked.csv",
                     mime="text/csv",
                     disabled=True,
                     help="Renueva tu plan para descargar tus datos."
                 )
            else:
                st.download_button(
                    label="📥 Descargar Reporte CSV",
                    data=csv,
                    file_name=f"reporte_financepro_{datetime.now().strftime('%d%m%Y')}.csv",
                    mime="text/csv",
                )
        else:
            st.info("📭 No hay transacciones registradas aún. ¡Empieza registrando tu primer movimiento!")

# --- CONTROL DE FLUJO PRINCIPAL ---
if st.session_state.get('reset_mode', False):
    render_reset_password_page()
elif st.session_state.get('logged_in', False):
    main_app()
else:
    login_register_page()
