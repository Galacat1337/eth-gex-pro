import streamlit as st
import requests
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import plotly.graph_objects as go

st.set_page_config(page_title="ETH GEX Pro", layout="wide")

# Инициализация "памяти" для отслеживания динамики уровней
if 'last_support' not in st.session_state:
    st.session_state.last_support = None
if 'last_magnet' not in st.session_state:
    st.session_state.last_magnet = None
if 'last_price' not in st.session_state:
    st.session_state.last_price = None

def get_eth_price():
    url = "https://www.deribit.com/api/v2/public/get_index_price?index_name=eth_usd"
    return requests.get(url).json()['result']['index_price']

def get_option_chain(currency="ETH"):
    url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={currency}&kind=option"
    data = requests.get(url).json()['result']
    df = pd.DataFrame(data)[['instrument_name', 'mark_iv', 'open_interest', 'underlying_price']]
    df[['currency', 'expiry', 'strike', 'type']] = df['instrument_name'].str.split('-', expand=True)
    df['strike'] = pd.to_numeric(df['strike'])
    df = df[(df['open_interest'] > 0) & (df['mark_iv'] > 0)].copy()
    
    # Сразу создаем даты экспирации для фильтрации
    df['expiry_date'] = pd.to_datetime(df['expiry'], format='%d%b%y') + pd.Timedelta(hours=8)
    df.reset_index(drop=True, inplace=True)
    return df

def calculate_gex(df):
    now = datetime.utcnow()
    df['T'] = (df['expiry_date'] - now).dt.total_seconds() / (365 * 24 * 3600)
    df = df[df['T'] > 0].copy()
    
    S, K, sigma, T, r = df['underlying_price'], df['strike'], df['mark_iv'] / 100.0, df['T'], 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    df['gamma'] = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    
    df['GEX'] = df['gamma'] * df['open_interest']
    df.loc[df['type'] == 'P', 'GEX'] *= -1
    return df

def plot_gex_profile(df, current_price):
    min_strike, max_strike = current_price * 0.7, current_price * 1.3
    filtered_df = df[(df['strike'] >= min_strike) & (df['strike'] <= max_strike)]
    gex_by_strike = filtered_df.groupby(['strike', 'type'])['GEX'].sum().unstack(fill_value=0)
    
    for col in ['C', 'P']:
        if col not in gex_by_strike.columns: gex_by_strike[col] = 0

    below_price = gex_by_strike[gex_by_strike.index < current_price]
    above_price = gex_by_strike[gex_by_strike.index > current_price]

    # ИЩЕМ КЛАСТЕРЫ (Сумма 3-х соседних страйков) вместо одиночных пиков
    support_strike = below_price['P'].rolling(window=3, center=True, min_periods=1).sum().idxmin() if not below_price.empty else None
    magnet_strike = above_price['C'].rolling(window=3, center=True, min_periods=1).sum().idxmax() if not above_price.empty else None

    fig = go.Figure()
    fig.add_trace(go.Bar(x=gex_by_strike.index, y=gex_by_strike['C'], name='+ GEX (Calls)', marker_color='dodgerblue', opacity=0.8))
    fig.add_trace(go.Bar(x=gex_by_strike.index, y=gex_by_strike['P'], name='- GEX (Puts)', marker_color='crimson', opacity=0.8))

    fig.add_vline(x=current_price, line_dash="dash", line_color="darkorange", annotation_text=f"Цена: {current_price:.0f}$", annotation_position="top left")
    if support_strike: fig.add_vline(x=support_strike, line_dash="dot", line_color="green", annotation_text=f"Блок Поддержки: {support_strike}$", annotation_position="bottom right")
    if magnet_strike: fig.add_vline(x=magnet_strike, line_dash="dot", line_color="red", annotation_text=f"Магнитный блок: {magnet_strike}$", annotation_position="top right")

    fig.update_layout(title='GEX Profile (С учетом Гамма-кластеров)', xaxis_title='Strike Price', yaxis_title='Gamma Exposure', barmode='relative', hovermode="x unified", margin=dict(l=20, r=20, t=50, b=20), height=450)
    return fig, support_strike, magnet_strike

# --- ИНТЕРФЕЙС ---
with st.sidebar:
    st.header("⚙️ Настройки модели")
    # ФИЛЬТР ЭКСПИРАЦИЙ (0DTE и ближние)
    exp_limit = st.slider("Учитывать ближайших экспираций:", min_value=1, max_value=10, value=2, help="1 = Только опционы истекающие сегодня/завтра. 10 = Весь месяц.")

st.title("📊 Институциональная система GEX | ETH")

if st.button("🔄 Обновить данные рынка", type="primary"):
    pass # Перезапуск страницы произойдет автоматически

with st.spinner('Анализируем ликвидность...'):
    current_price = get_eth_price()
    options_data = get_option_chain()
    
    # Применяем фильтр дат экспирации
    unique_dates = sorted(options_data['expiry_date'].unique())
    target_dates = unique_dates[:exp_limit]
    filtered_options = options_data[options_data['expiry_date'].isin(target_dates)]
    
    processed_data = calculate_gex(filtered_options)
    fig, support, magnet = plot_gex_profile(processed_data, current_price)

# РАСЧЕТ ДИНАМИКИ (Смещение уровней)
diff_price = current_price - st.session_state.last_price if st.session_state.last_price else None
diff_supp = support - st.session_state.last_support if st.session_state.last_support and support else None
diff_mag = magnet - st.session_state.last_magnet if st.session_state.last_magnet and magnet else None

col1, col2, col3 = st.columns(3)
col1.metric("Текущая цена ETH", f"{current_price:.2f} $", delta=f"{diff_price:.2f} $" if diff_price else None)
col2.metric("🟢 Блок поддержки", f"{support} $" if support else "Н/Д", delta=f"{diff_supp} $" if diff_supp else None, delta_color="normal")
col3.metric("🔴 Магнитный блок", f"{magnet} $" if magnet else "Н/Д", delta=f"{diff_mag} $" if diff_mag else None, delta_color="normal")

# Сохраняем текущие значения для следующего обновления
st.session_state.last_price = current_price
st.session_state.last_support = support
st.session_state.last_magnet = magnet

st.plotly_chart(fig, use_container_width=True)

# --- ЛОКАЛЬНЫЙ АЛГОРИТМ АНАЛИТИКИ ---
st.markdown("---")
st.subheader("🧠 Аналитический вывод системы")
if st.button("Сгенерировать торговый план"):
    if not support or not magnet:
        st.warning("Недостаточно данных для анализа.")
    else:
        with st.spinner('Анализирую кластеры гаммы...'):
            dist_to_support, dist_to_magnet = current_price - support, magnet - current_price
            
            st.markdown("### 📋 Краткий вывод:")
            if dist_to_magnet < dist_to_support:
                st.success("Рынок контролируют **БЫКИ** 🐂. Цена притягивается к магнитному кластеру сопротивления.")
            else:
                st.error("Рынок в зоне давления **МЕДВЕДЕЙ** 🐻. Высокая вероятность теста кластера поддержки.")
            
            # Анализ смещения (Динамики)
            if diff_mag and diff_mag > 0:
                st.info("🔥 **СИЛЬНЫЙ СИГНАЛ:** Магнит сместился ВВЕРХ с прошлого обновления! Крупные игроки ставят на продолжение роста.")
            elif diff_supp and diff_supp < 0:
                st.warning("⚠️ **ВНИМАНИЕ:** Поддержка провалилась НИЖЕ. Медведи продавливают ликвидность вниз.")
