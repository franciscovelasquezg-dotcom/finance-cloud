import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import time
import socket
import hashlib
from supabase import create_client, Client

# --- CONFIGURACIÓN SUPABASE ---
# ESTAS CREDENCIALES SON SEGURAS EN EL CLIENTE PORQUE SON DE TIPO "ANON" (PÚBLICAS)
SUPABASE_URL = "https://ucfdvkirludawhplqgjv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVjZmR2a2lybHVkYXdocGxxZ2p2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjcxMTY4NTMsImV4cCI6MjA4MjY5Mjg1M30.tR-Wl41jo64UvvltNMaIS2qwOrkdksD5BW1H-cWL7Oo"

@st.cache_resource
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
                        return None, "🔒 TIEMPO AGOTADO: Tu periodo de prueba terminó. Por favor renueva tu plan."
                
                if not profile.get('activo', True):
                    return None, "🔒 BLOQUEADO: Tu cuenta ha sido desactivada."
                
                # Inyectamos el email para que el frontend sepa si es admin
                profile['email'] = res.user.email 
                return profile, None 
            else:
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
        return True
    except:
        return False

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
        
        # Usamos Session State para controlar la vista activa (Login vs Registro) en lugar de tabs estáticos
        if 'auth_mode' not in st.session_state:
            st.session_state['auth_mode'] = 'login'

        # Selector de modo personalizado
        c_mode = st.columns(3)
        if c_mode[0].button("Ingresar", use_container_width=True, type="primary" if st.session_state['auth_mode'] == 'login' else "secondary"):
            st.session_state['auth_mode'] = 'login'
            st.rerun()
        if c_mode[1].button("Registrarse", use_container_width=True, type="primary" if st.session_state['auth_mode'] == 'register' else "secondary"):
            st.session_state['auth_mode'] = 'register'
            st.rerun()
        if c_mode[2].button("Recuperar", use_container_width=True, type="primary" if st.session_state['auth_mode'] == 'recover' else "secondary"):
            st.session_state['auth_mode'] = 'recover'
            st.rerun()
        
        st.write("---")

        if st.session_state['auth_mode'] == 'login':
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
        
        elif st.session_state['auth_mode'] == 'register':
            st.info("💎 Prueba Premium Gratis por 30 Días.")
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
                        st.session_state['auth_mode'] = 'login'
                        st.rerun()
                else:
                    st.error(f"Error: {msg}")

        elif st.session_state['auth_mode'] == 'recover':
            ru = st.text_input("Correo para recuperar", key="r_u")
            if st.button("Enviar Enlace", use_container_width=True):
                if db_recuperar_password(ru):
                    st.success("¡Enviado! Revisa tu bandeja de entrada.")
                else:
                    st.error("Error al enviar.")

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

# --- CONFIGURACIÓN ADMIN Y SOPORTE ---
ADMIN_EMAIL = "franciscovelasquezg@gmail.com"
# IMPORTANTE: CAMBIE ESTE NÚMERO POR EL SUYO (Formato internacional sin +)
WHATSAPP_NUMERO = "56940928228" 

