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
        # 1. Registrar en Supabase Auth
        res = supabase.auth.sign_up({
            "email": email,
            "password": password,
        })
        
        # 2. Si se crea, guardamos perfil con 30 días de regalo
        if res.user:
            user_id = res.user.id
            # Calcular fecha de vencimiento (Hoy + 30 días)
            fin_demo = (datetime.now() + timedelta(days=30)).isoformat()
            
            supabase.table("perfiles").insert({
                "id": user_id,
                "nombre": nombre,
                "plan": "trial",
                "activo": True,
                "subscription_end": fin_demo
            }).execute()
            return True, "Revisa tu correo para confirmar la cuenta."
    except Exception as e:
        return False, str(e)
    return False, "Error desconocido"

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
                    
                return profile, None 
            else:
                return {"id": res.user.id, "nombre": "Usuario", "plan": "free", "dias_restantes": 30}, None
                
    except Exception as e:
        return None, "Correo o contraseña incorrectos."
    
    return None, "Error de credenciales"

def db_recuperar_password(email):
    try:
        supabase.auth.reset_password_email(email)
        return True
    except:
        return False

# ... (Funciones db_insertar, etc. se mantienen igual) ...
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

# --- ESTILOS CSS ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;700&display=swap');
    html, body, [class*="css"] { font-family: 'Outfit', sans-serif; color: #E2E8F0; }
    .stApp { background-color: #0F172A; }
    .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox > div > div {
        background-color: #1E293B !important; color: white !important;
        border: 1px solid #334155 !important; border-radius: 8px !important;
    }
    .stButton > button {
        background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%);
        color: white; border: none; padding: 0.6rem 1.2rem; font-weight: 600; border-radius: 8px;
    }
    .metric-container { background-color: #1E293B; border-radius: 12px; padding: 24px; border: 1px solid #334155; }
    </style>
""", unsafe_allow_html=True)

# --- ESTADO Y RUTAS ---

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_info' not in st.session_state:
    st.session_state['user_info'] = None

def login_register_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"""
            <div style="text-align: center; margin-bottom: 2rem;">
                <h1 style="color: #60A5FA; margin-bottom: 0;">FinancePro <span style="font-size:0.5em">�</span></h1>
                <p style="color: #94A3B8;">Professional Cloud Suite</p>
                <div style="background: #1e293b; padding: 10px; border-radius: 8px; font-size: 0.8rem; margin-top: 10px; border: 1px solid #334155;">
                    🌍 <b>Estado:</b> <span style="color: #10B981;">Online (Nube Global)</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        t1, t2, t3 = st.tabs(["Ingresar", "Registro", "Recuperar"])
        
        with t1:
            u = st.text_input("Correo Electrónico", key="l_u")
            p = st.text_input("Contraseña", type="password", key="l_p")
            if st.button("Iniciar Sesión", use_container_width=True):
                user, error = db_login(u, p)
                if user:
                    st.success(f"Bienvenido de nuevo, {user.get('nombre', 'Usuario')}")
                    time.sleep(1)
                    st.session_state['logged_in'] = True
                    st.session_state['user_info'] = user
                    st.rerun()
                else:
                    st.error(error)
        
        with t2:
            st.info("Prueba Premium Gratis por 30 Días.")
            nu = st.text_input("Correo Electrónico", key="s_u")
            nn = st.text_input("Nombre Completo", key="s_n")
            np = st.text_input("Contraseña", type="password", help="Mínimo 6 caracteres", key="s_p")
            
            if st.button("Comenzar Prueba Gratis", use_container_width=True):
                ok, msg = db_crear_usuario(nu, np, nn)
                if ok:
                    st.success("¡Cuenta creada! Revisa tu correo para confirmar.")
                else:
                    st.error(f"Error: {msg}")

        with t3:
            ru = st.text_input("Correo para recuperar", key="r_u")
            if st.button("Enviar Enlace", use_container_width=True):
                if db_recuperar_password(ru):
                    st.success("¡Enviado! Revisa tu bandeja de entrada.")
                else:
                    st.error("Error al enviar.")

def main_app():
    user = st.session_state['user_info']
    
    # --- BARRA LATERAL CON INFORMACIÓN DE LA SUSCRIPCIÓN ---
    with st.sidebar:
        st.write(f"Hola, **{user.get('nombre', 'Usuario')}**")
        
        dias = user.get('dias_restantes', 30)
        
        if dias > 5:
            st.success(f"✅ Membresía Activa\n\nQuedan {dias} días")
        elif dias >= 0:
            st.warning(f"⚠️ **Atención**: Quedan solo {dias} días de prueba.")
            st.markdown("[Renovar Ahora](#)") # Aquí pondríamos el link de pago
        else:
            st.error("⛔ Plan Vencido")

        st.divider()
        nav = st.radio("", ["Panel", "Ingreso", "Gasto", "Datos"])
        
        st.divider()
        if st.button("Cerrar Sesión"):
            supabase.auth.sign_out()
            st.session_state['logged_in'] = False
            st.rerun()

    # --- CONTENIDO PRINCIPAL ---
    if nav == "Panel":
        if user.get('dias_restantes', 0) <= 5:
            st.info(f"💡 Recordatorio: Tu membresía vence en {user.get('dias_restantes')} días. Asegura tu acceso continuo.")

        st.title("Tu Balance")
        df = db_obtener(user['id'])
        
        ing = df[df['tipo']=='Ingreso']['monto'].sum() if not df.empty else 0
        gas = df[df['tipo']=='Gasto']['monto'].sum() if not df.empty else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Neto", f"${ing-gas:,.0f}")
        c2.metric("Entradas", f"${ing:,.0f}")
        c3.metric("Salidas", f"${gas:,.0f}")
        
        if not df.empty:
            st.plotly_chart(px.area(df, x='fecha', y='monto', color='tipo', color_discrete_map={'Ingreso':'#10B981','Gasto':'#EF4444'}), use_container_width=True)
        else:
            st.info("¡Bienvenido! Empieza registrando tus ingresos.")

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
