import streamlit as st
import requests
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import plotly.graph_objects as go

# --- НАСТРОЙКА СТРАНИЦЫ ВЕБ-САЙТА ---
st.set_page_config(page_title="ETH GEX Dashboard", layout="wide")

def get_eth_price():
    url = "https://www.deribit.com/api/v2/public/get_index_price?index_name=eth_usd"
    response = requests.get(url)
    return response.json()['result']['index_price']

def get_option_chain(currency="ETH"):
    url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={currency}&kind=option"
    response = requests.get(url)
    data = response.json()['result']
    df = pd.DataFrame(data)
    
    df = df[['instrument_name', 'mark_iv', 'open_interest', 'underlying_price']]
    df[['currency', 'expiry', 'strike', 'type']] = df['instrument_name'].str.split('-', expand=True)
    df['strike'] = pd.to_numeric(df['strike'])
    
    df = df[(df['open_interest'] > 0) & (df['mark_iv'] > 0)].copy()
    df.reset_index(drop=True, inplace=True)
    return df

def calculate_gex(df):
    now = datetime.utcnow()
    df['expiry_date'] = pd.to_datetime(df['expiry'], format='%d%b%y') + pd.Timedelta(hours=8)
    df['T'] = (df['expiry_date'] - now).dt.total_seconds() / (365 * 24 * 3600)
    df = df[df['T'] > 0].copy()
    
    S = df['underlying_price']
    K = df['strike']
    sigma = df['mark_iv'] / 100.0
    T = df['T']
    r = 0.0
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    df['gamma'] = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    
    df['GEX'] = df['gamma'] * df['open_interest']
    df.loc[df['type'] == 'P', 'GEX'] *= -1
    return df

def plot_gex_profile(df, current_price):
    min_strike = current_price * 0.7
    max_strike = current_price * 1.3
    filtered_df = df[(df['strike'] >= min_strike) & (df['strike'] <= max_strike)]
    
    gex_by_strike = filtered_df.groupby(['strike', 'type'])['GEX'].sum().unstack(fill_value=0)
    if 'C' not in gex_by_strike.columns: gex_by_strike['C'] = 0
    if 'P' not in gex_by_strike.columns: gex_by_strike['P'] = 0

    below_price = gex_by_strike[gex_by_strike.index < current_price]
    support_strike = below_price['P'].idxmin() if not below_price.empty else None

    above_price = gex_by_strike[gex_by_strike.index > current_price]
    magnet_strike = above_price['C'].idxmax() if not above_price.empty else None

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=gex_by_strike.index, y=gex_by_strike['C'],
        name='+ GEX (Calls / Быки)', marker_color='dodgerblue', opacity=0.8
    ))

    fig.add_trace(go.Bar(
        x=gex_by_strike.index, y=gex_by_strike['P'],
        name='- GEX (Puts / Медведи)', marker_color='crimson', opacity=0.8
    ))

    fig.add_vline(x=current_price, line_dash="dash", line_color="darkorange", 
                  annotation_text=f"Цена: {current_price:.0f}$", annotation_position="top left")
    
    if support_strike:
        fig.add_vline(x=support_strike, line_dash="dot", line_color="green", 
                      annotation_text=f"Поддержка: {support_strike}$", annotation_position="bottom right")
        
    if magnet_strike:
        fig.add_vline(x=magnet_strike, line_dash="dot", line_color="red", 
                      annotation_text=f"Магнит: {magnet_strike}$", annotation_position="top right")

    fig.update_layout(
        title='GEX Profile: Анализ уровней для торговли ETH',
        xaxis_title='Strike Price (Цена ETH)',
        yaxis_title='Gamma Exposure (GEX)',
        barmode='relative',
        hovermode="x unified",
        margin=dict(l=20, r=20, t=50, b=20),
        height=450
    )
    
    return fig, support_strike, magnet_strike

# --- ИНТЕРФЕЙС ВЕБ-САЙТА ---
st.title("📊 Торговая система GEX | Ethereum")

if st.button("🔄 Обновить данные рынка", type="primary"):
    st.rerun()

with st.spinner('Считаем опционную доску...'):
    current_price = get_eth_price()
    options_data = get_option_chain()
    processed_data = calculate_gex(options_data)
    fig, support, magnet = plot_gex_profile(processed_data, current_price)

col1, col2, col3 = st.columns(3)
col1.metric("Текущая цена ETH", f"{current_price:.2f} $")
col2.metric("🟢 Уровень поддержки (Отмена)", f"{support} $" if support else "Н/Д")
col3.metric("🔴 Уровень магнит (Цель)", f"{magnet} $" if magnet else "Н/Д")

st.plotly_chart(fig, use_container_width=True)

# --- ЛОКАЛЬНЫЙ АЛГОРИТМ АНАЛИТИКИ ---
st.markdown("---")
st.subheader("🧠 Аналитический вывод системы")

if st.button("Сгенерировать торговый план"):
    if not support or not magnet:
        st.warning("Недостаточно данных для анализа. Не найдены уровни поддержки или магнита.")
    else:
        with st.spinner('Анализирую профиль гаммы по методичке...'):
            # Математическая логика оценки рынка
            dist_to_support = current_price - support
            dist_to_magnet = magnet - current_price
            
            # Формируем вывод
            st.markdown("### 📋 Краткий вывод:")
            if dist_to_magnet < dist_to_support:
                st.success("Рынок контролируют **БЫКИ** 🐂. Цена находится ближе к уровню магнита. Американский перекос с высокой вероятностью потянет цену к сопротивлению.")
                st.markdown("### 🎯 Торговый план (Лонг):")
                st.markdown(f"""
                * **Стратегия:** Работаем по тренду в сторону положительной гаммы.
                * **Точка входа:** Текущие значения или небольшие откаты в сторону {support}$.
                * **Цель (Тейк-профит):** Зона магнита **{magnet}$**. На этом уровне маркетмейкеры начнут хеджировать позиции, рост замедлится. Фиксируйте прибыль!
                * **Отмена сценария (Стоп-лосс):** Пробой и закрепление ниже **{support}$**.
                """)
            else:
                st.error("Рынок в зоне давления **МЕДВЕДЕЙ** 🐻. Цена опасно близка к мощной отрицательной гамме.")
                st.markdown("### 🎯 Торговый план (Шорт / Ожидание):")
                st.markdown(f"""
                * **Стратегия:** Риск ложного пробоя вниз высок. Ожидаем реакцию на поддержку.
                * **Если поддержка выдержит:** Можно пробовать аккуратный лонг от **{support}$** со стопом сразу за уровнем.
                * **Если поддержка пробита:** Уходим в шорт на пробое **{support}$**.
                * **Глобальная цель роста:** Магнит **{magnet}$** (если цена удержится выше поддержки).
                """)
            
            st.info("💡 *Совет из методички:* Не жадничайте. При внутридневной торговле опционами забирайте 30-40% прибыли и не ждите экспирации!")