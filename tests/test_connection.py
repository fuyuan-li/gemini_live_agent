import os, asyncio
from dotenv import load_dotenv
from google import genai
from google.genai.types import LiveConnectConfig, Modality

load_dotenv("app/.env")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")  # 你当前能跑 live 的那个模型名
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))


async def main():
    cfg = LiveConnectConfig(response_modalities=[Modality.AUDIO])  # 只允许一种 modality  [oai_citation:2‡Google GitHub](https://google.github.io/adk-docs/streaming/dev-guide/part4/?utm_source=chatgpt.com)
    async with client.aio.live.connect(model=MODEL, config=cfg) as session:
        print("connected")
        await session.close()

asyncio.run(main())