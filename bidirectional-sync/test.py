from openai import OpenAI
import os


API_BASE="https://ai-gateway.uni-paderborn.de/v1/"

with open('/workspaces/conf/upb_ai_api_key.txt', 'r') as f:
    API_KEY=f.readline().strip()


API_CHAT_MODEL="hs-de.openai-gpt-oss-120b" #"hs-de.qwen3.8-27b" #gwdg.glm-5.3-flash"

client = OpenAI(
    api_key=API_KEY,
    base_url=API_BASE
)

prompt = "Nenne mir drei Gründe warum ich Python als Programmiersprache für KI nutzen sollte."
print("Prompt:", prompt)
print("Model:", API_CHAT_MODEL)

completion = client.chat.completions.create(
model=API_CHAT_MODEL,
messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
    ]
)

print(completion.choices[0].message)