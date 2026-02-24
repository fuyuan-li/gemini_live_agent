from google import genai
import os
from dotenv import load_dotenv

load_dotenv("app/.env")
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

# 列前 50 个模型名，方便你 grep
models = list(client.models.list())
for m in models[:100]:
    print(m.name)
print("Total:", len(models))