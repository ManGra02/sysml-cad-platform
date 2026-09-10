
from openai import OpenAI
API_CHAT_MODEL="gwdg.gemma-4-31b-it"

API_BASE="https://ai-gateway.uni-paderborn.de/v1/"

with open('/workspaces/conf/apikey.txt', 'r') as f:
    API_KEY=f.readline().strip()



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