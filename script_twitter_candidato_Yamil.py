#URL DE EJECUCION EN CONSOLA: C:\Users\57317\Desktop\PowerUps\JCVL\Web_Scrapping\script_twitter_candidato_yamil.py
import asyncio
import json
import pandas as pd
from playwright.async_api import async_playwright

USERNAME = "EspinalGeronimo"  # Cambia esto por tu usuario
PASSWORD = "122567896Ab+"  # Cambia esto por tu contraseña
TARGET_ACCOUNT = "JMilei"
SCROLL_TIMES = 5  # Cuántas veces hacer scroll para cargar más tweets
MIN_TWEETS = 100  # Número mínimo de tweets a obtener


async def scrape_x_timeline():
    tweets = []
    seen_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Interceptar respuestas de red para capturar datos JSON relevantes
        def on_response(response):
            try:
                url = response.url
                # esta parte es crítica: identificar endpoint de timeline de X
                if "UserTweets" in url or "UserTweetsAndReplies" in url:
                    # respuesta JSON
                    j = response.json()
                    return j
            except Exception:
                return None

        page.on("response", lambda resp: on_response(resp))

        # Login manual
        await page.goto("https://x.com/login")
        await page.wait_for_selector("input[name='text']", timeout=20000)
        await page.fill("input[name='text']", USERNAME)
        await page.press("input[name='text']", "Enter")
        await page.wait_for_timeout(2000)
        await page.fill("input[name='password']", PASSWORD)
        await page.press("input[name='password']", "Enter")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(5000)

        # Ir al perfil del usuario
        await page.goto(f"https://x.com/{TARGET_USERNAME}")
        await page.wait_for_selector("article", timeout=20000)

        # Hacer scroll hasta tener suficientes
        while len(tweets) < MAX_TWEETS:
            # Extraer los elementos actuales visibles
            articles = await page.query_selector_all("article")
            for art in articles:
                try:
                    cont = await art.inner_text()
                    # también buscar el atributo data-testid o id del tweet
                    # para evitar duplicados
                    # Muy simplificado:
                    if cont and cont not in seen_ids:
                        seen_ids.add(cont)
                        tweets.append({"tweet": cont})
                except Exception as e:
                    print("Error extrayendo artículo:", e)

            # Hacer scroll hacia abajo
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(2000)

        await browser.close()

    # Reducir al máximo permitido
    tweets = tweets[:MAX_TWEETS]
    df = pd.DataFrame(tweets)
    df.to_csv(f"tweets_{TARGET_USERNAME}.csv", index=False, encoding="utf-8")
    print(f"Guardados {len(tweets)} tweets en tweets_{TARGET_USERNAME}.csv")

if __name__ == "__main__":
    asyncio.run(scrape_x_timeline())