def admin_panel_page():
    st.title("🕵️‍♂️ Panel de Super-Admin")
    st.warning("⚠️ Zona de Control Maestra")
    
    # Obtener todos los perfiles
    try:
        res = supabase.table("perfiles").select("*").order("fecha_registro", desc=True).execute()
        users = res.data
        
        for u in users:
            with st.expander(f"{u.get('nombre')} ({u.get('email')}) - {u.get('plan')}"):
                c1, c2, c3 = st.columns(3)
                
                # Info
                activo = u.get('activo', True)
                estado_str = "🟢 Activo" if activo else "🔴 Bloqueado"
                c1.write(f"Estado: **{estado_str}**")
                
                vence = u.get('subscription_end')
                c1.write(f"Vence: `{vence}`")
                
                # Acciones
                with c2:
                    if st.button("📅 Extender 30 días", key=f"ext_{u['id']}"):
                        nuevo_venc = (datetime.now() + timedelta(days=30)).isoformat()
                        supabase.table("perfiles").update({"subscription_end": nuevo_venc, "activo": True}).eq("id", u['id']).execute()
                        st.success("¡Renovado!")
                        time.sleep(1)
                        st.rerun()

                with c3:
                    if activo:
                        if st.button("🛑 Bloquear Acceso", key=f"blk_{u['id']}"):
                            supabase.table("perfiles").update({"activo": False}).eq("id", u['id']).execute()
                            st.rerun()
                    else:
                        if st.button("✅ Desbloquear", key=f"unblk_{u['id']}"):
                            supabase.table("perfiles").update({"activo": True}).eq("id", u['id']).execute()
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
                st.markdown(f"""
                    <a href="{link_wa}" target="_blank">
                        <button style="width:100%; border:none; background-color:#25D366; color:white; padding:10px; border-radius:5px; font-weight:bold;">
                            💬 Renovar por WhatsApp
                        </button>
                    </a>
                """, unsafe_allow_html=True)
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
            nav = st.radio("", ["Panel", "Ingreso", "Gasto", "Datos"])
        
        st.divider()
        if st.button("Cerrar Sesión"):
            supabase.auth.sign_out()
            st.session_state['logged_in'] = False
            st.rerun()

    # --- ENRUTAMIENTO ---
    if 'nav' in locals() and nav == "ADMIN":
        admin_panel_page()
    elif nav == "Panel":
        if user.get('dias_restantes', 0) <= 5:
            st.info(f"💡 Recordatorio: Tu membresía vence en {user.get('dias_restantes')} días. Asegura tu acceso continuo.")

        st.title("Tu Balance")
        st.caption("Resumen financiero en tiempo real.")
        
        df = db_obtener(user['id'])
        
        ing = df[df['tipo']=='Ingreso']['monto'].sum() if not df.empty else 0
        gas = df[df['tipo']=='Gasto']['monto'].sum() if not df.empty else 0
        neto = ing - gas
        
        # Tarjetas Métricas Personalizadas (HTML + CSS Premium)
        # Pre-formatear valores para evitar errores de sintaxis en f-strings complejos
        neto_fmt = "{:,.0f}".format(neto)
        ing_fmt = "{:,.0f}".format(ing)
        gas_fmt = "{:,.0f}".format(gas)
        color_neto = '#10B981' if neto >= 0 else '#EF4444'

        c1.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8; font-size:0.9rem;">Balance Neto</span>
                <h2 style="color:{color_neto}; margin:0;">${neto_fmt}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        c2.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8; font-size:0.9rem;">Ingresos Totales</span>
                <h3 style="color:#F8FAFC; margin:0;">${ing_fmt}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        c3.markdown(f"""
            <div class="metric-card">
                <span style="color:#94A3B8; font-size:0.9rem;">Gastos Totales</span>
                <h3 style="color:#F8FAFC; margin:0;">${gas_fmt}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        st.write("") # Espaciador
        
        if not df.empty:
            # Gráfico con fondo transparente
            fig = px.area(df, x='fecha', y='monto', color='tipo', 
                          color_discrete_map={'Ingreso':'#10B981','Gasto':'#EF4444'},
                          title="Evolución Financiera")
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#94A3B8')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("¡Bienvenido! Empieza registrando tus ingresos en el menú lateral.")

    elif nav in ["Ingreso", "Gasto"]:
        st.header(f"Registrar {nav}")
        m = st.number_input("Monto", step=100.0)
        c1, c2 = st.columns(2)
        f = c1.date_input("Fecha", datetime.now())
        cat = c1.text_input("Categoría", "General")
        met = c2.selectbox("Método", ["Efectivo", "Tarjeta", "Transferencia"])
        desc = c2.text_input("Nota opcional")
        
        if st.button("Guardar Movimiento", use_container_width=True):
            db_insertar(user['id'], f, nav, cat, desc, m, met)
            st.success("¡Guardado!")
            time.sleep(0.5)
            st.rerun()

    elif nav == "Datos":
        st.title("Historial")
        st.dataframe(db_obtener(user['id']), use_container_width=True)

if st.session_state['logged_in']:
    main_app()
else:
    login_register_page()
